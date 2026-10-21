import json
from pathlib import Path

import pytest
from cinedub_api.dialogue_processing import process_review_translation
from cinedub_api.dialogue_review import source_contains
from cinedub_api.jobs import prepare_job
from cinedub_api.models import (
    Artifact,
    DialogueBrief,
    Job,
    Project,
    ProviderRun,
    Segment,
    Speaker,
    TimelineRevision,
)
from cinedub_api.schemas import DialogueBriefContent, JobCreate
from cinedub_api.worker import process_once, recover_jobs
from pydantic import ValidationError


def scene(session):
    project = Project(name="Original editorial fixture")
    session.add(project)
    session.flush()
    revision = TimelineRevision(project_id=project.id, provider="fake", model="editorial-test-v1")
    session.add(revision)
    session.flush()
    project.active_revision_id = revision.id
    speaker = Speaker(project_id=project.id, revision_id=revision.id, label="A", display_name="Ann")
    session.add(speaker)
    session.flush()
    for index, (source, target) in enumerate(
        [
            ("Ann met Captain Ravi.", "ആൻ രവിയെ കണ്ടു."),
            ("An anniversary celebration.", "ഒരു വാർഷിക ആഘോഷം."),
            ("Where is Ravi?", ""),
        ]
    ):
        session.add(
            Segment(
                project_id=project.id,
                revision_id=revision.id,
                speaker_id=speaker.id if index != 2 else None,
                index=index,
                start_ms=index * 2000,
                end_ms=(index + 1) * 2000,
                source_text=source,
                translated_text=target,
                status="approved" if target else "draft",
                human_edited=True,
                version=4,
            )
        )
    session.commit()
    return project, revision, speaker


def brief_url(project, revision):
    return f"/projects/{project.id}/revisions/{revision.id}/dialogue-brief"


def content(speaker):
    return {
        "scene_summary": "Ann is looking for Ravi after a tense reunion.",
        "adaptation_notes": "Keep the subtext; do not add a backstory.",
        "characters": [
            {"speaker_id": speaker.id, "intent": "Hide concern", "delivery_notes": "Quiet"}
        ],
        "glossary": [
            {"source": "Ann", "preferred_target": "ആൻ"},
            {"source": "Captain Ravi", "preferred_target": "ക്യാപ്റ്റൻ രവി", "note": "Keep the rank"},
        ],
    }


async def review(client, session, project, **extra):
    response = await client.post(
        f"/projects/{project.id}/jobs", json={"stage": "review_translation", **extra}
    )
    assert response.status_code == 202, response.text
    assert process_once(session)
    session.expire_all()
    job = session.get(Job, response.json()["id"])
    assert job.status == "completed", job.error_message
    artifact = session.get(Artifact, job.output_json["dialogue_review_artifact_id"])
    response = await client.get(f"/dialogue-review-reports/{artifact.id}")
    assert response.status_code == 200, response.text
    return job, artifact, response.json()


@pytest.mark.anyio
async def test_append_only_brief_conflicts_noops_and_revision_isolation(client, session):
    project, revision, speaker = scene(session)
    url = brief_url(project, revision)
    response = await client.get(url)
    assert response.json()["version"] == 0 and response.json()["id"] is None
    payload = {"expected_version": 0, "content": content(speaker)}
    first = await client.post(url, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert (await client.post(url, json=payload)).status_code == 409
    payload["expected_version"] = 1
    assert (await client.post(url, json=payload)).json()["version"] == 1
    assert session.query(DialogueBrief).count() == 1
    payload["content"]["scene_summary"] = "A changed scene brief"
    second = await client.post(url, json=payload)
    assert second.json()["version"] == 2
    session.expire_all()
    history = session.query(DialogueBrief).order_by(DialogueBrief.version).all()
    assert len(history) == 2 and history[0].content_json["scene_summary"].startswith("Ann")
    other = TimelineRevision(project_id=project.id, provider="fake", model="new-revision")
    session.add(other)
    session.commit()
    assert (await client.get(brief_url(project, other))).json()["version"] == 0
    assert (await client.get(f"/projects/{project.id}")).json()["dialogue_brief"]["version"] == 2


@pytest.mark.anyio
async def test_brief_rejects_foreign_speakers_extra_fields_and_oversized_notes(client, session):
    project, revision, speaker = scene(session)
    foreign, foreign_revision, foreign_speaker = scene(session)
    url = brief_url(project, revision)
    for invalid in [
        {"scene_summary": "x" * 4001},
        {"glossary": [{"source": "  ", "preferred_target": "വാക്ക്"}]},
        {
            "glossary": [
                {"source": "Ann", "preferred_target": "ആൻ"},
                {"source": "ann", "preferred_target": "ആൻ"},
            ]
        },
        {"characters": [{"speaker_id": foreign_speaker.id}]},
        {"characters": [{"speaker_id": speaker.id}, {"speaker_id": speaker.id}]},
        {"unexpected_vendor_prompt": "not supported"},
    ]:
        assert (
            await client.post(url, json={"expected_version": 0, "content": invalid})
        ).status_code == 422
    assert (await client.get(brief_url(project, foreign_revision))).status_code == 404
    assert session.query(DialogueBrief).count() == 0
    assert (await client.get(f"/projects/{foreign.id}")).status_code == 200


def test_literal_unicode_glossary_checks_are_not_regex_or_subword_matching():
    assert source_contains("ANN met Ravi", "Ann")
    assert not source_contains("anniversary", "Ann")
    assert source_contains("Use C++ today", "C++")
    assert not source_contains("Something else", ".*")
    assert source_contains("A cafe\u0301 visit", "café")
    assert source_contains("അവൻ രവി ആണ്", "രവി")
    assert not source_contains("അവൻ രവിയാണ്", "രവി")
    with pytest.raises(ValidationError):
        DialogueBriefContent(
            glossary=[
                {"source": "café", "preferred_target": "ഒന്ന്"},
                {"source": "cafe\u0301", "preferred_target": "രണ്ട്"},
            ]
        )


@pytest.mark.anyio
async def test_real_local_checks_preserve_dialogue_include_context_and_cost_nothing(
    client, session
):
    project, revision, speaker = scene(session)
    before = [
        (line.id, line.version, line.translated_text, line.status)
        for line in session.query(Segment).all()
    ]
    saved = await client.post(
        brief_url(project, revision), json={"expected_version": 0, "content": content(speaker)}
    )
    assert saved.status_code == 200
    estimate = (
        await client.post(
            f"/projects/{project.id}/jobs/estimate", json={"stage": "review_translation"}
        )
    ).json()
    assert estimate["estimated_cost_inr"] == 0
    job, artifact, report = await review(client, session, project)
    assert report["context_applied_by_model"] is False and report["stale_reason"] is None
    assert report["brief"]["version"] == 1
    assert report["lines"][0]["slot_duration_ms"] == 2000
    assert report["lines"][0]["character_direction"]["intent"] == "Hide concern"
    assert report["lines"][0]["previous_line"] is None
    assert report["lines"][0]["next_line"]["source_text"] == "An anniversary celebration."
    assert report["lines"][1]["matched_glossary"] == []
    assert [item["code"] for item in report["lines"][0]["findings"]] == ["missing_preferred_term"]
    assert [item["code"] for item in report["lines"][2]["findings"]] == [
        "missing_translation",
        "unassigned_speaker",
    ]
    assert report["lines"][0]["target_character_count"] == len("ആൻ രവിയെ കണ്ടു.")
    assert any("not an estimate" in warning for warning in report["warnings"])
    assert before == [
        (line.id, line.version, line.translated_text, line.status)
        for line in session.query(Segment).all()
    ]
    run = session.query(ProviderRun).one()
    assert run.provider == "local" and run.estimated_cost_inr == 0
    assert job.charged_estimate_inr == 0 and artifact.metadata_json["sha256"]
    cached = (
        await client.post(f"/projects/{project.id}/jobs", json={"stage": "review_translation"})
    ).json()
    assert cached["id"] == job.id
    assert not process_once(session)


@pytest.mark.anyio
async def test_subset_keeps_neighbors_and_rejects_duplicate_foreign_lines(client, session):
    project, revision, speaker = scene(session)
    ids = [line.id for line in session.query(Segment).order_by(Segment.index)]
    for selection in [[], [ids[0], ids[0]], ["foreign"]]:
        response = await client.post(
            f"/projects/{project.id}/jobs",
            json={"stage": "review_translation", "segment_ids": selection},
        )
        assert response.status_code == 422
    assert (
        await client.post(
            f"/projects/{project.id}/jobs",
            json={"stage": "review_translation", "provider": "sarvam"},
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/projects/{project.id}/jobs", json={"stage": "review_translation", "regenerate": True}
        )
    ).status_code == 422
    _, _, report = await review(client, session, project, segment_ids=[ids[1]])
    assert len(report["lines"]) == 1 and len(report["context_lines"]) == 3
    assert report["lines"][0]["previous_line"]["segment_id"] == ids[0]
    assert report["lines"][0]["next_line"]["segment_id"] == ids[2]


@pytest.mark.anyio
async def test_brief_edit_flags_old_report_and_does_not_change_translation_fingerprint(
    client, session
):
    project, revision, speaker = scene(session)
    _, initial, _ = prepare_job(session, project, JobCreate(stage="translate"))
    _, artifact, _ = await review(client, session, project)
    saved = await client.post(
        brief_url(project, revision), json={"expected_version": 0, "content": content(speaker)}
    )
    assert saved.status_code == 200
    _, after, _ = prepare_job(session, project, JobCreate(stage="translate"))
    assert initial["fingerprint"] == after["fingerprint"]
    response = await client.get(f"/dialogue-review-reports/{artifact.id}")
    assert "brief changed" in response.json()["stale_reason"]
    _, fresh, report = await review(client, session, project)
    assert fresh.id != artifact.id and report["brief"]["version"] == 1


@pytest.mark.anyio
async def test_unreviewed_neighbor_changes_stale_but_approval_only_does_not(client, session):
    project, revision, speaker = scene(session)
    lines = session.query(Segment).order_by(Segment.index).all()
    _, artifact, _ = await review(client, session, project, segment_ids=[lines[0].id])
    line = session.get(Segment, lines[0].id)
    line.status = "needs_review"
    line.version += 1
    session.commit()
    assert (await client.get(f"/dialogue-review-reports/{artifact.id}")).json()[
        "stale_reason"
    ] is None
    other = session.get(Segment, lines[2].id)
    other.source_text = "A corrected surrounding line"
    session.commit()
    response = await client.get(f"/dialogue-review-reports/{artifact.id}")
    assert "surrounding context changed" in response.json()["stale_reason"]


@pytest.mark.anyio
async def test_edits_while_queued_fail_readonly_without_publishing(client, session):
    project, revision, speaker = scene(session)
    response = await client.post(
        f"/projects/{project.id}/jobs", json={"stage": "review_translation"}
    )
    assert response.status_code == 202
    line = session.query(Segment).first()
    line.translated_text = "A new human edit"
    line.version += 1
    session.commit()
    assert process_once(session)
    session.expire_all()
    assert session.get(Job, response.json()["id"]).status == "failed"
    assert session.query(Artifact).count() == 0 and session.query(ProviderRun).count() == 0
    assert session.get(Segment, line.id).translated_text == "A new human edit"


@pytest.mark.anyio
async def test_report_integrity_and_persisted_recovery_do_not_duplicate_runs(client, session):
    project, revision, speaker = scene(session)
    job, artifact, report = await review(client, session, project)
    assert process_review_translation(session, job)["dialogue_review_artifact_id"] == artifact.id
    assert session.query(ProviderRun).count() == 1
    job.status = "running"
    session.commit()
    recover_jobs(session)
    assert process_once(session)
    assert session.query(Artifact).count() == 1 and session.query(ProviderRun).count() == 1
    report["lines"][0]["translated_text"] = "Changed report bytes"
    Path(artifact.path).write_text(json.dumps(report), encoding="utf-8")
    assert (await client.get(f"/dialogue-review-reports/{artifact.id}")).status_code == 409
    assert (await client.get("/dialogue-review-reports/missing")).status_code == 404
