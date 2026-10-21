"""Opt-in transcription diagnostic on already downloaded, private CREMA-D clips.

This measures a stitched acted-English scene, not natural-film quality, diarization,
word-timing accuracy or Malayalam. Reference sentences never enter the model request.
"""

import argparse
import hashlib
import importlib.util
import json
import re
import tempfile
import time
import wave
from importlib.metadata import version
from pathlib import Path

import httpx
from cinedub_api.providers.local_asr import MODEL_NAME, LocalTranscriber, read_manifest

README_BLOB = "394e5758ef79b060a53fc5d083a017b552598d84"
SENTENCE_CODES = {
    "IEO",
    "TIE",
    "IOM",
    "IWW",
    "TAI",
    "MTI",
    "IWL",
    "ITH",
    "DFA",
    "ITS",
    "TSI",
    "WSI",
}


def sentence_map(data):
    blob = b"blob " + str(len(data)).encode() + b"\0" + data
    if hashlib.sha1(blob).hexdigest() != README_BLOB:
        raise ValueError("Dataset sentence documentation checksum differs")
    source = data.decode("utf-8")
    start = source.index("Actors spoke from a selection of 12 sentences (in parentheses")
    end = source.index("The sentences were presented", start)
    matches = re.findall(r"^\s*[*-]\s+(.+?)\s+\(([A-Z]{3})\)\.?\s*$", source[start:end], re.M)
    result = {code: text for text, code in matches}
    if len(matches) != 12 or set(result) != SENTENCE_CODES:
        raise ValueError("Dataset sentence map is incomplete or ambiguous")
    return result


def tokens(text):
    # Explicit literal convention, not semantic normalization or Whisper's benchmark normalizer.
    text = text.casefold().replace("’", "'").replace("'", "")
    return re.findall(r"[^\W_]+", text, re.UNICODE)


def word_errors(reference, hypothesis):
    expected, actual = tokens(reference), tokens(hypothesis)
    # Cells are (edit distance, substitutions, deletions, insertions).
    previous = [(index, 0, 0, index) for index in range(len(actual) + 1)]
    for index, word in enumerate(expected, 1):
        current = [(index, 0, index, 0)]
        for column, recognized in enumerate(actual, 1):
            diagonal = previous[column - 1]
            if word == recognized:
                current.append(diagonal)
                continue
            deletion, insertion = previous[column], current[column - 1]
            current.append(
                min(
                    (diagonal[0] + 1, diagonal[1] + 1, diagonal[2], diagonal[3]),
                    (deletion[0] + 1, deletion[1], deletion[2] + 1, deletion[3]),
                    (insertion[0] + 1, insertion[1], insertion[2], insertion[3] + 1),
                    key=lambda value: value[0],
                )
            )
        previous = current
    distance, substitutions, deletions, insertions = previous[-1]
    return {
        "reference_words": len(expected),
        "hypothesis_words": len(actual),
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "word_errors": distance,
        "word_error_rate": distance / len(expected) if expected else None,
        "normalization": (
            "Unicode casefold; remove apostrophes; word tokens; no number/contraction expansion"
        ),
    }


def validate_audio(dataset, cases):
    if len(cases) != 24 or [case["id"] for case in cases] != [f"sample-{i:03}" for i in range(24)]:
        raise ValueError("Expected the complete fixed 24-clip diagnostic")
    scene = dataset / "scene.wav"
    with wave.open(str(scene), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError("Diagnostic requires mono 16kHz PCM16")
        if not 0 < audio.getnframes() <= 120 * 16000:
            raise ValueError("Diagnostic exceeds bounded scene duration")
        frames = audio.readframes(audio.getnframes())
    previous_end = 0
    for case in cases:
        start, end = case["start_ms"], case["end_ms"]
        if (
            type(start) is not int
            or type(end) is not int
            or not previous_end <= start < end <= len(frames) // 32
        ):
            raise ValueError("Diagnostic windows are invalid or overlap")
        previous_end = end
        original = dataset / (case["id"] + ".wav")
        if (
            original.stat().st_size > 2_000_000
            or hashlib.sha256(original.read_bytes()).hexdigest() != case["sha256"]
        ):
            raise ValueError("Original diagnostic recording changed")
        with wave.open(
            str(dataset / (case["id"].replace("sample", "normalized") + ".wav")), "rb"
        ) as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
                1,
                2,
                16000,
            ) or not 11200 <= audio.getnframes() <= 320000:
                raise ValueError("Normalized diagnostic clip differs from frozen bounds")
            pcm = audio.readframes(audio.getnframes())
        pcm += b"\0" * (-len(pcm) % 32)
        if pcm != frames[start * 32 : end * 32]:
            raise ValueError("Scene window differs from the original normalized diagnostic")
    return len(frames) // 32


def freeze_scene(dataset, cases, directory):
    scene = dataset / "scene.wav"
    before = hashlib.sha256(scene.read_bytes()).hexdigest()
    duration_ms = validate_audio(dataset, cases)
    data = scene.read_bytes()
    if hashlib.sha256(data).hexdigest() != before:
        raise ValueError("Diagnostic scene changed while being validated")
    (directory / "scene.wav").write_bytes(data)
    return duration_ms, before


def load_benchmark():
    spec = importlib.util.spec_from_file_location(
        "benchmark", Path(__file__).with_name("evaluate-emotion-benchmark.py")
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    return benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-directory", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    dataset = args.dataset_directory.resolve(strict=True)
    if dataset.is_relative_to(root):
        raise ValueError("Actor recordings must remain outside the repository")
    benchmark = load_benchmark()
    manifest_bytes = (dataset / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if (
        manifest["report"]["dataset_revision"] != benchmark.REVISION
        or manifest["report"]["seed"] != benchmark.SEED
    ):
        raise ValueError("Unexpected diagnostic dataset identity")
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        summary = benchmark.fetch(
            client, benchmark.BASE + "/processedResults/summaryTable.csv", 500_000
        )
        readme = benchmark.fetch(client, benchmark.BASE + "/README.md", 20_000)
    selected, sentences = benchmark.select_cases(summary), sentence_map(readme)
    cases = manifest["cases"]
    if [(case["file"], case["gold"]) for case in cases] != [
        (case["file"], case["gold"]) for case in selected
    ]:
        raise ValueError("Clips must match selection fixed before inference")
    reference = " ".join(sentences[case["file"].split("_")[1]] for case in cases)
    directory = Path(tempfile.mkdtemp(prefix="cinedub-asr-diagnostic-")).resolve()
    if directory.is_relative_to(root):
        raise ValueError("Private evaluation output must remain outside the repository")
    for name in ("ATTRIBUTION.txt", "LICENSE.txt"):
        (directory / name).write_bytes((dataset / name).read_bytes())
    (directory / "dataset-README.md").write_bytes(readme)
    duration_ms, scene_sha256 = freeze_scene(dataset, cases, directory)
    model_dir = root / "models/faster-whisper-small.en"
    installation = read_manifest(model_dir, verify=True)
    started = time.monotonic()
    result = LocalTranscriber(model_dir).transcribe(
        directory / "scene.wav", directory / "inference", cancel=lambda: None
    )
    wall_seconds = round(time.monotonic() - started, 3)
    if (
        read_manifest(model_dir, verify=True) != installation
        or result["local_metadata"]["model"] != MODEL_NAME
        or hashlib.sha256((directory / "scene.wav").read_bytes()).hexdigest() != scene_sha256
    ):
        raise ValueError("ASR audio or model provenance changed during evaluation")
    report = {
        "model": MODEL_NAME,
        "model_manifest": installation,
        "runtime_versions": {
            name: version(name) for name in ("faster-whisper", "ctranslate2", "onnxruntime")
        },
        "runner_sha256": hashlib.sha256(
            (root / "apps/api/cinedub_api/local_asr_runner.py").read_bytes()
        ).hexdigest(),
        "cases": len(cases),
        "dataset_revision": benchmark.REVISION,
        "selection_seed": benchmark.SEED,
        "baseline_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "scene_sha256": scene_sha256,
        "duration_ms": duration_ms,
        "metrics": word_errors(reference, result["transcript"]),
        "local_metadata": result["local_metadata"],
        "adapter_wall_seconds": wall_seconds,
        "limitations": [
            "Stitched acted-English clips, not natural conversational cinema",
            "No human listening verification of reference utterances",
            "No diarization or word-timing accuracy measurement",
            "Whisper training overlap is unknown; not independent film acceptance",
        ],
    }
    (directory / "report.json").write_text(json.dumps(report, indent=2))
    (directory / "private-reference.json").write_text(
        json.dumps(
            {"reference": reference, "hypothesis": result["transcript"], "cases": cases}, indent=2
        )
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "model_manifest"}, indent=2
        )
    )
    print(f"Private ASR evidence: {directory}")


if __name__ == "__main__":
    main()
