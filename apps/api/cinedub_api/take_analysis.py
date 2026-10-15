"""Immutable source/take analysis inputs, consent checks and material staleness."""

from pathlib import Path

from .alignment import freeze_alignment_audio, validate_alignment_source
from .consent import artifact_block_reason, profile_is_selected, validate_voice_use
from .media import file_digest
from .models import Artifact, Segment, VoiceProfile
from .schemas import TakePerformanceReport
from .timeline import revision_segments
from .voices import candidate_signature


def validate_take(session, project_id, revision_id, take, *, verify_files=False):
    line = session.get(Segment, take["segment_id"])
    candidate = session.get(Artifact, take["candidate_id"])
    voice = take["voice"]
    if not isinstance(voice, dict) or not {"profile_id", "profile_version"}.issubset(voice):
        raise ValueError("Take voice provenance is missing; regenerate it")
    profile = session.get(VoiceProfile, voice["profile_id"])
    if (
        not line
        or line.project_id != project_id
        or line.revision_id != revision_id
        or not candidate
        or candidate.kind != "dialogue_candidate"
        or candidate.project_id != project_id
        or candidate.metadata_json.get("segment_id") != line.id
        or candidate.metadata_json.get("revision_id") != revision_id
        or candidate.metadata_json.get("fit_status") != "ready"
    ):
        raise ValueError("Take does not belong to the current timing-ready dialogue")
    if (
        not profile
        or profile.project_id != project_id
        or profile.version != voice["profile_version"]
        or not profile_is_selected(session, profile)
        or candidate.metadata_json.get("voice") != voice
        or candidate.metadata_json.get("signature") != take["signature"]
        or candidate.metadata_json.get("sha256") != take["candidate_sha256"]
        or candidate_signature(
            {
                field: getattr(line, field)
                for field in ("source_text", "translated_text", "start_ms", "end_ms", "speaker_id")
            },
            voice,
        )
        != take["signature"]
    ):
        raise ValueError("Dialogue, timing or selected voice changed; analyze a current take")
    validate_voice_use(session, profile)
    if artifact_block_reason(session, candidate):
        raise ValueError("Take cloning consent is unavailable or revoked")
    if verify_files and file_digest(candidate.path) != take["candidate_sha256"]:
        raise ValueError("Candidate audio bytes changed; regenerate and analyze again")


def freeze_take_analysis(session, project, payload):
    revision_id = payload.revision_id or project.active_revision_id
    inputs = freeze_alignment_audio(session, project, revision_id, payload.transcription_input)
    if payload.source_asset_id and payload.source_asset_id != inputs["source_asset_id"]:
        raise ValueError("Selected source does not match the transcript")
    lines = revision_segments(session, project.id, revision_id)
    if payload.segment_ids is not None:
        ids = set(payload.segment_ids)
        if not ids or not ids.issubset({line.id for line in lines}):
            raise ValueError("Selected lines do not belong to this revision")
        lines = [line for line in lines if line.id in ids]
    candidate_ids = payload.candidate_ids or [line.selected_candidate_id for line in lines]
    if (
        not 0 < len(candidate_ids) <= 100
        or any(not value for value in candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
    ):
        raise ValueError("Select 1–100 distinct takes, or specify candidates explicitly")
    takes = []
    for candidate_id in candidate_ids:
        candidate = session.get(Artifact, candidate_id)
        line = next(
            (
                line
                for line in lines
                if candidate and line.id == candidate.metadata_json.get("segment_id")
            ),
            None,
        )
        if not line or not candidate.metadata_json.get("sha256"):
            raise ValueError("Candidate/checksum is unavailable for this timeline; regenerate it")
        metadata = candidate.metadata_json
        take = {
            "segment_id": line.id,
            "segment_version": line.version,
            "candidate_id": candidate.id,
            "candidate_sha256": metadata["sha256"],
            "source_text": line.source_text,
            "translated_text": line.translated_text,
            "start_ms": line.start_ms,
            "end_ms": line.end_ms,
            "speaker_id": line.speaker_id,
            "voice": metadata.get("voice", {}),
            "signature": metadata.get("signature"),
            "demo": bool(metadata.get("demo")) or metadata.get("provider") == "fake",
            "evaluation_fixture": bool(metadata.get("evaluation_fixture")),
            "fitted_padding_ms": max(
                0,
                line.end_ms
                - line.start_ms
                - round(metadata["raw_duration_ms"] / metadata["required_speedup"]),
            ),
        }
        validate_take(session, project.id, revision_id, take)
        takes.append(take)
    return {
        **inputs,
        "project_id": project.id,
        "takes": takes,
        "voices": {take["candidate_id"]: take["voice"] for take in takes},
        "candidates": {take["candidate_id"]: take["candidate_id"] for take in takes},
    }


def validate_take_analysis(session, inputs, *, verify_files=False):
    validate_alignment_source(session, inputs, verify_files=verify_files)
    for take in inputs["takes"]:
        validate_take(
            session, inputs["project_id"], inputs["revision_id"], take, verify_files=verify_files
        )


def read_take_report(session, artifact):
    if artifact_block_reason(session, artifact):
        raise PermissionError("Take analysis contains revoked or unavailable cloning provenance")
    if file_digest(artifact.path) != artifact.metadata_json.get("sha256"):
        raise ValueError("Take analysis report changed; analyze again")
    report = TakePerformanceReport.model_validate_json(Path(artifact.path).read_text())
    if report.project_id != artifact.project_id or report.revision_id != artifact.metadata_json.get(
        "revision_id"
    ):
        raise ValueError("Take analysis provenance is inconsistent")
    try:
        validate_alignment_source(session, report.model_dump(), verify_files=True)
    except ValueError as exc:
        report.stale_reason = str(exc)
    except OSError:
        report.stale_reason = "Source analysis media is unavailable; analyze again"
    for line in report.lines:
        try:
            validate_take(
                session, report.project_id, report.revision_id, line.model_dump(), verify_files=True
            )
        except ValueError as exc:
            line.stale_reason = str(exc)
        except OSError:
            line.stale_reason = "Candidate media is unavailable; analyze again"
    return report
