import copy
import json
from types import SimpleNamespace

import pytest
from cinedub_api.local_asr_profile import OPTIONS, build_profile, validate_result
from cinedub_api.local_asr_runner import decoder_evidence
from cinedub_api.providers.local_asr import LocalTranscriber


@pytest.fixture
def profile(monkeypatch):
    monkeypatch.setattr("cinedub_api.local_asr_profile.runtime_versions", lambda: {"fixture": "v1"})
    return build_profile(4)


def result(profile):
    return {
        "diarized_transcript": {"entries": [{"start_time_seconds": 0, "end_time_seconds": 1}]},
        "local_metadata": {
            "model": profile["model"],
            "asr_profile": profile,
            "sampling_segments": 1,
            "decoder_segments": [
                {
                    "index": 0,
                    "start": 0,
                    "end": 1,
                    "temperature": 0.4,
                    "avg_logprob": -0.2,
                    "compression_ratio": 1.1,
                    "no_speech_prob": 0.01,
                }
            ],
        },
    }


def test_profile_is_serializable_isolated_and_preserves_sampling_behavior(profile):
    assert json.loads(json.dumps(profile, allow_nan=False)) == profile
    assert profile["transcribe_options"]["temperature"] == [0, 0.2, 0.4, 0.6, 0.8, 1]
    profile["transcribe_options"]["temperature"].append(99)
    assert 99 not in OPTIONS["temperature"]
    assert build_profile()["transcribe_options"]["initial_prompt"] is None


def test_constructor_rejects_changed_runtime_and_does_not_alias_job_profile(profile, tmp_path):
    provider = LocalTranscriber(tmp_path, profile=profile)
    profile["runtime_versions"]["fixture"] = "changed"
    assert provider.profile["runtime_versions"]["fixture"] == "v1"
    with pytest.raises(ValueError, match="changed"):
        LocalTranscriber(tmp_path, profile=profile)


def test_actual_segment_sampling_summary_is_checked(profile):
    payload = result(profile)
    validate_result(payload, profile)
    payload["local_metadata"]["decoder_segments"][0]["temperature"] = 0
    payload["local_metadata"]["sampling_segments"] = 0
    validate_result(payload, profile)


def test_native_scalar_diagnostics_are_canonical_json_numbers(profile):
    class NativeFloat(float):
        pass

    raw = SimpleNamespace(
        start=NativeFloat(0),
        end=NativeFloat(1),
        temperature=NativeFloat(0.4),
        avg_logprob=NativeFloat(-0.2),
        compression_ratio=NativeFloat(1.1),
        no_speech_prob=NativeFloat(0.01),
    )
    evidence = decoder_evidence(raw, 0)
    assert all(type(value) is float for key, value in evidence.items() if key != "index")
    payload = result(profile)
    payload["local_metadata"]["decoder_segments"] = [evidence]
    validate_result(payload, profile)
    raw.avg_logprob = float("nan")
    payload["local_metadata"]["decoder_segments"] = [decoder_evidence(raw, 0)]
    with pytest.raises(ValueError, match="finite"):
        validate_result(payload, profile)


def test_model_hashes_must_match_frozen_job(profile):
    payload = result(profile)
    payload["local_metadata"]["model_sha256"] = {"model.bin": "actual"}
    validate_result(payload, profile, {"model.bin": "actual"})
    with pytest.raises(ValueError, match="model hashes"):
        validate_result(payload, profile, {"model.bin": "different"})


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "model",
        "missing",
        "time",
        "nan",
        "temperature",
        "probability",
        "count",
        "index",
        "structure",
    ],
)
def test_forged_or_incomplete_decoder_evidence_is_rejected(profile, fault):
    payload = result(copy.deepcopy(profile))
    metadata = payload["local_metadata"]
    segment = metadata["decoder_segments"][0]
    if fault == "profile":
        metadata["asr_profile"]["version"] = "foreign"
    elif fault == "model":
        metadata["model"] = "foreign"
    elif fault == "missing":
        metadata["decoder_segments"] = []
    elif fault == "time":
        segment["end"] = 2
    elif fault == "nan":
        segment["avg_logprob"] = float("nan")
    elif fault == "temperature":
        segment["temperature"] = 0.3
    elif fault == "probability":
        segment["no_speech_prob"] = 1.1
    elif fault == "count":
        metadata["sampling_segments"] = 0
    elif fault == "index":
        segment["index"] = True
    else:
        payload["local_metadata"] = None
    with pytest.raises(ValueError):
        validate_result(payload, profile)
