# Preserved originals for split and merge editing

## Decision

Allow editors to split one saved line into two or merge adjacent saved lines assigned to the same speaker. Keep replaced rows and their artifacts as historical provenance rather than delete them. Guarded reversal is a separate, append-only structural operation; it never silently overwrites later edits or restores old approvals and voice selections.

Use the existing timeline revision and speaker identities. Creating an entirely new transcript revision would unnecessarily duplicate unchanged lines, lose their selected-take associations and complicate consented speaker continuity. A `retired` flag gives the canonical timeline an explicit active-line boundary while retaining foreign-key references from historical artifacts and reviews.

## Structural contracts

| Action | Inputs and constraints | Result |
| --- | --- | --- |
| Split | Current revision and line version, a millisecond boundary strictly inside the source window, explicit English and optional Malayalam text for each part, replacement confirmation | Retire the original; create two new manual lines covering its exact time span |
| Merge | Current revision, both versions, the next active line in canonical order, matching speaker assignment, explicit reviewed merged text, replacement confirmation | Retire both originals; create one manual line spanning their combined window, including any pause or overlap |
| Reverse structure | Operation ID, current revision, exact versions of all affected active/inactive lines, restoration confirmation | Retire the operation's outputs and reactivate its original rows; record a new reverse operation |

All mutations hold the database write lock and refuse queued/running project work or inactive revisions. New timing must fit the current source duration. Split and reversal enforce a maximum of 500 active lines. Blank English text, stale versions, foreign/nonadjacent merge targets and differing speakers are refused before mutation. Correct speaker assignments explicitly before merging different speakers; the application does not infer that two actors are one character.

No automatic translation, word-boundary estimate, audio splice or provider request happens during structural editing. The split point starts as a midpoint suggestion for manual correction, not an inferred acoustic boundary. Editors must explicitly distribute source and translated text and confirm replacement.

## Canonical timeline and history

`revision_segments` excludes retired rows and orders active dialogue by source start time and index. Structural operations reindex active lines; changed indices receive new versions and normal audit entries. Unchanged lines retain IDs, text, approvals and selected takes. Index/version changes may conservatively stale earlier alignment or structural-reversal evidence without invalidating unchanged voice signatures.

Each replaced/reactivated line receives a new version, a normal before/after audit record, `needs_review`, human-edit attribution and no selected take. Applied alignment/adaptation markers are removed. New lines do not inherit earlier emotion predictions, approval or generated audio. Original pre-replacement snapshots, including old approval/selection, remain in the operation record for inspection only.

Direct edits, take selection and ordinary saved-history restoration refuse retired rows. New translation, synthesis, alignment, emotion, take-analysis and export preparation use active lines. Alignment/emotion/take checks detect replaced lines; retained-background mix validation requires the complete current active ID set. Old artifacts remain historical and subject to their original consent/download checks; preserving an artifact does not approve it for the new structure. Reference-clip speaker checks remain conservative about historical assignments rather than weakening clone-consent safety.

## Guarded reversal

The structure-history endpoint returns the latest 20 operations with saved before/after lines and a current reversal eligibility reason. Reversal requires unchanged output versions and the expected retired-original versions/material. Later content, status, selection or structural edits block reversal rather than discard them. A successful reverse operation can itself be reversed if its affected lines remain unchanged, providing grouped undo/redo without deleting audit records. This is intentionally stricter than ordinary material-only line history.

`GET /projects/{project_id}/revisions/{revision_id}/structure-edits` inspects history. `POST /segments/{id}/split`, `POST /segments/{id}/merge` and `POST /timeline-structure-edits/{id}/restore` apply the typed operations. Replayed/stale requests fail with 409 instead of creating duplicate replacements. After an uncertain response, refresh the project/history before retrying.

## Editor and draft safety

The collapsed split/merge panel contains saved-line selection, manual text and timing fields, source audition, confirmation and structural history. All dialogue and brief drafts must be saved or explicitly discarded first. Dialogue fields lock during the structural transaction so typing cannot be lost when a line is replaced.

Split/merge form text is preserved on refresh and server-version changes. If another editor replaces the selected line, its form stays visible and read-only for submission. Loading fresh lines or changing selection requires explicit draft-discard confirmation. Form changes participate in leave/revision-switch warnings. Structural reversal is disabled while a form draft exists.

If another tab removes a line with unsaved dialogue text, the mounted editor row is retained below current dialogue as a preserved draft. It is excluded from the canonical timeline, cannot be saved into a replaced line and offers an explicit JSON download or confirmed discard. Repeated refreshes preserve it; the download includes the original line/revision/version and local field values, not an approved translation or restored media artifact.

## Migration and verification

Migration `0009_timeline_structure` adds `segments.retired` with a false default and the `timeline_structure_edits` audit table. Existing dialogue, selected takes, emotion reviews and line history are preserved. Startup from schema 0008 creates a consistent `*.v02-emotion-*.bak` backup before upgrading. Stop processes and restore a consistent database/media backup for rollback; destructive downgrade is not supported. No normal-workspace migration or data cleanup was performed during implementation.

API tests cover split/merge/reversal chains, preserved originals and unaffected selections, source/500-line limits, conflicts, active jobs, speaker/adjacency restrictions, inactive-line guards, current SRT inputs and historical alignment/emotion review rejection. Migration tests check backup contents, retained reviews and unchanged existing approval/selection. Browser tests cover split/merge/reversal, reload, current subtitle download, mobile layout and a concurrent replacement preserving an unsaved structure form. These are editor/integration checks, not listening or natural-language-quality acceptance.

Broader grouped edits, editable waveforms/word boundaries, long-session performance, full accessibility/IME/device checks and recovery/packaging remain open in the completion ledger.
