"""Human performance interpretation is append-only and separate from model predictions."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..dependencies import SessionDep
from ..jobs import write_lock
from ..models import Artifact, SpeechEmotionReviewRecord
from ..schemas import SpeechEmotionReport, SpeechEmotionReview, SpeechEmotionReviewRead
from ..speech_emotion import read_emotion_report

router = APIRouter(tags=["speech-emotion"])


def require_report(session, artifact_id):
    artifact = session.get(Artifact, artifact_id)
    if not artifact or artifact.kind != "speech_emotion_report":
        raise HTTPException(404, "Speech-emotion report not found")
    try:
        return read_emotion_report(session, artifact)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(
            409, "Speech-emotion evidence changed or is unavailable; analyze again"
        ) from exc


@router.get("/speech-emotion-reports/{artifact_id}", response_model=SpeechEmotionReport)
def emotion_report(artifact_id: str, session: SessionDep):
    return require_report(session, artifact_id)


@router.post("/speech-emotion-reports/{artifact_id}/review", response_model=SpeechEmotionReviewRead)
def review_emotion(artifact_id: str, payload: SpeechEmotionReview, session: SessionDep):
    write_lock(session)
    report = require_report(session, artifact_id)
    line = next((item for item in report.lines if item.segment_id == payload.segment_id), None)
    if not line:
        raise HTTPException(422, "This line is not in the speech-emotion report")
    if report.stale_reason or line.stale_reason:
        raise HTTPException(409, report.stale_reason or line.stale_reason)
    current = session.scalar(
        select(SpeechEmotionReviewRecord)
        .where(
            SpeechEmotionReviewRecord.artifact_id == artifact_id,
            SpeechEmotionReviewRecord.segment_id == line.segment_id,
        )
        .order_by(SpeechEmotionReviewRecord.version.desc())
        .limit(1)
    )
    version = current.version if current else 0
    if payload.expected_review_version != version:
        raise HTTPException(
            409, "Another review was saved; load the latest report before reviewing"
        )
    if not payload.listening_confirmed:
        raise HTTPException(
            422, "Listen to the source window before recording performance direction"
        )
    label = payload.label
    if payload.status == "accepted":
        if line.suggested_label is None or label not in {None, line.suggested_label}:
            raise HTTPException(
                422,
                "Only an actual model suggestion can be accepted; use a human correction instead",
            )
        label = line.suggested_label
    elif payload.status == "corrected" and label is None:
        raise HTTPException(422, "Choose a human performance label for a correction")
    elif payload.status == "rejected" and label is not None:
        raise HTTPException(422, "A rejected prediction cannot retain a chosen emotion label")
    record = SpeechEmotionReviewRecord(
        artifact_id=artifact_id,
        segment_id=line.segment_id,
        version=version + 1,
        status=payload.status,
        label=label,
        direction=payload.direction,
        reviewed_by=payload.reviewed_by,
        note=payload.note,
    )
    session.add(record)
    session.commit()
    return record
