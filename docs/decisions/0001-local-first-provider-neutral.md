# ADR 0001: Local-first, provider-neutral pipeline

## Status

Accepted for the first rebuild milestone.

## Decision

CineDub runs as a localhost browser application with separate web, API, and worker processes. Product records use application-owned contracts. External services and local models implement capability interfaces and never define database or UI shapes.

SQLite and a database-backed job queue are the zero-service development defaults because this machine currently has neither Docker, PostgreSQL, nor Redis. The database and worker boundaries are intentionally replaceable; hosted deployments will use PostgreSQL and a dedicated queue without changing public product contracts.

Sarvam initially supplies translation and consented voice generation. Deterministic providers make development and tests reproducible without credentials or billable calls. Local GPU models are added only after the NVIDIA runtime passes diagnostics.

## Consequences

- Provider changes happen capability-by-capability.
- Approved human edits are never overwritten by reruns.
- Job records and queued work survive restarts. Automatic recovery of interrupted running jobs and retry orchestration remain follow-up work.
- SQLite supports one worker only; concurrent workers require PostgreSQL and a queue implementation with atomic claims.
- Fake output is visibly labeled and cannot be mistaken for model evaluation evidence.
