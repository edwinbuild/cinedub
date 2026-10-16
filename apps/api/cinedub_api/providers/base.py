from collections.abc import Callable
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


@dataclass(frozen=True)
class VoiceRegistrationResult:
    voice_id: str
    provider: str
    model: str
    reference_text: str = ""
    request_id: str | None = None


class VoiceCloner(Protocol):
    name: str

    def register_voice(
        self, reference_path: Path, name: str, language: str
    ) -> VoiceRegistrationResult: ...
    def delete_voice(self, voice_id: str) -> None: ...


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
        voice_kind: str = "preset",
        pace: float = 1.0,
    ) -> SynthesisResult: ...


class BatchTranscriber(Protocol):
    name: str

    def create(self, model: str, language: str, num_speakers: int | None) -> str: ...
    def upload(self, job_id: str, audio_path: Path) -> None: ...
    def start(self, job_id: str) -> None: ...
    def status(self, job_id: str) -> str: ...
    def result(self, job_id: str, output_dir: Path) -> dict: ...


class OfflineTranscriber(Protocol):
    name: str

    def transcribe(
        self, audio_path: Path, output_dir: Path, cancel: Callable[[], None]
    ) -> dict: ...


class StemSeparator(Protocol):
    name: str

    def separate(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        duration_ms: int,
        gain_db: float,
        cancel: Callable[[], None],
        progress: Callable[[int, int], None],
    ) -> dict: ...


class Aligner(Protocol):
    name: str

    def align(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        lines: list[dict],
        duration_ms: int,
        language: str,
        cancel: Callable[[], None],
        progress: Callable[[int, int], None],
    ) -> dict: ...


class PerformanceAnalyzer(Protocol):
    name: str

    def analyze(self, samples, *, offset_ms: int, word_count: int) -> dict: ...


class TakePerformanceAnalyzer(Protocol):
    name: str

    def compare(
        self,
        request: dict,
        output_dir: Path,
        *,
        cancel: Callable[[], None],
        progress: Callable[[int, int], None],
    ) -> dict: ...


class DialogueAdapter(Protocol):
    name: str

    def adapt(
        self,
        request: dict,
        output_dir: Path,
        *,
        cancel: Callable[[], None],
        progress: Callable[[list[dict]], None],
    ) -> dict: ...


class EmotionAnalyzer(Protocol):
    name: str

    def analyze(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        windows: list[dict],
        duration_ms: int,
        language: str,
        cancel: Callable[[], None],
        progress: Callable[[int, int], None],
    ) -> dict: ...
