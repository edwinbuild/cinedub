"""Bounded offline inference entrypoint; invoked only by the worker adapter."""

import argparse
import copy
import json
import resource
import time
import wave
from pathlib import Path

from .local_asr_profile import build_profile, validate_result
from .providers.local_asr import MODEL_NAME, read_manifest


def decoder_evidence(segment, index):
    # VAD restoration can retain NumPy scalars; validate canonical JSON numbers.
    return {
        "index": index,
        "start": float(segment.start),
        "end": float(segment.end),
        "temperature": float(segment.temperature),
        "avg_logprob": float(segment.avg_logprob),
        "compression_ratio": float(segment.compression_ratio),
        "no_speech_prob": float(segment.no_speech_prob),
    }


def run(model_dir: Path, audio: Path, output: Path, threads: int, profile=None) -> dict:
    profile = build_profile(threads) if profile is None else profile
    if profile != build_profile(threads):
        raise ValueError("Local ASR profile/runtime differs from the scheduled request")
    installation = read_manifest(model_dir, verify=True)
    # Linux-only application profile. Cap virtual memory and native thread count.
    memory_limit = 10 * 1024**3
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
    import numpy as np
    import onnxruntime
    from faster_whisper import WhisperModel

    onnxruntime.disable_telemetry_events()

    # Ingest already produces canonical PCM. Avoid re-decoding arbitrary containers
    # or relying on version-sensitive PyAV options inside the model library.
    with wave.open(str(audio), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError("Local ASR requires prepared 16 kHz mono PCM16 audio")
        if source.getnframes() > 120 * 16000:
            raise ValueError("Local ASR scene exceeds the two-minute laptop profile")
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(
            np.float32
        )
        samples /= 32768.0

    started = time.monotonic()
    model = WhisperModel(
        str(model_dir),
        **copy.deepcopy(profile["model_options"]),
    )
    segments, info = model.transcribe(
        samples,
        **copy.deepcopy(profile["transcribe_options"]),
    )
    entries, words, decoding = [], [], []
    for segment in segments:
        decoding.append(decoder_evidence(segment, len(entries)))
        entries.append(
            {
                "transcript": segment.text.strip(),
                "start_time_seconds": segment.start,
                "end_time_seconds": segment.end,
                "speaker_id": None,
            }
        )
        words.extend(
            {
                "word": word.word,
                "start": word.start,
                "end": word.end,
                "probability": word.probability,
            }
            for word in segment.words or []
        )
    payload = {
        "transcript": " ".join(entry["transcript"] for entry in entries),
        "diarized_transcript": {"entries": entries},
        "words": words,
        "local_metadata": {
            "model": MODEL_NAME,
            "asr_profile": profile,
            "model_sha256": installation["sha256"],
            "decoder_segments": decoding,
            "sampling_segments": sum(segment["temperature"] > 0 for segment in decoding),
            "device": "cpu",
            "compute_type": "int8",
            "threads": threads,
            "diarization": False,
            "word_timing": "whisper-estimated (not forced alignment)",
            "language": info.language,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        },
    }
    if read_manifest(model_dir, verify=True) != installation or build_profile(threads) != profile:
        raise ValueError("Local ASR installation or runner/runtime changed during inference")
    validate_result(payload, profile, installation["sha256"])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--profile", type=Path, required=True)
    arguments = parser.parse_args()
    run(
        arguments.model_dir,
        arguments.audio,
        arguments.output,
        arguments.threads,
        json.loads(arguments.profile.read_text(encoding="utf-8")),
    )
