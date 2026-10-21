"""Application-owned timeline normalization and revisions."""

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Project, Segment, Speaker, TimelineRevision


def normalize_transcript(payload: dict, duration_ms: int) -> tuple[list[dict], list[str]]:
    entries = (payload.get("diarized_transcript") or {}).get("entries")
    warnings: list[str] = []
    if entries is None:
        times = payload.get("timestamps") or {}
        chunks = times.get("chunks", times.get("words", []))
        starts = times.get("start_time_seconds", [])
        ends = times.get("end_time_seconds", [])
        if not (len(chunks) == len(starts) == len(ends)):
            raise ValueError("Transcript timestamp arrays do not match")
        entries = [
            {"transcript": text, "start_time_seconds": start, "end_time_seconds": end}
            for text, start, end in zip(chunks, starts, ends, strict=True)
        ]
        if not entries and payload.get("transcript", "").strip():
            raise ValueError("Provider returned text without usable phrase timings")
    if not isinstance(entries, list):
        raise ValueError("Transcript entries must be an array")
    normalized = []
    for entry in entries:
        text = entry.get("transcript", "").strip()
        if not text:
            continue
        start = float(entry["start_time_seconds"]) * 1000
        end = float(entry["end_time_seconds"]) * 1000
        if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end <= start:
            raise ValueError("Provider returned invalid phrase timing")
        line_warnings = []
        if end > duration_ms:
            if end > duration_ms + 250 or start >= duration_ms:
                raise ValueError("Provider timing exceeds source duration")
            end = duration_ms
            line_warnings.append("End timing clamped to source duration")
        start_ms, end_ms = round(start), round(end)
        if end_ms <= start_ms:
            raise ValueError("Provider phrase is shorter than one millisecond")
        label = entry.get("speaker_id")
        if label is None or str(label).strip() == "":
            label = None
            line_warnings.append("Speaker unassigned; review this line")
        normalized.append(
            {
                "source_text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker_label": str(label) if label is not None else None,
                "warnings_json": line_warnings,
            }
        )
    normalized.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    if not normalized:
        warnings.append("No speech detected; no dialogue lines were created")
    if any(item["speaker_label"] is None for item in normalized):
        warnings.append("Some lines have no speaker assignment")
    return normalized, warnings


def revision_segments(session: Session, project_id: str, revision_id: str | None) -> list[Segment]:
    return list(
        session.scalars(
            select(Segment)
            .where(
                Segment.project_id == project_id,
                Segment.revision_id == revision_id,
                Segment.retired.is_(False),
            )
            .order_by(Segment.start_ms, Segment.index)
        ).all()
    )


def import_transcript(
    session: Session,
    project: Project,
    *,
    source_asset_id: str | None,
    job_id: str,
    provider: str,
    model: str,
    entries: list[dict],
    warnings: list[str],
) -> TimelineRevision:
    existing = session.scalar(select(TimelineRevision).where(TimelineRevision.job_id == job_id))
    if existing:
        return existing
    revision = TimelineRevision(
        project_id=project.id,
        source_asset_id=source_asset_id,
        job_id=job_id,
        provider=provider,
        model=model,
        warnings_json=warnings,
    )
    session.add(revision)
    session.flush()
    speakers = {}
    for index, entry in enumerate(entries):
        values = dict(entry)
        label = values.pop("speaker_label")
        if label is not None and label not in speakers:
            speaker = Speaker(
                project_id=project.id,
                revision_id=revision.id,
                label=label,
                display_name=f"Speaker {chr(65 + len(speakers))}",
            )
            session.add(speaker)
            session.flush()
            speakers[label] = speaker.id
        session.add(
            Segment(
                project_id=project.id,
                revision_id=revision.id,
                speaker_id=speakers.get(label),
                index=index,
                **values,
            )
        )
    if not project.active_revision_id:
        project.active_revision_id = revision.id
    session.flush()
    return revision
