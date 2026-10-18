"""Stage registry, typed request/input/output contracts and fingerprint compatibility."""

from pathlib import Path
from typing import get_args

import pytest
from cinedub_api import worker
from cinedub_api.jobs import request_fields
from cinedub_api.models import Artifact, Job
from cinedub_api.schemas import JOB_REQUESTS, JobCreate, JobFields, RequestableStage
from cinedub_api.stages import STAGES, STORED_INPUTS
from cinedub_api.worker import process_once
from pydantic import TypeAdapter
from test_voice_workflow import prepare_reviewed_scene

REQUEST = TypeAdapter(JobCreate)
SAMPLES = [
    {"stage": "ingest", "source_asset_id": "a"},
    {"stage": "demo_pipeline", "provider": "fake"},
    {"stage": "transcribe", "source_asset_id": "a", "num_speakers": 2, "force_new": True},
    {"stage": "transcribe", "source_asset_id": "a", "transcription_input": "dialogue_stem"},
    {"stage": "separate", "source_asset_id": "a", "force_new": True},
    {"stage": "translate", "revision_id": "r", "segment_ids": ["s"], "regenerate": True},
    {"stage": "synthesize", "revision_id": "r", "segment_ids": ["s"], "force_new": True},
    {"stage": "export", "revision_id": "r", "allow_incomplete": True},
    {"stage": "render_preview", "revision_id": "r"},
    {"stage": "render_mix", "mix_settings": {"music_gain_db": -3}, "force_new": True},
    {"stage": "review_translation", "revision_id": "r"},
    {"stage": "adapt_dialogue", "segment_ids": ["s"], "candidate_ids": ["c"]},
    {"stage": "prepare_reference", "voice_profile_id": "v"},
    {
        "stage": "register_voice",
        "voice_profile_id": "v",
        "reference_reviewed": True,
        "registration_allowance_inr": 5,
    },
    {"stage": "delete_voice", "voice_profile_id": "v"},
    {"stage": "align", "source_asset_id": "a", "transcription_input": "dialogue_stem"},
    {"stage": "analyze_takes", "candidate_ids": ["c"], "include_target_alignment": True},
    {"stage": "analyze_emotion", "revision_id": "r", "segment_ids": ["s"]},
]


def test_every_requestable_stage_has_one_registered_contract():
    requestable = set(get_args(RequestableStage))
    request_stages = {get_args(model.model_fields["stage"].annotation)[0] for model in JOB_REQUESTS}
    assert request_stages == requestable
    assert set(STAGES) == requestable | {"package_mix"}
    assert STAGES["package_mix"].internal
    assert set(worker.PROCESSORS) == set(STAGES)
    for spec in STAGES.values():
        assert spec.input_model and spec.output_model and spec.process
    # Stage-specific preparation lives in the registry, not in the job service.
    source = Path(worker.__file__).with_name("jobs.py").read_text()
    assert "payload.stage" not in source and "stage in {" not in source


@pytest.mark.parametrize("raw", SAMPLES, ids=lambda raw: raw["stage"])
def test_typed_requests_freeze_the_same_fields_as_v02(raw):
    # The flat frozen shape is part of every job fingerprint; reuse of paid jobs depends on it.
    typed = request_fields(REQUEST.validate_python(raw))
    assert typed.model_dump() == JobFields.model_validate(raw).model_dump()


@pytest.mark.parametrize(
    "raw",
    [
        {"stage": "separate", "segment_ids": ["s"]},
        {"stage": "translate", "mix_settings": {}},
        {"stage": "render_mix", "candidate_ids": ["c"]},
        {"stage": "package_mix", "mix_id": "m"},
        {"stage": "unknown"},
    ],
)
@pytest.mark.anyio
async def test_options_for_another_stage_are_rejected_not_ignored(client, raw):
    project = (await client.post("/projects", json={"name": "Contracts"})).json()
    response = await client.post(f"/projects/{project['id']}/jobs", json=raw)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_freezes_inputs_once_and_stored_jobs_validate(client, session, monkeypatch):
    detail = await prepare_reviewed_scene(client, session)
    calls = []
    from cinedub_api import main

    original = main.prepare_stage
    monkeypatch.setattr(
        main, "prepare_stage", lambda *args: calls.append(args[2].stage) or original(*args)
    )
    response = await client.post(f"/projects/{detail['id']}/jobs", json={"stage": "render_preview"})
    assert response.status_code == 202, response.text
    assert calls == ["render_preview"]
    assert process_once(session)
    session.expire_all()
    for job in session.query(Job).filter_by(project_id=detail["id"]):
        if job.status != "completed":
            continue
        STAGES[job.stage].input_model.model_validate(job.input_json)
        STAGES[job.stage].output_model.model_validate(job.output_json)


@pytest.mark.anyio
async def test_invalid_stored_inputs_never_enter_a_processor(client, session, monkeypatch):
    detail = await prepare_reviewed_scene(client, session)
    invoked = []
    monkeypatch.setitem(worker.PROCESSORS, "export", lambda *args: invoked.append(1) or {})
    job = Job(project_id=detail["id"], stage="export", provider="local", input_json={})
    session.add(job)
    session.commit()
    assert process_once(session)
    session.expire_all()
    stored = session.get(Job, job.id)
    assert stored.status == "failed" and stored.error_code == "InvalidJobInput"
    assert not invoked and not stored.output_json
    # Older rows with extra, later-removed keys still validate leniently; new writes do not.
    legacy = {"revision_id": "r", "segments": [], "removed_option": True}
    assert STORED_INPUTS["export"].model_validate(legacy)
    with pytest.raises(ValueError):
        STAGES["export"].input_model.model_validate(legacy)


@pytest.mark.anyio
async def test_contract_breaking_output_is_not_recorded(client, session, monkeypatch):
    detail = await prepare_reviewed_scene(client, session)
    revision = detail["active_revision_id"]

    def broken(current, active):
        current.add(
            Artifact(
                project_id=active.project_id,
                job_id=active.id,
                kind="subtitle",
                path="/nonexistent",
                filename="x.srt",
                media_type="text/plain",
                metadata_json={},
            )
        )
        current.commit()
        return {"unexpected": True}

    monkeypatch.setitem(worker.PROCESSORS, "export", broken)
    response = await client.post(
        f"/projects/{detail['id']}/jobs", json={"stage": "export", "revision_id": revision}
    )
    assert response.status_code == 202, response.text
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "failed" and job.error_code == "InvalidJobOutput"
    assert job.output_json == {}
