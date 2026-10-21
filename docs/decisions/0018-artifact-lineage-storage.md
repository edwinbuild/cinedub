# ADR 0018: Artifact lineage and the storage boundary

## Status

Accepted for v0.3 on 2026-10-19.

## Context

Provenance existed, but it was ad hoc. Each feature kept its own keys in `Artifact.metadata_json`: `source_asset_id`, `stem_set_id`, `master_artifact_id` and candidate maps. Some features used `StemSet`/`MixRender` artifact maps instead. Nothing could answer "which source media and which provider runs produced this exported file" without feature-specific code. Fifteen modules built absolute paths as `storage_root / project / area / job`, and four modules repeated their own `is_relative_to(storage_root)` guards.

## Decision

- **Integrity columns.** `artifacts` gains `sha256`, `size_bytes`, a root-relative `storage_key`, the producing `provider_run_id` and `lineage_version` (migration `0011`).
- **Edge table.** `artifact_inputs` stores one row per input: another artifact or a source `MediaAsset`, with a role. Roles include:
  - `source`
  - `derived_from`
  - `analysis_audio`
  - `take`
  - `background:<stem>`
  - `voice_reference`
  - `timing_take`
  - `accepted:<output>`
- **Derivation.** `lineage.record_job_lineage()` runs once when a job completes. It derives edges from the job's immutable frozen inputs and each artifact's recorded provenance. Edges are computed once and persisted, not re-derived on read. The same function idempotently backfills older artifacts after `create_database()` upgrades a workspace. Upgrading from schema `0010` now takes the same pre-upgrade backup as earlier versions.
- **Read API.** `GET /artifacts/{id}/lineage` returns the ancestor graph: files, edges, producing jobs, provider runs (provider, model, latency, cost estimate) and source media checksums.
- **Export bundles.** Accepted bundles now contain `lineage.json` (the union of every exported file's ancestry). The listening certificate lists and hashes it like every other file.
- **Storage boundary.** `storage.LocalStorage` owns every job directory (`job_dir`, plus a non-creating `job_path` for provenance checks), upload directories, root-relative keys, traversal-safe resolution, the download/evidence `readable` guard, usage reporting and project deletion. A structural test rejects media paths built from the storage root anywhere else. Workspace/worker lock files are exempt.

## Consequences

- Every exported mix file traces to the uploaded source through recorded edges. The DEMO workflow test asserts this end to end, along with each artifact's recorded hash and size against the bytes on disk.
- `Artifact.path` stays absolute for one release, because recovery rewrites it and processors still read it. `storage_key` is root-relative, so a restored or relocated workspace keeps valid keys without rewriting. A future object store implements the same `LocalStorage` methods; processors no longer know the layout.
- Lineage records what was frozen into a job. It does not claim anything about media quality.
