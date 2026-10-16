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

## Verification and remaining editor scope

`tests/api/test_segment_history.py` covers multilevel replay, persisted history, approval/take invalidation, abandoned redo branches, missing confirmation, stale/foreign targets, active-job/inactive-revision gates, provider discontinuities, speaker warnings, old snapshots and bounded responses. Existing timeline tests exercise the extracted normal-edit validation. `tests/e2e/edit-history.spec.ts` covers keyboard saving/navigation, saved undo/redo across reload, filtered navigation, unsaved-draft protection, two-tab conflict handling and the narrow-screen layout.

Saved history does not yet cover line splitting/merging, brief/voice edits, cross-line grouped operations or undoing approval alone. Full accessibility/IME/device coverage and long-session performance remain separate acceptance gates. This milestone does not establish natural-language or media quality.
