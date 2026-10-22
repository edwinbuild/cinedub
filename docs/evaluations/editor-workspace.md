# Editor workspace reference and interaction checks

## Reference decisions

The three user-supplied editor screenshots are the visual references for this
refinement. Their shared patterns are a neutral charcoal application frame,
compact controls, a prominent source viewer, grouped tools and a separate
timeline. The first reference informs panel boundaries and information density;
the second informs field alignment and restrained control styling; the third
informs media import, tool navigation and the docked timeline.

The implementation uses those patterns for CineDub's dialogue workflow. It does
not add decorative colour wheels, node graphs or buttons for unsupported media
operations. Cyan identifies selections, focus and actionable controls; muted grey
identifies secondary information. Amber/red remain available for actual warnings.

## Connected interactions

- File picker and single-file drop use the same API upload and ingest path.
  Multiple dropped files are refused before an upload is sent.
- Dialogue clip bodies move their timing windows while preserving length and
  respecting neighbouring lines. Edges trim. Pointer and keyboard changes stay
  in the line draft until saved through the existing version-checked API.
- Selecting a clip reveals its dialogue line. **Split / merge** opens the existing
  structural editor for that selection. Explicit text partitioning, confirmation,
  history and renewed approval remain required.
- Tools, dialogue inspector and timeline can collapse and reopen without
  unmounting unsaved forms. Navigation also reopens the selected tool panel.
- Text fields, dropdowns, checkboxes, buttons, focus states and hover states share
  the workspace control palette, including advanced forms.
- Tools and inspector widths and timeline height support pointer and keyboard
  resizing. Bounds protect the monitor; layouts adapt to smaller windows and
  phones stack the panels. Only pane sizes persist in browser storage.
- Nested panel outlines are replaced by spacing, subtle dividers and solid
  charcoal surfaces. Dialogue/take clips use opaque fills. Focus, selection,
  warnings and unavailable actions remain distinguishable.

These are dialogue-timeline operations. Source-video splicing and full-film
assembly are outside the existing short-scene workspace contract.

## Verification procedure

Run `npm run test:e2e -- tests/e2e/editor-interactions.spec.ts` for dropped video,
preview playback, hover/focus styling, collapse/draft preservation, clip movement,
keyboard nudging, save/reopen and a persisted split. It also checks the page at
1440, 1280, 1024, 768 and 390 pixels without horizontal page overflow.
The pane-sizing check also covers persistence, collapse/draft preservation,
keyboard limits/reset, smaller-window resizing, compact audio controls and
unclipped fields across every tool at the minimum tools width.

Run the full default browser suite for the remaining review, conflict, consent,
mix, export, keyboard, split/merge/reversal and timeline workflows. The CI browser
selection includes both `editor-interactions.spec.ts` and `workspace-ui.spec.ts`.
All fixtures are synthetic; model/provider/listening quality is a separate gate.

Browser-view connections were unavailable in this session. Checks use the actual
installed Chrome with isolated Next.js, API and worker processes, plus captured
screenshots inspected visually. The normal workspace database and its existing
development server are not used for the rehearsals.

## Recorded result — 2026-10-21

- Full default Chrome suite: **25 passed**, seven optional model cases skipped.
- Production build, strict TypeScript, ESLint and generated contracts: passed.
- Frontend unit tests: **11 passed**, including whole-clip movement bounds.
- Desktop, laptop, tablet and phone screenshots were inspected. The initial
  phone header wrapped into the tool navigation; its height and row layout were
  corrected. The final responsive checks report no horizontal page overflow.
- The initial new-test failures were a missing wait for an asynchronous demo job
  and an alert locator matching Next.js's route announcer. The tests now wait for
  the saved transcript and scope the upload error to its drop zone. Existing
  regression assertions were retained.

Optional model inference, physical IME/screen-reader use, natural speech quality
and professional source-video assembly are not established by these UI checks.

## Pane and surface refinement — 2026-10-21

- The complete default Chrome suite passed **26 tests**, with seven optional
  model cases skipped. After the compact-monitor and smaller-window sizing
  corrections, **five focused editor/workspace checks** passed on the final source.
- The final production build, strict TypeScript and ESLint passed. Generated
  contracts and all **11 frontend unit tests** passed; their inputs are unchanged
  by the final layout corrections.
- Pointer resizing, keyboard bounds/reset, persisted sizes and draft preservation
  passed. Every tool was expanded at the minimum tools width: no horizontal pane
  scrolling or clipped input/select/textarea fields were detected.
- Screenshots at desktop/tablet/phone sizes and the resizing limits were inspected.
  The initially cramped audio placeholder was corrected: a compact monitor keeps
  its actual playback controls and waveform visible. No horizontal page overflow
  was detected, including a 1120×650 window with large saved pane preferences.

The tests still use synthetic fixtures and isolated local services. These results
do not extend the provider/model/listening-quality acceptance boundary above.

## Rounded controls and button hints — 2026-10-21

Controls now share a 6px radius; cards and tooltip bubbles share 8px. Hints explain
tool tabs and compact header/timeline actions without adding permanent labels or
extra panels. They appear after a short hover or on keyboard focus, stay hoverable,
and dismiss on Escape, blur, scrolling, resize or activation. Touch stays direct.

The final focused Chrome run passed **nine tests**, covering named/described
hover hints, keyboard focus and Escape, viewport bounds, button activation,
accessibility, upload/playback, clip movement/split, pane sizing and draft retention.
Desktop and phone hint screenshots were inspected. Production build, strict
TypeScript, ESLint and all **11 frontend unit tests** passed. The earlier full
26-test run covers the preceding pane/surface refinement; hosted CI runs the
complete default editor workflows for the final PR head.

## PR review follow-up — 2026-10-22

PR #4 had no review comments or unresolved threads; both hosted checks passed on
`acc96e8`. A source review and two browser regressions exposed these edge cases:

- Escape during the 350ms hover delay did not cancel the pending tooltip because
  its dismissal listeners were attached only after the bubble appeared. The
  listeners now cover pending and visible hints, including scrolling and resizing,
  and are removed when the hint closes.
- Alt/Ctrl/Meta with an arrow key changed dialogue timing by 10ms. Clip and trim
  handlers now leave these combinations to the browser; plain arrows and
  Shift-arrows retain the existing exact 10ms/100ms nudges.

Both added regressions failed before the fix and passed afterward. They also
confirm a fresh hint can still open and normal clip/trim nudging still works.

The final complete default Chrome suite passed **29 tests**; seven optional
model cases were skipped. The production build, strict TypeScript, ESLint,
generated contracts and all **11 frontend unit tests** passed. The rehearsal used
isolated services and synthetic media; provider/listening quality remains outside
this verification scope.
