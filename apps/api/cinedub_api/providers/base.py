from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TranslationResult:
    text: str
    provider: str
    model: str
    request_id: str | None = None


@dataclass(frozen=True)
class SynthesisResult:
    audio_path: Path
    provider: str
    model: str
    request_id: str | None = None


class Translator(Protocol):
    name: str

    def translate(
        self, text: str, source_language: str, target_language: str
    ) -> TranslationResult: ...


class VoiceSynthesizer(Protocol):
    name: str

    def synthesize(
        self,
        text: str,
        language: str,
        output_path: Path,
        *,
        voice_id: str | None,
    ) -> SynthesisResult: ...
