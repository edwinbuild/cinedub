"""One bounded CPU child for source/take acoustics and optional Malayalam word suggestions."""

import argparse
import json
import resource
import time
import wave
from pathlib import Path


def load_pcm16(path, np):
    with wave.open(str(path)) as handle:
        if (
            handle.getnchannels() != 1
            or handle.getframerate() != 16000
            or handle.getsampwidth() != 2
            or not 0 < handle.getnframes() <= 16000 * 120
        ):
            raise ValueError("Analysis requires bounded mono 16 kHz PCM16 WAV")
        return (
            np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32)
            / 32768
        )


def word_suggestions(model, samples, text, vocab, *, start_ms, end_ms, np):
    from .alignment_dsp import force_align, malayalam_tokens
    from .providers.local_target_alignment import MODEL_NAME

    result = {"status": "unalignable", "model": MODEL_NAME, "words": [], "warnings": []}
    try:
        normalized, tokens = malayalam_tokens(text, vocab)
        if not 400 <= len(samples) <= 16000 * 20:
            raise ValueError("Malayalam word suggestions need a 25 ms–20 s take")
        if float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) < 10 ** (-65 / 20):
            raise ValueError("No usable signal energy for word alignment")
        values = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
        feed = {"input_values": values[None].astype(np.float32)}
        if any(item.name == "attention_mask" for item in model.get_inputs()):
            feed["attention_mask"] = np.ones((1, len(values)), dtype=np.int64)
        logits = model.run(None, feed)[0][0]
        result["inference_ran"] = True
        alignment = force_align(
            logits, tokens, normalized, vocab, offset_ms=start_ms, duration_ms=end_ms
        )
        reliable = (
            alignment["acoustic_score"] >= 0.45
            and min(word["acoustic_score"] for word in alignment["words"]) >= 0.2
            and alignment["text_error_ratio"] <= 0.5
        )
        result.update(alignment, status="aligned" if reliable else "needs_review")
        result["warnings"].append("Experimental Malayalam estimates; never automatically applied")
        if not reliable:
            result["warnings"].append(
                "Weak acoustic/text agreement; inspect the spoken words manually"
            )
    except ValueError as exc:
        result["warnings"].append(str(exc))
    return result


def run(request_path, output_dir, threads):
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 10 * 1024**3))
    import numpy as np

    from .performance_comparison import compare_performance
    from .providers.local_performance import LocalPerformanceAnalyzer

    request = json.loads(request_path.read_text())
    if not 0 < len(request["takes"]) <= 100:
        raise ValueError("Analyze between 1 and 100 takes per job")
    source = load_pcm16(Path(request["source_audio_path"]), np)
    if len(source) != request["duration_ms"] * 16:
        raise ValueError("Source analysis audio does not match the scene timeline")
    started = time.monotonic()
    model, vocab, model_name = None, None, None
    if request["include_target_alignment"]:
        import onnxruntime as ort

        from .providers.local_target_alignment import MODEL_FILE, MODEL_NAME, read_manifest

        directory = Path(request["target_model_dir"])
        read_manifest(directory, verify=True)
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        ort.disable_telemetry_events()
        model = ort.InferenceSession(
            str(directory / MODEL_FILE), sess_options=options, providers=["CPUExecutionProvider"]
        )
        vocab = json.loads((directory / "vocab.json").read_text())
        model_name = MODEL_NAME
    analyzer, outputs, inference_count = LocalPerformanceAnalyzer(), [], 0
    for index, take in enumerate(request["takes"]):
        start, end = take["start_ms"], take["end_ms"]
        if not 0 <= start < end <= request["duration_ms"]:
            raise ValueError("Take is outside the source scene")
        target = load_pcm16(Path(take["prepared_audio_path"]), np)
        if len(target) != (end - start) * 16:
            raise ValueError("Prepared take does not match its saved timing envelope")
        source_features = analyzer.analyze(
            source[start * 16 : end * 16],
            offset_ms=start,
            word_count=len(take["source_text"].split()),
        )
        target_features = analyzer.analyze(
            target, offset_ms=start, word_count=len(take["translated_text"].split())
        )
        alignment = {"status": "not_requested", "words": [], "warnings": []}
        if request["include_target_alignment"]:
            alignment = (
                {
                    "status": "unalignable",
                    "model": model_name,
                    "words": [],
                    "warnings": ["Demo tones are not speech; word alignment was not run"],
                }
                if take["demo"]
                else word_suggestions(
                    model,
                    target,
                    take["translated_text"],
                    vocab,
                    start_ms=start,
                    end_ms=end,
                    np=np,
                )
            )
        inference_count += int(alignment.pop("inference_ran", False))
        outputs.append(
            {
                "candidate_id": take["candidate_id"],
                "source_performance": source_features,
                "target_performance": target_features,
                "target_alignment": alignment,
                "comparison": compare_performance(
                    source_features,
                    target_features,
                    start_ms=start,
                    end_ms=end,
                    fitted_padding_ms=take["fitted_padding_ms"],
                ),
            }
        )
        temporary = output_dir / "progress.part"
        temporary.write_text(json.dumps({"completed": index + 1, "total": len(request["takes"])}))
        temporary.replace(output_dir / "progress.json")
    result = {
        "lines": outputs,
        "metadata": {
            "model": analyzer.model,
            "target_alignment_model": model_name,
            "device": "cpu",
            "threads": threads,
            "sample_rate": 16000,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "target_alignment_requested": request["include_target_alignment"],
            "target_inference_count": inference_count,
        },
    }
    temporary = output_dir / "take-analysis-result.part"
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    temporary.replace(output_dir / "take-analysis-result.json")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    run(args.request, args.output_dir, args.threads)
