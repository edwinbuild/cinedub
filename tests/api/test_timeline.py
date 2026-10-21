import io
import math
import wave

import httpx
import pytest
from cinedub_api.config import get_settings
from cinedub_api.database import SessionLocal
from cinedub_api.models import Job, Project, Segment, SegmentEdit, TimelineRevision
from cinedub_api.providers import ProviderRegistry
from cinedub_api.providers.base import TranslationResult
from cinedub_api.timeline import normalize_transcript
from cinedub_api.worker import claim_job, process_once, recover_jobs


def synthetic_wav(seconds=2):
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x10\x00" * int(16_000 * seconds))
    return data.getvalue()


async def prepare_scene(client, session):
    project = (await client.post("/projects", json={"name": "Recorded provider scene"})).json()
    asset = (
        await client.post(
            f"/projects/{project['id']}/assets",
            files={"file": ("scene.wav", synthetic_wav(), "audio/wav")},
        )
    ).json()
    assert process_once(session)
    return project, asset


async def transcribe(client, session, project, asset, **extra):
    response = await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "transcribe", "source_asset_id": asset["id"], **extra},
    )
    assert response.status_code == 202, response.text
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["status"] == "completed", detail["jobs"][0]
    return detail


@pytest.mark.anyio
async def test_real_ingest_revision_edit_playback_and_export(client, session):
    project, asset = await prepare_scene(client, session)
    detail = await transcribe(client, session, project, asset)
    assert len(detail["segments"]) == 2
    assert len(detail["speakers"]) == 2
    assert detail["revisions"][0]["source_asset_id"] == asset["id"]
    assert all(line["emotion_label"] is None for line in detail["segments"])
    audio = next(item for item in detail["artifacts"] if item["kind"] == "source_audio")
    full = await client.get(audio["content_url"])
    assert full.status_code == 200 and full.content[:4] == b"RIFF"
    for value, expected in [
        ("bytes=0-3", full.content[:4]),
        ("bytes=-7", full.content[-7:]),
        ("bytes=5-", full.content[5:]),
    ]:
        response = await client.get(audio["content_url"], headers={"Range": value})
        assert response.status_code == 206 and response.content == expected
        assert response.headers["content-range"].endswith(f"/{len(full.content)}")
    head = await client.head(audio["content_url"])
    assert head.status_code == 200 and not head.content
    assert int(head.headers["content-length"]) == len(full.content)
    for value in ["bytes=999999-", "bytes=8-3", "bytes=-0", "bytes=0-1,4-5", "garbage"]:
        response = await client.get(audio["content_url"], headers={"Range": value})
        assert response.status_code == 416
    response = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "export"})
    assert response.status_code == 422
    response = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "translate"})
    assert response.status_code == 202
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    line = detail["segments"][0]
    changed = (
        await client.patch(
            f"/segments/{line['id']}",
            json={
                "source_text": "Corrected English dialogue",
                "translated_text": "തിരുത്തിയ വരി",
                "start_ms": 50,
                "end_ms": 900,
                "status": "approved",
                "expected_version": line["version"],
            },
        )
    ).json()
    assert changed["status"] == "needs_review" and changed["human_edited"]
    approved = (
        await client.patch(
            f"/segments/{line['id']}",
            json={"status": "approved", "expected_version": changed["version"]},
        )
    ).json()
    assert approved["status"] == "approved"
    assert session.query(SegmentEdit).count() == 2
    assert (
        await client.patch(
            f"/segments/{line['id']}",
            json={"end_ms": 9000, "expected_version": approved["version"]},
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/segments/{line['id']}",
            json={"start_ms": None, "expected_version": approved["version"]},
        )
    ).status_code == 422
    await client.post(f"/projects/{project['id']}/jobs", json={"stage": "export"})
    assert process_once(session)
    detail = (await client.get(f"/projects/{project['id']}")).json()
    subtitle = next(item for item in detail["artifacts"] if item["kind"] == "subtitle")
    assert "demo" in subtitle["filename"]
    text = (await client.get(subtitle["download_url"])).text
    assert "00:00:00,050 --> 00:00:00,900" in text and "തിരുത്തിയ വരി" in text
    assert subtitle["metadata_json"]["segment_versions"][line["id"]] == approved["version"]


@pytest.mark.anyio
async def test_retranscription_is_candidate_and_old_edits_survive(client, session):
    project, asset = await prepare_scene(client, session)
    first = await transcribe(client, session, project, asset)
    old_id = first["active_revision_id"]
    line = first["segments"][0]
    await client.patch(
        f"/segments/{line['id']}",
        json={"translated_text": "മനുഷ്യൻ തിരുത്തിയ വരി", "expected_version": line["version"]},
    )
    reused = await client.post(
        f"/projects/{project['id']}/jobs",
        json={"stage": "transcribe", "source_asset_id": asset["id"]},
    )
    assert reused.json()["id"] == first["jobs"][0]["id"]
    assert not process_once(session)
    second = await transcribe(client, session, project, asset, force_new=True)
    assert len(second["revisions"]) == 2 and second["active_revision_id"] == old_id
    new_id = second["revisions"][0]["id"]
    for target in [new_id, old_id]:
        response = await client.post(
            f"/projects/{project['id']}/revisions/{target}/activate",
            json={"expected_active_revision_id": old_id if target == new_id else new_id},
        )
        assert response.status_code == 200, response.text
    assert response.json()["segments"][0]["translated_text"] == "മനുഷ്യൻ തിരുത്തിയ വരി"
    assert (
        await client.post(
            f"/projects/{project['id']}/revisions/{new_id}/activate",
            json={"expected_active_revision_id": new_id},
        )
    ).status_code == 409
    assert session.query(TimelineRevision).count() == 2


@pytest.mark.anyio
async def test_late_translation_keeps_newer_edit_and_retains_candidate(
    client, session, monkeypatch
):
    project, asset = await prepare_scene(client, session)
    detail = await transcribe(client, session, project, asset)
    first = detail["segments"][0]

    class SlowProvider:
        def translate(self, text, source_language, target_language):
            if text == first["source_text"]:
                with SessionLocal() as editor:
                    line = editor.get(Segment, first["id"])
                    line.translated_text = "New human draft"
                    line.human_edited = True
                    line.version += 1
                    editor.commit()
            return TranslationResult("Late model output", "fake", "recorded")

    monkeypatch.setattr(ProviderRegistry, "translator", lambda *_: SlowProvider())
    await client.post(f"/projects/{project['id']}/jobs", json={"stage": "translate"})
    assert process_once(session)
    session.expire_all()
    assert session.get(Segment, first["id"]).translated_text == "New human draft"
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["jobs"][0]["output_json"]["candidate_results"][first["id"]] == "Late model output"
    assert detail["jobs"][0]["warnings_json"]


@pytest.mark.anyio
async def test_budgets_and_conflicting_jobs(client, session, monkeypatch):
    project, asset = await prepare_scene(client, session)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-only-not-a-credential")
    record = session.get(Project, project["id"])
    record.budget_inr = 0.001
    session.commit()
    payload = {"stage": "transcribe", "provider": "sarvam", "source_asset_id": asset["id"]}
    estimate = (await client.post(f"/projects/{project['id']}/jobs/estimate", json=payload)).json()
    assert estimate["estimated_cost_inr"] == 0.025
    assert (await client.post(f"/projects/{project['id']}/jobs", json=payload)).status_code == 402
    record.budget_inr = 50
    session.commit()
    job = (await client.post(f"/projects/{project['id']}/jobs", json=payload)).json()
    assert job["estimated_cost_inr"] == 0.025
    conflict = await client.post(f"/projects/{project['id']}/jobs", json={"stage": "demo_pipeline"})
    assert conflict.status_code == 409
    await client.post(f"/jobs/{job['id']}/cancel")
    detail = (await client.get(f"/projects/{project['id']}")).json()
    assert detail["reserved_inr"] == 0
    assert detail["status"] == "review"


class RecordedBatch:
    def __init__(self):
        self.created = self.uploaded = self.started = self.polled = 0
        self.payload = {
            "diarized_transcript": {
                "entries": [
                    {
                        "transcript": "A recorded response",
                        "start_time_seconds": 0.1,
                        "end_time_seconds": 1.8,
                        "speaker_id": "0",
                    }
                ]
            }
        }

    def create(self, *args):
        self.created += 1
        return "recorded-job"

    def upload(self, job_id, path):
        assert path.is_file()
        self.uploaded += 1

    def start(self, job_id):
        self.started += 1

    def status(self, job_id):
        self.polled += 1
        return "Completed"

    def result(self, job_id, output_dir):
        return self.payload


@pytest.mark.anyio
async def test_batch_lifecycle_resume_and_silence(client, session, monkeypatch):
    project, asset = await prepare_scene(client, session)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-only-not-a-credential")
    batch = RecordedBatch()
    monkeypatch.setattr(ProviderRegistry, "transcriber", lambda *_: batch)
    detail = await transcribe(client, session, project, asset, provider="sarvam")
    assert batch.created == batch.uploaded == batch.started == 1
    assert detail["segments"][0]["source_text"] == "A recorded response"
    assert detail["jobs"][0]["charged_estimate_inr"] == 0.025
    second = (
        await client.post(
            f"/projects/{project['id']}/jobs",
            json={
                "stage": "transcribe",
                "provider": "sarvam",
                "source_asset_id": asset["id"],
                "force_new": True,
            },
        )
    ).json()
    job = session.get(Job, second["id"])
    job.status = "running"
    job.phase = "polling"
    job.remote_job_id = "recorded-job"
    job.checkpoint_json = {"poll_started_at": None}
    session.commit()
    recover_jobs(session)
    assert process_once(session)
    assert batch.created == batch.uploaded == batch.started == 1
    assert batch.polled == 2
    batch.payload = {"transcript": "", "diarized_transcript": {"entries": []}}
    detail = await transcribe(client, session, project, asset, provider="sarvam", force_new=True)
    assert detail["jobs"][0]["output_json"]["segments"] == 0
    assert "No speech" in detail["revisions"][0]["warnings_json"][0]


@pytest.mark.anyio
async def test_uncertain_submission_is_not_requeued(client, session):
    project, _ = await prepare_scene(client, session)
    for stage, phase, checkpoint in [
        ("transcribe", "creating", {}),
        ("translate", "translating", {"pending_chunk": "line:0"}),
    ]:
        job = Job(
            project_id=project["id"],
            stage=stage,
            provider="sarvam",
            status="running",
            phase=phase,
            checkpoint_json=checkpoint,
            charged_estimate_inr=1,
        )
        session.add(job)
        session.commit()
        recover_jobs(session)
        assert job.status == "failed" and job.error_code == "uncertain_submission"
        assert not job.retryable and job.charged_estimate_inr == 1
    assert claim_job(session) is None


@pytest.mark.parametrize(
    "entry",
    [
        {"start_time_seconds": -1, "end_time_seconds": 1},
        {"start_time_seconds": 1, "end_time_seconds": 1},
        {"start_time_seconds": math.nan, "end_time_seconds": 1},
        {"start_time_seconds": 1, "end_time_seconds": 5},
    ],
)
def test_invalid_provider_timing(entry):
    with pytest.raises(ValueError):
        normalize_transcript(
            {"diarized_transcript": {"entries": [{"transcript": "Bad timing", **entry}]}}, 2000
        )


def test_overlap_missing_speaker_and_boundary_warning():
    lines, warnings = normalize_transcript(
        {
            "diarized_transcript": {
                "entries": [
                    {
                        "transcript": "First",
                        "start_time_seconds": 0,
                        "end_time_seconds": 1.5,
                        "speaker_id": "0",
                    },
                    {"transcript": "Second", "start_time_seconds": 1, "end_time_seconds": 2.1},
                ]
            }
        },
        2000,
    )
    assert lines[1]["start_ms"] < lines[0]["end_ms"]
    assert lines[1]["end_ms"] == 2000 and lines[1]["speaker_label"] is None
    assert lines[1]["warnings_json"] and warnings


@pytest.mark.anyio
async def test_unreadable_upload_and_cross_project_source(client, session):
    project, asset = await prepare_scene(client, session)
    response = await client.post(
        f"/projects/{project['id']}/assets",
        files={"file": ("broken.mp4", b"not media", "video/mp4")},
    )
    assert response.status_code == 422
    other = (await client.post("/projects", json={"name": "Other project"})).json()
    assert (
        await client.post(
            f"/projects/{other['id']}/jobs",
            json={"stage": "transcribe", "source_asset_id": asset["id"]},
        )
    ).status_code == 422


def test_provider_error_never_leaks_headers():
    from cinedub_api.providers.retry import safe_error

    request = httpx.Request("POST", "https://api.invalid?token=private")
    response = httpx.Response(403, request=request)
    error = safe_error(httpx.HTTPStatusError("secret headers", request=request, response=response))
    assert "403" in error and "private" not in error and "secret" not in error


@pytest.mark.anyio
async def test_timeout_resume_does_not_submit_or_bill_twice(client, session, monkeypatch):
    project, asset = await prepare_scene(client, session)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-only")
    monkeypatch.setattr(get_settings(), "provider_timeout_seconds", 0)
    batch = RecordedBatch()
    monkeypatch.setattr(batch, "status", lambda _: "Running")
    monkeypatch.setattr(ProviderRegistry, "transcriber", lambda *_: batch)
    created = (
        await client.post(
            f"/projects/{project['id']}/jobs",
            json={"stage": "transcribe", "provider": "sarvam", "source_asset_id": asset["id"]},
        )
    ).json()
    assert process_once(session)
    job = session.get(Job, created["id"])
    session.refresh(job)
    assert job.status == "failed" and job.retryable
    cost = job.charged_estimate_inr
    response = await client.post(f"/jobs/{job.id}/resume")
    assert response.status_code == 200
    monkeypatch.setattr(batch, "status", lambda _: "Completed")
    assert process_once(session)
    session.refresh(job)
    assert job.status == "completed" and job.charged_estimate_inr == cost
    assert batch.created == batch.uploaded == batch.started == 1


@pytest.mark.anyio
async def test_running_batch_cancellation_keeps_estimated_charge(client, session, monkeypatch):
    project, asset = await prepare_scene(client, session)
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-only")
    batch = RecordedBatch()
    monkeypatch.setattr(ProviderRegistry, "transcriber", lambda *_: batch)
    created = (
        await client.post(
            f"/projects/{project['id']}/jobs",
            json={"stage": "transcribe", "provider": "sarvam", "source_asset_id": asset["id"]},
        )
    ).json()

    def cancel_while_polling(_):
        with SessionLocal() as editor:
            job = editor.get(Job, created["id"])
            job.cancel_requested = True
            editor.commit()
        return "Running"

    monkeypatch.setattr(batch, "status", cancel_while_polling)
    assert process_once(session)
    job = session.get(Job, created["id"])
    session.refresh(job)
    assert job.status == "cancelled" and job.charged_estimate_inr == 0.025
    assert "billed" in job.error_message


def test_sentence_split_respects_limits_without_losing_words():
    from cinedub_api.processing import split_translation

    text = "First complete sentence. Another sentence with several longer words. Last one."
    chunks = split_translation(text, 35)
    assert chunks[0] == "First complete sentence."
    assert all(len(part) <= 35 for part in chunks)
    assert " ".join(chunks).split() == text.split()
    assert split_translation("x" * 2500, 1000) == ["x" * 1000, "x" * 1000, "x" * 500]
