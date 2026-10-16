"""Opt-in CREMA-D diagnostic. Recordings stay in a private directory outside the repo."""

import csv
import hashlib
import io
import json
import math
import re
import subprocess
import tempfile
import wave
from collections import Counter
from pathlib import Path

import httpx
from cinedub_api.providers.local_emotion import LABELS, MODEL_NAME, PROFILE, LocalEmotionAnalyzer
from cinedub_api.schemas import SpeechEmotionInference

REVISION = "1658cd342dff90010aa843eaeebd53610a08b1dc"
BASE = f"https://raw.githubusercontent.com/CheyneyComputerScience/CREMA-D/{REVISION}"
MEDIA = f"https://media.githubusercontent.com/media/CheyneyComputerScience/CREMA-D/{REVISION}"
SUMMARY_BLOB = "77b40b6c688687800348320c784e4c387c7731ab"
SEED = "cinedub-ser-diagnostic-v1"
GOLD = {"N": "neutral", "H": "happy", "A": "angry", "S": "sad", "F": "fearful", "D": "disgusted"}


def fetch(client, url, limit):
    result = bytearray()
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            result.extend(chunk)
            if len(result) > limit:
                raise ValueError("Dataset response exceeds size limit")
    return bytes(result)


def select_cases(data, count=4):
    blob = b"blob " + str(len(data)).encode() + b"\0" + data
    if hashlib.sha1(blob).hexdigest() != SUMMARY_BLOB:
        raise ValueError("Dataset summary checksum changed")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    names = [row["FileName"] for row in rows]
    if len(set(names)) != len(names) or any(
        not re.fullmatch(r"[0-9]{4}_[A-Z]{3}_[A-Z]{3}_[A-Z]{2}", name) for name in names
    ):
        raise ValueError("Invalid or duplicate dataset filename")
    cases = []
    for code, label in GOLD.items():
        candidates = sorted(
            (row for row in rows if row["VoiceVote"] == code),
            key=lambda row: hashlib.sha256((SEED + row["FileName"]).encode()).hexdigest(),
        )
        if len(candidates) < count:
            raise ValueError("Insufficient single-label audio votes")
        cases.extend({"file": row["FileName"], "gold": label} for row in candidates[:count])
    return cases


def metrics(cases, lines):
    expected = {case["id"] for case in cases}
    if len(expected) != len(cases) or len(lines) != len(cases):
        raise ValueError("Invalid benchmark case count")
    by_id = {line["segment_id"]: line for line in lines}
    if len(by_id) != len(lines) or set(by_id) != expected:
        raise ValueError("Benchmark response IDs differ")
    confusion = {gold: dict.fromkeys((*LABELS, "withheld"), 0) for gold in GOLD.values()}
    supported = suggested = correct = raw_correct = out = out_suggested = 0
    statuses = Counter()
    for case in cases:
        line = by_id[case["id"]]
        if (line["start_ms"], line["end_ms"]) != (case["start_ms"], case["end_ms"]):
            raise ValueError("Benchmark response timing differs")
        scores = {item["label"]: item["score"] for item in line["scores"]}
        if scores and (
            len(line["scores"]) != 4
            or set(scores) != set(LABELS)
            or any(not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values())
            or not math.isclose(sum(scores.values()), 1, abs_tol=0.001)
        ):
            raise ValueError("Invalid class scores")
        ranked = sorted(scores, key=lambda label: (-scores[label], LABELS.index(label)))
        top = ranked[0] if ranked else None
        eligible = bool(
            ranked
            and scores[top] >= PROFILE["suggestion_score"]
            and scores[top] - scores[ranked[1]] >= PROFILE["suggestion_margin"]
        )
        prediction = line["suggested_label"]
        if prediction != (top if eligible else None):
            raise ValueError("Suggestion violates frozen thresholds")
        expected_status = "needs_review" if prediction else "ambiguous"
        if (scores and line["status"] != expected_status) or (
            not scores and line["status"] not in {"no_speech", "too_short", "too_long", "overlap"}
        ):
            raise ValueError("Status differs from inference evidence")
        confusion[case["gold"]][prediction or "withheld"] += 1
        statuses[line["status"]] += 1
        if case["gold"] in LABELS:
            supported += 1
            suggested += prediction is not None
            correct += prediction == case["gold"]
            raw_correct += top == case["gold"]
        else:
            out += 1
            out_suggested += prediction is not None
    f1 = []
    for label in LABELS:
        tp = confusion[label][label]
        fn = sum(confusion[label].values()) - tp
        fp = sum(confusion[gold][label] for gold in LABELS if gold != label)
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None)
    return {
        "cases": len(cases),
        "supported_cases": supported,
        "supported_suggestions": suggested,
        "supported_correct_suggestions": correct,
        "supported_raw_argmax_accuracy": raw_correct / supported if supported else None,
        "supported_suggestion_coverage": suggested / supported if supported else None,
        "supported_selective_accuracy": correct / suggested if suggested else None,
        "supported_macro_f1_with_abstention": sum(f1) / 4 if None not in f1 else None,
        "out_of_class_cases": out,
        "out_of_class_suggestions": out_suggested,
        "out_of_class_false_suggestion_rate": out_suggested / out if out else None,
        "status_counts": dict(statuses),
        "confusion": confusion,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    directory = Path(tempfile.mkdtemp(prefix="cinedub-crema-d-")).resolve()
    if directory.is_relative_to(root):
        raise ValueError("Dataset recordings must remain outside the repository")
    print(f"Private benchmark directory: {directory}", flush=True)
    (directory / "ATTRIBUTION.txt").write_text(
        "CREMA-D: Cao et al. (2014), doi:10.1109/TAFFC.2014.2336244\n"
        "https://github.com/CheyneyComputerScience/CREMA-D\n"
        "Declared database license: ODbL 1.0; contents: DbCL 1.0.\n"
        "https://opendatacommons.org/licenses/odbl/1-0/\n"
        "https://opendatacommons.org/licenses/dbcl/1-0/\n"
        "Maintainers request registration; no personal information submitted by this script.\n"
        "Diagnostic only: no cloning, training, identity or mental-state inference.\n"
    )
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        summary = fetch(client, BASE + "/processedResults/summaryTable.csv", 500_000)
        cases = select_cases(summary)
        license_text = fetch(client, BASE + "/LICENSE.txt", 100_000)
        (directory / "LICENSE.txt").write_bytes(license_text)
        frames = bytearray()
        for index, case in enumerate(cases):
            name = case["file"] + ".wav"
            pointer = fetch(client, BASE + "/AudioWAV/" + name, 1024).decode()
            match = re.fullmatch(
                r"version https://git-lfs.github.com/spec/v1\noid sha256:([a-f0-9]{64})\n"
                r"size ([0-9]+)\n?",
                pointer,
            )
            if not match or not 0 < int(match[2]) <= 2_000_000:
                raise ValueError("Invalid LFS pointer")
            recording = fetch(client, MEDIA + "/AudioWAV/" + name, 2_000_000)
            if len(recording) != int(match[2]) or hashlib.sha256(recording).hexdigest() != match[1]:
                raise ValueError("Recording checksum differs")
            source = directory / f"sample-{index:03}.wav"
            source.write_bytes(recording)
            normalized = directory / f"normalized-{index:03}.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(normalized),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            with wave.open(str(normalized), "rb") as audio:
                if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (
                    16000,
                    1,
                    2,
                ):
                    raise ValueError("Unexpected normalized audio format")
                if not 11200 <= audio.getnframes() <= 320000:
                    raise ValueError("Recording outside frozen window limits")
                pcm = audio.readframes(audio.getnframes())
            pcm += b"\0" * (-len(pcm) % 32)
            case.update(
                id=f"sample-{index:03}",
                start_ms=len(frames) // 32,
                end_ms=(len(frames) + len(pcm)) // 32,
                sha256=match[1],
            )
            frames.extend(pcm + b"\0" * 8000)
    duration = len(frames) // 32
    if duration > 120000:
        raise ValueError("Selected diagnostic exceeds scene cap; do not truncate cases")
    scene = directory / "scene.wav"
    with wave.open(str(scene), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(frames)
    windows = [
        {key: case[key] for key in ("id", "start_ms", "end_ms")} | {"overlap": False}
        for case in cases
    ]
    result = LocalEmotionAnalyzer(root / "models/speech-emotion").analyze(
        scene,
        directory / "inference",
        windows=windows,
        duration_ms=duration,
        language="en-IN",
        cancel=lambda: None,
        progress=lambda done, total: print(f"Classified {done}/{total}", flush=True),
    )
    if (
        result["provider"] != "local"
        or result["model"] != MODEL_NAME
        or result["profile"] != PROFILE
    ):
        raise ValueError("Unexpected inference provenance")
    lines = [SpeechEmotionInference.model_validate(line).model_dump() for line in result["lines"]]
    report = {
        "dataset_revision": REVISION,
        "seed": SEED,
        "model": MODEL_NAME,
        "profile": PROFILE,
        "metadata": result["metadata"],
        "metrics": metrics(cases, lines),
    }
    (directory / "manifest.json").write_text(
        json.dumps({"cases": cases, "report": report}, indent=2)
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
