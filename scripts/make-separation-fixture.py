"""Original synthetic speech, procedural music and effects with known reference stems."""

import argparse
import json
import subprocess
import wave
from pathlib import Path

import numpy as np


def write_audio(path, samples, rate=44100):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/evaluation/separation"))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    spoken = args.directory / "original-speech.wav"
    text = (
        "Welcome to our cinema workshop. Please review every line before export. "
        "The music should stay in the background. Keep the original sound effects, "
        "but replace this dialogue with our approved Malayalam translation."
    )
    subprocess.run(["espeak-ng", "-v", "en-us", "-s", "135", "-w", str(spoken), text], check=True)
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(spoken),
            "-ar",
            "44100",
            "-ac",
            "1",
            "-f",
            "f32le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    voice = np.frombuffer(decoded.stdout, dtype="<f4")
    length = len(voice) + 44100 * 3
    dialogue = np.zeros((length, 2), dtype=np.float32)
    dialogue[44100 : 44100 + len(voice)] = voice[:, None] * 0.7
    times = np.arange(length) / 44100
    music = np.zeros_like(dialogue)
    # Procedural chords with attack/release and a changing melody, not downloaded music.
    for index, root in enumerate([130.81, 174.61, 196, 146.83] * 4):
        start, end = index * 2, min(index * 2 + 2, length / 44100)
        ids = (times >= start) & (times < end)
        local = times[ids] - start
        envelope = np.minimum(1, np.minimum(local / 0.1, (2 - local) / 0.2))
        chord = sum(np.sin(2 * np.pi * root * ratio * local) for ratio in [1, 1.25, 1.5]) * 0.025
        music[ids, 0] = chord * envelope
        music[ids, 1] = (
            chord * envelope * 0.8 + np.sin(2 * np.pi * root * 2 * local) * 0.008 * envelope
        )
    effects = np.zeros_like(dialogue)
    rng = np.random.default_rng(105)
    for seconds, channel in [(2.5, 0), (7.5, 1), (12.5, 0), (17.5, 1)]:
        start = round(seconds * 44100)
        frames = min(11025, length - start)
        if frames > 0:
            hit = rng.normal(0, 0.09, frames) * np.exp(-np.arange(frames) / 1500)
            effects[start : start + frames, channel] += hit
    mixture = dialogue + music + effects
    for name, samples in [
        ("dialogue", dialogue),
        ("music", music),
        ("effects", effects),
        ("mixture", mixture),
    ]:
        write_audio(args.directory / f"{name}.wav", samples)
    (args.directory / "fixture.json").write_text(
        json.dumps(
            {
                "license": "Original procedural fixture; no actor recording or downloaded sound",
                "duration_ms": round(length / 44100 * 1000),
                "sample_rate": 44100,
                "speech": "eSpeak NG synthetic English",
                "text": text,
                "warning": "Controlled-separation evaluation only, not cinematic quality",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Original separation fixture: {args.directory}")


if __name__ == "__main__":
    main()
