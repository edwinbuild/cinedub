"""Deterministic DEMO transcription and stems. Fixtures only; never quality evidence."""

import json
from pathlib import Path

DEMO_MODEL = "deterministic-fixture-v1"
TRANSCRIPT_MODEL = "deterministic-fixture-v2"
STEM_WARNING = (
    "DEMO stems: dialogue is the unseparated source mix and music/effects are synthetic "
    "tones. No separation was performed; do not use for listening or quality review."
)


class FakeTranscriber:
    name = "fake"
    model = TRANSCRIPT_MODEL

    def fixture(self, duration_ms: int) -> dict:
        end = duration_ms / 1000
        return {
            "transcript": "Demonstration transcript.",
            "diarized_transcript": {
                "entries": [
                    {
                        "transcript": "Welcome to CineDub.",
                        "start_time_seconds": 0,
                        "end_time_seconds": end / 2,
                        "speaker_id": "0",
                    },
                    {
                        "transcript": "We can review every line before export.",
                        "start_time_seconds": end / 2,
                        "end_time_seconds": end,
                        "speaker_id": "1",
                    },
                ]
            },
        }


class FakeSeparator:
    """Writes the same three 48 kHz float32 stereo stems the local runner produces."""

    name = "fake"
    model = DEMO_MODEL

    def separate(self, audio_path, output_dir, *, duration_ms, gain_db, cancel, progress):
        from ..media import run_ffmpeg

        cancel()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw = ["-f", "f32le", "-ar", "44100", "-ac", "2", "-i", str(audio_path)]
        tones = {
            "music": "0.02*sin(2*PI*220*t)|0.02*sin(2*PI*330*t)",
            "effects": "0.015*sin(2*PI*880*t)*lt(mod(t,1),0.1)",
        }
        # Dialogue is a plain copy of the source; music/effects keep the source length exactly.
        run_ffmpeg(
            [*raw, "-ar", "48000", "-c:a", "pcm_f32le", str(output_dir / "dialogue.wav")],
            timeout=60,
            cancel=cancel,
        )
        progress(1, 3)
        for index, (name, expression) in enumerate(tones.items(), start=2):
            run_ffmpeg(
                [
                    *raw,
                    "-f",
                    "lavfi",
                    "-i",
                    f"aevalsrc='{expression}':s=44100:c=stereo",
                    "-filter_complex",
                    "[0:a]volume=0[silent];[silent][1:a]amix=inputs=2:duration=first:"
                    "normalize=0,aresample=48000",
                    "-c:a",
                    "pcm_f32le",
                    str(output_dir / f"{name}.wav"),
                ],
                timeout=60,
                cancel=cancel,
            )
            progress(index, 3)
        metadata = {
            "model": self.model,
            "latency_ms": 0,
            "peak_rss_mib": 0,
            "warning": STEM_WARNING,
            "device": "none",
            "demo": True,
            "stems": {name: {"fixture": True} for name in ("dialogue", "music", "effects")},
        }
        (output_dir / "separation-result.json").write_text(json.dumps(metadata))
        return metadata
