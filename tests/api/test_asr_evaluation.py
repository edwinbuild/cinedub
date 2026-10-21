import hashlib
import importlib.util
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "asr_evaluation", Path(__file__).resolve().parents[2] / "scripts/evaluate-local-asr.py"
)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


@pytest.mark.parametrize(
    "reference,hypothesis,counts",
    [
        ("One two three", "one two three", (0, 0, 0)),
        ("One two three", "one four three", (1, 0, 0)),
        ("One two three", "one three", (0, 1, 0)),
        ("One two three", "one two extra three", (0, 0, 1)),
        ("one", "one two three four", (0, 0, 3)),
        ("", "inserted words", (0, 0, 2)),
        ("two words", "", (0, 2, 0)),
    ],
)
def test_word_error_counts_are_explicit(reference, hypothesis, counts):
    result = evaluation.word_errors(reference, hypothesis)
    assert (result["substitutions"], result["deletions"], result["insertions"]) == counts
    assert result["word_errors"] == sum(counts)
    denominator = len(evaluation.tokens(reference))
    assert result["word_error_rate"] == (sum(counts) / denominator if denominator else None)


def test_literal_normalization_does_not_invent_semantic_equivalence():
    assert evaluation.tokens("WE’RE here, at 11!") == ["were", "here", "at", "11"]
    assert evaluation.word_errors("eleven", "11")["substitutions"] == 1
    assert evaluation.tokens("മലയാളം")  # Non-English output is not silently erased.


def test_pinned_sentence_map_must_be_complete_and_unambiguous(monkeypatch):
    data = (
        "Actors spoke from a selection of 12 sentences (in parentheses are codes):\n"
        + "\n".join(
            f"* Example sentence {i} ({code})."
            for i, code in enumerate(sorted(evaluation.SENTENCE_CODES))
        )
        + "\nThe sentences were presented using different emotions.\n"
    ).encode()
    blob = b"blob " + str(len(data)).encode() + b"\0" + data
    monkeypatch.setattr(evaluation, "README_BLOB", hashlib.sha1(blob).hexdigest())
    assert set(evaluation.sentence_map(data)) == evaluation.SENTENCE_CODES
    with pytest.raises(ValueError, match="checksum"):
        evaluation.sentence_map(data + b"changed")


def write_wav(path, pcm, rate=16000):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)


def synthetic_dataset(tmp_path):
    frames, cases = bytearray(), []
    for i in range(24):
        pcm = b"\x01\x00" * 11200
        source, normalized = tmp_path / f"sample-{i:03}.wav", tmp_path / f"normalized-{i:03}.wav"
        write_wav(source, pcm)
        write_wav(normalized, pcm)
        cases.append(
            {
                "id": f"sample-{i:03}",
                "file": "9999_DFA_ANG_XX",
                "gold": "neutral",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "start_ms": len(frames) // 32,
                "end_ms": len(frames) // 32 + 700,
            }
        )
        frames.extend(pcm + b"\0" * 8000)
    write_wav(tmp_path / "scene.wav", frames)
    return frames, cases


@pytest.mark.parametrize("fault", [None, "ids", "window", "original", "scene", "format"])
def test_audio_validation_is_bound_to_original_complete_scene(tmp_path, fault):
    frames, cases = synthetic_dataset(tmp_path)
    if fault == "ids":
        cases[1]["id"] = cases[0]["id"]
    elif fault == "window":
        cases[1]["start_ms"] = 0
    elif fault == "original":
        (tmp_path / "sample-000.wav").write_bytes(b"changed")
    elif fault == "scene":
        frames[0] = 2
        write_wav(tmp_path / "scene.wav", frames)
    elif fault == "format":
        write_wav(tmp_path / "normalized-000.wav", b"\0" * 22400, rate=8000)
    if fault:
        with pytest.raises(ValueError):
            evaluation.validate_audio(tmp_path, cases)
    else:
        assert evaluation.validate_audio(tmp_path, cases) == 24 * 950
        output = tmp_path / "frozen"
        output.mkdir()
        duration, digest = evaluation.freeze_scene(tmp_path, cases, output)
        assert duration == 24 * 950
        assert digest == hashlib.sha256((tmp_path / "scene.wav").read_bytes()).hexdigest()
        assert (output / "scene.wav").read_bytes() == (tmp_path / "scene.wav").read_bytes()


def test_cli_scores_private_snapshot_without_passing_reference_to_native_model(
    tmp_path, monkeypatch
):
    dataset, output = tmp_path / "dataset", tmp_path / "output"
    dataset.mkdir()
    output.mkdir()
    _, cases = synthetic_dataset(dataset)
    (dataset / "manifest.json").write_text(
        json.dumps(
            {
                "cases": cases,
                "report": {
                    "dataset_revision": "fixture",
                    "seed": "fixture-seed",
                },
            }
        )
    )
    for name in ("ATTRIBUTION.txt", "LICENSE.txt"):
        (dataset / name).write_text("Original synthetic test fixture")
    monkeypatch.setattr(
        evaluation,
        "load_benchmark",
        lambda: SimpleNamespace(
            REVISION="fixture",
            SEED="fixture-seed",
            BASE="https://example.test",
            fetch=lambda *_: b"synthetic metadata",
            select_cases=lambda _: cases,
        ),
    )
    monkeypatch.setattr(evaluation, "sentence_map", lambda _: {"DFA": "sample human speech"})
    monkeypatch.setattr(evaluation.tempfile, "mkdtemp", lambda **_: str(output))
    monkeypatch.setattr(evaluation, "read_manifest", lambda *_, **__: {"fixture": True})
    monkeypatch.setattr(evaluation, "version", lambda _: "synthetic-version")
    monkeypatch.setattr("sys.argv", ["evaluate-local-asr.py", "--dataset-directory", str(dataset)])
    calls = []

    class Recorded:
        def __init__(self, *_):
            pass

        def transcribe(self, audio, output_directory, cancel):
            cancel()
            calls.append((audio, output_directory))
            assert (
                audio != dataset / "scene.wav"
                and audio.read_bytes() == (dataset / "scene.wav").read_bytes()
            )
            return {
                "transcript": "sample human speech",
                "local_metadata": {"model": evaluation.MODEL_NAME},
            }

    monkeypatch.setattr(evaluation, "LocalTranscriber", Recorded)
    evaluation.main()
    assert len(calls) == 1 and calls[0][0] == output / "scene.wav"
    report = json.loads((output / "report.json").read_text())
    assert report["metrics"]["reference_words"] == 72
    assert report["metrics"]["deletions"] == 69
    assert set(report["runtime_versions"].values()) == {"synthetic-version"}
    assert len(report["runner_sha256"]) == 64
    assert (output / "private-reference.json").is_file()
