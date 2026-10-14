import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal, create_database
from .media import (
    copy_reference_video,
    create_preview_proxy,
    extract_audio,
    write_srt,
    write_waveform,
)
from .models import Artifact, Job, MediaAsset, Project, ProviderRun, Segment, Speaker, VoiceProfile
from .providers import ProviderRegistry

logger = logging.getLogger("cinedub.worker")
settings = get_settings()


def _update_progress(session: Session, job: Job, progress: float) -> None:
    session.refresh(job)
    if job.cancel_requested:
        raise InterruptedError("Job cancelled")
    job.progress = progress
    session.commit()


def _provider_run(
    session: Session,
    job: Job,
    capability: str,
    provider: str,
    model: str,
    latency_ms: int,
) -> None:
    session.add(
        ProviderRun(
            project_id=job.project_id,
            job_id=job.id,
            capability=capability,
            provider=provider,
            model=model,
            parameters_json={},
            latency_ms=latency_ms,
            status="completed",
        )
    )


def process_demo_pipeline(session: Session, job: Job) -> dict:
    existing = session.scalar(select(Segment).where(Segment.project_id == job.project_id))
    if existing:
        return {"preserved_existing_segments": True}
    speakers = [
        Speaker(project_id=job.project_id, label="SPEAKER_00", display_name="Speaker A"),
        Speaker(project_id=job.project_id, label="SPEAKER_01", display_name="Speaker B"),
    ]
    session.add_all(speakers)
    session.flush()
    rows = [
        (
            0,
            0,
            3400,
            speakers[0].id,
            "Welcome to CineDub.",
            "സിനിഡബിലേക്ക് സ്വാഗതം.",
            "happy",
            0.78,
            0.62,
            1.0,
        ),
        (
            1,
            3700,
            7900,
            speakers[1].id,
            "We can review every line before export.",
            "കയറ്റുമതിക്ക് മുമ്പ് ഓരോ വരിയും പരിശോധിക്കാം.",
            "neutral",
            0.72,
            0.48,
            0.95,
        ),
        (
            2,
            8300,
            12100,
            speakers[0].id,
            "The timing and delivery stay editable.",
            "സമയക്രമവും അവതരണവും തിരുത്താനാകും.",
            "confident",
            0.64,
            0.71,
            1.08,
        ),
        (
            3,
            12600,
            16600,
            speakers[1].id,
            "This is a deterministic demonstration.",
            "ഇത് സ്ഥിരതയുള്ള ഒരു പ്രദർശനമാണ്.",
            "neutral",
            0.83,
            0.45,
            0.92,
        ),
    ]
    for index, start, end, speaker, source, target, emotion, confidence, energy, pace in rows:
        session.add(
            Segment(
                project_id=job.project_id,
                speaker_id=speaker,
                index=index,
                start_ms=start,
                end_ms=end,
                source_text=source,
                translated_text=target,
                status="translated",
                emotion_label=emotion,
                emotion_confidence=confidence,
                energy=energy,
                pace=pace,
                delivery_json={"source": "deterministic-fixture", "editable": True},
            )
        )
    _provider_run(session, job, "pipeline", "fake", "deterministic-fixture-v1", 0)
    session.commit()
    return {"segments": len(rows), "speakers": len(speakers)}


def process_ingest(session: Session, job: Job) -> dict:
    source = session.scalar(
        select(MediaAsset)
        .where(MediaAsset.project_id == job.project_id, MediaAsset.kind == "source")
        .order_by(MediaAsset.created_at.desc())
    )
    if not source:
        raise ValueError("No source media is available")
    source_path = Path(source.path)
    output_dir = settings.storage_root / job.project_id / "ingest" / job.id
    audio_path = output_dir / "source-48khz.wav"
    extract_audio(source_path, audio_path)
    _update_progress(session, job, 0.45)
    waveform_path = output_dir / "waveform.json"
    write_waveform(audio_path, waveform_path)
    artifacts = [
        Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="source_audio",
            path=str(audio_path.resolve()),
            filename="source-48khz.wav",
            media_type="audio/wav",
            metadata_json={"sample_rate": 48000, "channels": 2},
        ),
        Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="waveform",
            path=str(waveform_path.resolve()),
            filename="waveform.json",
            media_type="application/json",
            metadata_json={},
        ),
    ]
    streams = source.metadata_json.get("streams", [])
    has_video = any(stream.get("codec_type") == "video" for stream in streams)
    if has_video:
        proxy_path = output_dir / "preview.mp4"
        create_preview_proxy(source_path, proxy_path)
        artifacts.append(
            Artifact(
                project_id=job.project_id,
                job_id=job.id,
                kind="preview_proxy",
                path=str(proxy_path.resolve()),
                filename="preview.mp4",
                media_type="video/mp4",
                metadata_json={"purpose": "browser-preview"},
            )
        )
    session.add_all(artifacts)
    session.commit()
    return {"artifact_ids": [artifact.id for artifact in artifacts]}


def process_translate(session: Session, job: Job) -> dict:
    registry = ProviderRegistry(settings)
    provider = registry.translator(job.provider)
    segments = session.scalars(
        select(Segment).where(Segment.project_id == job.project_id).order_by(Segment.index)
    ).all()
    if not segments:
        raise ValueError("No transcript segments exist")
    translated = 0
    for index, segment in enumerate(segments, start=1):
        if segment.status == "approved":
            continue
        started = time.monotonic()
        result = provider.translate(segment.source_text, "en-IN", "ml-IN")
        elapsed = round((time.monotonic() - started) * 1000)
        segment.translated_text = result.text
        segment.status = "translated"
        segment.version += 1
        _provider_run(session, job, "translator", result.provider, result.model, elapsed)
        translated += 1
        _update_progress(session, job, index / len(segments) * 0.9)
    session.commit()
    return {"translated_segments": translated, "preserved_approved": len(segments) - translated}


def process_synthesize(session: Session, job: Job) -> dict:
    provider = ProviderRegistry(settings).voice_synthesizer(job.provider)
    segments = session.scalars(
        select(Segment).where(Segment.project_id == job.project_id).order_by(Segment.index)
    ).all()
    profiles = {
        profile.speaker_id: profile
        for profile in session.scalars(
            select(VoiceProfile).where(VoiceProfile.project_id == job.project_id)
        ).all()
    }
    created = []
    for index, segment in enumerate(segments, start=1):
        profile = profiles.get(segment.speaker_id or "")
        if job.provider != "fake" and (not profile or profile.consent_status != "approved"):
            raise PermissionError(
                f"Approved voice consent is missing for segment {segment.index + 1}"
            )
        output = settings.storage_root / job.project_id / "voice" / f"{segment.id}.wav"
        started = time.monotonic()
        result = provider.synthesize(
            segment.translated_text or segment.source_text,
            "ml-IN",
            output,
            voice_id=profile.provider_voice_id if profile else segment.speaker_id,
        )
        elapsed = round((time.monotonic() - started) * 1000)
        artifact = Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="dialogue_candidate",
            path=str(result.audio_path.resolve()),
            filename=f"segment-{segment.index + 1}-ml.wav",
            media_type="audio/wav",
            metadata_json={"segment_id": segment.id, "provider": result.provider},
        )
        session.add(artifact)
        segment.status = "voiced"
        segment.version += 1
        _provider_run(session, job, "voice_synthesizer", result.provider, result.model, elapsed)
        session.flush()
        created.append(artifact.id)
        _update_progress(session, job, index / len(segments) * 0.9)
    session.commit()
    return {"artifact_ids": created}


def process_export(session: Session, job: Job) -> dict:
    segments = session.scalars(
        select(Segment).where(Segment.project_id == job.project_id).order_by(Segment.index)
    ).all()
    if not segments:
        raise ValueError("No segments are available to export")
    export_dir = settings.storage_root / job.project_id / "exports" / job.id
    srt_path = export_dir / "malayalam.srt"
    write_srt(list(segments), srt_path)
    subtitle = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="subtitle",
        path=str(srt_path.resolve()),
        filename="malayalam.srt",
        media_type="application/x-subrip",
        metadata_json={"language": "ml-IN", "segment_count": len(segments)},
    )
    session.add(subtitle)
    session.flush()
    artifact_ids = [subtitle.id]
    source = session.scalar(
        select(MediaAsset)
        .where(MediaAsset.project_id == job.project_id, MediaAsset.kind == "source")
        .order_by(MediaAsset.created_at.desc())
    )
    if source and Path(source.path).suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
        target = export_dir / f"reference{Path(source.path).suffix.lower()}"
        copy_reference_video(Path(source.path), target)
        reference = Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="reference_video",
            path=str(target.resolve()),
            filename=target.name,
            media_type=source.media_type,
            metadata_json={"warning": "Picture reference only; dubbed mix is not rendered yet"},
        )
        session.add(reference)
        session.flush()
        artifact_ids.append(reference.id)
    session.commit()
    return {"artifact_ids": artifact_ids, "validated": True, "dubbed_mix": False}


PROCESSORS = {
    "ingest": process_ingest,
    "demo_pipeline": process_demo_pipeline,
    "translate": process_translate,
    "synthesize": process_synthesize,
    "export": process_export,
}


def claim_job(session: Session) -> Job | None:
    job = session.scalar(
        select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1)
    )
    if not job:
        return None
    job.status = "running"
    job.started_at = datetime.now(UTC)
    job.attempts += 1
    session.commit()
    session.refresh(job)
    return job


def process_once(session: Session) -> bool:
    job = claim_job(session)
    if not job:
        return False
    project = session.get(Project, job.project_id)
    try:
        processor = PROCESSORS[job.stage]
        output = processor(session, job)
        session.refresh(job)
        if job.cancel_requested:
            raise InterruptedError("Job cancelled")
        job.output_json = output
        job.progress = 1.0
        job.status = "completed"
        if job.stage == "ingest":
            project.status = "draft"
        elif job.stage == "export":
            project.status = "ready"
        else:
            project.status = "review"
    except InterruptedError as exc:
        session.rollback()
        job = session.get(Job, job.id)
        project = session.get(Project, job.project_id)
        job.status = "cancelled"
        job.error_code = "cancelled"
        job.error_message = str(exc)
        project.status = "review"
    except Exception as exc:  # worker boundary records structured failures
        logger.exception("Job %s failed", job.id)
        session.rollback()
        job = session.get(Job, job.id)
        project = session.get(Project, job.project_id)
        job.status = "failed"
        job.error_code = type(exc).__name__
        job.error_message = str(exc)[:2000]
        project.status = "failed"
    job.finished_at = datetime.now(UTC)
    session.commit()
    return True


def run_worker(poll_interval: float = 1.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    create_database()
    logger.info("CineDub worker started")
    while True:
        with SessionLocal() as session:
            worked = process_once(session)
        if not worked:
            time.sleep(poll_interval)
