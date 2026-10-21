"""Explicit, offline-after-download candidate diagnostic; never changes application routing.

CREMA-D overlaps this candidate's declared training corpus. Results are diagnostics,
NOT held-out accuracy or grounds to promote the model. No actor data enters the repo.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
import resource
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

REPOSITORY = "smkrv/speech-emotion-classification-onnx"
REVISION = "5e6da6730a4add4cb8f4997b902df89c7d38c4e9"
GRAPH = "fp32/onnx/model_quantized.onnx"
GRAPH_SIZE = 95389059
GRAPH_SHA256 = "3217e95e4b28d53913fbe94cd9650b520f8e7ecf2bd643b9e45fc5b8b93b8aab"
BLOBS = {
    "fp32/config.json": "7827b4f26b7555ac7b0c19fc4f0ce62fa3525459",
    "fp32/preprocessor_config.json": "a0b7227fc1d916e469b14f6c154ad6dfea1e6891",
    "README.md": "b4dc085a36acf64faa5b7265455ab8d14a6c1da7",
}
LABELS = ("angry", "calm", "disgusted", "fearful", "happy", "neutral", "sad", "surprised")
TRAINING_OVERLAP = "CREMA-D is included in the declared SSI training corpus; not held-out accuracy"


def verify_model(directory):
    path = directory / GRAPH
    with path.open("rb") as handle:
        if (
            path.stat().st_size != GRAPH_SIZE
            or hashlib.file_digest(handle, "sha256").hexdigest() != GRAPH_SHA256
        ):
            raise ValueError("Candidate graph checksum differs")
    for name, wanted in BLOBS.items():
        data = (directory / name).read_bytes()
        blob = b"blob " + str(len(data)).encode() + b"\0" + data
        if hashlib.sha1(blob).hexdigest() != wanted:
            raise ValueError("Candidate configuration/attribution checksum differs")
    config = json.loads((directory / "fp32/config.json").read_text())
    expected = ("ANG", "CAL", "DIS", "FEA", "HAP", "NEU", "SAD", "SUR")
    if config["id2label"] != {str(i): label for i, label in enumerate(expected)}:
        raise ValueError("Candidate label order differs")
    preprocessing = json.loads((directory / "fp32/preprocessor_config.json").read_text())
    if preprocessing["sampling_rate"] != 16000 or preprocessing["do_normalize"] is not True:
        raise ValueError("Candidate preprocessing differs")


def summarize(cases, predictions):
    ids = {case["id"] for case in cases}
    if (
        len(ids) != len(cases)
        or len(predictions) != len(cases)
        or {p["id"] for p in predictions} != ids
    ):
        raise ValueError("Candidate prediction IDs/count differ")
    by_id = {p["id"]: p for p in predictions}
    confusion = {
        gold: dict.fromkeys((*LABELS, "withheld"), 0) for gold in {c["gold"] for c in cases}
    }
    correct = raw_correct = suggested = common_correct = common_suggested = 0
    common = sum(case["gold"] in {"neutral", "happy", "angry", "sad"} for case in cases)
    for case in cases:
        value = by_id[case["id"]]
        scores = value["scores"]
        if scores:
            if (
                set(scores) != set(LABELS)
                or any(not math.isfinite(s) or not 0 <= s <= 1 for s in scores.values())
                or not math.isclose(sum(scores.values()), 1, abs_tol=0.001)
            ):
                raise ValueError("Invalid candidate scores")
            order = sorted(LABELS, key=lambda label: (-scores[label], LABELS.index(label)))
            top = order[0]
            prediction = (
                top if scores[top] >= 0.6 and scores[top] - scores[order[1]] >= 0.15 else None
            )
        else:
            top = prediction = None
        if value["suggested_label"] != prediction:
            raise ValueError("Candidate suggestion violates fixed thresholds")
        correct += prediction == case["gold"]
        raw_correct += top == case["gold"]
        suggested += prediction is not None
        confusion[case["gold"]][prediction or "withheld"] += 1
        if case["gold"] in {"neutral", "happy", "angry", "sad"}:
            common_correct += prediction == case["gold"]
            common_suggested += prediction is not None
    return {
        "cases": len(cases),
        "raw_correct": raw_correct,
        "suggestions": suggested,
        "correct_suggestions": correct,
        "selective_agreement": correct / suggested if suggested else None,
        "common_four_class_cases": common,
        "common_four_class_suggestions": common_suggested,
        "common_four_class_correct_suggestions": common_correct,
        "confusion": confusion,
        "training_overlap_warning": TRAINING_OVERLAP,
    }


def infer(directory):
    resource.setrlimit(resource.RLIMIT_AS, (10 * 1024**3, 10 * 1024**3))
    import numpy as np
    from cinedub_api.local_emotion_runner import session, speech_presence

    request = json.loads((directory / "request.json").read_text())
    model_directory = Path(request["model_directory"])
    verify_model(model_directory)
    root = Path(request["dataset"])
    from cinedub_api.providers.local_emotion import read_manifest

    vad_dir = Path(__file__).resolve().parents[1] / "models/speech-emotion"
    read_manifest(vad_dir, verify=True)
    started = time.monotonic()
    vad = session(vad_dir, "vad/model.onnx", 4)
    model = session(model_directory, GRAPH, 4)
    if {item.name for item in model.get_inputs()} != {"input_values"}:
        raise ValueError("Candidate input contract differs")
    predictions = []
    for value in request["samples"]:
        path = root / (value["id"].replace("sample", "normalized") + ".wav")
        with wave.open(str(path), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                raise ValueError("Candidate requires mono 16kHz PCM16")
            if not 11200 <= audio.getnframes() <= 320000:
                raise ValueError("Candidate window outside frozen bounds")
            pcm = audio.readframes(audio.getnframes())
            pcm += b"\0" * (-len(pcm) % 32)
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if hashlib.sha256(path.read_bytes()).hexdigest() != value["sha256"]:
            raise ValueError("Candidate diagnostic audio changed")
        speech_ms, fraction, _ = speech_presence(vad, samples)
        scores, prediction = {}, None
        if (
            speech_ms >= 300
            and fraction >= 0.2
            and np.sqrt(np.mean(samples * samples)) > 10 ** (-65 / 20)
        ):
            normalized = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)
            logits = np.asarray(
                model.run(None, {"input_values": normalized[None]})[0], dtype=np.float64
            )
            if logits.shape != (1, 8) or not np.isfinite(logits).all():
                raise ValueError("Invalid candidate logits")
            probabilities = np.exp(logits[0] - logits[0].max())
            probabilities /= probabilities.sum()
            scores = dict(zip(LABELS, map(float, probabilities), strict=True))
            order = sorted(LABELS, key=lambda label: (-scores[label], LABELS.index(label)))
            if scores[order[0]] >= 0.6 and scores[order[0]] - scores[order[1]] >= 0.15:
                prediction = order[0]
        predictions.append(
            {
                "id": value["id"],
                "scores": scores,
                "suggested_label": prediction,
                "speech_ms": speech_ms,
                "speech_fraction": fraction,
            }
        )
    result = {
        "predictions": predictions,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }
    (directory / "result.json").write_text(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-directory", type=Path)
    parser.add_argument(
        "--model-directory", type=Path, help="Reuse verified candidate files without downloading"
    )
    parser.add_argument("--infer", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.infer:
        infer(args.infer)
        return
    if not args.dataset_directory:
        parser.error("--dataset-directory from evaluate-emotion-benchmark.py is required")
    root = Path(__file__).resolve().parents[1]
    dataset = args.dataset_directory.resolve(strict=True)
    if dataset.is_relative_to(root):
        raise ValueError("Actor recordings must remain outside the repository")
    manifest = json.loads((dataset / "manifest.json").read_text())
    spec = importlib.util.spec_from_file_location(
        "benchmark", Path(__file__).with_name("evaluate-emotion-benchmark.py")
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    if (
        manifest["report"]["dataset_revision"] != benchmark.REVISION
        or manifest["report"]["seed"] != benchmark.SEED
    ):
        raise ValueError("Dataset diagnostic identity differs")
    cases = manifest["cases"]
    if len(cases) != 24 or {c["id"] for c in cases} != {f"sample-{i:03}" for i in range(24)}:
        raise ValueError("Expected complete frozen diagnostic")
    import httpx

    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        summary = benchmark.fetch(
            client, benchmark.BASE + "/processedResults/summaryTable.csv", 500_000
        )
    selected = benchmark.select_cases(summary)
    if [(c["file"], c["gold"]) for c in cases] != [(c["file"], c["gold"]) for c in selected]:
        raise ValueError("Candidate must use the same preselected clips and audio-only gold labels")
    with wave.open(str(dataset / "scene.wav"), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError("Baseline scene format differs")
        if audio.getnframes() > 16000 * 120:
            raise ValueError("Baseline scene exceeds bounded diagnostic")
        scene = audio.readframes(audio.getnframes())
    for case in cases:
        source = dataset / (case["id"] + ".wav")
        if hashlib.sha256(source.read_bytes()).hexdigest() != case["sha256"]:
            raise ValueError("Original diagnostic recording changed")
        with wave.open(
            str(dataset / (case["id"].replace("sample", "normalized") + ".wav")), "rb"
        ) as audio:
            pcm = audio.readframes(audio.getnframes())
        pcm += b"\0" * (-len(pcm) % 32)
        if pcm != scene[case["start_ms"] * 32 : case["end_ms"] * 32]:
            raise ValueError("Candidate window differs from baseline audio")
    directory = Path(tempfile.mkdtemp(prefix="cinedub-emotion-candidate-")).resolve()
    if directory.is_relative_to(root):
        raise ValueError("Diagnostic output must remain outside the repository")
    model_directory = (
        args.model_directory.resolve(strict=True) if args.model_directory else directory
    )
    if not args.model_directory:
        from huggingface_hub import hf_hub_download

        for filename in (GRAPH, *BLOBS):
            hf_hub_download(
                REPOSITORY, filename, revision=REVISION, local_dir=directory, token=False
            )
    verify_model(model_directory)
    samples = [
        {
            "id": c["id"],
            "sha256": hashlib.sha256(
                (dataset / (c["id"].replace("sample", "normalized") + ".wav")).read_bytes()
            ).hexdigest(),
        }
        for c in cases
    ]
    (directory / "request.json").write_text(
        json.dumps(
            {"dataset": str(dataset), "samples": samples, "model_directory": str(model_directory)}
        )
    )
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
    env.update(
        PYTHONPATH=str(root / "apps/api"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="4",
    )
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--infer", str(directory)],
        env=env,
        check=True,
        timeout=900,
    )
    result = json.loads((directory / "result.json").read_text())
    verify_model(model_directory)
    report = {
        "candidate": f"{REPOSITORY}@{REVISION}",
        "graph_sha256": GRAPH_SHA256,
        "threads": 4,
        "baseline_manifest_sha256": hashlib.sha256(
            (dataset / "manifest.json").read_bytes()
        ).hexdigest(),
        "baseline_scene_sha256": hashlib.sha256((dataset / "scene.wav").read_bytes()).hexdigest(),
        "normalization": "per-window mean/variance + 1e-7 (pinned do_normalize=true)",
        "metrics": summarize(cases, result["predictions"]),
        "elapsed_ms": result["elapsed_ms"],
        "peak_rss_mib": result["peak_rss_mib"],
        "promotion": "not eligible: training overlap and no independent quality evaluation",
    }
    (directory / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"Private candidate evidence: {directory}")


if __name__ == "__main__":
    main()
