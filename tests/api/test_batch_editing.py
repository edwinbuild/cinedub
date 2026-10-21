import pytest
from cinedub_api.models import Segment, SegmentEdit
from test_timeline import prepare_scene, transcribe


async def setup_scene(client, session):
    project, asset = await prepare_scene(client, session)
    detail = await transcribe(client, session, project, asset)
    payload = {
        "revision_id": detail["active_revision_id"],
        "lines": [
            {
                "segment_id": line["id"],
                "expected_version": line["version"],
                "source_text": f"Human correction {index}",
            }
            for index, line in enumerate(detail["segments"])
        ],
    }
    return project, detail, payload


@pytest.mark.anyio
async def test_grouped_save_persists_history_and_requires_review(client, session):
    project, detail, payload = await setup_scene(client, session)
    for line in detail["segments"]:
        saved = session.get(Segment, line["id"])
        saved.status = "approved"
        saved.selected_candidate_id = "previous-take"
    session.commit()
    response = await client.patch(f"/projects/{project['id']}/segments", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["lines"]) == 2
    for old, new in zip(detail["segments"], result["lines"], strict=True):
        assert new["version"] == old["version"] + 1
        assert new["human_edited"] and new["status"] == "needs_review"
        assert new["selected_candidate_id"] is None
    edits = session.query(SegmentEdit).all()
    assert len(edits) == 2
    assert {edit.after_json["group_id"] for edit in edits} == {result["group_id"]}
    assert [edit.before_json["source_text"] for edit in edits] == [
        line["source_text"] for line in detail["segments"]
    ]
    replay = await client.patch(f"/projects/{project['id']}/segments", json=payload)
    assert replay.status_code == 409
    assert session.query(SegmentEdit).count() == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault,code",
    [
        ("stale", 409),
        ("timing", 422),
        ("blank", 422),
        ("speaker", 422),
        ("retired", 409),
        ("missing", 422),
        ("revision", 409),
    ],
)
async def test_late_invalid_line_rolls_back_entire_group(client, session, fault, code):
    project, detail, payload = await setup_scene(client, session)
    last = payload["lines"][-1]
    if fault == "stale":
        last["expected_version"] += 1
    elif fault == "timing":
        last["end_ms"] = 900000
    elif fault == "blank":
        last["source_text"] = " "
    elif fault == "speaker":
        last["speaker_id"] = "foreign"
    elif fault == "retired":
        session.get(Segment, last["segment_id"]).retired = True
        session.commit()
    elif fault == "missing":
        last["segment_id"] = "missing"
    else:
        payload["revision_id"] = "different"
    response = await client.patch(f"/projects/{project['id']}/segments", json=payload)
    assert response.status_code == code, response.text
    session.expire_all()
    for line in detail["segments"]:
        saved = session.get(Segment, line["id"])
        assert saved.version == line["version"]
        assert saved.source_text == line["source_text"]
    assert session.query(SegmentEdit).count() == 0


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["duplicate", "empty", "unknown", "no_change", "too_many"])
async def test_grouped_payload_is_strict_and_bounded(client, session, fault):
    project, _, payload = await setup_scene(client, session)
    if fault == "duplicate":
        payload["lines"][1] = payload["lines"][0]
    elif fault == "empty":
        payload["lines"] = []
    elif fault == "unknown":
        payload["lines"][-1]["unsupported"] = True
    elif fault == "no_change":
        payload["lines"][-1].pop("source_text")
    else:
        payload["lines"] *= 51
    response = await client.patch(f"/projects/{project['id']}/segments", json=payload)
    assert response.status_code == 422, response.text
    assert session.query(SegmentEdit).count() == 0


@pytest.mark.anyio
async def test_group_cannot_cross_project_boundary(client, session):
    project, detail, payload = await setup_scene(client, session)
    other, _, foreign = await setup_scene(client, session)
    assert other["id"] != project["id"]
    payload["lines"][-1]["segment_id"] = foreign["lines"][0]["segment_id"]
    response = await client.patch(f"/projects/{project['id']}/segments", json=payload)
    assert response.status_code == 422
    assert session.query(SegmentEdit).count() == 0
    assert (
        session.get(Segment, detail["segments"][0]["id"]).source_text
        == detail["segments"][0]["source_text"]
    )
