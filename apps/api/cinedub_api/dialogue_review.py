"""Provider-neutral editorial context and deterministic checks, not AI adaptation."""

import re
import unicodedata
from pathlib import Path

from sqlalchemy import select

from .media import file_digest
from .models import DialogueBrief, Job, Speaker, TimelineRevision
from .schemas import (
    DialogueBriefContent,
    DialogueBriefRead,
    DialogueReviewLine,
    DialogueReviewReport,
)
from .storage import storage
from .timeline import revision_segments

METHOD = "dialogue-review-v1"
LIMITATIONS = [
    "Local editorial checks only: scene and character notes are not sent to a translation model",
    "Preferred-text checks cannot judge meaning, grammar, inflection or natural Malayalam",
    "The saved time window is a constraint, not an estimate of spoken translation duration",
    "Character intent and delivery notes are human direction, not inferred speech emotion",
]


def latest_brief(session, project_id, revision_id):
    row = session.scalar(
        select(DialogueBrief)
        .where(DialogueBrief.project_id == project_id, DialogueBrief.revision_id == revision_id)
        .order_by(DialogueBrief.version.desc())
        .limit(1)
    )
    return DialogueBriefRead(
        id=row.id if row else None,
        project_id=project_id,
        revision_id=revision_id,
        version=row.version if row else 0,
        content=DialogueBriefContent.model_validate(row.content_json)
        if row
        else DialogueBriefContent(),
    )


def context_lines(session, project_id, revision_id):
    speakers = {
        item.id: item.display_name
        for item in session.scalars(
            select(Speaker).where(
                Speaker.project_id == project_id, Speaker.revision_id == revision_id
            )
        )
    }
    return [
        {
            "segment_id": line.id,
            "source_text": line.source_text,
            "translated_text": line.translated_text,
            "speaker_id": line.speaker_id,
            "speaker_name": speakers.get(line.speaker_id),
            "start_ms": line.start_ms,
            "end_ms": line.end_ms,
        }
        for line in revision_segments(session, project_id, revision_id)
    ]


def freeze_dialogue_review(session, project, payload):
    revision_id = payload.revision_id or project.active_revision_id
    revision = session.get(TimelineRevision, revision_id) if revision_id else None
    if not revision or revision.project_id != project.id:
        raise ValueError("Select a timeline revision first")
    if payload.regenerate:
        raise ValueError("Editorial checks do not regenerate or replace dialogue")
    context = context_lines(session, project.id, revision.id)
    if not context or len(context) > 500:
        raise ValueError("Editorial review requires 1 to 500 saved dialogue lines")
    selected = (
        payload.segment_ids
        if payload.segment_ids is not None
        else [line["segment_id"] for line in context]
    )
    if (
        not selected
        or len(selected) != len(set(selected))
        or not set(selected).issubset({line["segment_id"] for line in context})
    ):
        raise ValueError("Select distinct lines from this timeline revision")
    versions = {
        line.id: line.version for line in revision_segments(session, project.id, revision.id)
    }
    return {
        "model": METHOD,
        "revision_id": revision.id,
        "source_asset_id": revision.source_asset_id,
        "brief": latest_brief(session, project.id, revision.id).model_dump(mode="json"),
        "context_lines": context,
        "review_ids": [line["segment_id"] for line in context if line["segment_id"] in selected],
        "observed_versions": versions,
    }


def stale_reason(session, project_id, inputs):
    session.expire_all()
    revision = session.get(TimelineRevision, inputs["revision_id"])
    if (
        not revision
        or revision.project_id != project_id
        or revision.source_asset_id != inputs["source_asset_id"]
    ):
        return "Timeline source changed or is unavailable; review again"
    if latest_brief(session, project_id, revision.id).model_dump(mode="json") != inputs["brief"]:
        return "Saved dialogue brief changed; review again"
    if context_lines(session, project_id, revision.id) != inputs["context_lines"]:
        return "Saved dialogue, timing, speaker or surrounding context changed; review again"
    return None


def normalized(text):
    return unicodedata.normalize("NFC", text).casefold()


def is_word_character(character):
    return bool(character) and (unicodedata.category(character)[0] in "LNM" or character == "_")


def source_contains(text, term):
    """Literal Unicode-aware boundaries, including Indic combining marks; no user regex."""
    text, term = normalized(text), normalized(term)
    for match in re.finditer(re.escape(term), text):
        left = text[match.start() - 1] if match.start() else ""
        right = text[match.end()] if match.end() < len(text) else ""
        if is_word_character(term[0]) and is_word_character(left):
            continue
        if is_word_character(term[-1]) and is_word_character(right):
            continue
        return True
    return False


def review_findings(line, matched):
    findings = []
    if not line["translated_text"].strip():
        findings.append(
            {"code": "missing_translation", "message": "This saved line has no translation"}
        )
    else:
        for term in matched:
            if normalized(term.preferred_target) not in normalized(line["translated_text"]):
                findings.append(
                    {
                        "code": "missing_preferred_term",
                        "message": (
                            f"Preferred text “{term.preferred_target}” for “{term.source}” "
                            "is not present; review wording or inflection"
                        ),
                        "source_term": term.source,
                        "preferred_target": term.preferred_target,
                    }
                )
    if not line["speaker_id"]:
        findings.append(
            {"code": "unassigned_speaker", "message": "Assign a speaker to use character direction"}
        )
    return findings


def build_review(inputs, project_id):
    brief = DialogueBriefRead.model_validate(inputs["brief"])
    directions = {item.speaker_id: item for item in brief.content.characters}
    lines = []
    for index, line in enumerate(inputs["context_lines"]):
        if line["segment_id"] not in inputs["review_ids"]:
            continue
        matched = [
            term
            for term in brief.content.glossary
            if source_contains(line["source_text"], term.source)
        ]
        lines.append(
            DialogueReviewLine(
                **line,
                segment_version=inputs["observed_versions"][line["segment_id"]],
                slot_duration_ms=line["end_ms"] - line["start_ms"],
                target_character_count=len(line["translated_text"]),
                previous_line=inputs["context_lines"][index - 1] if index else None,
                next_line=inputs["context_lines"][index + 1]
                if index + 1 < len(inputs["context_lines"])
                else None,
                character_direction=directions.get(line["speaker_id"]),
                matched_glossary=matched,
                findings=review_findings(line, matched),
            )
        )
    return DialogueReviewReport(
        project_id=project_id,
        revision_id=inputs["revision_id"],
        source_language=inputs["source_language"],
        target_language=inputs["target_language"],
        brief=brief,
        context_lines=inputs["context_lines"],
        lines=lines,
        warnings=LIMITATIONS,
    )


def read_dialogue_review(session, artifact):
    path = Path(artifact.path).resolve()
    if not storage().readable(path):
        raise ValueError("Editorial report is outside storage or unavailable")
    if file_digest(path) != artifact.metadata_json.get("sha256"):
        raise ValueError("Editorial report bytes changed")
    report = DialogueReviewReport.model_validate_json(path.read_text(encoding="utf-8"))
    job = session.get(Job, artifact.job_id)
    if not job or job.stage != "review_translation" or job.project_id != artifact.project_id:
        raise ValueError("Editorial report lineage is unavailable")
    expected = build_review(job.input_json, job.project_id)
    if report.model_dump() != expected.model_dump():
        raise ValueError("Editorial report differs from its saved inputs")
    report.stale_reason = stale_reason(session, job.project_id, job.input_json)
    return report
