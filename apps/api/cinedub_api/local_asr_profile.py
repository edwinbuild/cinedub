"""Versioned English decoding inputs and output provenance; no native imports."""

import copy
import hashlib
import math
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

MODEL_ID = "Systran/faster-whisper-small.en"
MODEL_REVISION = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
MODEL_NAME = f"{MODEL_ID}@{MODEL_REVISION}"
OPTIONS = {
    "language": "en",
    "task": "transcribe",
    "log_progress": False,
    "beam_size": 5,
    "best_of": 5,
    "patience": 1,
    "length_penalty": 1,
    "repetition_penalty": 1,
    "no_repeat_ngram_size": 0,
    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "compression_ratio_threshold": 2.4,
    "log_prob_threshold": -1.0,
    "no_speech_threshold": 0.6,
    "condition_on_previous_text": False,
    "prompt_reset_on_temperature": 0.5,
    "initial_prompt": None,
    "prefix": None,
    "suppress_blank": True,
    "suppress_tokens": [-1],
    "without_timestamps": False,
    "max_initial_timestamp": 1.0,
    "word_timestamps": True,
    "prepend_punctuations": "\"'“¿([{-",
    "append_punctuations": "\"'.。,，!！?？:：”)]}、",
    "multilingual": False,
    "vad_filter": True,
    "vad_parameters": {"min_silence_duration_ms": 500},
    "max_new_tokens": None,
    "chunk_length": None,
    "clip_timestamps": "0",
    "hallucination_silence_threshold": None,
    "hotwords": None,
    "language_detection_threshold": 0.5,
    "language_detection_segments": 1,
}


def runtime_versions():
    try:
        return {
            name: version(name)
            for name in ("faster-whisper", "ctranslate2", "onnxruntime", "numpy")
        }
    except PackageNotFoundError as error:
        raise ValueError("Local ASR runtime is incomplete; install the local-asr extra") from error


def build_profile(threads=4):
    if type(threads) is not int or not 1 <= threads <= 8:
        raise ValueError("Local ASR requires 1–8 CPU threads")
    return {
        "version": "english-asr-v1",
        "model": MODEL_NAME,
        "runner_sha256": hashlib.sha256(
            Path(__file__).with_name("local_asr_runner.py").read_bytes()
        ).hexdigest(),
        "runtime_versions": runtime_versions(),
        "random_seed": None,
        "model_options": {
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": threads,
            "num_workers": 1,
            "local_files_only": True,
        },
        "transcribe_options": copy.deepcopy(OPTIONS),
    }


def validate_result(payload, profile, model_hashes=None):
    if not isinstance(payload, dict) or not isinstance(payload.get("local_metadata"), dict):
        raise ValueError("Local ASR output has no structured decoding metadata")
    metadata = payload.get("local_metadata", {})
    if metadata.get("model") != profile["model"] or metadata.get("asr_profile") != profile:
        raise ValueError("Local ASR output decoding/model provenance differs from the frozen job")
    if model_hashes is not None and metadata.get("model_sha256") != model_hashes:
        raise ValueError("Local ASR output model hashes differ from the frozen installation")
    transcript = payload.get("diarized_transcript")
    if not isinstance(transcript, dict):
        raise ValueError("Local ASR output has no structured transcript windows")
    entries = transcript.get("entries", [])
    evidence = metadata.get("decoder_segments", [])
    if (
        not isinstance(entries, list)
        or not isinstance(evidence, list)
        or len(entries) != len(evidence)
    ):
        raise ValueError("Local ASR segment decoding evidence is incomplete")
    sampling = 0
    for index, (entry, segment) in enumerate(zip(entries, evidence, strict=True)):
        if not isinstance(entry, dict) or not isinstance(segment, dict):
            raise ValueError("Local ASR segment evidence is malformed")
        if segment.get("index") != index or (segment.get("start"), segment.get("end")) != (
            entry.get("start_time_seconds"),
            entry.get("end_time_seconds"),
        ):
            raise ValueError("Local ASR decoding evidence does not match transcript windows")
        if type(segment.get("index")) is not int:
            raise ValueError("Local ASR decoding index must be an integer")
        for key in (
            "start",
            "end",
            "temperature",
            "avg_logprob",
            "compression_ratio",
            "no_speech_prob",
        ):
            value = segment.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Local ASR decoding evidence must be finite")
        if segment["temperature"] not in profile["transcribe_options"]["temperature"]:
            raise ValueError("Local ASR used an unapproved decoding temperature")
        if not 0 <= segment["no_speech_prob"] <= 1 or segment["compression_ratio"] < 0:
            raise ValueError("Local ASR decoding diagnostics are outside their valid range")
        if not 0 <= segment["start"] <= segment["end"]:
            raise ValueError("Local ASR decoding window is invalid")
        sampling += segment["temperature"] > 0
    if (
        type(metadata.get("sampling_segments")) is not int
        or metadata.get("sampling_segments") != sampling
    ):
        raise ValueError("Local ASR sampling summary differs from segment evidence")
