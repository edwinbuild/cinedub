"""Offline bounded line-wise CTC inference; model memory is released with this child."""

import argparse
import json
import resource
import time
import wave
from pathlib import Path

from .providers.local_alignment import MODEL_FILE, MODEL_NAME, read_manifest
from .providers.local_performance import LocalPerformanceAnalyzer


def run(model_dir, audio, output_dir, request, threads):
    read_manifest(model_dir, verify=True)
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 10 * 1024**3))
    import numpy as np
    import onnxruntime as ort

    from .alignment_dsp import english_tokens, force_align

    inputs = json.loads(request.read_text())
    duration_ms, lines = inputs["duration_ms"], inputs["lines"]
    if not 0 < duration_ms <= 120000 or not 0 < len(lines) <= 500:
        raise ValueError("Alignment exceeds the two-minute/500-line laptop profile")
    with wave.open(str(audio), "rb") as handle:
        if (
            handle.getnchannels() != 1
            or handle.getframerate() != 16000
            or handle.getsampwidth() != 2
            or handle.getnframes() > 16000 * 121
        ):
            raise ValueError("Alignment requires bounded mono 16 kHz PCM16 WAV")
        samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(
            np.float32
        )
    samples /= 32768
    if abs(len(samples) / 16 - duration_ms) > 2:
        raise ValueError("Analysis audio is not mapped to the canonical scene timeline")
    vocab = json.loads((model_dir / "vocab.json").read_text())
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    ort.disable_telemetry_events()
    started = time.monotonic()
    model = ort.InferenceSession(
        str(model_dir / MODEL_FILE), sess_options=options, providers=["CPUExecutionProvider"]
    )
    outputs = []
    analyzer = LocalPerformanceAnalyzer()
    for index, line in enumerate(lines):
        start, end = line["start_ms"], line["end_ms"]
        if not 0 <= start < end <= duration_ms:
            raise ValueError("Line timing is outside source duration")
        raw = samples[start * 16 : end * 16]
        performance = analyzer.analyze(
            raw, offset_ms=start, word_count=len(line["source_text"].split())
        )
        result = {
            "segment_id": line["id"],
            "segment_version": line["version"],
            "source_text": line["source_text"],
            "original_start_ms": start,
            "original_end_ms": end,
            "status": "unalignable",
            "words": [],
            "performance": performance,
            "warnings": [],
        }
        left, right = max(0, start - 300), min(duration_ms, end + 300)
        try:
            normalized, tokens = english_tokens(line["source_text"], vocab)
            if right - left > 20000:
                raise ValueError("Split phrases longer than 19.4 seconds before alignment")
            window = samples[left * 16 : right * 16]
            if len(window) < 400:
                raise ValueError("Audio window is too short for the acoustic model")
            if performance["rms_dbfs"] is None or performance["rms_dbfs"] < -65:
                raise ValueError("No usable energy in the selected phrase")
            window = (window - window.mean()) / np.sqrt(window.var() + 1e-7)
            feed = {"input_values": window[None].astype(np.float32)}
            if any(item.name == "attention_mask" for item in model.get_inputs()):
                feed["attention_mask"] = np.ones((1, len(window)), dtype=np.int64)
            logits = model.run(None, feed)[0][0]
            alignment = force_align(
                logits, tokens, normalized, vocab, offset_ms=left, duration_ms=right
            )
            reliable = (
                alignment["acoustic_score"] >= 0.45
                and min(word["acoustic_score"] for word in alignment["words"]) >= 0.2
                and alignment["text_error_ratio"] <= 0.5
            )
            result.update(alignment, status="aligned" if reliable else "needs_review")
            if not reliable:
                result["warnings"].append(
                    "Weak acoustic/text agreement; timing application disabled"
                )
            if any(
                other["id"] != line["id"]
                and alignment["words"][0]["start_ms"] < other["end_ms"]
                and alignment["words"][-1]["end_ms"] > other["start_ms"]
                for other in lines
            ):
                result["warnings"].append("Suggested timing overlaps another dialogue line")
        except ValueError as exc:
            result["warnings"].append(str(exc))
        outputs.append(result)
        temporary = output_dir / "progress.part"
        temporary.write_text(json.dumps({"completed": index + 1, "total": len(lines)}))
        temporary.replace(output_dir / "progress.json")
    result = {
        "model": MODEL_NAME,
        "lines": outputs,
        "metadata": {
            "device": "cpu",
            "precision": "float32",
            "threads": threads,
            "sample_rate": 16000,
            "max_window_seconds": 20,
            "context_ms": 300,
            "frame_stride_ms": 20,
            "method": "ctc-viterbi-v1",
            "acoustic_method": analyzer.model,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "minimum_mean_score": 0.45,
            "minimum_word_score": 0.2,
            "maximum_greedy_text_error_ratio": 0.5,
        },
    }
    temporary = output_dir / "alignment-result.part"
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    temporary.replace(output_dir / "alignment-result.json")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    run(args.model_dir, args.audio, args.output_dir, args.request, args.threads)
