"""Startup configuration validation. Messages name settings, never their values."""

from urllib.parse import urlparse

from .config import Settings

ROUTED = (
    "transcriber",
    "translator",
    "dialogue_adapter",
    "emotion_analyzer",
    "voice_synthesizer",
    "performance_analyzer",
    "stem_separator",
    "timing_aligner",
    "target_timing_aligner",
)


class ConfigurationError(RuntimeError):
    """The service must not start with this configuration."""


def validate_settings(settings: Settings) -> list[str]:
    """Return non-fatal warnings; raise ConfigurationError for fatal problems."""
    errors, warnings = [], []
    production = settings.env == "production"
    origin = urlparse(settings.web_origin)
    if origin.scheme not in {"http", "https"} or not origin.netloc:
        errors.append("CINEDUB_WEB_ORIGIN must be an http(s) origin")
    if not settings.database_url.startswith(("sqlite:///", "postgresql")):
        errors.append("CINEDUB_DATABASE_URL must be a SQLite or PostgreSQL URL")
    if settings.storage_root.exists() and not settings.storage_root.is_dir():
        errors.append("CINEDUB_STORAGE_ROOT must be a directory")
    sarvam = [name for name in ROUTED if getattr(settings, name) == "sarvam"]
    if sarvam and not settings.sarvam_api_key:
        message = "SARVAM_API_KEY is not configured; these stages are unavailable: " + ", ".join(
            sarvam
        )
        (errors if production else warnings).append(message)
    demo = [name for name in ROUTED if getattr(settings, name) == "fake"]
    if demo and not settings.demo_providers_allowed():
        errors.append(
            "DEMO providers are selected but disabled in this environment: " + ", ".join(demo)
        )
    elif demo:
        warnings.append("DEMO providers selected (outputs are fixtures): " + ", ".join(demo))
    if settings.api_host not in {"127.0.0.1", "localhost", "::1"}:
        warnings.append("API listens beyond localhost; this workspace has no authentication")
    if errors:
        raise ConfigurationError("; ".join(errors))
    return warnings
