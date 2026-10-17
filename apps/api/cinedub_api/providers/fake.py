import math
import struct
import wave
from pathlib import Path

from .base import SynthesisResult, TranslationResult, VoiceRegistrationResult


class FakeProvider:
    name = "fake"
    model = "deterministic-fixture-v1"

    _translations = {
        "Welcome to CineDub.": "സിനിഡബിലേക്ക് സ്വാഗതം.",
        "We can review every line before export.": "കയറ്റുമതിക്ക് മുമ്പ് ഓരോ വരിയും പരിശോധിക്കാം.",
        "The timing and delivery stay editable.": "സമയക്രമവും അവതരണവും തിരുത്താനാകും.",
        "This is a deterministic demonstration.": "ഇത് സ്ഥിരതയുള്ള ഒരു പ്രദർശനമാണ്.",
    }

    def register_voice(
        self, reference_path: Path, name: str, language: str
    ) -> VoiceRegistrationResult:
        import hashlib

        identity = hashlib.sha256(reference_path.read_bytes()).hexdigest()[:20]
        return VoiceRegistrationResult(
            f"demo-{identity}", self.name, self.model, "DEMO: no voice was cloned"
        )

    def delete_voice(self, voice_id: str) -> None:
        if not voice_id.startswith("demo-"):
            raise ValueError("Not a demo voice")

    def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        translated = self._translations.get(text, f"[പരിശോധിക്കുക] {text}")
        return TranslationResult(text=translated, provider=self.name, model=self.model)

    def synthesize(
        self,
        text: str,
        language: str,
        output_path: Path,
        *,
        voice_id: str | None,
        voice_kind: str = "preset",
        pace: float = 1.0,
        variation: float | None = None,
    ) -> SynthesisResult:
        if variation is not None:
            raise ValueError("Demo tones do not support speech generation variation")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 24_000
        duration = max(0.7, min(4.0, len(text) / 15))
        frames = int(sample_rate * duration)
        frequency = 220 if voice_id != "speaker-b" else 174
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for index in range(frames):
                envelope = min(1.0, index / 600, (frames - index) / 600)
                value = int(
                    2_200 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate)
                )
                wav.writeframesraw(struct.pack("<h", value))
        return SynthesisResult(audio_path=output_path, provider=self.name, model=self.model)
