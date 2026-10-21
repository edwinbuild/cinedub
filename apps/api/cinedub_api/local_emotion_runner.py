"""Bounded audio-only performance hints. Never reads a transcript or edits project state."""

import argparse
import gc
import json
import resource
import time
import wave

from .providers.local_emotion import LABELS, MODEL_NAME, PROFILE, read_manifest


def scores_from_logits(logits):
    import numpy as np

    values = np.asarray(logits, dtype=np.float64)
    if values.shape != (1, 4) or not np.isfinite(values).all():
        raise ValueError("Emotion classifier returned invalid logits")
    probabilities = np.exp(values[0] - values[0].max())
    probabilities /= probabilities.sum()
    order = np.argsort(probabilities)[::-1]
    margin = float(probabilities[order[0]] - probabilities[order[1]])
    label = (
        LABELS[int(order[0])]
        if probabilities[order[0]] >= PROFILE["suggestion_score"]
        and margin >= PROFILE["suggestion_margin"]
        else None
    )
    return (
        [
            {"label": label, "score": float(score)}
            for label, score in zip(LABELS, probabilities, strict=True)
        ],
        label,
        margin,
    )


def speech_presence(model, samples):
    import numpy as np

    state = np.zeros((2, 1, 128), dtype=np.float32)
    context = np.zeros(64, dtype=np.float32)
    speech_samples = 0
    frames = 0
    for offset in range(0, len(samples), 512):
        raw = samples[offset : offset + 512]
        chunk = np.pad(raw, (0, 512 - len(raw)))
        window = np.concatenate((context, chunk))[None]
        probability, state = model.run(
            None,
            {
                "input": window.astype(np.float32),
                "state": state,
                "sr": np.array(16000, dtype=np.int64),
            },
        )
        value = float(np.asarray(probability).reshape(-1)[0])
        if not np.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Speech-presence model returned an invalid score")
        if value >= PROFILE["speech_threshold"]:
            speech_samples += len(raw)
        context = chunk[-64:]
        frames += 1
    return round(speech_samples / 16), speech_samples / len(samples), frames


def session(directory, filename, threads):
    import onnxruntime as ort

    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(
        str(directory / filename), sess_options=options, providers=["CPUExecutionProvider"]
    )


def run(args):
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 10 * 1024**3))
    import numpy as np

    read_manifest(args.model_dir, verify=True)
    inputs = json.loads(args.request.read_text(encoding="utf-8"))
    windows, duration = inputs["windows"], inputs["duration_ms"]
    if (
        inputs.get("profile") != PROFILE
        or not 0 < duration <= 120000
        or not 0 < len(windows) <= 500
    ):
        raise ValueError("Unsupported emotion input/profile")
    with wave.open(str(args.audio), "rb") as handle:
        if (
            handle.getnchannels() != 1
            or handle.getframerate() != 16000
            or handle.getsampwidth() != 2
            or handle.getnframes() > 16000 * 121
        ):
            raise ValueError("Emotion analysis requires bounded mono 16 kHz PCM16 WAV")
        samples = (
            np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32)
            / 32768
        )
    if abs(len(samples) / 16 - duration) > 2:
        raise ValueError("Emotion audio does not match the saved scene timeline")
    started = time.monotonic()
    lines, pending = [], []
    for window in windows:
        start, end = window["start_ms"], window["end_ms"]
        if not 0 <= start < end <= duration:
            raise ValueError("Emotion window exceeds the source duration")
        raw = samples[start * 16 : end * 16]
        rms = float(np.sqrt(np.mean(raw * raw)))
        result = {
            "segment_id": window["id"],
            "start_ms": start,
            "end_ms": end,
            "status": "no_speech",
            "suggested_label": None,
            "scores": [],
            "score_margin": None,
            "speech_ms": 0,
            "speech_fraction": 0.0,
            "rms_dbfs": round(20 * np.log10(rms), 2) if rms else None,
            "warnings": [],
        }
        if window.get("overlap"):
            result.update(
                status="overlap",
                warnings=["Overlapping dialogue needs a clean single-speaker window"],
            )
        elif end - start < PROFILE["min_window_ms"]:
            result.update(
                status="too_short", warnings=["Window is too short for this experimental profile"]
            )
        elif end - start > PROFILE["max_window_ms"]:
            result.update(
                status="too_long", warnings=["Split windows longer than 20 seconds before analysis"]
            )
        elif rms > 10 ** (-65 / 20):
            pending.append((len(lines), raw))
        else:
            result["warnings"].append("No usable audio energy; no emotion label was generated")
        lines.append(result)
    vad_frames = 0
    if pending:
        vad = session(args.model_dir, "vad/model.onnx", args.threads)
        if {item.name for item in vad.get_inputs()} != {"input", "state", "sr"}:
            raise ValueError("Speech-presence model interface changed")
        classified = []
        for index, raw in pending:
            milliseconds, fraction, frames = speech_presence(vad, raw)
            vad_frames += frames
            lines[index].update(speech_ms=milliseconds, speech_fraction=fraction)
            if (
                milliseconds >= PROFILE["min_speech_ms"]
                and fraction >= PROFILE["min_speech_fraction"]
            ):
                classified.append((index, raw))
            else:
                lines[index]["warnings"].append(
                    "Speech-presence guard found insufficient speech; no emotion label"
                )
        del vad
        gc.collect()
    else:
        classified = []
    if classified:
        configuration = json.loads((args.model_dir / "ser/config.json").read_text())
        preprocessing = json.loads((args.model_dir / "ser/preprocessor_config.json").read_text())
        if (
            configuration["id2label"] != {"0": "neu", "1": "hap", "2": "ang", "3": "sad"}
            or preprocessing["do_normalize"] is not False
            or preprocessing["sampling_rate"] != 16000
        ):
            raise ValueError("Emotion classifier preprocessing/label mapping changed")
        model = session(args.model_dir, "ser/model.onnx", args.threads)
        names = {item.name for item in model.get_inputs()}
        if "input_values" not in names or names - {"input_values", "attention_mask"}:
            raise ValueError("Emotion classifier interface changed")
        for completed, (index, raw) in enumerate(classified):
            feed = {"input_values": raw[None].astype(np.float32)}
            if "attention_mask" in names:
                feed["attention_mask"] = np.ones((1, len(raw)), dtype=np.int64)
            scores, label, margin = scores_from_logits(model.run(None, feed)[0])
            lines[index].update(
                status="needs_review" if label else "ambiguous",
                suggested_label=label,
                scores=scores,
                score_margin=margin,
                warnings=[
                    "Normalized model scores are not calibrated confidence or psychological facts",
                    "Only four English training classes; "
                    "speech presence and cinematic/generalization quality are not guaranteed",
                ],
            )
            temporary = args.output_dir / "progress.tmp"
            temporary.write_text(json.dumps({"completed": completed + 1, "total": len(classified)}))
            temporary.replace(args.output_dir / "progress.json")
    result = {
        "provider": "local",
        "model": MODEL_NAME,
        "profile": PROFILE,
        "lines": lines,
        "metadata": {
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "threads": args.threads,
            "emotion_inference_count": len(classified),
            "vad_frame_count": vad_frames,
        },
    }
    (args.output_dir / "emotion-result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("model-dir", "audio", "request", "output-dir"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--threads", type=int, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
