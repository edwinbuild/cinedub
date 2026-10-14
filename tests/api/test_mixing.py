import array
import hashlib
import io
import json
import math
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from cinedub_api.config import get_settings
from cinedub_api.database import SessionLocal
from cinedub_api.media import extract_audio, file_digest, probe_media, run_ffmpeg
from cinedub_api.mix_media import normalize_mix, render_float_sum
from cinedub_api.models import Artifact, Job, MediaAsset, MixRender, Segment, StemSet
from cinedub_api.schemas import MixSettings
from cinedub_api.worker import process_once, recover_jobs
from test_voice_workflow import prepare_reviewed_scene


def background_fixture(session, detail):
    source = session.get(MediaAsset, detail["assets"][0]["id"])
    job = Job(project_id=detail["id"], stage="separate", provider="local", status="completed")
    session.add(job)
    session.flush()
    stems = StemSet(
        project_id=detail["id"],
        source_asset_id=source.id,
        job_id=job.id,
        provider="recorded-test",
        model="original-procedural-stems",
        status="approved",
        metadata_json={"timeline_mapping_version": 2},
    )
    session.add(stems)
    session.flush()
    directory = get_settings().storage_root / detail["id"] / "known-stems"
    directory.mkdir(parents=True)
    artifacts = {}
    for name, expression in [
        ("music", "0.04*sin(2*PI*330*t)|0.03*sin(2*PI*550*t)"),
        ("effects", "0.03*sin(2*PI*880*t)*between(t,3,4)|0.03*sin(2*PI*880*t)*between(t,3,4)"),
    ]:
        path = directory / f"{name}.wav"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"aevalsrc='{expression}':s=48000:d={source.duration_ms / 1000}",
                "-c:a",
                "pcm_f32le",
                str(path),
            ]
        )
        artifact = Artifact(
            project_id=detail["id"],
            job_id=job.id,
            kind="stem_master",
            path=str(path),
            filename=path.name,
            media_type="audio/wav",
            metadata_json={"stem_set_id": stems.id, "sha256": file_digest(path)},
        )
        session.add(artifact)
        session.flush()
        artifacts[name] = {"master": artifact.id}
    stems.artifacts_json = artifacts
    source.active_stem_set_id = stems.id
    session.commit()
    return stems


async def render(client, session, detail, **settings):
    response = await client.post(
        f"/projects/{detail['id']}/jobs",
        json={"stage": "render_mix", "force_new": True, "mix_settings": settings},
    )
    assert response.status_code == 202, response.text
    assert response.json()["estimated_cost_inr"] == 0
    assert process_once(session)
    job = session.get(Job, response.json()["id"])
    assert job.status == "completed", job.error_message
    project = (await client.get(f"/projects/{detail['id']}")).json()
    return project, project["mixes"][0], job


def decode(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ac",
            "2",
            "-ar",
            "48000",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    samples = array.array("f")
    samples.frombytes(result.stdout)
    return samples


def amplitude(samples, frequency, start=3.1, seconds=0.5, channel=0):
    values = samples[round(start * 48000) * 2 + channel : round((start + seconds) * 48000) * 2 : 2]
    real = sum(
        value * math.cos(2 * math.pi * frequency * index / 48000)
        for index, value in enumerate(values)
    )
    imaginary = sum(
        value * math.sin(2 * math.pi * frequency * index / 48000)
        for index, value in enumerate(values)
    )
    return math.hypot(real, imaginary) * 2 / len(values)


@pytest.mark.anyio
async def test_reviewed_mix_golden_audio_acceptance_and_bundle(client, session):
    detail = await prepare_reviewed_scene(client, session)
    assert (
        await client.post(f"/projects/{detail['id']}/jobs", json={"stage": "render_mix"})
    ).status_code == 422
    stems = background_fixture(session, detail)
    assert (
        await client.post(
            f"/projects/{detail['id']}/jobs",
            json={"stage": "render_mix", "segment_ids": [detail["segments"][0]["id"]]},
        )
    ).status_code == 422
    project, mix, job = await render(client, session, detail)
    assert mix["status"] == "needs_review" and mix["stale_reason"] is None
    quality = mix["quality_json"]
    assert quality["technical_status"] == "passed" and quality["human_listening"] == "pending"
    assert quality["audio_master"]["sample_count"] == 8 * 48000
    assert abs(quality["audio_master"]["integrated_lufs"] + 23) <= 1
    assert quality["audio_master"]["true_peak_dbfs"] <= -1.8
    assert quality["normalization"]["second_pass"]["normalization_type"] == "linear"
    master = session.get(Artifact, mix["artifacts_json"]["master"])
    samples = decode(master.path)
    assert amplitude(samples, 330) > 0.01 and amplitude(samples, 550, channel=1) > 0.01
    assert amplitude(samples, 880) > 0.005
    assert amplitude(samples, 440) < 1e-5 and amplitude(samples, 330, channel=1) < 1e-5
    manifest = session.get(Artifact, mix["artifacts_json"]["manifest"])
    evidence = json.loads(Path(manifest.path).read_text())
    assert (
        not evidence["original_dialogue_track_mapped"]
        and not evidence["source_audio_mapped_to_video"]
    )
    assert evidence["separation_may_retain_dialogue_leakage"]
    assert evidence["stem_set"]["id"] == stems.id and len(evidence["input_files"]) == 4
    for item in evidence["files"]:
        assert file_digest(session.get(Artifact, item["artifact_id"]).path) == item["sha256"]
    review = {
        "status": "approved",
        "expected_version": 1,
        "reviewed_by": "Fixture reviewer",
        "note": "Automated workflow, not human listening evidence",
    }
    assert (await client.post(f"/mixes/{mix['id']}/review", json=review)).status_code == 422
    accepted = await client.post(
        f"/mixes/{mix['id']}/review", json={**review, "listening_confirmed": True}
    )
    assert accepted.status_code == 200 and accepted.json()["version"] == 2
    assert (
        accepted.json()["reviews"][0]["bundle_artifact_id"] is None
    )  # Packaging is a durable job.
    assert process_once(session)
    project = (await client.get(f"/projects/{detail['id']}")).json()
    assert project["jobs"][0]["status"] == "completed", project["jobs"][0]
    record = project["mixes"][0]["reviews"][0]
    bundle = session.get(Artifact, record["bundle_artifact_id"])
    response = await client.get(f"/artifacts/{bundle.id}/download")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        certificate = json.loads(archive.read("listening-acceptance.json"))
        assert certificate["render_manifest_sha256"] == file_digest(manifest.path)
        assert certificate["reviewed_by"] == "Fixture reviewer" and certificate["demo"]
        for item in certificate["files"]:
            assert hashlib.sha256(archive.read(item["filename"])).hexdigest() == item["sha256"]
        assert "സിനിഡബിലേക്ക് സ്വാഗതം." in archive.read("demo-malayalam.srt").decode()
    # Recovered packaging must return committed artifact IDs, not create duplicate approvals/ZIPs.
    packaging = session.get(Job, project["jobs"][0]["id"])
    packaging.status = "running"
    session.commit()
    recover_jobs(session)
    assert (
        process_once(session)
        and session.query(Artifact).filter_by(job_id=packaging.id).count() == 2
    )
    stale = await client.post(
        f"/mixes/{mix['id']}/review", json={**review, "listening_confirmed": True}
    )
    assert stale.status_code == 409
    line = project["segments"][0]
    await client.patch(
        f"/segments/{line['id']}", json={"expected_version": line["version"], "start_ms": 10}
    )
    changed = (await client.get(f"/projects/{detail['id']}")).json()
    assert changed["mixes"][0]["stale_reason"]
    assert (
        await client.post(
            f"/mixes/{mix['id']}/review",
            json={**review, "expected_version": 2, "listening_confirmed": True},
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/mixes/{mix['id']}/review",
            json={**review, "status": "rejected", "expected_version": 2},
        )
    ).status_code == 200
    assert (
        await client.get(f"/artifacts/{bundle.id}/download")
    ).status_code == 200  # Historical, not silently deleted.


@pytest.mark.anyio
async def test_mix_levels_mutes_and_changed_input_hash(client, session):
    detail = await prepare_reviewed_scene(client, session)
    stems = background_fixture(session, detail)
    _, baseline, _ = await render(client, session, detail)
    _, quieter, _ = await render(client, session, detail, music_gain_db=-6, effects_muted=True)
    first = decode(session.get(Artifact, baseline["artifacts_json"]["master"]).path)
    second = decode(session.get(Artifact, quieter["artifacts_json"]["master"]).path)
    ratio_a = amplitude(first, 330, start=0.3) / amplitude(first, 220, start=0.3)
    ratio_b = amplitude(second, 330, start=0.3) / amplitude(second, 220, start=0.3)
    assert ratio_b / ratio_a == pytest.approx(10 ** (-6 / 20), abs=0.02)
    assert amplitude(second, 880) < 1e-5
    submitted = (
        await client.post(
            f"/projects/{detail['id']}/jobs", json={"stage": "render_mix", "force_new": True}
        )
    ).json()
    artifact = session.get(Artifact, stems.artifacts_json["music"]["master"])
    with Path(artifact.path).open("ab") as handle:
        handle.write(b"changed")
    assert process_once(session)
    assert "checksum changed" in session.get(Job, submitted["id"]).error_message
    assert session.query(MixRender).count() == 2


def test_silent_mix_and_dynamics_opt_in(tmp_path):
    raw = tmp_path / "silent.wav"
    render_float_sum([], 8000, raw, lambda: None)
    with pytest.raises(ValueError, match="silent"):
        normalize_mix(raw, tmp_path / "output.wav", 8000, MixSettings().model_dump(), lambda: None)


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_mix_ffmpeg_native_process_is_terminated(monkeypatch, stop):
    native = subprocess.Popen
    children = []

    def start(command, **kwargs):
        assert "SARVAM_API_KEY" not in kwargs["env"]
        child = native([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr("cinedub_api.media.subprocess.Popen", start)
    monkeypatch.setenv("SARVAM_API_KEY", "not-a-real-key")

    def cancel():
        if stop == "cancel" and children:
            raise InterruptedError("requested")

    with pytest.raises(InterruptedError if stop == "cancel" else TimeoutError):
        run_ffmpeg([], timeout=-1, cancel=cancel)
    assert children[0].poll() is not None


def test_container_audio_offset_is_preserved(tmp_path):
    source = tmp_path / "delayed.mkv"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=s=320x180:r=24:d=4",
            "-itsoffset",
            "0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=3.5",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            str(source),
        ]
    )
    assert float(probe_media(source)["streams"][1]["start_time"]) == 0.5
    extracted = tmp_path / "timeline.wav"
    extract_audio(source, extracted)
    samples = decode(extracted)
    assert max(abs(value) for value in samples[: round(0.49 * 48000) * 2]) == 0
    assert amplitude(samples, 440, start=0.6) > 0.05
    assert len(samples) == 4000 * 48 * 2


@pytest.mark.anyio
async def test_full_resolution_video_replaces_source_audio(client, session, tmp_path):
    source = tmp_path / "full-resolution.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1440x810:r=12:d=8",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=8",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-threads",
            "4",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ]
    )
    detail = await prepare_reviewed_scene(
        client, session, ("scene.mp4", source.read_bytes(), "video/mp4")
    )
    background_fixture(session, detail)
    project, mix, _ = await render(client, session, detail)
    quality = mix["quality_json"]["video"]
    assert quality["width"] == 1440 and quality["height"] == 810 and quality["source_video_copied"]
    assert quality["audio"]["codec"] == "aac" and quality["audio"]["true_peak_dbfs"] <= -1
    video = session.get(Artifact, mix["artifacts_json"]["video"])
    output = decode(video.path)
    assert amplitude(output, 440) < 0.0001 and amplitude(output, 330) > 0.01

    def video_packets(path):
        return json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v",
                    "-show_packets",
                    "-show_data_hash",
                    "sha256",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout
        )["packets"]

    assert [packet["data_hash"] for packet in video_packets(source)] == [
        packet["data_hash"] for packet in video_packets(video.path)
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["edit", "add_line"])
async def test_late_edits_do_not_publish_a_stale_mix(client, session, monkeypatch, change):
    from cinedub_api.mix_processing import normalize_mix as native_normalize

    detail = await prepare_reviewed_scene(client, session)
    background_fixture(session, detail)
    submitted = (
        await client.post(f"/projects/{detail['id']}/jobs", json={"stage": "render_mix"})
    ).json()

    def edited_during_render(*args):
        result = native_normalize(*args)
        with SessionLocal() as concurrent:
            line = concurrent.get(Segment, detail["segments"][0]["id"])
            if change == "edit":
                line.version += 1
                line.translated_text = "New human edit must win"
            else:
                concurrent.add(
                    Segment(
                        project_id=detail["id"],
                        revision_id=detail["active_revision_id"],
                        index=2,
                        start_ms=3000,
                        end_ms=3500,
                        source_text="New line",
                        translated_text="Added line",
                    )
                )
            concurrent.commit()
        return result

    monkeypatch.setattr("cinedub_api.mix_processing.normalize_mix", edited_during_render)
    assert process_once(session)
    assert session.get(Job, submitted["id"]).status == "failed"
    assert "changed" in session.get(Job, submitted["id"]).error_message
    assert session.query(MixRender).count() == 0
    assert session.query(Artifact).filter_by(job_id=submitted["id"]).count() == 0


@pytest.mark.anyio
async def test_changed_render_file_cannot_enter_an_accepted_bundle(client, session):
    detail = await prepare_reviewed_scene(client, session)
    background_fixture(session, detail)
    _, mix, _ = await render(client, session, detail)
    accepted = await client.post(
        f"/mixes/{mix['id']}/review",
        json={
            "status": "approved",
            "expected_version": 1,
            "reviewed_by": "Fixture reviewer",
            "listening_confirmed": True,
        },
    )
    assert accepted.status_code == 200
    master = session.get(Artifact, mix["artifacts_json"]["master"])
    with Path(master.path).open("ab") as handle:
        handle.write(b"modified after review")
    assert process_once(session)
    project = (await client.get(f"/projects/{detail['id']}")).json()
    assert (
        project["jobs"][0]["status"] == "failed"
        and "checksum" in project["jobs"][0]["error_message"]
    )
    assert project["mixes"][0]["reviews"][0]["bundle_artifact_id"] is None
    assert session.query(Artifact).filter_by(kind="mix_bundle").count() == 0


def test_dynamic_normalization_requires_explicit_opt_in(tmp_path):
    raw = tmp_path / "peaky.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='0.0001*sin(2*PI*220*t)+0.9*eq(n,144000)':s=48000:d=8",
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(raw),
        ]
    )
    settings = MixSettings(target_lufs=-14).model_dump()
    with pytest.raises(ValueError, match="dynamics processing"):
        normalize_mix(raw, tmp_path / "blocked.wav", 8000, settings, lambda: None)
    settings["allow_dynamic_normalization"] = True
    report = normalize_mix(raw, tmp_path / "allowed.wav", 8000, settings, lambda: None)
    assert report["second_pass"]["normalization_type"] == "dynamic"


@pytest.mark.anyio
async def test_clone_revocation_quarantines_mix_manifest_bundle_and_cancels_render(client, session):
    from test_cloning import setup_clone, stage

    scene, _, payload = await setup_clone(client, session)
    profile = (await client.post(f"/projects/{scene['id']}/voice-profiles", json=payload)).json()
    await stage(
        client,
        session,
        scene["id"],
        {"stage": "prepare_reference", "voice_profile_id": profile["id"]},
    )
    await stage(
        client,
        session,
        scene["id"],
        {
            "stage": "register_voice",
            "provider": "fake",
            "voice_profile_id": profile["id"],
            "reference_reviewed": True,
        },
    )
    first = scene["segments"][0]
    assert (
        await client.post(
            f"/speakers/{first['speaker_id']}/voice-profile",
            json={
                "profile_id": profile["id"],
                "expected_profile_id": next(
                    item["id"]
                    for item in scene["voice_profiles"]
                    if item["speaker_id"] == first["speaker_id"]
                ),
            },
        )
    ).status_code == 200
    regenerated = await stage(
        client,
        session,
        scene["id"],
        {"stage": "synthesize", "segment_ids": [first["id"]], "force_new": True},
    )
    line = regenerated["segments"][0]
    candidate = next(
        item
        for item in regenerated["artifacts"]
        if item["kind"] == "dialogue_candidate"
        and item["metadata_json"]["voice"]["profile_id"] == profile["id"]
    )
    assert (
        await client.post(
            f"/segments/{line['id']}/candidate",
            json={"artifact_id": candidate["id"], "expected_version": line["version"]},
        )
    ).status_code == 200
    background_fixture(session, scene)
    _, mix, _ = await render(client, session, scene)
    assert (
        await client.post(
            f"/mixes/{mix['id']}/review",
            json={
                "status": "approved",
                "expected_version": 1,
                "reviewed_by": "Fixture",
                "listening_confirmed": True,
            },
        )
    ).status_code == 200
    assert process_once(session)
    project = (await client.get(f"/projects/{scene['id']}")).json()
    bundle_id = project["mixes"][0]["reviews"][0]["bundle_artifact_id"]
    assert bundle_id
    queued = (
        await client.post(
            f"/projects/{scene['id']}/jobs", json={"stage": "render_mix", "force_new": True}
        )
    ).json()
    assert (
        await client.post(
            f"/voice-profiles/{profile['id']}/revoke", json={"attested_by": "Fixture reviewer"}
        )
    ).status_code == 200
    session.expire_all()
    assert session.get(Job, queued["id"]).status == "cancelled"
    for identifier in [
        *mix["artifacts_json"].values(),
        bundle_id,
        project["mixes"][0]["reviews"][0]["certificate_artifact_id"],
    ]:
        assert (
            await client.get(f"/artifacts/{identifier}/download", headers={"Range": "bytes=0-3"})
        ).status_code == 403
        assert (await client.head(f"/artifacts/{identifier}/content")).status_code == 403
