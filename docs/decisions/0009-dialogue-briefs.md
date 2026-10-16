# ADR 0009 Dialogue briefs and local editorial checks

Status: implemented editorial-context foundation, 2026-10-15. An optional experimental model adapter is now connected separately in [ADR 0010](0010-local-dialogue-adaptation.md); language-quality acceptance remains open.

## Saved context

Each timeline revision has a scene summary, adaptation notes, preferred source-to-target terms and human character intent/delivery notes. Speaker references must belong to that revision. Saving creates an immutable version; a stale `expected_version` returns HTTP 409, while identical content creates no new version. A new transcript starts with an empty brief rather than attaching direction to potentially different speaker identities. Migration 0007 adds the history table; upgrading schema 0006 first creates a consistent `.v02-mixes-*.bak` SQLite backup.

The editor keeps brief drafts through project refreshes, warns before leaving with unsaved work, and requires an explicit discard to load another editor's newer brief. Saving a brief does not change dialogue, approvals, voice choices or paid-job fingerprints.

## Local review contract

The `review_translation` job freezes the brief, selected lines and the entire surrounding timeline context. `dialogue-review-v1` checks for missing translations, unassigned speakers and preferred target text that is absent when its source term occurs. Source matching uses literal, Unicode-normalized word boundaries; glossary entries are not regular expressions. Target matching is a literal normalized substring check, not a grammar or terminology-quality judgment. It never replaces text automatically.

The downloadable report records neighboring dialogue, character direction, glossary matches, exact saved time windows and Unicode character counts. It does not estimate speaking duration, infer emotion or score Malayalam quality. A completed local run has zero API charge; CPU, electricity and hardware costs are not estimated.

Reports have checksums and frozen job lineage. Typed reads validate the saved bytes and deterministic result. Changed briefs, dialogue, timing, speaker names or surrounding lines mark historical reports stale; approval or take-selection changes alone do not. Jobs interrupted after report publication reuse the committed report without duplicate run records. Cancellation and queued-input conflicts use the existing durable worker boundary.

## Model capability boundary

The [Sarvam text-translation request](https://docs.sarvam.ai/api-reference/text/translate-text), checked on 2026-10-15, exposes source/target language, model, style and formatting options, but no separate scene, character, glossary or duration fields. Do not prepend those instructions to dialogue and pretend they are a supported context channel.

`translation_reviewer` remains a local deterministic check and its reports explicitly record `context_applied_by_model=false`. The separate optional `dialogue_adapter` consumes frozen context and returns model alternatives with provenance. Plain translation is not silently rerouted through it. Model drafts still need independent Malayalam review, and the editorial checks do not become AI quality scores merely because a model is installed.

## Verification

Run `npm test` and `npm run test:e2e -- tests/e2e/dialogue-review.spec.ts`. Tests cover immutable brief versions, conflicts, revision/speaker isolation, Unicode term boundaries, read-only reports, selected-line context, byte integrity, durable recovery, stale reports, paid-cache preservation, draft preservation, two-tab conflicts, reload and narrow-screen layout. These are editorial-workflow checks, not model translation or human-language acceptance.
