"""Candidate diagnostics stay separate from production inference and promotion."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "emotion_candidate",
    Path(__file__).resolve().parents[2] / "scripts/evaluate-emotion-candidate.py",
)
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


def example(gold="fearful"):
    cases = [{"id": "sample-000", "gold": gold}]
    scores = {label: 0.03 for label in candidate.LABELS}
    scores["fearful"] = 0.79
    values = [{"id": "sample-000", "scores": scores, "suggested_label": "fearful"}]
    return cases, values


def test_expanded_class_not_mapped_to_four_class_label():
    cases, values = example()
    result = candidate.summarize(cases, values)
    assert result["raw_correct"] == result["correct_suggestions"] == 1
    assert result["common_four_class_cases"] == 0
    assert result["confusion"]["fearful"]["fearful"] == 1
    assert "not held-out" in result["training_overlap_warning"]


def test_abstention_and_missing_denominators_are_explicit():
    cases, values = example("neutral")
    values[0].update(scores={}, suggested_label=None)
    result = candidate.summarize(cases, values)
    assert result["raw_correct"] == 0
    assert result["selective_agreement"] is None
    assert result["common_four_class_cases"] == 1
    assert result["confusion"]["neutral"]["withheld"] == 1


@pytest.mark.parametrize("fault", ["id", "duplicate", "nan", "label", "threshold"])
def test_reject_malformed_candidate_evidence(fault):
    cases, values = example()
    if fault == "id":
        values[0]["id"] = "foreign"
    elif fault == "duplicate":
        values.append(values[0])
    elif fault == "nan":
        values[0]["scores"]["fearful"] = float("nan")
    elif fault == "label":
        values[0]["scores"]["foreign"] = values[0]["scores"].pop("fearful")
    else:
        values[0]["suggested_label"] = "angry"
    with pytest.raises(ValueError):
        candidate.summarize(cases, values)


def test_candidate_model_must_match_pinned_checksum(tmp_path):
    path = tmp_path / candidate.GRAPH
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="graph checksum"):
        candidate.verify_model(tmp_path)
