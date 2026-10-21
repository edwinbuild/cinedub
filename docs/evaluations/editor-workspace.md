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

These are dialogue-timeline operations. Source-video splicing and full-film
assembly are outside the existing short-scene workspace contract.

## Verification procedure

Run `npm run test:e2e -- tests/e2e/editor-interactions.spec.ts` for dropped video,
preview playback, hover/focus styling, collapse/draft preservation, clip movement,
keyboard nudging, save/reopen and a persisted split. It also checks the page at
1440, 1280, 1024, 768 and 390 pixels without horizontal page overflow.

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
