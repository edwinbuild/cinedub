"""Bounded offline inference entrypoint; invoked only by the worker adapter."""

import argparse
import json
import resource
import time
import wave
from pathlib import Path

from .providers.local_asr import MODEL_NAME, read_manifest


def run(model_dir: Path, audio: Path, output: Path, threads: int) -> dict:
    read_manifest(model_dir, verify=True)
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
        device="cpu",
        compute_type="int8",
        cpu_threads=threads,
        num_workers=1,
        local_files_only=True,
    )
    segments, info = model.transcribe(
        samples,
        language="en",
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    entries, words = [], []
    for segment in segments:
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
    arguments = parser.parse_args()
    run(arguments.model_dir, arguments.audio, arguments.output, arguments.threads)
