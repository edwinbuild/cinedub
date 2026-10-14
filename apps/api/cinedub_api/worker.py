import fcntl
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from .clone_processing import (
    process_delete_voice,
    process_prepare_reference,
    process_register_voice,
)
from .config import get_settings
from .database import SessionLocal, create_database
from .media import (
    copy_reference_video,
    create_preview_proxy,
    extract_audio,
    run_ffmpeg,
    write_srt,
    write_waveform,
)
from .models import (
    Artifact,
    Job,
    MediaAsset,
    Project,
    ProviderRun,
    Segment,
    Speaker,
    TimelineRevision,
)
from .processing import process_transcribe
from .processing import process_translate as process_real_translate
from .providers.retry import safe_error
from .separation_processing import process_separate
from .voice_processing import process_render_preview
from .voice_processing import process_synthesize as process_voice_candidates

logger = logging.getLogger("cinedub.worker")
settings = get_settings()


def _update_progress(session: Session, job: Job, progress: float, phase: str | None = None) -> None:
    session.refresh(job)
    if job.cancel_requested:
        raise InterruptedError("Job cancelled")
    job.progress = progress
    if phase:
        job.phase = phase
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
    revision = TimelineRevision(
        project_id=job.project_id,
        job_id=job.id,
        provider="fake",
        model="deterministic-fixture-v1",
        warnings_json=["DEMO: dialogue and performance are fixtures"],
    )
    session.add(revision)
    session.flush()
    session.get(Project, job.project_id).active_revision_id = revision.id
    speakers = [
        Speaker(
            project_id=job.project_id,
            revision_id=revision.id,
            label="SPEAKER_00",
            display_name="Speaker A",
        ),
        Speaker(
            project_id=job.project_id,
            revision_id=revision.id,
            label="SPEAKER_01",
            display_name="Speaker B",
        ),
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
                revision_id=revision.id,
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
    existing = session.scalars(select(Artifact).where(Artifact.job_id == job.id)).all()
    if existing:
        return {"artifact_ids": [item.id for item in existing]}
    source = session.get(MediaAsset, job.input_json.get("source_asset_id"))
    if not source:
        raise ValueError("No source media is available")
    source_path = Path(source.path)
    output_dir = settings.storage_root / job.project_id / "ingest" / job.id
    audio_path = output_dir / "source-48khz.wav"
    _update_progress(session, job, 0, "extracting_audio")
    extract_audio(source_path, audio_path)
    _update_progress(session, job, 0.35, "creating_waveform")
    waveform_path = output_dir / "waveform.json"
    write_waveform(audio_path, waveform_path)
    _update_progress(session, job, 0.5, "preparing_recognition_audio")
    recognition_path = output_dir / "recognition-16khz.wav"
    run_ffmpeg(
        [
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(recognition_path),
        ]
    )
    artifacts = [
        Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="source_audio",
            path=str(audio_path.resolve()),
            filename="source-48khz.wav",
            media_type="audio/wav",
            metadata_json={"sample_rate": 48000, "channels": 2, "source_asset_id": source.id},
        ),
        Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="waveform",
            path=str(waveform_path.resolve()),
            filename="waveform.json",
            media_type="application/json",
            metadata_json={"source_asset_id": source.id},
        ),
        Artifact(
            project_id=job.project_id,
            job_id=job.id,
            kind="recognition_audio",
            path=str(recognition_path.resolve()),
            filename=recognition_path.name,
            media_type="audio/wav",
            metadata_json={"sample_rate": 16000, "channels": 1, "source_asset_id": source.id},
        ),
    ]
    streams = source.metadata_json.get("streams", [])
    has_video = any(stream.get("codec_type") == "video" for stream in streams)
    if has_video:
        _update_progress(session, job, 0.7, "creating_video_proxy")
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
                metadata_json={"purpose": "browser-preview", "source_asset_id": source.id},
            )
        )
    session.add_all(artifacts)
    session.commit()
    return {"artifact_ids": [artifact.id for artifact in artifacts]}


def process_translate(session: Session, job: Job) -> dict:
    return process_real_translate(session, job)


def process_synthesize(session: Session, job: Job) -> dict:
    return process_voice_candidates(session, job)


def process_export(session: Session, job: Job) -> dict:
    existing = session.scalars(select(Artifact).where(Artifact.job_id == job.id)).all()
    if existing:
        return {"artifact_ids": [item.id for item in existing], "dubbed_mix": False}
    _update_progress(session, job, 0, "writing_subtitles")
    segments = [SimpleNamespace(**snapshot) for snapshot in job.input_json.get("segments", [])]
    if not segments:
        raise ValueError("No segments are available to export")
    export_dir = settings.storage_root / job.project_id / "exports" / job.id
    revision = session.get(TimelineRevision, job.input_json.get("revision_id"))
    filename = "demo-malayalam.srt" if revision.provider == "fake" else "malayalam.srt"
    srt_path = export_dir / filename
    write_srt(list(segments), srt_path)
    subtitle = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="subtitle",
        path=str(srt_path.resolve()),
        filename=filename,
        media_type="application/x-subrip",
        metadata_json={
            "language": "ml-IN",
            "segment_count": len(segments),
            "revision_id": revision.id,
            "provider": revision.provider,
            "segment_versions": {line.id: line.version for line in segments},
            "incomplete": any(not line.translated_text.strip() for line in segments),
        },
    )
    session.add(subtitle)
    session.flush()
    artifact_ids = [subtitle.id]
    source = session.get(MediaAsset, revision.source_asset_id) if revision.source_asset_id else None
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
    "transcribe": process_transcribe,
    "translate": process_translate,
    "synthesize": process_synthesize,
    "export": process_export,
    "render_preview": process_render_preview,
    "prepare_reference": process_prepare_reference,
    "register_voice": process_register_voice,
    "delete_voice": process_delete_voice,
    "separate": process_separate,
}


def claim_job(session: Session) -> Job | None:
    job = session.scalar(
        select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1)
    )
    if not job:
        return None
    result = session.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == "queued")
        .values(
            status="running",
            started_at=datetime.now(UTC),
            attempts=Job.attempts + 1,
            phase=case((Job.phase == "queued", "preparing"), else_=Job.phase),
        )
    )
    if result.rowcount != 1:
        session.rollback()
        return None
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
        job.phase = "completed"
        if job.stage == "ingest":
            project.status = "draft"
        elif job.stage in {"export", "render_preview"}:
            project.status = "ready"
        else:
            project.status = "review"
    except InterruptedError as exc:
        session.rollback()
        job = session.get(Job, job.id)
        project = session.get(Project, job.project_id)
        job.status = "cancelled"
        job.phase = "cancelled"
        job.error_code = "cancelled"
        job.error_message = str(exc)
        project.status = "review"
    except Exception as exc:  # worker boundary records structured failures
        logger.error("job_id=%s stage=%s error_type=%s", job.id, job.stage, type(exc).__name__)
        session.rollback()
        job = session.get(Job, job.id)
        project = session.get(Project, job.project_id)
        job.status = "failed"
        job.retryable = (
            job.stage == "transcribe"
            and bool(job.remote_job_id)
            and isinstance(exc, (TimeoutError, ConnectionError))
        )
        # Status/download errors can safely resume a known remote job without resubmission.
        if (
            job.stage == "transcribe"
            and job.remote_job_id
            and job.phase in {"starting", "polling", "downloading"}
        ):
            job.retryable = True
        job.error_code = type(exc).__name__
        job.error_message = safe_error(exc)
        if job.stage == "register_voice" and job.checkpoint_json.get("pending_registration"):
            job.error_code = "uncertain_registration"
            job.error_message = (
                "Voice upload outcome is unknown. Inspect provider voices/usage "
                "before an explicit retry."
            )
        project.status = "failed"
    job.finished_at = datetime.now(UTC)
    session.commit()
    return True


def recover_jobs(session: Session) -> None:
    for job in session.scalars(select(Job).where(Job.status == "running")).all():
        uncertain = job.provider != "fake" and (
            (job.stage == "transcribe" and not job.remote_job_id and job.phase == "creating")
            or bool(job.checkpoint_json.get("pending_chunk"))
            or bool(job.checkpoint_json.get("pending_voice"))
            or bool(job.checkpoint_json.get("pending_registration"))
        )
        if uncertain:
            job.status = "failed"
            job.error_code = "uncertain_submission"
            job.error_message = (
                "Interrupted provider submission; inspect usage before explicitly retrying"
            )
            job.finished_at = datetime.now(UTC)
            session.get(Project, job.project_id).status = "failed"
        else:
            job.status = "queued"
            if job.stage == "transcribe" and job.remote_job_id and job.phase == "creating":
                job.phase = "created"
    session.commit()


def worker_lock_path() -> Path:
    if settings.database_url.startswith("sqlite:///"):
        database = Path(settings.database_url.removeprefix("sqlite:///")).resolve()
        return database.with_name(f"{database.name}.worker.lock")
    return settings.storage_root / ".worker.lock"


def run_worker(poll_interval: float = 1.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    lock_path = worker_lock_path()
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A CineDub worker is already running for this database") from exc
        create_database()
        with SessionLocal() as session:
            recover_jobs(session)
        _worker_loop(poll_interval)


def _worker_loop(poll_interval: float) -> None:
    logger.info("CineDub worker started")
    while True:
        with SessionLocal() as session:
            worked = process_once(session)
        if not worked:
            time.sleep(poll_interval)
