# CineDub Engineering Guide

## Scope

These instructions apply to the entire repository.

`OLD/` is an ignored, read-only snapshot of the pre-rebuild prototype. It is reference material, not the current application. Do not edit it, import runtime code from it, install dependencies inside it, or make it part of a build. Reuse an asset or idea only after reviewing it and placing an intentional, updated copy in the new project structure.

## Product Goal

Build a production-grade cinema dubbing workspace that can:

- ingest video and separate dialogue from music and effects;
- transcribe and identify speakers accurately;
- translate and adapt dialogue with scene, character, and timing context;
- infer and preserve emotion, delivery, pacing, and vocal identity;
- synthesize or transform voices with explicit consent and provenance;
- align dialogue to the original performance and lip/timing constraints;
- let an editor review every automated decision;
- mix, preview, and export verifiable media deliverables.

The target is not a pixel-for-pixel or file-for-file recreation of `OLD/`. Preserve useful product knowledge while replacing fragile contracts, mocked intelligence, oversized components, and incomplete media workflows.

## Source of Truth

When information conflicts, use this order:

1. The user's current request and explicitly agreed product decisions.
2. Current code, contracts, tests, and documentation outside `OLD/`.
3. Provider documentation and measured evaluation results.
4. `OLD/` as historical reference only.

Do not treat completion claims in archived documents as proof that a feature works.

## Intended Repository Shape

Prefer a workspace with clear runtime and ownership boundaries:

```text
apps/
  web/          # Editor and review UI
  api/          # Auth, projects, metadata, orchestration API
  worker/       # Long-running media and AI jobs
packages/
  contracts/    # Shared schemas and generated API/event types
  media/        # FFmpeg/ffprobe, alignment, mixing, export
  ai/           # Provider-neutral interfaces and routing
  ui/           # Reusable design system components
  config/       # Shared lint, TypeScript, and test configuration
tests/
  fixtures/     # Small, licensed golden media fixtures
  e2e/          # End-to-end project workflows
docs/
  decisions/    # Architecture decision records
  evaluations/  # Reproducible provider and quality benchmarks
```

Adjust this structure only when a simpler boundary is demonstrably better.

## Architecture Rules

- Design contracts before screens and handlers. Validate HTTP, job, database, and event payloads from the same shared schemas.
- Keep the web process responsive. Run transcription, separation, synthesis, alignment, and export in durable background jobs.
- Put each external AI service behind a provider-neutral adapter. Business logic must not depend directly on one vendor's request or response shape.
- Route providers by capability, language, measured quality, latency, availability, consent constraints, and cost. Do not scatter provider selection across UI components or route handlers.
- Persist job state and artifact lineage. A process restart must not silently lose a project or make an export unverifiable.
- Store large media in object storage, not database documents or process memory. Persist metadata and references in the database.
- Version translations, voice settings, timing edits, model/provider identifiers, prompts, and source artifacts so an output can be reproduced.
- Treat browser previews as proxies. Generate final media server-side with explicit codecs, sample rates, channel layouts, and loudness targets.
- Never label random values, placeholders, or text sentiment as speech-emotion analysis. Demo fixtures must be clearly marked and isolated from production paths.
- Prefer small, cohesive modules. Split large editor or pipeline components by domain responsibility, not arbitrary line count.

## AI and Media Pipeline

Model the workflow as independently retryable stages:

1. Ingest and probe media.
2. Extract audio and create preview proxies.
3. Separate dialogue from music/effects when required.
4. Transcribe with word timing, language detection, and speaker diarization.
5. Map speakers to project characters and approved voice profiles.
6. Translate and adapt using scene context, glossary, character intent, and duration constraints.
7. Analyze performance signals such as energy, pitch, tempo, pauses, and textual/scene emotion.
8. Synthesize candidate lines through a selected voice provider.
9. Align, time-stretch within safe limits, and review lip/timing fit.
10. Mix dialogue with retained stems and export validated deliverables.

Every stage must expose status, progress, warnings, structured errors, inputs, outputs, and retry behavior.

## Provider and Model Rules

- Never hard-code ElevenLabs, Sarvam, OpenAI, or another provider as the domain model.
- Define capabilities such as `Transcriber`, `Translator`, `EmotionAnalyzer`, `VoiceSynthesizer`, `VoiceCloner`, and `Aligner`.
- Record provider, model/version, parameters, latency, cost estimate, and quality evaluation with each generated artifact.
- Support per-stage and per-language routing instead of switching the entire application to one vendor.
- Use deterministic fallbacks. A fallback must be visible to the user and auditable.
- Keep API keys server-side and validate required configuration at startup.
- Respect voice ownership, actor consent, regional privacy law, retention rules, and provider-specific cloning restrictions.

## UX Rules

- Optimize the editor around review and correction, not decorative dashboards.
- Keep video, waveform, dialogue, speaker, language, timing, and version state synchronized through one canonical timeline model.
- Preserve user edits when an AI stage is rerun; require explicit confirmation before replacing approved work.
- Make low-confidence transcription, translation, emotion, voice, and timing decisions easy to find.
- Show actual job progress and actionable failure states. Do not simulate progress for real work.
- Keep keyboard editing, undo/redo, accessibility, and long-session performance as first-class requirements.

## Engineering Standards

- Use strict TypeScript and explicit boundary validation. Do not suppress type or build errors to make CI pass.
- Keep secrets out of source, fixtures, logs, client bundles, and error responses.
- Add database migrations for schema changes; do not rely on implicit production mutations.
- Use structured logging with correlation IDs across API, worker, provider calls, and artifacts.
- Add idempotency to expensive or externally billed operations.
- Apply timeouts, bounded retries with backoff, cancellation, concurrency limits, and budget controls to provider jobs.
- Sanitize filenames and media metadata. Validate type, size, duration, codec, and content before processing uploads.
- Use licensed or synthetic test media only. Keep personally identifying or actor voice data out of the repository.

## Verification

For an affected workflow, verify at the lowest sufficient levels and report what was not tested:

- formatting, linting, and strict type checking;
- focused unit tests for domain logic and adapters;
- contract tests for API, events, and provider mappings;
- integration tests for database, queue, storage, and FFmpeg boundaries;
- end-to-end tests for ingest through reviewed export;
- golden-media checks for duration, synchronization, clipping, loudness, channels, subtitles, and playable output;
- human listening review and language-expert scoring for model/provider evaluations.

A passing unit suite is not evidence that a rendered film segment sounds natural or stays synchronized.

## Working With `OLD/`

Before reusing anything from the archive:

1. Identify the user or product behavior it represents.
2. Trace its dependencies and confirm whether it was genuinely functional.
3. Write or update the current contract and acceptance criteria.
4. Reimplement the smallest coherent capability in the new architecture.
5. Add tests and a migration note when archived data must remain compatible.

Good early candidates for selective reuse are visual design tokens, interaction ideas, legally usable fixtures, and product terminology. Rebuild API contracts, authentication, persistence, job orchestration, AI analysis, provider integrations, media processing, and export unless current evidence proves an archived implementation is sound.

## Git and Change Discipline

- Keep changes scoped to the requested task and preserve unrelated user work.
- Do not commit, push, open a pull request, deploy, or modify external systems unless the user explicitly asks.
- Never force-push, rewrite shared history, or remove project data without explicit approval.
- Do not add anything from `OLD/` to Git, including generated artifacts or copied dependency folders.
- Before any requested commit, review `git status`, inspect the diff, and run relevant verification.
- Document consequential architecture decisions in `docs/decisions/` once the decision is agreed.

## Definition of Done

A feature is complete only when its real execution path is connected, failure behavior is handled, relevant tests pass, documentation matches reality, and the user-facing result has been checked. Mocks, polished UI, or successful builds alone do not make a dubbing capability complete.
