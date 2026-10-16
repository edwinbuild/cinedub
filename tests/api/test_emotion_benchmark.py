"""Offline checks for diagnostic selection and honest metric denominators."""

import hashlib
import importlib.util
from pathlib import Path

import httpx
import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/evaluate-emotion-benchmark.py"
SPEC = importlib.util.spec_from_file_location("emotion_benchmark", PATH)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def sample(gold="neutral", prediction="neutral"):
    case = {"id": "sample-000", "gold": gold, "start_ms": 0, "end_ms": 1000}
    scores = (
        [
            {"label": label, "score": 0.7 if label == prediction else 0.1}
            for label in benchmark.LABELS
        ]
        if prediction
        else []
    )
    line = {
        "segment_id": case["id"],
        "start_ms": 0,
        "end_ms": 1000,
        "scores": scores,
        "suggested_label": prediction,
        "status": "needs_review" if prediction else "no_speech",
    }
    return case, line


def test_supported_and_out_of_class_denominators():
    case, line = sample()
    result = benchmark.metrics([case], [line])
    assert result["supported_selective_accuracy"] == 1
    assert result["out_of_class_false_suggestion_rate"] is None
    case["gold"] = "fearful"
    result = benchmark.metrics([case], [line])
    assert result["out_of_class_false_suggestion_rate"] == 1
    assert result["supported_raw_argmax_accuracy"] is None


def test_abstention_is_not_counted_as_correct():
    case, line = sample(prediction=None)
    result = benchmark.metrics([case], [line])
    assert result["supported_raw_argmax_accuracy"] == 0
    assert result["supported_selective_accuracy"] is None
    assert result["confusion"]["neutral"]["withheld"] == 1


@pytest.mark.parametrize("fault", ["id", "time", "nan", "threshold", "duplicate", "labels"])
def test_reject_invalid_results(fault):
    case, line = sample()
    if fault == "id":
        line["segment_id"] = "other"
    elif fault == "time":
        line["end_ms"] = 999
    elif fault == "nan":
        line["scores"][0]["score"] = float("nan")
    elif fault == "threshold":
        line["suggested_label"] = None
    elif fault == "duplicate":
        line["scores"].append(line["scores"][0])
    else:
        line["scores"][0]["label"] = "fearful"
    with pytest.raises(ValueError):
        benchmark.metrics([case], [line])


def test_selection_uses_single_audio_votes_and_fixed_seed(monkeypatch):
    rows = [
        f"1001_DFA_ANG_{suffix},{code}"
        for code, suffix in zip(benchmark.GOLD, ["AA", "BB", "CC", "DD", "EE", "FF"], strict=True)
    ]
    rows.append("1001_DFA_ANG_GG,A:N")
    data = ("FileName,VoiceVote\n" + "\n".join(rows) + "\n").encode()
    digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    monkeypatch.setattr(benchmark, "SUMMARY_BLOB", digest)
    cases = benchmark.select_cases(data, count=1)
    assert [case["gold"] for case in cases] == list(benchmark.GOLD.values())
    assert len(cases) == 6
    assert benchmark.select_cases(data, count=1) == cases
    with pytest.raises(ValueError, match="checksum"):
        benchmark.select_cases(data + b"changed", count=1)
    with pytest.raises(ValueError, match="Insufficient"):
        benchmark.select_cases(data, count=2)


def test_download_is_bounded_and_does_not_follow_redirects():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"12345"))
    with httpx.Client(transport=transport) as client:
        assert benchmark.fetch(client, "https://example.test/audio", 5) == b"12345"
        with pytest.raises(ValueError, match="size limit"):
            benchmark.fetch(client, "https://example.test/audio", 4)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "https://other.test/audio"})
    )
    with httpx.Client(transport=transport, follow_redirects=False) as client:
        with pytest.raises(httpx.HTTPStatusError):
            benchmark.fetch(client, "https://example.test/audio", 5)
