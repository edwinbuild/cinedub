from dataclasses import dataclass

from ..config import Settings
from .fake import FakeProvider
from .sarvam import SarvamProvider


@dataclass(frozen=True)
class Capability:
    capability: str
    selected_provider: str
    available: bool
    reason: str | None = None


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def translator(self, name: str | None = None):
        selected = name or self.settings.translator
        if selected == "fake":
            return FakeProvider()
        if selected == "sarvam":
            return SarvamProvider(self.settings.sarvam_api_key or "", self.settings.sarvam_base_url)
        raise ValueError(f"Translator provider '{selected}' is not installed")

    def voice_synthesizer(self, name: str | None = None):
        selected = name or self.settings.voice_synthesizer
        if selected == "fake":
            return FakeProvider()
        if selected == "sarvam":
            return SarvamProvider(self.settings.sarvam_api_key or "", self.settings.sarvam_base_url)
        raise ValueError(f"Voice provider '{selected}' is not installed")

    def capabilities(self) -> list[Capability]:
        sarvam_ready = bool(self.settings.sarvam_api_key)
        values = {
            "transcriber": self.settings.transcriber,
            "speaker_diarizer": self.settings.diarizer,
            "translator": self.settings.translator,
            "voice_synthesizer": self.settings.voice_synthesizer,
            "performance_analyzer": self.settings.performance_analyzer,
            "stem_separator": self.settings.stem_separator,
            "timing_aligner": self.settings.timing_aligner,
            "media_exporter": "local",
        }
        implemented = {
            ("transcriber", "fake"),
            ("speaker_diarizer", "fake"),
            ("translator", "fake"),
            ("translator", "sarvam"),
            ("voice_synthesizer", "fake"),
            ("voice_synthesizer", "sarvam"),
            ("performance_analyzer", "local"),
            ("media_exporter", "local"),
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
            result.append(Capability(capability, provider, available, reason))
        return result
