"""Measure pinned local alignment on original synthetic speech, not natural-film quality."""

import argparse
import json
import subprocess
import tempfile
import wave
from pathlib import Path

from cinedub_api.providers.local_alignment import LocalAligner


def evaluate(model_dir: Path, duration_seconds: int, text: str):
    root = Path("data/evaluation")
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="alignment-", dir=root))
    speech, prepared = directory / "speech.wav", directory / "speech-16k.wav"
    subprocess.run(
        ["espeak-ng", "-v", "en-us", "-s", "135", "-w", str(speech), text],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(speech),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(prepared),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with wave.open(str(prepared), "rb") as handle:
        pcm = handle.readframes(handle.getnframes())
    slot_seconds = 15
    if len(pcm) > (slot_seconds - 2) * 16000 * 2:
        raise ValueError("Generated speech is longer than the fixed benchmark slot")
    slots = duration_seconds // slot_seconds
    lines = [
        {
            "id": f"synthetic-{index}",
            "version": 1,
            "source_text": text,
            "start_ms": index * slot_seconds * 1000,
            "end_ms": (index + 1) * slot_seconds * 1000,
            "speaker_id": None,
        }
        for index in range(slots)
    ]
    path = directory / "scene.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        for _ in range(slots):
            handle.writeframes(
                b"\0" * 32000 + pcm + b"\0" * (slot_seconds * 32000 - 32000 - len(pcm))
            )
    result = LocalAligner(model_dir).align(
        path,
        directory,
        lines=lines,
        duration_ms=duration_seconds * 1000,
        language="en-IN",
        cancel=lambda: None,
        progress=lambda done, total: print(f"Aligned {done}/{total} lines"),
    )
    summary = {
        "fixture": "Original eSpeak NG connected English phrases; known 1-second leading silence",
        "source_duration_seconds": duration_seconds,
        "expected_words": slots * len(text.split()),
        "aligned_words": sum(len(line["words"]) for line in result["lines"]),
        "line_statuses": [line["status"] for line in result["lines"]],
        "first_word_start_ms": [
            line["words"][0]["start_ms"] if line["words"] else None for line in result["lines"]
        ],
        "metadata": result["metadata"],
        "model": result["model"],
        "limits": "Synthetic throughput check; no manual word reference or film-quality score",
    }
    (directory / "evaluation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Local evidence: {directory}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=Path("models/wav2vec2-english"))
    parser.add_argument("--duration-seconds", type=int, choices=(15, 120), default=15)
    parser.add_argument(
        "--text",
        default=("Welcome to our cinema workshop. Please review every line before export."),
    )
    args = parser.parse_args()
    evaluate(args.model_dir, args.duration_seconds, args.text)
