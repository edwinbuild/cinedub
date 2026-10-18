# ADR 0020: Pipeline orchestrator with human review gates

## Status

Accepted for v0.3 on 2026-10-19.

## Context

Each of the 17 stages had to be started by hand, in an order the editor had to remember. The only chained run was the fake `demo_pipeline` fixture, which wrote rows directly and skipped the real stages. AGENTS.md asks for independently retryable stages and for preserving human edits, so automation must not approve or replace reviewed work.

## Decision

- **Model.** A `pipelines` row (migration `0013`) records:
  - the source
  - options (dialogue separation, adaptation, performance analysis, expected speakers)
  - an ordered step list of jobs and gates, with the current step
  - status: `running`, `awaiting_review`, `completed`, `failed` or `cancelled`
  - an explanation of what is needed next
  - the confirmed budget and correlation ID

  A project has at most one active pipeline.
- **Steps.** The default plan is:
  1. ingest
  2. [separate → **stems_approved**]
  3. transcribe → **speakers_assigned**
  4. translate → [review → adapt]
  5. **lines_approved** → **voices_assigned**
  6. synthesize → **takes_selected**
  7. [align → take analysis → emotion]
  8. render mix → **mix_accepted**

  `POST /projects/{id}/pipelines/plan` previews it without queueing anything.
- **One submit path.** Every job is submitted through `jobs.submit_job()`, the same path as `POST /jobs`, so revision binding, consent, staleness, DEMO refusal, cached reuse, project budget and the one-active-job rule all still apply. Cached completed results (for example media already prepared at upload) are reused rather than recomputed.
- **Gates.** Gates never approve anything. A gate opens only on an explicit `POST /pipelines/{id}/continue`, and only when its predicate is satisfied by saved human state:
  - an approved stem set
  - a speaker for every line
  - every line approved and translated
  - a voice for every speaker
  - a selected take for every line
  - an approved mix whose accepted bundle exists

  Otherwise the request returns 409 with what is missing.
- **Budget.** Paid steps cannot be estimated before the transcript exists, so a pipeline carries a confirmed budget instead. Before a step would exceed it, the pipeline pauses with nothing submitted or reserved, and `continue` can raise the budget. DEMO pipelines cost nothing.
- **Advancing.** The worker advances the pipeline after committing each job's own outcome, so a pipeline step never rewrites job results.
  - A failed job stops the pipeline and explains why.
  - A stage-policy resume of that job resumes the pipeline.
  - Cancelling cancels the active job and keeps completed work.
  - After a worker restart, interrupted jobs are requeued, and active pipelines whose current job already stopped are settled.

## Consequences

- The whole workflow runs as one supervised pipeline on DEMO providers or real ones. Editors still make every review decision.
- Existing manual endpoints remain. A pipeline only queues the same jobs a person could. `demo_pipeline` stays registered for historical rows; the UI replaces it with a real pipeline in Phase 8.
