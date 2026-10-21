import pytest
from cinedub_api.models import Job, Segment, SegmentEdit
from test_dialogue_review import scene


def first_line(session):
    return session.query(Segment).order_by(Segment.index).first()


async def edit(client, session, line, **changes):
    response = await client.patch(
        f"/segments/{line.id}", json={"expected_version": line.version, **changes}
    )
    assert response.status_code == 200, response.text
    session.expire_all()
    return response.json()


async def history(client, line):
    response = await client.get(f"/segments/{line.id}/history")
    assert response.status_code == 200, response.text
    return response.json()


async def restore(client, session, line, action, **extra):
    state = await history(client, line)
    response = await client.post(
        f"/segments/{line.id}/history",
        json={
            "action": action,
            "expected_version": state["version"],
            "expected_edit_id": state[f"{action}_edit_id"],
            "restoration_confirmed": True,
            **extra,
        },
    )
    session.expire_all()
    return response


@pytest.mark.anyio
async def test_multilevel_undo_redo_is_append_only_and_survives_new_sessions(client, session):
    scene(session)
    line = first_line(session)
    original = line.translated_text
    await edit(client, session, line, translated_text="Manual A", start_ms=50)
    await edit(client, session, line, translated_text="Manual B", end_ms=1900)
    for action, text, start, end in [
        ("undo", "Manual A", 50, 2000),
        ("undo", original, 0, 2000),
        ("redo", "Manual A", 50, 2000),
        ("redo", "Manual B", 50, 1900),
    ]:
        response = await restore(client, session, line, action)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert (saved["translated_text"], saved["start_ms"], saved["end_ms"]) == (text, start, end)
        assert saved["status"] == "needs_review" and saved["human_edited"]
        assert saved["selected_candidate_id"] is None
    assert session.query(SegmentEdit).count() == 6 and line.version == 10
    assert (await history(client, line))["redo_edit_id"] is None
    assert [e["action"] for e in (await history(client, line))["entries"]] == [
        "redo",
        "redo",
        "undo",
        "undo",
        "edit",
        "edit",
    ]


@pytest.mark.anyio
async def test_fresh_edit_clears_redo_but_status_only_edits_do_not_restore_approval(
    client, session
):
    scene(session)
    line = first_line(session)
    await edit(client, session, line, translated_text="First draft")
    await edit(client, session, line, status="approved")
    line.selected_candidate_id = "historical-voice-not-restorable"
    line.delivery_json = {"applied_alignment_artifact_id": "old", "keep": "provenance"}
    session.commit()
    response = await restore(client, session, line, "undo")
    assert response.status_code == 200, response.text
    assert line.status == "needs_review" and line.selected_candidate_id is None
    assert line.delivery_json == {"keep": "provenance"}
    assert (await history(client, line))["redo_edit_id"]
    await edit(client, session, line, translated_text="New branch of human edits")
    assert (await history(client, line))["redo_edit_id"] is None
    assert (await restore(client, session, line, "undo")).status_code == 200
    # The replaced redo branch remains visible but is no longer executable.
    assert session.query(SegmentEdit).count() == 5


@pytest.mark.anyio
async def test_conflicts_confirmation_foreign_targets_and_active_jobs_are_refused(client, session):
    project, revision, speaker = scene(session)
    line = first_line(session)
    await edit(client, session, line, source_text="Changed English")
    for extra, status in [
        ({"restoration_confirmed": False}, 422),
        ({"expected_version": 1}, 409),
        ({"expected_edit_id": "foreign"}, 409),
    ]:
        response = await restore(client, session, line, "undo", **extra)
        assert response.status_code == status, response.text
    queued = Job(project_id=project.id, stage="translate", provider="fake", status="queued")
    session.add(queued)
    session.commit()
    assert (await restore(client, session, line, "undo")).status_code == 409
    queued.status = "cancelled"
    project.active_revision_id = None
    session.commit()
    assert (await restore(client, session, line, "undo")).status_code == 409
    assert session.query(SegmentEdit).count() == 1
    assert (await client.get("/segments/missing/history")).status_code == 404


@pytest.mark.anyio
async def test_provider_content_change_stops_old_chain_but_new_manual_edits_can_be_undone(
    client, session
):
    scene(session)
    line = first_line(session)
    await edit(client, session, line, translated_text="Human draft")
    old_id = (await history(client, line))["undo_edit_id"]
    line.translated_text = "Simulated new provider draft"
    line.version += 1
    session.commit()
    state = await history(client, line)
    assert state["undo_edit_id"] is None and state["unavailable_reason"]
    response = await client.post(
        f"/segments/{line.id}/history",
        json={
            "action": "undo",
            "expected_edit_id": old_id,
            "expected_version": line.version,
            "restoration_confirmed": True,
        },
    )
    assert response.status_code == 409
    await edit(client, session, line, translated_text="Manual correction of new provider draft")
    assert (await restore(client, session, line, "undo")).status_code == 200
    assert line.translated_text == "Simulated new provider draft"
    assert (await history(client, line))["undo_edit_id"] is None


@pytest.mark.anyio
async def test_speaker_history_uses_current_revision_validation_and_warnings(client, session):
    scene(session)
    line = first_line(session)
    speaker_id = line.speaker_id
    await edit(client, session, line, speaker_id=None)
    assert "Speaker unassigned; review this line" in line.warnings_json
    assert (await restore(client, session, line, "undo")).status_code == 200
    assert line.speaker_id == speaker_id
    assert "Speaker unassigned; review this line" not in line.warnings_json
    assert (await restore(client, session, line, "redo")).status_code == 200
    assert line.speaker_id is None


@pytest.mark.anyio
async def test_recent_history_response_is_bounded_and_old_snapshots_are_readonly(client, session):
    scene(session)
    line = first_line(session)
    session.add(SegmentEdit(segment_id=line.id, version=1, before_json={}, after_json=[]))
    session.commit()
    state = await history(client, line)
    assert state["entries"][0]["before"] is None and state["undo_edit_id"] is None
    original = line.source_text
    line.source_text = ""
    session.commit()
    assert (await history(client, line))["unavailable_reason"]
    line.source_text = original
    session.commit()
    for index in range(24):
        await edit(client, session, line, translated_text=f"Original synthetic edit {index}")
    state = await history(client, line)
    assert state["total_entries"] == 25 and len(state["entries"]) == 20
    assert (await restore(client, session, line, "undo")).status_code == 200


@pytest.mark.anyio
async def test_concurrent_history_submission_is_not_applied_twice(client, session):
    scene(session)
    line = first_line(session)
    await edit(client, session, line, translated_text="Original correction")
    state = await history(client, line)
    payload = {
        "action": "undo",
        "expected_version": state["version"],
        "expected_edit_id": state["undo_edit_id"],
        "restoration_confirmed": True,
    }
    url = f"/segments/{line.id}/history"
    assert (await client.post(url, json=payload)).status_code == 200
    assert (await client.post(url, json=payload)).status_code == 409
    assert session.query(SegmentEdit).count() == 2
