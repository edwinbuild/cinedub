"""Artifact lineage: which files and source media every artifact was produced from.

Edges are derived once, when the producing job completes, from that job's frozen inputs and
the artifact's own provenance metadata, then persisted in `artifact_inputs`. The same
derivation backfills artifacts written before lineage existed.
"""

from collections import deque
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .media import file_digest
from .models import Artifact, ArtifactInput, Job, MediaAsset, MixRender, ProviderRun, StemSet
from .storage import storage

LINEAGE_VERSION = 1


def _edges(session: Session, artifact: Artifact, job: Job | None) -> list[tuple[str, str, str]]:
    """(role, kind, id) with kind "artifact" or "asset"."""
    inputs = job.input_json if job else {}
    meta = artifact.metadata_json
    edges = []
    source = inputs.get("source_asset_id") or meta.get("source_asset_id")
    if source:
        edges.append(("source", "asset", source))
    if meta.get("master_artifact_id"):
        edges.append(("derived_from", "artifact", meta["master_artifact_id"]))
    if artifact.kind == "stem_recognition_audio" and meta.get("stem_set_id"):
        stems = session.get(StemSet, meta["stem_set_id"])
        dialogue = (stems.artifacts_json or {}).get("dialogue", {}) if stems else {}
        if dialogue.get("master"):
            edges.append(("derived_from", "artifact", dialogue["master"]))
    if inputs.get("recognition_artifact_id"):
        edges.append(("analysis_audio", "artifact", inputs["recognition_artifact_id"]))
    if inputs.get("reference_artifact_id"):
        edges.append(("voice_reference", "artifact", inputs["reference_artifact_id"]))
    for candidate in (inputs.get("candidates") or {}).values():
        edges.append(("take", "artifact", candidate))
    for name, spec in (inputs.get("background") or {}).items():
        edges.append((f"background:{name}", "artifact", spec["artifact_id"]))
    for feedback in (inputs.get("timing_feedback") or {}).values():
        edges.append(("timing_take", "artifact", feedback["candidate_id"]))
    if job and job.stage == "package_mix" and inputs.get("mix_id"):
        mix = session.get(MixRender, inputs["mix_id"])
        for key, identifier in (mix.artifacts_json or {}).items() if mix else []:
            edges.append((f"accepted:{key}", "artifact", identifier))
    unique, seen = [], set()
    for edge in edges:
        if edge[2] and edge not in seen and edge[2] != artifact.id:
            seen.add(edge)
            unique.append(edge)
    return unique


def record_artifact(session: Session, artifact: Artifact, job: Job | None) -> None:
    if artifact.lineage_version:
        return
    path = Path(artifact.path)
    exists = path.is_file()
    artifact.sha256 = artifact.metadata_json.get("sha256") or (
        file_digest(path) if exists else None
    )
    artifact.size_bytes = path.stat().st_size if exists else None
    artifact.storage_key = storage().key_for(path)
    if job:
        run = session.scalar(
            select(ProviderRun)
            .where(ProviderRun.job_id == job.id)
            .order_by(ProviderRun.created_at.desc())
        )
        artifact.provider_run_id = run.id if run else None
    for role, kind, identifier in _edges(session, artifact, job):
        exists = session.get(Artifact if kind == "artifact" else MediaAsset, identifier)
        if exists:
            session.add(
                ArtifactInput(
                    artifact_id=artifact.id,
                    role=role,
                    input_artifact_id=identifier if kind == "artifact" else None,
                    input_asset_id=identifier if kind == "asset" else None,
                )
            )
    artifact.lineage_version = LINEAGE_VERSION


def record_job_lineage(session: Session, job: Job) -> None:
    for artifact in session.scalars(select(Artifact).where(Artifact.job_id == job.id)).all():
        record_artifact(session, artifact, job)


def backfill_lineage(session: Session) -> int:
    """Idempotently record lineage for artifacts written before lineage existed."""
    pending = session.scalars(select(Artifact).where(Artifact.lineage_version.is_(None))).all()
    for artifact in pending:
        record_artifact(
            session, artifact, session.get(Job, artifact.job_id) if artifact.job_id else None
        )
    session.commit()
    return len(pending)


def ancestry(session: Session, artifact: Artifact) -> dict:
    """Breadth-first ancestor graph with provider provenance for every produced file."""
    nodes, edges, assets = {}, [], {}
    queue, seen = deque([artifact.id]), {artifact.id}
    while queue:
        current = session.get(Artifact, queue.popleft())
        if not current:
            continue
        job = session.get(Job, current.job_id) if current.job_id else None
        runs = (
            session.scalars(select(ProviderRun).where(ProviderRun.job_id == job.id)).all()
            if job
            else []
        )
        nodes[current.id] = {
            "id": current.id,
            "kind": current.kind,
            "filename": current.filename,
            "sha256": current.sha256,
            "size_bytes": current.size_bytes,
            "storage_key": current.storage_key,
            "demo": bool(current.metadata_json.get("demo")),
            "job": {"id": job.id, "stage": job.stage, "provider": job.provider} if job else None,
            "provider_runs": [
                {
                    "capability": run.capability,
                    "provider": run.provider,
                    "model": run.model,
                    "status": run.status,
                    "latency_ms": run.latency_ms,
                    "estimated_cost_inr": run.estimated_cost_inr,
                }
                for run in runs
            ],
        }
        for edge in session.scalars(
            select(ArtifactInput)
            .where(ArtifactInput.artifact_id == current.id)
            .order_by(ArtifactInput.role)
        ).all():
            edges.append(
                {
                    "artifact_id": current.id,
                    "role": edge.role,
                    "input_artifact_id": edge.input_artifact_id,
                    "input_asset_id": edge.input_asset_id,
                }
            )
            if edge.input_artifact_id and edge.input_artifact_id not in seen:
                seen.add(edge.input_artifact_id)
                queue.append(edge.input_artifact_id)
            if edge.input_asset_id and edge.input_asset_id not in assets:
                asset = session.get(MediaAsset, edge.input_asset_id)
                if asset:
                    assets[asset.id] = {
                        "id": asset.id,
                        "filename": asset.filename,
                        "sha256": asset.metadata_json.get("sha256"),
                        "duration_ms": asset.duration_ms,
                    }
    return {
        "artifact_id": artifact.id,
        "artifacts": list(nodes.values()),
        "edges": edges,
        "sources": list(assets.values()),
    }
