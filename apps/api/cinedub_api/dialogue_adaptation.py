"""Reviewable dialogue alternatives with frozen context and explicit application lineage."""

import unicodedata
from pathlib import Path

from .adaptation_timing import validate_timing_feedback
from .consent import artifact_block_reason
from .dialogue_prompt import GENERATION, PROMPT_VERSION, adaptation_requests, request_digest
from .dialogue_review import build_review, context_lines, latest_brief, review_findings
from .media import file_digest
from .models import Job, Segment, TimelineRevision
from .schemas import DialogueAdaptationReport, DialogueNativeLine
from .storage import storage

WARNINGS = [
    "Experimental model drafts: a Malayalam-speaking editor must verify meaning and naturalness",
    "Scene, character and timing constraints were supplied to the model, not verified as obeyed",
    "Concise text is not proof of spoken duration, lip fit, acting or preserved emotion",
    "Model notes are generated suggestions, not trusted analysis or calibrated confidence",
]


def validate_results(inputs, project_id, values, *, complete=False):
    requests = adaptation_requests(inputs, project_id)
    if (
        not isinstance(values, list)
        or len(values) > len(requests)
        or (complete and len(values) != len(requests))
    ):
        raise ValueError("Dialogue adapter did not return the requested line set")
    result = []
    for value, request in zip(values, requests, strict=False):
        line = DialogueNativeLine.model_validate(value)
        if line.segment_id != request["segment_id"] or line.request_sha256 != request_digest(
            request
        ):
            raise ValueError("Dialogue adapter returned mismatched line/prompt provenance")
        result.append(line.model_dump())
    return result


def script_warnings(text):
    letters = [char for char in text if unicodedata.category(char).startswith("L")]
    warnings = []
    if not any("MALAYALAM" in unicodedata.name(char, "") for char in letters):
        warnings.append("No Malayalam letters detected; correct this draft manually")
    if any(not unicodedata.name(char, "").startswith(("MALAYALAM", "LATIN")) for char in letters):
        warnings.append("Unexpected non-Malayalam script detected; correct this draft manually")
    if any(marker in text for marker in ("<|", "|>", "<think>", "</think>")):
        warnings.append("Model control markers detected; correct this draft manually")
    return warnings


def numerals(text):
    return [unicodedata.digit(char) for char in text if char.isdecimal()]


def make_report(inputs, project_id, values, runtime):
    values = validate_results(inputs, project_id, values, complete=True)
    review = build_review(inputs, project_id)
    lines = []
    for evidence, value in zip(review.lines, values, strict=True):
        alternatives = []
        for kind in ("faithful", "concise"):
            text = value["output"][kind]
            findings = review_findings(
                {"translated_text": text, "speaker_id": evidence.speaker_id},
                evidence.matched_glossary,
            )
            critical = script_warnings(text)
            warnings = list(critical)
            if numerals(evidence.source_text) != numerals(text):
                warnings.append(
                    "Source numerals differ; verify any written-out numbers against the source"
                )
            if kind == "concise" and len(text) > len(value["output"]["faithful"]):
                warnings.append(
                    "Concise alternative has more characters; "
                    "listen rather than assuming it is shorter"
                )
            alternatives.append(
                {
                    "kind": kind,
                    "text": text,
                    "findings": findings,
                    "warnings": warnings,
                    "eligible_for_application": not critical,
                }
            )
        lines.append(
            {
                **evidence.model_dump(),
                "timing_feedback": inputs.get("timing_feedback", {}).get(evidence.segment_id),
                "alternatives": alternatives,
                "model_notes": value["output"]["notes"],
                **{
                    key: value[key]
                    for key in ("prompt_sha256", "request_sha256", "prompt_tokens", "latency_ms")
                },
            }
        )
    return DialogueAdaptationReport(
        project_id=project_id,
        revision_id=inputs["revision_id"],
        source_language=inputs["source_language"],
        target_language=inputs["target_language"],
        brief=review.brief,
        context_lines=review.context_lines,
        provider=inputs["adaptation_provider"],
        model=inputs["model"],
        prompt_version=PROMPT_VERSION,
        generation_parameters={**GENERATION, "threads": inputs["threads"]},
        runtime=runtime,
        lines=lines,
        warnings=WARNINGS,
    )


def adaptation_freshness(session, artifact_id, inputs, report):
    session.expire_all()
    revision = session.get(TimelineRevision, inputs["revision_id"])
    if (
        not revision
        or revision.project_id != report.project_id
        or revision.source_asset_id != inputs["source_asset_id"]
    ):
        return "Timeline source changed; adapt again", []
    if (
        latest_brief(session, report.project_id, revision.id).model_dump(mode="json")
        != inputs["brief"]
    ):
        return "Saved dialogue brief changed; adapt again", []
    current = context_lines(session, report.project_id, revision.id)
    if len(current) != len(inputs["context_lines"]):
        return "Surrounding dialogue changed; adapt again", []
    proposals = {line.segment_id: line for line in report.lines}
    applied = []
    for saved, actual in zip(inputs["context_lines"], current, strict=True):
        if any(actual[key] != value for key, value in saved.items() if key != "translated_text"):
            return "Source dialogue, timing or speaker context changed; adapt again", []
        segment = session.get(Segment, actual["segment_id"])
        proposal = proposals.get(segment.id)
        known = (
            proposal
            and segment.delivery_json.get("applied_dialogue_adaptation_artifact_id") == artifact_id
            and any(
                option.kind == segment.delivery_json.get("applied_dialogue_adaptation_kind")
                and option.text == segment.translated_text
                for option in proposal.alternatives
            )
        )
        if known:
            applied.append(segment.id)
        elif actual["translated_text"] != saved["translated_text"]:
            return "Saved translation or surrounding context changed; adapt again", []
    try:
        validate_timing_feedback(session, report.project_id, inputs)
    except (OSError, ValueError) as exc:
        return f"Timing feedback is unavailable or changed: {exc}", applied
    return None, applied


def read_adaptation_report(session, artifact):
    if artifact_block_reason(session, artifact):
        raise PermissionError("Dialogue alternatives contain revoked timing-take provenance")
    path = Path(artifact.path).resolve()
    if (
        not storage().contains(path)
        or not path.is_file()
        or file_digest(path) != artifact.metadata_json.get("sha256")
    ):
        raise ValueError("Dialogue adaptation report is unavailable or changed")
    report = DialogueAdaptationReport.model_validate_json(path.read_text(encoding="utf-8"))
    job = session.get(Job, artifact.job_id)
    if not job or job.stage != "adapt_dialogue" or job.project_id != artifact.project_id:
        raise ValueError("Dialogue adaptation lineage is unavailable")
    inputs = job.input_json
    # Read history against committed inputs/results, not today's prompt or policy.
    # A later model/prompt upgrade must not silently regenerate historical evidence.
    if (
        report.project_id != job.project_id
        or report.revision_id != inputs["revision_id"]
        or report.model != inputs["model"]
        or report.provider != inputs["adaptation_provider"]
        or report.prompt_version != inputs["prompt_version"]
        or report.generation_parameters
        != {**inputs["generation_parameters"], "threads": inputs["threads"]}
        or report.brief.model_dump(mode="json") != inputs["brief"]
        or [line.model_dump() for line in report.context_lines] != inputs["context_lines"]
        or report.runtime != job.checkpoint_json["adaptation_runtime"]
        or report.applied_line_ids
        or report.applied_translations
    ):
        raise ValueError("Dialogue adaptation report differs from its committed evidence")
    values = [
        DialogueNativeLine.model_validate(value)
        for value in job.checkpoint_json["adaptation_completed_lines"]
    ]
    if [line.segment_id for line in report.lines] != inputs["review_ids"] or len(values) != len(
        report.lines
    ):
        raise ValueError("Dialogue adaptation line set changed")
    context = {line["segment_id"]: line for line in inputs["context_lines"]}
    for line, value in zip(report.lines, values, strict=True):
        if (
            line.segment_id != value.segment_id
            or any(getattr(line, key) != item for key, item in context[line.segment_id].items())
            or line.segment_version != inputs["observed_versions"][line.segment_id]
            or (line.timing_feedback.model_dump() if line.timing_feedback else None)
            != inputs.get("timing_feedback", {}).get(line.segment_id)
            or line.model_notes != value.output.notes
            or any(
                getattr(line, key) != getattr(value, key)
                for key in ("prompt_sha256", "request_sha256", "prompt_tokens", "latency_ms")
            )
            or [(option.kind, option.text) for option in line.alternatives]
            != [("faithful", value.output.faithful), ("concise", value.output.concise)]
        ):
            raise ValueError("Dialogue adaptation line differs from committed model output")
    report.stale_reason, report.applied_line_ids = adaptation_freshness(
        session, artifact.id, job.input_json, report
    )
    report.applied_translations = {
        identifier: session.get(Segment, identifier).translated_text
        for identifier in report.applied_line_ids
    }
    return report
