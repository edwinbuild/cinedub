import base64
import math
import re
from pathlib import Path

import httpx

from .base import SynthesisResult, TranslationResult, VoiceRegistrationResult


class SarvamProvider:
    name = "sarvam"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "mayura:v1",
        style: str = "modern-colloquial",
    ) -> None:
        if not api_key:
            raise ValueError("SARVAM_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.style = style

    @property
    def headers(self) -> dict[str, str]:
        return {"api-subscription-key": self.api_key}

    def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        response = httpx.post(
            f"{self.base_url}/translate",
            headers=self.headers,
            json={
                "input": text,
                "source_language_code": source_language,
                "target_language_code": target_language,
                "model": self.model,
                "mode": self.style if self.model == "mayura:v1" else "formal",
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        return TranslationResult(
            text=payload["translated_text"],
            provider=self.name,
            model=self.model,
            request_id=payload.get("request_id"),
        )

    def synthesize(
        self,
        text: str,
        language: str,
        output_path: Path,
        *,
        voice_id: str | None,
        voice_kind: str = "clone",
        pace: float = 1.0,
        variation: float | None = None,
    ) -> SynthesisResult:
        if variation is not None and (
            voice_kind != "preset" or not math.isfinite(variation) or not 0.01 <= variation <= 1
        ):
            raise ValueError(
                "Generation variation requires a stock voice and a value from 0.01 to 1"
            )
        if not voice_id:
            raise ValueError("A saved Sarvam voice_id is required for consented cloning")
        if voice_kind == "preset":
            response = httpx.post(
                f"{self.base_url}/text-to-speech",
                headers=self.headers,
                json={
                    "text": text,
                    "language_code": language,
                    "speaker": voice_id,
                    "model": "bulbul:v3",
                    "pace": pace,
                    "temperature": variation if variation is not None else 0.6,
                    "speech_sample_rate": 24000,
                    "output_audio_codec": "wav",
                },
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            audios = payload.get("audios", [])
            if len(audios) != 1:
                raise ValueError("Expected one audio result for a single synthesis input")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(base64.b64decode(audios[0], validate=True))
            return SynthesisResult(
                audio_path=output_path,
                provider=self.name,
                model="bulbul:v3",
                request_id=payload.get("request_id"),
            )
        if voice_kind != "clone":
            raise ValueError("Unsupported voice kind")
        if len(text) > 1000:
            raise ValueError("Cloned voice input exceeds 1000 characters")
        response = httpx.post(
            f"{self.base_url}/voices/clone",
            headers=self.headers,
            files={
                key: (None, value)
                for key, value in {
                    "voice_id": voice_id,
                    "text": text,
                    "language_code": language,
                    "pace": str(pace),
                    "enable_qc": "true",
                    "output_audio_codec": "wav",
                    "speech_sample_rate": "24000",
                }.items()
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(
            base64.b64decode(payload.get("audio_b64") or payload["audio"], validate=True)
        )
        return SynthesisResult(
            audio_path=output_path,
            provider=self.name,
            model="sarvam-voice-cloning-beta",
            request_id=payload.get("request_id"),
        )

    def register_voice(
        self, reference_path: Path, name: str, language: str
    ) -> VoiceRegistrationResult:
        with reference_path.open("rb") as audio:
            response = httpx.post(
                f"{self.base_url}/voices/create",
                headers=self.headers,
                data={"name": name[:100], "language": language},
                files={"file": ("reference.wav", audio, "audio/wav")},
                timeout=120,
            )
        response.raise_for_status()
        payload = response.json()
        values = payload.get("data", {})
        voice_id = values.get("voice_id", "")
        if payload.get("status") != "success" or not re.fullmatch(
            r"svc-[A-Za-z0-9-]{1,100}", voice_id
        ):
            raise ValueError("Voice registration returned an invalid saved voice identifier")
        return VoiceRegistrationResult(
            voice_id,
            self.name,
            "sarvam-voice-cloning-beta",
            values.get("reference_text", ""),
            payload.get("request_id"),
        )

    def delete_voice(self, voice_id: str) -> None:
        if not re.fullmatch(r"svc-[A-Za-z0-9-]{1,100}", voice_id):
            raise ValueError("Invalid saved voice identifier")
        response = httpx.delete(
            f"{self.base_url}/voices/delete/{voice_id}", headers=self.headers, timeout=45
        )
        if response.status_code != 404:
            response.raise_for_status()
