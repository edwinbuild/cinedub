import pytest
from cinedub_api.models import Job, Segment, SegmentEdit, TimelineStructureEdit
from cinedub_api.worker import process_once
from test_dialogue_review import scene


def first(session):
    return session.query(Segment).order_by(Segment.index).first()


async def split(client, session, line, **extra):
    response = await client.post(
        f"/segments/{line.id}/split",
        json={
            "revision_id": line.revision_id,
            "expected_version": line.version,
            "split_ms": (line.start_ms + line.end_ms) // 2,
            "first": {"source_text": "Original first half", "translated_text": "ആദ്യ ഭാഗം"},
            "second": {"source_text": "Original second half", "translated_text": "രണ്ടാം ഭാഗം"},
            "replacement_confirmed": True,
            **extra,
        },
    )
    session.expire_all()
    return response


async def reverse(client, session, operation, **extra):
    versions = {line["id"]: line["version"] + 1 for line in operation["before"]}
    versions.update({line["id"]: line["version"] for line in operation["after"]})
    response = await client.post(
        f"/timeline-structure-edits/{operation['id']}/restore",
        json={
            "revision_id": operation["revision_id"],
            "expected_versions": versions,
            "restoration_confirmed": True,
            **extra,
        },
    )
    session.expire_all()
    return response


@pytest.mark.anyio
async def test_split_preserves_originals_and_unaffected_takes_and_reverse_is_audited(
    client, session
):
    project, revision, _ = scene(session)
    original = first(session)
    other = session.query(Segment).filter_by(index=1).one()
    original.selected_candidate_id = "historical-take"
    other.selected_candidate_id = "unaffected-take"
    session.commit()
    old_id, old_text = original.id, original.translated_text
    response = await split(client, session, original)
    assert response.status_code == 200, response.text
    operation = response.json()
    assert operation["restorable"] and operation["before"][0]["status"] == "approved"
    assert operation["before"][0]["selected_candidate_id"] == "historical-take"
    assert original.retired and original.selected_candidate_id is None
    detail = (await client.get(f"/projects/{project.id}")).json()
    assert len(detail["segments"]) == 4 and old_id not in {s["id"] for s in detail["segments"]}
    assert [s["index"] for s in detail["segments"]] == list(range(4))
    assert other.selected_candidate_id == "unaffected-take" and other.status == "approved"
    assert [(s["start_ms"], s["end_ms"]) for s in operation["after"]] == [(0, 1000), (1000, 2000)]
    assert all(s["human_edited"] and s["status"] == "needs_review" for s in operation["after"])
    # Retired rows and their full audit remain available, but cannot be edited/selected.
    assert (
        await client.patch(
            f"/segments/{old_id}",
            json={
                "expected_version": original.version,
                "translated_text": "Forbidden old-row edit",
            },
        )
    ).status_code == 409
    history = (await client.get(f"/segments/{old_id}/history")).json()
    assert history["undo_edit_id"] is None and "read-only" in history["unavailable_reason"]
    assert (
        await client.post(
            f"/segments/{old_id}/candidate",
            json={
                "expected_version": original.version,
                "artifact_id": "historical-take",
            },
        )
    ).status_code == 422
    response = await reverse(client, session, operation)
    assert response.status_code == 200, response.text
    restored = response.json()
    assert restored["action"] == "restore" and restored["parent_edit_id"] == operation["id"]
    assert restored["restorable"] and not original.retired
    assert original.translated_text == old_text and original.status == "needs_review"
    assert original.selected_candidate_id is None
    assert (await reverse(client, session, restored)).status_code == 200
    assert original.retired and session.query(Segment).count() == 5
    assert session.query(TimelineStructureEdit).count() == 3
    assert session.query(SegmentEdit).count() >= 6


@pytest.mark.anyio
async def test_merge_requires_current_adjacent_same_speaker_lines_and_exact_text(client, session):
    project, revision, _ = scene(session)
    original = first(session)
    other = session.query(Segment).filter_by(index=1).one()
    payload = {
        "revision_id": revision.id,
        "next_segment_id": other.id,
        "expected_version": original.version,
        "expected_next_version": other.version,
        "replacement_confirmed": True,
        "text": {
            "source_text": "A manually reviewed combined sentence.",
            "translated_text": "മനുഷ്യൻ ചേർത്ത വരി",
        },
    }
    response = await client.post(f"/segments/{original.id}/merge", json=payload)
    assert response.status_code == 200, response.text
    session.expire_all()
    operation = response.json()
    assert original.retired and other.retired
    assert operation["after"][0]["source_text"] == payload["text"]["source_text"]
    assert (operation["after"][0]["start_ms"], operation["after"][0]["end_ms"]) == (0, 4000)
    assert len((await client.get(f"/projects/{project.id}")).json()["segments"]) == 2
    assert (await reverse(client, session, operation)).status_code == 200
    assert not original.retired and not other.retired


@pytest.mark.anyio
async def test_structural_conflicts_active_jobs_and_invalid_windows_do_not_mutate(client, session):
    project, revision, _ = scene(session)
    line = first(session)
    for extra, status in [
        ({"replacement_confirmed": False}, 422),
        ({"expected_version": 1}, 409),
        ({"split_ms": line.start_ms}, 422),
        ({"split_ms": line.end_ms}, 422),
        ({"first": {"source_text": "   "}}, 422),
    ]:
        assert (await split(client, session, line, **extra)).status_code == status
    job = Job(project_id=project.id, stage="translate", provider="fake", status="queued")
    session.add(job)
    session.commit()
    assert (await split(client, session, line)).status_code == 409
    job.status = "cancelled"
    project.active_revision_id = None
    session.commit()
    assert (await split(client, session, line)).status_code == 409
    assert session.query(TimelineStructureEdit).count() == 0
    assert session.query(Segment).count() == 3


@pytest.mark.anyio
async def test_wrong_merge_speaker_foreign_or_nonadjacent_line_are_refused(client, session):
    project, revision, _ = scene(session)
    line = first(session)
    second, third = session.query(Segment).order_by(Segment.index).all()[1:]
    other_project, other_revision, _ = scene(session)
    foreign = session.query(Segment).filter_by(project_id=other_project.id).first()
    for candidate in [third, foreign, line]:
        response = await client.post(
            f"/segments/{line.id}/merge",
            json={
                "revision_id": revision.id,
                "next_segment_id": candidate.id,
                "expected_version": line.version,
                "expected_next_version": candidate.version,
                "replacement_confirmed": True,
                "text": {"source_text": "Do not merge these"},
            },
        )
        assert response.status_code == 422, response.text
    second.speaker_id = None
    session.commit()
    response = await client.post(
        f"/segments/{line.id}/merge",
        json={
            "revision_id": revision.id,
            "next_segment_id": second.id,
            "expected_version": line.version,
            "expected_next_version": second.version,
            "replacement_confirmed": True,
            "text": {"source_text": "Different speakers"},
        },
    )
    assert response.status_code == 422 and "same speaker" in response.text
    assert not session.query(TimelineStructureEdit).count()


@pytest.mark.anyio
async def test_later_content_change_prevents_reversal_and_duplicate_split_is_refused(
    client, session
):
    project, revision, _ = scene(session)
    original = first(session)
    old_version = original.version
    response = await split(client, session, original)
    assert response.status_code == 200
    operation = response.json()
    assert (await split(client, session, original, expected_version=old_version)).status_code == 409
    line = session.get(Segment, operation["after"][0]["id"])
    response = await client.patch(
        f"/segments/{line.id}",
        json={
            "expected_version": line.version,
            "source_text": "A later human correction",
        },
    )
    assert response.status_code == 200
    assert (await reverse(client, session, operation)).status_code == 409
    history = (
        await client.get(f"/projects/{project.id}/revisions/{revision.id}/structure-edits")
    ).json()
    assert len(history) == 1 and not history[0]["restorable"] and history[0]["unavailable_reason"]
    session.expire_all()
    assert session.get(Segment, line.id).source_text == "A later human correction"


@pytest.mark.anyio
async def test_export_and_jobs_use_only_active_lines_after_split(client, session):
    project, revision, _ = scene(session)
    original = first(session)
    operation = (await split(client, session, original)).json()
    response = await client.post(
        f"/projects/{project.id}/jobs",
        json={
            "stage": "translate",
            "segment_ids": [original.id],
        },
    )
    assert response.status_code == 422
    response = await client.post(
        f"/projects/{project.id}/jobs",
        json={
            "stage": "export",
            "allow_incomplete": True,
        },
    )
    assert response.status_code == 202, response.text
    job = session.get(Job, response.json()["id"])
    assert original.id not in {s["id"] for s in job.input_json["segments"]}
    assert len(job.input_json["segments"]) == 4
    assert process_once(session)
    session.expire_all()
    assert job.status == "completed", job.error_message
    detail = (await client.get(f"/projects/{project.id}")).json()
    subtitle = next(a for a in detail["artifacts"] if a["kind"] == "subtitle")
    text = (await client.get(subtitle["content_url"])).text
    assert "ആദ്യ ഭാഗം" in text and "രണ്ടാം ഭാഗം" in text
    assert operation["after"][0]["translated_text"] in text


@pytest.mark.anyio
async def test_reversal_confirmation_and_versions_are_required(client, session):
    project, revision, _ = scene(session)
    operation = (await split(client, session, first(session))).json()
    assert (
        await reverse(client, session, operation, restoration_confirmed=False)
    ).status_code == 422
    assert (await reverse(client, session, operation, expected_versions={})).status_code == 409
    assert session.query(TimelineStructureEdit).count() == 1


@pytest.mark.anyio
async def test_active_line_limit_and_source_duration_are_enforced_before_split(client, session):
    from cinedub_api.models import MediaAsset

    project, revision, _ = scene(session)
    line = first(session)
    for index in range(3, 500):
        session.add(
            Segment(
                project_id=project.id,
                revision_id=revision.id,
                index=index,
                start_ms=6000 + index,
                end_ms=7000 + index,
                source_text="Synthetic bounded fixture",
            )
        )
    session.commit()
    response = await split(client, session, line)
    assert response.status_code == 422 and "500" in response.text
    assert not session.query(TimelineStructureEdit).count()
    # Retire synthetic limit fixtures, then make the saved original exceed its current source.
    for extra in session.query(Segment).filter(Segment.index >= 3):
        extra.retired = True
    source = MediaAsset(
        project_id=project.id,
        filename="synthetic.wav",
        media_type="audio/wav",
        path="synthetic-test-only",
        kind="source_audio",
        duration_ms=1000,
    )
    session.add(source)
    session.flush()
    revision.source_asset_id = source.id
    session.commit()
    response = await split(client, session, line)
    assert response.status_code == 422 and "source scene" in response.text
    assert not session.query(TimelineStructureEdit).count()
