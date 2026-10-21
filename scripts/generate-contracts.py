"""Generate web contracts from the same Pydantic schemas that validate the API."""

import argparse
import json
from pathlib import Path
from typing import get_args

from cinedub_api import schemas
from cinedub_api.job_errors import JobErrorCode
from pydantic import TypeAdapter

NAMES = {
    "ProjectRead": "ProjectSummary",
    "MediaAssetRead": "MediaAsset",
    "SpeakerRead": "Speaker",
    "SegmentRead": "Segment",
    "JobRead": "Job",
    "ArtifactRead": "Artifact",
    "ArtifactLineage": "ArtifactLineage",
    "PipelineCreate": "PipelineCreate",
    "PipelineContinue": "PipelineContinue",
    "PipelinePlan": "PipelinePlan",
    "PipelineRead": "Pipeline",
    "ProjectDeletion": "ProjectDeletion",
    "StorageUsage": "StorageUsage",
    "ProjectDetail": "ProjectDetail",
    "RevisionRead": "TimelineRevision",
    "JobEstimate": "JobEstimate",
    "CapabilityRead": "CapabilityStatus",
    "HardwareRead": "HardwareStatus",
    "SegmentUpdate": "SegmentUpdate",
    "SegmentBatchItem": "SegmentBatchItem",
    "SegmentBatchUpdate": "SegmentBatchUpdate",
    "SegmentBatchResult": "SegmentBatchResult",
    "EditGroupSummary": "EditGroupSummary",
    "EditGroupHistory": "EditGroupHistory",
    "EditGroupRestore": "EditGroupRestore",
    "SegmentHistory": "SegmentHistory",
    "SegmentHistoryAction": "SegmentHistoryAction",
    "SegmentSplit": "SegmentSplit",
    "SegmentMerge": "SegmentMerge",
    "TimelineStructureEditRead": "TimelineStructureEdit",
    "TimelineStructureRestore": "TimelineStructureRestore",
    "SpeakerUpdate": "SpeakerUpdate",
    "SpeakerCreate": "SpeakerCreate",
    "SpeakerReusePreview": "SpeakerReusePreview",
    "SpeakerReuseApply": "SpeakerReuseApply",
    "SpeakerReuseRead": "SpeakerReuse",
    "BudgetUpdate": "BudgetUpdate",
    "VoiceProfileCreate": "VoiceProfileCreate",
    "VoiceProfileRead": "VoiceProfile",
    "ConsentInput": "ConsentInput",
    "RevisionActivate": "RevisionActivate",
    "StockVoiceAssignment": "StockVoiceAssignment",
    "VoiceChoice": "VoiceChoice",
    "CandidateSelection": "CandidateSelection",
    "VoiceProfileSelection": "VoiceProfileSelection",
    "ConsentRevocation": "ConsentRevocation",
    "ConsentRecordRead": "ConsentRecord",
    "StemSetRead": "StemSet",
    "StemReview": "StemReview",
    "StemReviewRecordRead": "StemReviewRecord",
    "MixSettings": "MixSettings",
    "MixReview": "MixReview",
    "MixReviewRecordRead": "MixReviewRecord",
    "MixRenderRead": "MixRender",
    "AlignmentReport": "AlignmentReport",
    "AlignmentApply": "AlignmentApply",
    "TakePerformanceReport": "TakePerformanceReport",
    "DialogueBriefRead": "DialogueBrief",
    "DialogueBriefUpdate": "DialogueBriefUpdate",
    "DialogueBriefContent": "DialogueBriefContent",
    "DialogueReviewReport": "DialogueReviewReport",
    "DialogueAdaptationReport": "DialogueAdaptationReport",
    "DialogueAdaptationApply": "DialogueAdaptationApply",
    "SpeechEmotionReport": "SpeechEmotionReport",
    "SpeechEmotionReview": "SpeechEmotionReview",
}
# Discriminated unions are emitted as TypeScript union types of their member interfaces.
UNIONS = {"JobRequest": schemas.JobCreate, "ProjectEvent": schemas.ProjectEvent}
REQUESTS = {
    "PipelineCreate",
    "PipelineContinue",
    *(model.__name__ for model in schemas.JOB_REQUESTS),
    "SpeakerReuseApply",
    "SegmentUpdate",
    "SegmentBatchItem",
    "SegmentBatchUpdate",
    "EditGroupRestore",
    "EditGroupVersion",
    "SegmentHistoryAction",
    "SegmentSplit",
    "SegmentMerge",
    "TimelineStructureRestore",
    "SpeakerUpdate",
    "SpeakerCreate",
    "BudgetUpdate",
    "VoiceProfileCreate",
    "ConsentInput",
    "RevisionActivate",
    "StockVoiceAssignment",
    "CandidateSelection",
    "VoiceProfileSelection",
    "ConsentRevocation",
    "StemReview",
    "MixReview",
    "MixSettings",
    "AlignmentApply",
    "DialogueBriefUpdate",
    "DialogueAdaptationApply",
    "SpeechEmotionReview",
}


def typescript(value):
    if "$ref" in value:
        name = value["$ref"].rsplit("/", 1)[1]
        return NAMES.get(name, name)
    for key in ("anyOf", "oneOf"):
        if key in value:
            return " | ".join(typescript(item) for item in value[key])
    if "allOf" in value and len(value["allOf"]) == 1:
        return typescript(value["allOf"][0])
    if "enum" in value:
        return " | ".join(json.dumps(item, ensure_ascii=False) for item in value["enum"])
    if "const" in value:
        return json.dumps(value["const"])
    kind = value.get("type")
    if kind == "array":
        return f"Array<{typescript(value.get('items', {}))}>"
    if kind == "object":
        additional = value.get("additionalProperties")
        inner = typescript(additional) if isinstance(additional, dict) else "unknown"
        return f"Record<string, {inner}>"
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(kind, "unknown")


def generate():
    definitions = {}
    for name in NAMES:
        value = getattr(schemas, name).model_json_schema()
        definitions.update(value.pop("$defs", {}))
        definitions[name] = value
    unions = {}
    for name, union in UNIONS.items():
        value = TypeAdapter(union).json_schema()
        definitions.update(value.pop("$defs", {}))
        unions[name] = typescript(value)
    lines = ["// Generated by scripts/generate-contracts.py. Do not edit by hand.", ""]
    for name in ("LanguageCode", "ProjectStatus", "JobStatus", "SegmentStatus", "RequestableStage"):
        union = " | ".join(json.dumps(value) for value in get_args(getattr(schemas, name)))
        lines.extend([f"export type {name} = {union};", ""])
    codes = " | ".join(json.dumps(code.value) for code in JobErrorCode)
    lines.extend([f"export type JobErrorCode = {codes};", ""])
    for name, union in unions.items():
        lines.extend([f"export type {name} = {union};", ""])
    for name, value in definitions.items():
        lines.append(f"export interface {NAMES.get(name, name)} {{")
        required = set(value.get("required", []))
        for field, specification in value.get("properties", {}).items():
            optional = "?" if name in REQUESTS and field not in required else ""
            lines.append(f"  {field}{optional}: {typescript(specification)};")
        lines.extend(["}", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "packages/contracts/src/index.ts"
    content = generate()
    if args.check:
        if target.read_text(encoding="utf-8") != content:
            parser.exit(1, "API contracts changed; run npm run contracts:generate\n")
    elif args.write:
        target.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
