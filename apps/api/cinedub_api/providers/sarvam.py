import base64
from pathlib import Path

import httpx

from .base import SynthesisResult, TranslationResult


class SarvamProvider:
    name = "sarvam"

    def __init__(self, api_key: str, base_url: str) -> None:
        if not api_key:
            raise ValueError("SARVAM_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

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
                "model": "sarvam-translate:v1",
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        return TranslationResult(
            text=payload["translated_text"],
            provider=self.name,
            model="sarvam-translate:v1",
            request_id=payload.get("request_id"),
        )

    def synthesize(
        self,
        text: str,
        language: str,
        output_path: Path,
        *,
        voice_id: str | None,
    ) -> SynthesisResult:
        if not voice_id:
            raise ValueError("A saved Sarvam voice_id is required for consented cloning")
        response = httpx.post(
            f"{self.base_url}/voices/clone",
            headers=self.headers,
            data={"voice_id": voice_id, "text": text, "language_code": language},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(payload["audio"], validate=True))
        return SynthesisResult(
            audio_path=output_path,
            provider=self.name,
            model="sarvam-voice-cloning",
            request_id=payload.get("request_id"),
        )
