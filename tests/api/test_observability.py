"""Correlation IDs, structured logs, secret hygiene and startup configuration checks."""

import json
import logging

import pytest
from cinedub_api.config import Settings, get_settings
from cinedub_api.config_checks import ConfigurationError, validate_settings
from cinedub_api.models import Artifact, Job, ProviderRun
from cinedub_api.observability import JsonFormatter, accepted_id, bound
from cinedub_api.providers import ProviderRegistry
from cinedub_api.worker import process_once
from test_voice_workflow import wav

SECRET = "sk-test-NEVER-LOG-THIS-VALUE-42"


@pytest.mark.anyio
async def test_one_id_traces_request_job_provider_runs_and_artifacts(client, session):
    project = (await client.post("/projects", json={"name": "Traced"})).json()
    upload = await client.post(
        f"/projects/{project['id']}/assets",
        files={"file": ("scene.wav", wav(2), "audio/wav")},
        headers={"X-Request-ID": "upload-trace-1"},
    )
    assert upload.headers["x-request-id"] == "upload-trace-1"
    assert process_once(session)
    ingest = session.query(Job).filter_by(project_id=project["id"], stage="ingest").one()
    assert ingest.correlation_id == "upload-trace-1"
    artifacts = session.query(Artifact).filter_by(job_id=ingest.id).all()
    assert artifacts and {item.correlation_id for item in artifacts} == {"upload-trace-1"}

    response = await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "transcribe", "source_asset_id": upload.json()["id"]},
        headers={"X-Request-ID": "transcribe-trace-2"},
    )
    assert response.json()["correlation_id"] == "transcribe-trace-2"
    assert process_once(session)
    runs = session.query(ProviderRun).filter_by(job_id=response.json()["id"]).all()
    assert runs and {run.correlation_id for run in runs} == {"transcribe-trace-2"}
    raw = session.query(Artifact).filter_by(job_id=response.json()["id"]).one()
    assert raw.correlation_id == "transcribe-trace-2"


@pytest.mark.anyio
async def test_untrusted_request_ids_are_replaced(client):
    for value in ["has spaces", "x" * 65, "<script>", ""]:
        response = await client.get("/health", headers={"X-Request-ID": value})
        generated = response.headers["x-request-id"]
        assert generated != value and len(generated) == 32
    assert accepted_id("abc-123_DEF.4:5") == "abc-123_DEF.4:5"


def test_log_lines_are_json_with_correlation_and_no_exception_text():
    formatter = JsonFormatter("api")
    try:
        raise ValueError(f"provider said {SECRET}")
    except ValueError:
        import sys

        record = logging.LogRecord("cinedub", logging.ERROR, __file__, 1, "job_failed", (), None)
        record.exc_info = sys.exc_info()
    record.event_fields = {"job_id": "j1", "error_code": "provider_rejected"}
    with bound("trace-9"):
        line = formatter.format(record)
    payload = json.loads(line)
    assert payload["event"] == "job_failed" and payload["correlation_id"] == "trace-9"
    assert payload["service"] == "api" and payload["error_type"] == "ValueError"
    assert payload["job_id"] == "j1" and SECRET not in line


@pytest.mark.anyio
async def test_worker_emits_structured_lifecycle_events(client, session, caplog):
    project = (await client.post("/projects", json={"name": "Events"})).json()
    await client.post(
        f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline", "provider": "fake"}
    )
    with caplog.at_level(logging.INFO, logger="cinedub"):
        assert process_once(session)
    events = [getattr(record, "event_fields", None) for record in caplog.records]
    names = [record.getMessage() for record in caplog.records]
    assert "job_started" in names and "job_completed" in names
    completed = events[names.index("job_completed")]
    assert completed["stage"] == "demo_pipeline" and completed["duration_ms"] >= 0


@pytest.mark.anyio
async def test_credentials_never_reach_logs_errors_or_responses(
    client, session, caplog, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "sarvam_api_key", SECRET)
    monkeypatch.setattr(settings, "translator", "sarvam")

    class Leaky:
        def translate(self, *args, **kwargs):
            raise Exception(f"401 Unauthorized for key {SECRET}")  # noqa: TRY002

    monkeypatch.setattr(ProviderRegistry, "translator", lambda *args: Leaky())
    project = (await client.post("/projects", json={"name": "Secrets"})).json()
    await client.post(
        f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline", "provider": "fake"}
    )
    assert process_once(session)
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            f"/projects/{project['id']}/jobs", json={"stage": "translate", "provider": "sarvam"}
        )
        assert response.status_code == 202, response.text
        assert process_once(session)
        bodies = [
            (await client.get(path)).text
            for path in ("/health", "/capabilities", f"/projects/{project['id']}")
        ]
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "failed" and SECRET not in (job.error_message or "")
    assert all(SECRET not in body for body in bodies)
    assert SECRET not in caplog.text
    formatter = JsonFormatter("test")
    assert all(SECRET not in formatter.format(record) for record in caplog.records)


def test_startup_validation_reports_without_values(tmp_path):
    base = {"storage_root": tmp_path, "database_url": f"sqlite:///{tmp_path}/a.db"}
    demo = validate_settings(Settings(**base, transcriber="fake", translator="fake"))
    assert any(item.startswith("DEMO providers selected") for item in demo)
    development = Settings(**base, translator="sarvam", sarvam_api_key=None)
    assert any(
        "SARVAM_API_KEY is not configured" in item for item in validate_settings(development)
    )
    with pytest.raises(ConfigurationError, match="SARVAM_API_KEY"):
        validate_settings(Settings(**base, env="production", translator="sarvam"))
    with pytest.raises(ConfigurationError, match="DEMO providers are selected but disabled"):
        validate_settings(Settings(**base, env="production", sarvam_api_key=SECRET))
    configured = Settings(
        **base,
        env="production",
        sarvam_api_key=SECRET,
        **{name: "sarvam" for name in ("transcriber", "translator", "voice_synthesizer")},
        **{
            name: "local"
            for name in (
                "dialogue_adapter",
                "emotion_analyzer",
                "performance_analyzer",
                "stem_separator",
                "timing_aligner",
                "target_timing_aligner",
            )
        },
    )
    assert validate_settings(configured) == []
    with pytest.raises(ConfigurationError) as error:
        validate_settings(Settings(**base, web_origin="not a url", sarvam_api_key=SECRET))
    assert SECRET not in str(error.value)
    file = tmp_path / "file"
    file.write_text("x")
    with pytest.raises(ConfigurationError, match="STORAGE_ROOT"):
        validate_settings(Settings(storage_root=file, database_url=base["database_url"]))
    with pytest.raises(ValueError):
        Settings(**base, stem_separator="unknown")
