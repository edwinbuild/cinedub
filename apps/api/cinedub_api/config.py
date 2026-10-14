from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CINEDUB_",
        extra="ignore",
    )

    env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    database_url: str = "sqlite:///./data/cinedub.db"
    storage_root: Path = Path("./data/storage")
    web_origin: str = "http://127.0.0.1:3000"
    max_upload_bytes: int = 1_073_741_824
    max_duration_seconds: int = 120

    transcriber: str = "fake"
    diarizer: str = "fake"
    translator: str = "fake"
    voice_synthesizer: str = "fake"
    performance_analyzer: str = "local"
    stem_separator: str = "local"
    timing_aligner: str = "local"
    transcription_model: Literal["saaras:v4", "saaras:v3"] = "saaras:v4"
    translation_model: Literal["mayura:v1", "sarvam-translate:v1"] = "mayura:v1"
    translation_style: Literal[
        "formal", "modern-colloquial", "classic-colloquial", "code-mixed"
    ] = "modern-colloquial"
    project_budget_inr: float = Field(default=50.0, gt=0)
    stt_diarization_inr_per_hour: float = Field(default=45.0, ge=0)
    translation_inr_per_10k_chars: float = Field(default=20.0, ge=0)
    provider_poll_seconds: float = Field(default=5.0, gt=0)
    provider_timeout_seconds: int = Field(default=600, gt=0)
    synthesis_model: Literal["bulbul:v3"] = "bulbul:v3"
    synthesis_inr_per_10k_chars: float = Field(default=30.0, ge=0)
    max_timing_speedup: float = Field(default=1.15, ge=1, le=1.25)
    local_asr_model_dir: Path = Path("./models/faster-whisper-small.en")
    local_asr_threads: int = Field(default=4, ge=1, le=8)
    local_asr_timeout_seconds: int = Field(default=600, ge=10, le=1800)
    local_separator_model_dir: Path = Path("./models/mrx")
    local_separator_threads: int = Field(default=4, ge=1, le=8)
    local_separator_timeout_seconds: int = Field(default=900, ge=10, le=1800)

    sarvam_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SARVAM_API_KEY", "CINEDUB_SARVAM_API_KEY"),
    )
    sarvam_base_url: str = Field(
        default="https://api.sarvam.ai",
        validation_alias=AliasChoices("SARVAM_BASE_URL", "CINEDUB_SARVAM_BASE_URL"),
    )

    def ensure_directories(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
