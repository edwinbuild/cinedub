"""Original speech/tone/silence controls; validates execution, not emotion accuracy."""

import json
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from cinedub_api.providers.local_emotion import LocalEmotionAnalyzer


def main():
    root = Path("data/evaluation")
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="speech-emotion-", dir=root)).resolve()
    speech = directory / "original-synthetic-speech.wav"
    recording = subprocess.run(
        [
            "espeak-ng",
            "-v",
            "en-us",
            "-s",
            "145",
            "--stdout",
            "Please listen carefully. We should leave before the rain starts.",
        ],
        capture_output=True,
        check=True,
    ).stdout
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(speech),
        ],
        input=recording,
        capture_output=True,
        check=True,
    )
    with wave.open(str(speech), "rb") as handle:
        data = handle.readframes(handle.getnframes())
    data += b"\x00" * ((-len(data)) % 32)
    speech_ms = len(data) // 32
    tone = b"".join(
        struct.pack("<h", round(3200 * math.sin(2 * math.pi * 220 * index / 16000)))
        for index in range(32000)
    )
    audio = directory / "controls.wav"
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(data + tone + b"\x00" * 64000)
    windows = [
        {"id": "synthetic-speech", "start_ms": 0, "end_ms": speech_ms, "overlap": False},
        {"id": "tone-control", "start_ms": speech_ms, "end_ms": speech_ms + 2000, "overlap": False},
        {
            "id": "silence-control",
            "start_ms": speech_ms + 2000,
            "end_ms": speech_ms + 4000,
            "overlap": False,
        },
    ]
    result = LocalEmotionAnalyzer(Path("models/speech-emotion")).analyze(
        audio,
        directory,
        windows=windows,
        duration_ms=speech_ms + 4000,
        language="en-IN",
        cancel=lambda: None,
        progress=lambda completed, total: print(f"Classified {completed}/{total}", flush=True),
    )
    print(json.dumps({"output_directory": str(directory), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
