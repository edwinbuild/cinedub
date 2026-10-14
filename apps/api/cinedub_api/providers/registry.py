from dataclasses import dataclass

from ..config import Settings
from .fake import FakeProvider
from .local_asr import LocalTranscriber, availability
from .local_separation import LocalSeparator
from .local_separation import availability as separator_availability
from .sarvam import SarvamProvider
from .transcription import SarvamTranscriber


@dataclass(frozen=True)
class Capability:
    capability: str
    selected_provider: str
    available: bool
    reason: str | None = None
    configured: bool = False
    implemented: bool = False
    verified: bool = False


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def translator(self, name: str | None = None):
        selected = name or self.settings.translator
        if selected == "fake":
            return FakeProvider()
        if selected == "sarvam":
            return SarvamProvider(
                self.settings.sarvam_api_key or "",
                self.settings.sarvam_base_url,
                self.settings.translation_model,
                self.settings.translation_style,
            )
        raise ValueError(f"Translator provider '{selected}' is not installed")

    def voice_synthesizer(self, name: str | None = None):
        selected = name or self.settings.voice_synthesizer
        if selected == "fake":
            return FakeProvider()
        if selected == "sarvam":
            return SarvamProvider(self.settings.sarvam_api_key or "", self.settings.sarvam_base_url)
        raise ValueError(f"Voice provider '{selected}' is not installed")

    def voice_cloner(self, name: str | None = None):
        return self.voice_synthesizer(name)

    def stem_separator(self, name: str | None = None, options: dict | None = None):
        if (name or self.settings.stem_separator) != "local":
            raise ValueError("This stem separator adapter is not installed")
        values = options or {}
        return LocalSeparator(
            values.get("model_dir", self.settings.local_separator_model_dir),
            values.get("threads", self.settings.local_separator_threads),
            values.get("timeout_seconds", self.settings.local_separator_timeout_seconds),
        )

    def transcriber(self, name: str | None = None, options: dict | None = None):
        selected = name or self.settings.transcriber
        if selected == "local":
            from pathlib import Path

            values = options or {}
            return LocalTranscriber(
                Path(values.get("local_model_dir", self.settings.local_asr_model_dir)),
                values.get("threads", self.settings.local_asr_threads),
                values.get("timeout_seconds", self.settings.local_asr_timeout_seconds),
            )
        if selected == "sarvam":
            return SarvamTranscriber(
                self.settings.sarvam_api_key or "", self.settings.sarvam_base_url
            )
        raise ValueError(f"Batch transcription provider '{selected}' is unavailable")

    def capabilities(self) -> list[Capability]:
        sarvam_ready = bool(self.settings.sarvam_api_key)
        values = {
            "transcriber": self.settings.transcriber,
            "speaker_diarizer": self.settings.transcriber,
            "translator": self.settings.translator,
            "voice_synthesizer": self.settings.voice_synthesizer,
            "voice_cloner": self.settings.voice_synthesizer,
            "performance_analyzer": self.settings.performance_analyzer,
            "stem_separator": self.settings.stem_separator,
            "timing_aligner": self.settings.timing_aligner,
            "media_exporter": "local",
        }
        implemented = {
            ("transcriber", "fake"),
            ("transcriber", "sarvam"),
            ("transcriber", "local"),
            ("speaker_diarizer", "fake"),
            ("speaker_diarizer", "sarvam"),
            ("translator", "fake"),
            ("translator", "sarvam"),
            ("voice_synthesizer", "fake"),
            ("voice_synthesizer", "sarvam"),
            ("voice_cloner", "fake"),
            ("voice_cloner", "sarvam"),
            ("media_exporter", "local"),
            ("stem_separator", "local"),
        }
        result = []
        for capability, provider in values.items():
            available = (capability, provider) in implemented
            reason = None
            if provider == "sarvam" and not sarvam_ready:
                available = False
                reason = "SARVAM_API_KEY is not configured"
            elif not available:
                reason = "Adapter contract exists; runtime integration is not installed yet"
            if capability == "transcriber" and provider == "local":
                available, reason = availability(self.settings.local_asr_model_dir)
            if capability == "stem_separator" and provider == "local":
                available, reason = separator_availability(self.settings.local_separator_model_dir)
            is_implemented = (capability, provider) in implemented
            configured = provider != "sarvam" or sarvam_ready
            if provider == "sarvam" and available:
                reason = "Configured adapter; live success is recorded per provider job"
            if capability == "performance_analyzer":
                reason = "Not implemented; demo emotion values are fixtures"
            if capability == "speaker_diarizer" and available:
                reason = "Diarization is part of the selected batch transcriber"
            if capability == "voice_synthesizer" and provider == "sarvam" and available:
                reason = "Bulbul v3 stock voices or explicitly selected consented clones"
            if capability == "voice_cloner" and available:
                reason = (
                    "DEMO only: tones, no real cloning"
                    if provider == "fake"
                    else "Beta; consent, reference review and explicit provider upload required"
                )
            if capability == "media_exporter":
                reason = (
                    "Subtitles, dialogue previews and reviewed stereo music/effects mix exports"
                )
            result.append(
                Capability(
                    capability, provider, available, reason, configured, is_implemented, False
                )
            )
        return result
