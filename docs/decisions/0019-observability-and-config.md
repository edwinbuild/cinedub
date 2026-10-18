# ADR 0019: Correlation IDs, structured logs and startup configuration checks

## Status

Accepted for v0.3 on 2026-10-19.

## Context

The API and worker emitted about five free-text log lines. Nothing connected an HTTP request to the job it created, the provider calls that job made, or the files it produced. Provider routing settings were plain strings, and a missing Sarvam key surfaced only later, as an unavailable capability.

## Decision

- **Request ID.** An outermost ASGI middleware accepts a caller's `X-Request-ID` if it is a short opaque token. Otherwise it mints one. It binds the ID to a context variable and echoes it on every response. CORS allows and exposes the header.
- **Persistence.** `jobs`, `provider_runs` and `artifacts` gain `correlation_id` (migration `0012`). A single SQLAlchemy `before_insert` hook stamps the active ID, so no processor needed changes.
- **Worker binding.** The worker binds a job's stored ID (or its job ID) while processing it, so the request ID follows into provider runs and artifacts created later in another process.
- **JSON logs.** Both services log one JSON object per line: timestamp, service, level, event name, correlation ID and explicit fields such as `job_started`, `job_completed`, `job_failed` (with error code and type), `job_cancelled`, `http_request` and `configuration_warning`. Exceptions contribute only their type; request bodies, dialogue text, paths and credentials are never logged. Logging is reconfigured after migrations because Alembic's file config replaces handlers.
- **Startup checks.** `validate_settings()` runs at API and worker startup.
  - Invalid origins, database URLs or storage roots are fatal.
  - DEMO providers selected while disallowed are fatal.
  - A missing Sarvam key for selected Sarvam stages is fatal in production and a warning in development.
  - Messages name settings, never values. `/health` reports the warnings.
  - Provider settings were already strictly typed (`Literal`) in Phase 1, so unknown values fail at load.

## Consequences

- One ID traces a request through its job, provider runs and artifacts. Tests verify this for upload→ingest and transcribe.
- A test drives a provider exception that embeds a fake API key through a real job. It verifies that the key does not appear in the job error, captured logs, formatted JSON lines, or the health, capabilities and project responses.
- Log volume stays low: one line per request and a handful per job.
