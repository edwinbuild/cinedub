# Saved dialogue history and keyboard correction

## Decision

Provide durable, line-level undo and redo for saved English/Malayalam text, speaker assignments and timing. Keep the browser's native text undo for unsaved typing. Restoring a saved snapshot is a new manual edit requiring review, not reinstatement of old voice or approval state.

This uses the existing append-only `segment_edits` table. No schema migration or external service is needed. The normal segment patch endpoint and history restoration share validation, optimistic version checks, warning updates and take invalidation in `line_editing.py`.

## API and history replay

`GET /segments/{id}/history` returns the current segment version, next undo/redo edit IDs, any material discontinuity warning, total record count and the most recent 20 before/after records. The browser loads this only when a line's history is opened or explicitly refreshed; project refresh does not fetch all line histories.

`POST /segments/{id}/history` accepts `action`, `expected_version`, `expected_edit_id` and `restoration_confirmed`. Restoration requires the active revision, no queued/running project jobs, the current segment version and the next eligible action. It cannot select an arbitrary historical record or submit replacement text through this endpoint. Current speaker ownership and source-duration validation still apply.

History replay keeps per-line undo/redo stacks. Material edits add an undo item and clear redo; status-only saves are not material undo items. Undo/redo records name the original edit in their `after_json` using `history_action` and `history_target_edit_id`, and never delete earlier records. A provider change outside the material chain makes older history read-only. A subsequent manual correction establishes a new chain from that provider draft. Malformed legacy snapshots are displayed as unavailable and cannot be restored.

## Restored fields and safety

| State | Restoration rule |
| --- | --- |
| Source and translated text, speaker, start/end | Restore from the eligible original edit's before/after snapshot and validate against current ownership/timing constraints |
| Segment version and audit history | Increment version and append a new immutable edit record |
| Approval and human-edit status | Set `needs_review` and mark human edited; never automatically restore prior approval |
| Selected voice take | Clear selection; old artifacts remain historical and must be explicitly reviewed/reselected if still eligible |
| Consent, voices, emotion, acoustic/model results | Never restore through saved line history |
| Applied alignment/adaptation markers | Remove current applied-result markers; a manual restoration is not a fresh application of AI evidence |
| Unsaved drafts and concurrent edits | Disable restoration while a draft exists; stale API versions return 409 without changing the line |

Selection/status-only version changes do not erase an unchanged material chain, but the request must always use the latest version. Any restored content will still clear selected audio and require review again. New edits after undo abandon the executable redo branch while preserving its records for inspection.

## Editor interactions

Each line exposes collapsed **Saved edit history**, explicit restoration acknowledgement, undo/redo buttons and inspectable before/after snapshots. Only the affected line's fields lock during a save or restoration. Drafts in other lines remain untouched. History changes from another tab require refreshing; a newer server line never silently replaces an unsaved local draft.

Alt+Up/Down moves focus between visible lines without saving, playing or discarding drafts. Native select/combobox, media and content-editable controls keep their key handling. Previous/Next buttons provide the same navigation without shortcuts. Ctrl/Command+Enter saves the focused line; composition and repeated key events are ignored. Ctrl/Command+Z is not intercepted. Focused lines have a visible outline.

The editor's first keyboard link is **Skip to dialogue editor**, which focuses a named region before the navigation controls. It is visible only on focus and works at narrow widths. Saving restores the original field's focus after the temporary field lock, but only if focus is still on the document body; it does not steal focus from another control. When the original button becomes disabled, focus returns to the line instead. Failed saves keep the draft and restore editing focus under the same rule. A polite status distinguishes saved work requiring review from a saved approval, and clears when typing or newer saved state replaces it. Both `isComposing` and legacy IME key code 229 suppress shortcuts; Shift+Ctrl/Command+Enter is not the save command.

## Atomic grouped dialogue saves

`PATCH /projects/{project_id}/segments` accepts an active `revision_id` and 1–100 strict `SegmentBatchItem` entries, each with a unique line ID, expected version and explicit changes. The generated TypeScript contracts come from the same Pydantic schemas. SQLite acquires its existing immediate write lock before reading the active revision; cross-project/revision, retired, stale and invalid lines reject the request. All line updates and immutable history records commit together, or roll back together. The shared `apply_line_edit` helper retains its normal commit behavior for existing single-line callers and supports flush-only use inside the grouped transaction.

Content changes retain the existing review/take invalidation rules. Each history record stores the same `group_id`; the grouped content-restoration endpoints below use that immutable membership. Historical revisions and media are not deleted. No schema migration or paid operation is involved. Optimistic versions prevent duplicate edits on replay; a lost response may follow a successful commit, so the browser retains drafts and tells the editor to inspect saved versions before retrying instead of promising that nothing was saved.

The editor registry holds each line's existing local draft and original version rather than creating a second editable copy. Grouped saving includes filtered-out drafts and requires explicit count/scope confirmation. It rejects pending/stale/removed drafts locally and disables line editing while the request is in flight. Success acknowledges only returned lines; failure preserves all drafts. Brief, voice, mix, emotion and consent forms are excluded. When the save control disappears, focus recovers to the timeline heading only if the editor has not deliberately moved focus elsewhere.

The focused API checks cover successful grouped persistence and shared audit IDs, approval/take invalidation, replay conflicts, late stale/invalid/missing/foreign lines, retired lines, active-revision mismatch, strict payloads and bounds. Browser checks cover cancelled confirmation, injected 507 retention, successful saving of hidden drafts, reload persistence, a real second-line conflict leaving the first line unchanged, focus recovery and mobile layout. Physical-disk/power-loss acceptance remains a separate gate.

Verification on 2026-10-17: the complete collected backend run passed 253 tests in 213.97 seconds. A new grouped capacity test added after that collection passed separately: a bounded real SQLite page quota allowed the first line/history to flush, failed the second, returned sanitized 507, retained both original lines and no history, then succeeded on explicit retry after quota release. No host disk was filled. All 37 focused batch/timeline/history checks and the final four supervised browser workflows passed; the first four-browser run also passed before adding focus recovery. The 390-pixel grouped controls screenshot was inspected and full-page horizontal overflow was absent. Production build, strict types, ESLint, generated contracts, Ruff/format and diff checks passed. One initial focused-test command named a nonexistent history file and collected no tests; the corrected command and full run above are authoritative.

## Atomic grouped content undo/redo

`GET /projects/{project_id}/edit-groups?revision_id=...` returns at most the latest 20 original save-group summaries. Older audit records remain accessible by ID. `GET /projects/{project_id}/edit-groups/{group_id}` lazily inspects original membership (at most 100), original material snapshots, current versions and per-line undo/redo eligibility. Every material member must have that exact original edit as its next eligible stack item for the same action. A newer manual/provider change, independently undone subset, retired line, malformed snapshot or inactive revision prevents partial restoration. Identical-content/status-only members are explicitly counted as excluded; approvals are not content undo items.

`POST /projects/{project_id}/edit-groups/{group_id}/restore` accepts the action, revision, exact set of material line IDs/current versions/original edit IDs and explicit restoration confirmation. It accepts no replacement text. Under the immediate write lock it re-inspects membership, rejects active jobs or mismatched versions/targets, and restores original before/after content through the shared validator in one transaction. It appends per-line `history_action`, `history_target_edit_id` and `history_group_id` evidence; it does not reuse `group_id` for new original membership, duplicate groups or erase records. Selected takes and applied-result markers are cleared and review is required again. Group and individual history replay interoperate; a mixed per-line state blocks grouped restoration rather than filling in the missing members automatically.

The editor's lazy panel shows the scope and before/after content. Loading/choosing another group resets the acknowledgement. Unsaved dialogue, structural, reference and other review drafts disable restoration. A successful action refreshes project/history; failed operations retain saved content and show refresh-before-retry guidance for uncertain responses. Focus recovery does not steal a deliberate focus move. No migration, external provider or model call is required.

Verification on 2026-10-17: 47 focused group/batch/individual-history/capacity tests passed, including a late injected validation failure after the first real restoration/history flush, exact membership/version/target rejection, replay protection, provider discontinuity, partial individual undo, status-only exclusions and bounded summaries without deleting older records. The final five supervised browser workflows passed undo → reload → redo, cancelled/injected-507 requests, unsaved-draft blocking, a real independent-edit conflict, refreshed acknowledgement, focus and mobile overflow checks. The mobile panel screenshot was inspected. The first browser run had four passes and an older history test failed before entering the editor: its trace shows `POST /projects` returned 201 in 46.19 ms while the Next.js project RSC navigation remained pending. The isolated rerun without concurrent backend tests passed all five; the precise cause of that transient navigation stall is not established. Strict types, ESLint, generated contracts, Ruff/format and diff checks passed. The prior full backend evidence remains the 253-test run plus separately added grouped-capacity test; no new full-suite pass is claimed here.

## Remaining editor acceptance

The production frontend build also passed for grouped content restoration. Physical-disk/power-loss behavior, exhaustive browser scheduling races and long-session latency are not established by these focused checks.

`tests/api/test_segment_history.py` covers multilevel replay, persisted history, approval/take invalidation, abandoned redo branches, missing confirmation, stale/foreign targets, active-job/inactive-revision gates, provider discontinuities, speaker warnings, old snapshots and bounded responses. Existing timeline tests exercise the extracted normal-edit validation. `tests/e2e/edit-history.spec.ts` covers keyboard saving/navigation, saved undo/redo across reload, filtered navigation, unsaved-draft protection, two-tab conflict handling and the narrow-screen layout.

`tests/e2e/editor-accessibility.spec.ts` reproduces the original save-focus loss and covers restored focus, a delayed save without focus theft, save-conflict draft preservation, synthetic composition suppression without PATCH requests, native select handling, first-tab skip navigation and its mobile focus treatment. Synthetic composition events and DOM semantics are not physical Malayalam IME or screen-reader listening evidence.

Ordinary saved line history does not reverse structural edits; use the separate [split/merge history](0013-timeline-structure.md). Brief/voice edits and undoing approval alone remain outside this history contract. Full accessibility/IME/device coverage and long-session performance remain separate acceptance gates. This milestone does not establish natural-language or media quality.
