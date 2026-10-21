import pytest
from cinedub_api.models import Job, Segment, SegmentEdit
from test_batch_editing import setup_scene


async def grouped_scene(client, session):
    project, detail, edits = await setup_scene(client, session)
    response = await client.patch(f"/projects/{project['id']}/segments", json=edits)
    assert response.status_code == 200, response.text
    group_id = response.json()["group_id"]
    url = f"/projects/{project['id']}/edit-groups/{group_id}"
    view = (await client.get(url)).json()
    return project, detail, url, view


def restore_payload(view, action="undo"):
    return {
        "revision_id": view["revision_id"],
        "action": action,
        "restoration_confirmed": True,
        "lines": [
            {key: line[key] for key in ("segment_id", "expected_version", "expected_edit_id")}
            for line in view["lines"]
        ],
    }


@pytest.mark.anyio
async def test_grouped_undo_redo_persist_without_restoring_approval(client, session):
    project, original, url, view = await grouped_scene(client, session)
    assert view["can_undo"] and not view["can_redo"] and len(view["lines"]) == 2
    listed = (
        await client.get(
            f"/projects/{project['id']}/edit-groups", params={"revision_id": view["revision_id"]}
        )
    ).json()
    assert listed[0]["group_id"] == view["group_id"] and listed[0]["line_count"] == 2
    response = await client.post(url + "/restore", json=restore_payload(view))
    assert response.status_code == 200, response.text
    assert [line["source_text"] for line in response.json()["lines"]] == [
        line["source_text"] for line in original["segments"]
    ]
    assert all(
        line["status"] == "needs_review" and line["selected_candidate_id"] is None
        for line in response.json()["lines"]
    )
    assert (await client.post(url + "/restore", json=restore_payload(view))).status_code == 409
    undone = (await client.get(url)).json()
    assert undone["can_redo"] and not undone["can_undo"]
    redone = await client.post(url + "/restore", json=restore_payload(undone, "redo"))
    assert redone.status_code == 200, redone.text
    assert [line["source_text"] for line in redone.json()["lines"]] == [
        "Human correction 0",
        "Human correction 1",
    ]
    assert (await client.get(url)).json()["can_undo"]
    assert session.query(SegmentEdit).count() == 6
    assert {
        record.after_json.get("history_group_id") for record in session.query(SegmentEdit).all()[2:]
    } == {view["group_id"]}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault,code",
    [
        ("stale", 409),
        ("missing", 409),
        ("foreign_target", 409),
        ("duplicate", 409),
        ("unconfirmed", 422),
        ("active_job", 409),
        ("retired", 409),
        ("newer_edit", 409),
        ("provider_change", 409),
        ("revision", 409),
    ],
)
async def test_group_restore_is_exact_and_never_partial(client, session, fault, code):
    _, _, url, view = await grouped_scene(client, session)
    payload = restore_payload(view)
    last = payload["lines"][-1]
    if fault == "stale":
        last["expected_version"] += 1
    elif fault == "missing":
        payload["lines"].pop()
    elif fault == "foreign_target":
        last["expected_edit_id"] = "foreign"
    elif fault == "duplicate":
        payload["lines"].append(payload["lines"][0])
    elif fault == "unconfirmed":
        payload["restoration_confirmed"] = False
    elif fault == "active_job":
        project_id = session.get(Segment, last["segment_id"]).project_id
        session.add(Job(project_id=project_id, stage="translate", provider="fake", status="queued"))
        session.commit()
    elif fault == "retired":
        session.get(Segment, last["segment_id"]).retired = True
        session.commit()
    elif fault == "newer_edit":
        response = await client.patch(
            f"/segments/{last['segment_id']}",
            json={
                "expected_version": last["expected_version"],
                "source_text": "Newer manual correction",
            },
        )
        assert response.status_code == 200
    elif fault == "provider_change":
        session.get(Segment, last["segment_id"]).source_text = "Provider changed content"
        session.commit()
    else:
        payload["revision_id"] = "other"
    session.expire_all()
    before = [
        (
            line["segment_id"],
            session.get(Segment, line["segment_id"]).version,
            session.get(Segment, line["segment_id"]).source_text,
        )
        for line in view["lines"]
    ]
    count = session.query(SegmentEdit).count()
    response = await client.post(url + "/restore", json=payload)
    assert response.status_code == code, response.text
    session.expire_all()
    assert [
        (line_id, session.get(Segment, line_id).version, session.get(Segment, line_id).source_text)
        for line_id, _, _ in before
    ] == before
    assert session.query(SegmentEdit).count() == count


@pytest.mark.anyio
async def test_group_restore_cannot_cross_projects(client, session):
    _, _, url, view = await grouped_scene(client, session)
    other = (await client.post("/projects", json={"name": "Other project"})).json()
    foreign = f"/projects/{other['id']}/edit-groups/{view['group_id']}"
    assert (await client.get(foreign)).status_code == 404
    assert (await client.post(foreign + "/restore", json=restore_payload(view))).status_code == 404
    assert (await client.get(url)).json()["can_undo"]


@pytest.mark.anyio
async def test_mixed_material_and_status_only_group_does_not_undo_approval(client, session):
    project, detail, edits = await setup_scene(client, session)
    last = edits["lines"][-1]
    last.pop("source_text")
    last["status"] = "needs_review"
    result = (await client.patch(f"/projects/{project['id']}/segments", json=edits)).json()
    url = f"/projects/{project['id']}/edit-groups/{result['group_id']}"
    view = (await client.get(url)).json()
    assert len(view["lines"]) == view["excluded_nonmaterial_count"] == 1
    response = await client.post(url + "/restore", json=restore_payload(view))
    assert response.status_code == 200, response.text
    assert len(response.json()["lines"]) == 1
    session.expire_all()
    unchanged = session.get(Segment, detail["segments"][-1]["id"])
    assert unchanged.version == detail["segments"][-1]["version"] + 1
    assert unchanged.status == "needs_review"


@pytest.mark.anyio
async def test_late_restoration_validation_rolls_back_earlier_member(client, session, monkeypatch):
    from cinedub_api.routes import group_history
    from fastapi import HTTPException

    _, _, url, view = await grouped_scene(client, session)
    apply, completed = group_history.apply_line_edit, []

    def late_failure(*args, **kwargs):
        if completed:
            raise HTTPException(422, "Later historical speaker is unavailable")
        result = apply(*args, **kwargs)
        completed.append(result.id)
        return result

    monkeypatch.setattr(group_history, "apply_line_edit", late_failure)
    response = await client.post(url + "/restore", json=restore_payload(view))
    assert response.status_code == 422 and len(completed) == 1
    session.expire_all()
    assert [session.get(Segment, line["segment_id"]).source_text for line in view["lines"]] == [
        "Human correction 0",
        "Human correction 1",
    ]
    assert session.query(SegmentEdit).count() == 2


@pytest.mark.anyio
async def test_individual_undo_cannot_cause_partial_group_redo(client, session):
    _, _, url, view = await grouped_scene(client, session)
    line = view["lines"][0]
    payload = {
        "action": "undo",
        "expected_version": line["expected_version"],
        "expected_edit_id": line["expected_edit_id"],
        "restoration_confirmed": True,
    }
    response = await client.post(f"/segments/{line['segment_id']}/history", json=payload)
    assert response.status_code == 200, response.text
    mixed = (await client.get(url)).json()
    assert not mixed["can_undo"] and not mixed["can_redo"]
    assert "no partial" in mixed["unavailable_reason"]
    assert (
        await client.post(url + "/restore", json=restore_payload(mixed, "redo"))
    ).status_code == 409


@pytest.mark.anyio
async def test_status_only_group_has_no_restorable_content(client, session):
    project, _, edits = await setup_scene(client, session)
    for item in edits["lines"]:
        item.pop("source_text")
        item["status"] = "needs_review"
    result = (await client.patch(f"/projects/{project['id']}/segments", json=edits)).json()
    view = (await client.get(f"/projects/{project['id']}/edit-groups/{result['group_id']}")).json()
    assert view["lines"] == [] and view["excluded_nonmaterial_count"] == 2
    assert not view["can_undo"] and not view["can_redo"]


@pytest.mark.anyio
async def test_group_listing_is_bounded_without_deleting_older_history(client, session):
    project, _, edits = await setup_scene(client, session)
    ids = []
    for index in range(21):
        for item in edits["lines"]:
            item["source_text"] = f"Original grouped correction {index}"
        response = await client.patch(f"/projects/{project['id']}/segments", json=edits)
        assert response.status_code == 200, response.text
        result = response.json()
        ids.append(result["group_id"])
        for item, saved in zip(edits["lines"], result["lines"], strict=True):
            item["expected_version"] = saved["version"]
    result = (
        await client.get(
            f"/projects/{project['id']}/edit-groups", params={"revision_id": edits["revision_id"]}
        )
    ).json()
    assert len(result) == 20 and result[0]["group_id"] == ids[-1]
    assert ids[0] not in {item["group_id"] for item in result}
    assert (await client.get(f"/projects/{project['id']}/edit-groups/{ids[0]}")).status_code == 200
    assert session.query(SegmentEdit).count() == 42
