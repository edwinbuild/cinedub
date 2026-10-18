# ADR 0017: Stage registry and typed job contracts

## Status

Accepted for v0.3 on 2026-10-19.

## Context

Seventeen job stages shared one flat `JobCreate` request. A 560-line `prepare_job` if-chain froze each stage's inputs, and `estimate_job` ran it a second time. Processors read untyped `job.input_json`/`output_json` dictionaries, and the worker kept its own `PROCESSORS` map and stage-specific branches. Nothing validated stored inputs before processing or recorded outputs before persisting them, so a preparation bug or an older row could fail deep inside a processor or persist a malformed result.

## Decision

- `cinedub_api.stages` holds one `StageSpec` per stage:
  - its request, frozen-input and output contracts
  - default provider routing and capability
  - ordered preparation steps
  - its processor
  - retry policy and review gate
- `STAGES` is the single source for the worker dispatch table, provider defaults and preparation.
- `JobCreate` is a discriminated union of per-stage request models (`extra="forbid"`). A field that a stage does not accept is now rejected (422) instead of silently ignored. `package_mix` stays internal: it is created only by an accepted mix review.
- Requests are normalized to the unchanged flat `JobFields` shape before freezing. The frozen `input_json`, and therefore every job fingerprint, stays byte-compatible with v0.2. A v0.2 completed or paid job is still reused rather than resubmitted.
- `prepare_stage()` is the only preparation path, shared by estimate and create, so create freezes inputs once instead of twice. It validates the frozen inputs against the stage's strict input model before any row is written.
- The worker re-validates stored inputs with a lenient variant (unknown keys ignored, required keys enforced) before entering a processor. It validates the processor result against the output model before recording it. Failures stop with `InvalidJobInput` or `InvalidJobOutput` and never persist a partial result.
- Model-backed preparation steps live in per-family modules: `source`, `timeline`, `analysis`, `dialogue` and `voice`. Their check order is preserved, so the same request yields the same first error.

## Consequences

- Processors still read the validated `input_json` dictionary internally, and helpers such as `freeze_*` and `validate_*` keep their dictionary signatures. The boundary is enforced at preparation and dispatch rather than by rewriting every processor's internals.
- Adding a stage means adding one `StageSpec` plus its contracts. The worker, estimate and contract generator pick it up automatically.
- The TypeScript `JobRequest` is now a union of per-stage interfaces, so the web client cannot send an option to the wrong stage.
- Tests that patched model-availability helpers on `cinedub_api.jobs` now patch them where preparation uses them. Tests that inserted contract-invalid jobs now insert valid ones.
