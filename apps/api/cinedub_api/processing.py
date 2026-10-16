"""Resumable transcription and revision-safe translation stages."""

import json
import re
import time
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Artifact, Job, MediaAsset, Project, ProviderRun, Segment, StemSet
from .providers import ProviderRegistry
from .providers.local_asr import read_manifest
from .providers.retry import retry_safe
from .timeline import import_transcript, normalize_transcript


def check_cancel(session: Session, job: Job) -> None:
    session.refresh(job)
    if job.cancel_requested:
        raise InterruptedError("Job cancelled; a submitted provider request may still be billed")


def checkpoint(session: Session, job: Job, phase: str, **values) -> None:
    check_cancel(session, job)
    job.phase = phase
    job.checkpoint_json = {**job.checkpoint_json, **values}
    session.commit()


def charge(session: Session, job: Job, amount: float) -> None:
    check_cancel(session, job)
    if job.charged_estimate_inr + amount > job.estimated_cost_inr + 0.000001:
        raise ValueError("This operation has exhausted its reserved estimate")
    job.charged_estimate_inr = round(job.charged_estimate_inr + amount, 6)
    session.commit()


def process_transcribe(session: Session, job: Job) -> dict:
    settings = get_settings()
    source = session.get(MediaAsset, job.input_json["source_asset_id"])
    project = session.get(Project, job.project_id)
    if not source or source.project_id != job.project_id:
        raise ValueError("Selected source is unavailable")
    output_dir = settings.storage_root / job.project_id / "transcript" / job.id
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw-transcript.json"
    model = job.input_json.get("model", settings.transcription_model)
    if job.input_json.get("stem_set_id"):
        stems = session.get(StemSet, job.input_json["stem_set_id"])
        if (
            not stems
            or stems.status != "approved"
            or stems.version != job.input_json["stem_set_version"]
            or source.active_stem_set_id != stems.id
        ):
            raise ValueError("Selected dialogue stems changed; submit a new transcription request")
    if job.provider == "fake":
        model = "deterministic-fixture-v2"
        end = source.duration_ms / 1000
        payload = {
            "transcript": "Demonstration transcript.",
            "diarized_transcript": {
                "entries": [
                    {
                        "transcript": "Welcome to CineDub.",
                        "start_time_seconds": 0,
                        "end_time_seconds": end / 2,
                        "speaker_id": "0",
                    },
                    {
                        "transcript": "We can review every line before export.",
                        "start_time_seconds": end / 2,
                        "end_time_seconds": end,
                        "speaker_id": "1",
                    },
                ]
            },
        }
    elif raw_path.is_file():
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        audio = (
            session.get(Artifact, job.input_json["recognition_artifact_id"])
            if job.input_json.get("recognition_artifact_id")
            else next(
                (
                    artifact
                    for artifact in session.scalars(
                        select(Artifact).where(
                            Artifact.project_id == job.project_id,
                            Artifact.kind == "recognition_audio",
                        )
                    ).all()
                    if artifact.metadata_json.get("source_asset_id") == source.id
                ),
                None,
            )
        )
        if not audio:
            raise ValueError("Prepare the scene audio before transcription")

        def cancel():
            check_cancel(session, job)

        if job.provider == "local":
            directory = Path(job.input_json["local_model_dir"])
            if read_manifest(directory) != job.input_json["local_model_manifest"]:
                raise ValueError("Local model changed since scheduling; submit a new job")
            checkpoint(session, job, "local_inference")
            provider = ProviderRegistry(settings).transcriber(job.provider, job.input_json)
            payload = provider.transcribe(Path(audio.path), output_dir, cancel)
        else:
            payload = _batch_transcribe(session, job, audio, output_dir, cancel)
    staging_path = output_dir / "raw-transcript.part"
    staging_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    staging_path.replace(raw_path)
    return _import_result(session, job, project, source, model, raw_path, payload)


def _batch_transcribe(session, job, audio, output_dir, cancel):
    settings = get_settings()
    provider = ProviderRegistry(settings).transcriber(job.provider)
    if not job.remote_job_id:
        checkpoint(session, job, "creating")
        # No blind retries for remote creation: an unsuccessful response can be ambiguous.
        remote_id = provider.create(
            job.input_json["model"],
            job.input_json["source_language"],
            job.input_json.get("num_speakers"),
        )
        job.remote_job_id = remote_id
        session.commit()
        checkpoint(session, job, "created")
    if job.phase in {"created", "uploading"}:
        checkpoint(session, job, "uploading")
        retry_safe(lambda: provider.upload(job.remote_job_id, Path(audio.path)), cancel)
        checkpoint(session, job, "uploaded")
    if job.phase == "uploaded":
        checkpoint(session, job, "starting", poll_started_at=time.time())
        if job.charged_estimate_inr == 0:
            charge(session, job, job.estimated_cost_inr)
        provider.start(job.remote_job_id)
        checkpoint(session, job, "polling")
    if not job.checkpoint_json.get("poll_started_at"):
        checkpoint(session, job, "polling", poll_started_at=time.time())
    while True:
        cancel()
        state = retry_safe(lambda: provider.status(job.remote_job_id), cancel)
        if state == "Completed":
            break
        if state == "Failed":
            raise ValueError("Sarvam transcription failed; check the source audio")
        if (
            time.time() - job.checkpoint_json["poll_started_at"]
            >= settings.provider_timeout_seconds
        ):
            raise TimeoutError("Transcription polling deadline exceeded")
        checkpoint(session, job, "polling", remote_state=state)
        # Do not invent provider percent completion.
        for _ in range(max(1, round(settings.provider_poll_seconds * 2))):
            time.sleep(0.5)
            cancel()
    checkpoint(session, job, "downloading")
    payload = retry_safe(
        lambda: provider.result(job.remote_job_id, output_dir / "download"), cancel
    )
    return payload


def _import_result(session, job, project, source, model, raw_path, payload):
    raw_artifact = session.scalar(
        select(Artifact).where(Artifact.job_id == job.id, Artifact.kind == "raw_transcript")
    )
    if not raw_artifact:
        raw_artifact = Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="raw_transcript",
            path=str(raw_path.resolve()),
            filename="raw-transcript.json",
            media_type="application/json",
            metadata_json={
                "source_asset_id": source.id,
                "provider": job.provider,
                "model": model,
                "recognition_artifact_id": job.input_json.get("recognition_artifact_id"),
                "stem_set_id": job.input_json.get("stem_set_id"),
            },
        )
        session.add(raw_artifact)
        session.commit()
    entries, warnings = normalize_transcript(payload, source.duration_ms)
    if job.provider == "fake":
        warnings.append("DEMO: generated fixture dialogue, not a transcription of this media")
    if job.provider == "local":
        warnings.append(
            "Local ASR has no diarization; create speakers and assign every line manually"
        )
    checkpoint(session, job, "importing")
    revision = import_transcript(
        session,
        project,
        source_asset_id=source.id,
        job_id=job.id,
        provider=job.provider,
        model=model,
        entries=entries,
        warnings=warnings,
    )
    raw_artifact.metadata_json = {**raw_artifact.metadata_json, "revision_id": revision.id}
    if not session.scalar(
        select(ProviderRun.id).where(
            ProviderRun.job_id == job.id, ProviderRun.capability == "transcriber"
        )
    ):
        session.add(
            ProviderRun(
                project_id=job.project_id,
                job_id=job.id,
                capability="transcriber",
                provider=job.provider,
                model=model,
                status="completed",
                parameters_json={
                    "source_asset_id": source.id,
                    "remote_job_id": job.remote_job_id,
                    "local_inference": payload.get("local_metadata"),
                },
                latency_ms=payload.get("local_metadata", {}).get("latency_ms", 0),
                estimated_cost_inr=job.charged_estimate_inr,
            )
        )
    job.warnings_json = warnings
    session.commit()
    return {"revision_id": revision.id, "segments": len(entries), "warnings": warnings}


def split_translation(text: str, limit: int) -> list[str]:
    if limit <= 0:
        raise ValueError("Translation chunk limit must be positive")
    remaining = text.strip()
    parts = []
    while len(remaining) > limit:
        window = remaining[: limit + 1]
        sentences = list(re.finditer(r"[.!?]\s+", window))
        words = list(re.finditer(r"\s+", window))
        cut = sentences[-1].start() + 1 if sentences else words[-1].start() if words else limit
        if cut == 0:
            cut = limit
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def process_translate(session: Session, job: Job) -> dict:
    settings = get_settings()
    provider = ProviderRegistry(settings).translator(job.provider)
    if job.provider == "sarvam":
        provider.model = job.input_json["model"]
        provider.style = job.input_json["style"]
    snapshots = job.input_json.get("segments", [])
    translated, preserved = 0, 0
    results = dict(job.checkpoint_json.get("translation_results", {}))
    for index, snapshot in enumerate(snapshots):
        check_cancel(session, job)
        line = session.get(Segment, snapshot["id"])
        if snapshot["id"] in job.checkpoint_json.get("applied_ids", []):
            translated += 1
            continue
        # Never dispatch paid work for a line that was edited after scheduling.
        if (
            not line
            or line.retired
            or (line.version != snapshot["version"] and snapshot["id"] not in results)
        ):
            preserved += 1
            continue
        if snapshot["id"] not in results:
            chunks = split_translation(
                snapshot["source_text"], 1000 if job.input_json["model"] == "mayura:v1" else 2000
            )
            translated_chunks = list(job.checkpoint_json.get("chunks", {}).get(snapshot["id"], []))
            for chunk_index, chunk in enumerate(chunks):
                if chunk_index < len(translated_chunks):
                    continue
                checkpoint(session, job, "translating", pending_chunk=f"{line.id}:{chunk_index}")

                def before_attempt(chunk=chunk):
                    if job.provider == "sarvam":
                        charge(
                            session,
                            job,
                            len(chunk) / 10_000 * job.input_json["unit_rate_inr"],
                        )

                started = time.monotonic()
                result = retry_safe(
                    lambda chunk=chunk: provider.translate(
                        chunk, job.input_json["source_language"], job.input_json["target_language"]
                    ),
                    lambda: check_cancel(session, job),
                    before_attempt,
                )
                translated_chunks.append(result.text)
                session.add(
                    ProviderRun(
                        project_id=job.project_id,
                        job_id=job.id,
                        capability="translator",
                        provider=result.provider,
                        model=result.model,
                        status="completed",
                        latency_ms=round((time.monotonic() - started) * 1000),
                        estimated_cost_inr=(
                            len(chunk) / 10_000 * job.input_json["unit_rate_inr"]
                            if job.provider == "sarvam"
                            else 0
                        ),
                        parameters_json={
                            "segment_id": line.id,
                            "source_version": snapshot["version"],
                            "request_id": result.request_id,
                            "style": job.input_json["style"],
                        },
                    )
                )
                checkpoint(
                    session,
                    job,
                    "translating",
                    pending_chunk=None,
                    chunks={**job.checkpoint_json.get("chunks", {}), line.id: translated_chunks},
                )
            results[line.id] = " ".join(translated_chunks)
            checkpoint(session, job, "applying", translation_results=results)
        text = results[snapshot["id"]]
        changed = session.execute(
            update(Segment)
            .where(Segment.id == snapshot["id"], Segment.version == snapshot["version"])
            .values(
                translated_text=text,
                status="translated",
                human_edited=False,
                delivery_json={
                    **line.delivery_json,
                    "translation_source": snapshot["source_text"],
                    "translation_provider": job.provider,
                    "translation_model": job.input_json["model"],
                },
                version=snapshot["version"] + 1,
            )
        )
        if changed.rowcount:
            translated += 1
        else:
            # The candidate is retained in the job, not written over an editor's new text.
            preserved += 1
        checkpoint(
            session,
            job,
            "translating",
            applied_ids=[*job.checkpoint_json.get("applied_ids", []), snapshot["id"]],
        )
        job.progress = (index + 1) / max(1, len(snapshots))
        session.commit()
    if preserved:
        job.warnings_json = [
            "Newer human edits were preserved; unused translations remain in job results"
        ]
    output_dir = settings.storage_root / job.project_id / "translation" / job.id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "translation-candidates.json"
    path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    if not session.scalar(select(Artifact.id).where(Artifact.job_id == job.id)):
        session.add(
            Artifact(
                project_id=job.project_id,
                job_id=job.id,
                kind="translation_candidates",
                path=str(path.resolve()),
                filename=path.name,
                media_type="application/json",
                metadata_json={
                    "revision_id": job.input_json["revision_id"],
                    "provider": job.provider,
                    "model": job.input_json["model"],
                },
            )
        )
    session.commit()
    return {
        "translated_segments": translated,
        "preserved_newer_edits": preserved,
        "candidate_results": results,
    }
