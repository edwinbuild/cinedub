"""Cancellable worker-side export packaging, never an API-thread ZIP operation."""

import json
import zipfile
from pathlib import Path

from .lineage import ancestry
from .mix_processing import checked_file, render_artifacts
from .mixes import validate_mix_snapshot
from .models import Artifact, Job, MixRender, MixReviewRecord
from .processing import check_cancel, checkpoint
from .storage import storage


def process_package_mix(session, job):
    mix = session.get(MixRender, job.input_json["mix_id"])
    review = session.get(MixReviewRecord, job.input_json["review_record_id"])
    render_job = session.get(Job, mix.job_id)

    def cancel():
        check_cancel(session, job)
        session.expire_all()
        if review.status != "approved" or mix.status != "approved" or mix.version != review.version:
            raise ValueError("Mix acceptance changed before packaging; review the current render")
        validate_mix_snapshot(session, render_job.input_json)

    cancel()
    if review.bundle_artifact_id:
        for identifier in (review.bundle_artifact_id, review.certificate_artifact_id):
            artifact = session.get(Artifact, identifier)
            checked_file(artifact.path, artifact.metadata_json["sha256"])
        return {
            "mix_id": mix.id,
            "artifact_ids": [review.certificate_artifact_id, review.bundle_artifact_id],
        }
    checkpoint(session, job, "verifying_export_files")
    artifacts = render_artifacts(session, mix)
    manifest = next(item for item in artifacts if item.kind == "mix_manifest")
    directory = storage().job_dir(job.project_id, "mixes", mix.job_id, "acceptance", review.id)
    lineage = directory / "lineage.json"
    lineage.write_text(
        json.dumps(export_lineage(session, artifacts), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    certificate = directory / "listening-acceptance.json"
    certificate.write_text(
        json.dumps(
            {
                "schema_version": "cinedub-acceptance-v1",
                "mix_id": mix.id,
                "render_manifest_sha256": manifest.metadata_json["sha256"],
                "review_id": review.id,
                "review_version": review.version,
                "status": review.status,
                "reviewed_by": review.reviewed_by,
                "note": review.note,
                "accepted_at": review.created_at.isoformat(),
                "scope": "Local editor listening/timing attestation, "
                "not independent language or cinema certification",
                "demo": manifest.metadata_json["demo"],
                "files": [
                    {
                        "filename": item.filename,
                        "sha256": item.metadata_json["sha256"],
                        "bytes": Path(item.path).stat().st_size,
                    }
                    for item in artifacts
                ]
                + [{"filename": lineage.name, **checked_file(lineage)}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    metadata = {
        **manifest.metadata_json,
        "review_id": review.id,
        "review_version": review.version,
        "review_required": False,
    }
    checkpoint(session, job, "packaging_accepted_export")
    bundle = directory / ("demo-reviewed-export.zip" if metadata["demo"] else "reviewed-export.zip")
    staging = bundle.with_suffix(".part")
    with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, name in [(Path(item.path), item.filename) for item in artifacts] + [
            (lineage, lineage.name),
            (certificate, certificate.name),
        ]:
            cancel()
            with path.open("rb") as source, archive.open(name, "w") as destination:
                while chunk := source.read(1024 * 1024):
                    check_cancel(session, job)
                    destination.write(chunk)
    cancel()
    # Revalidate the exact files after reading them into the bundle.
    render_artifacts(session, mix)
    with zipfile.ZipFile(staging) as archive:
        if archive.testzip():
            raise ValueError("Export archive integrity check failed")
    staging.replace(bundle)
    certificate_artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="mix_acceptance",
        path=str(certificate.resolve()),
        filename=certificate.name,
        media_type="application/json",
        metadata_json={**metadata, **checked_file(certificate)},
    )
    bundle_artifact = Artifact(
        project_id=job.project_id,
        job_id=job.id,
        kind="mix_bundle",
        path=str(bundle.resolve()),
        filename=bundle.name,
        media_type="application/zip",
        metadata_json={**metadata, **checked_file(bundle)},
    )
    session.add_all([certificate_artifact, bundle_artifact])
    session.flush()
    review.certificate_artifact_id = certificate_artifact.id
    review.bundle_artifact_id = bundle_artifact.id
    session.flush()
    cancel()
    session.commit()
    return {"mix_id": mix.id, "artifact_ids": [certificate_artifact.id, bundle_artifact.id]}


def export_lineage(session, artifacts) -> dict:
    """Union of every exported file's ancestry, down to the original source media."""
    nodes, edges, sources = {}, [], {}
    for artifact in artifacts:
        graph = ancestry(session, artifact)
        nodes.update({node["id"]: node for node in graph["artifacts"]})
        edges.extend(edge for edge in graph["edges"] if edge not in edges)
        sources.update({source["id"]: source for source in graph["sources"]})
    return {
        "schema_version": "cinedub-lineage-v1",
        "exported_artifact_ids": [artifact.id for artifact in artifacts],
        "artifacts": list(nodes.values()),
        "edges": edges,
        "sources": list(sources.values()),
    }
