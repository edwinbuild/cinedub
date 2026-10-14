"""Compare separated stems with the original procedural fixture (not a listening score)."""

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np


def decode(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float64)


def scores(reference, estimate):
    if abs(len(reference) - len(estimate)) > 90:
        raise ValueError("Reference/estimate duration differs by more than one millisecond")
    size = min(len(reference), len(estimate))
    reference, estimate = reference[:size], estimate[:size]
    target = reference * (np.dot(estimate, reference) / max(np.dot(reference, reference), 1e-12))
    snr = 10 * np.log10(
        max(np.dot(reference, reference), 1e-12) / max(np.sum((estimate - reference) ** 2), 1e-12)
    )
    sisdr = 10 * np.log10(
        max(np.dot(target, target), 1e-12) / max(np.sum((estimate - target) ** 2), 1e-12)
    )
    return {"snr_db": round(float(snr), 2), "si_sdr_db": round(float(sisdr), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/evaluation/separation"))
    args = parser.parse_args()
    mixture = decode(args.directory / "mixture.wav")
    result = {
        "scope": "One original synthetic/procedural clip; not cinematic quality",
        "model": json.loads((args.directory / "result/separation-result.json").read_text())[
            "model"
        ],
        "stems": {},
    }
    for name in ["dialogue", "music", "effects"]:
        reference = decode(args.directory / f"{name}.wav")
        estimate = decode(args.directory / "result" / f"{name}.wav")
        baseline = scores(reference, mixture)
        separated = scores(reference, estimate)
        result["stems"][name] = {
            "mixture_baseline": baseline,
            "separated": separated,
            "si_sdr_improvement_db": round(separated["si_sdr_db"] - baseline["si_sdr_db"], 2),
        }
    (args.directory / "evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
