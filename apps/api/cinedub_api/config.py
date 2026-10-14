from functools import lru_cache
from pathlib import Path

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
