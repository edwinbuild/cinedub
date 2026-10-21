# 0021 — Focused editing workspace

Date: 2026-10-21

The editor previously placed processing controls in one rail, every domain panel in
the central column and project administration in another rail. The monitor and
time-based timeline scrolled out of view while reviewing dialogue. This made the
initial screen difficult to explain and required editors to scan unrelated tools.

Use the familiar media-bin, monitor, inspector and timeline arrangement from
desktop video editors, adapted to dialogue review. A labelled tool navigation
selects Media, Workflow, Voices, Analysis, Export or Project. The source monitor,
dialogue editor and timeline remain available on desktop; smaller screens stack
these regions without horizontal page overflow. The home screen remains a simple
project launcher.

Tool containers use `hidden` rather than conditional unmounting. Switching tools
must preserve dialogue, workflow options, mix, consent and analysis drafts. The
existing canonical timeline, save/conflict handling, consent and budget gates,
provider routing, DEMO disclosures and export acceptance remain authoritative.
Navigation buttons only select tools; the header Export action opens the export
controls and does not render or approve anything.

Timeline track labels identify source, dialogue, selected takes and retained
stems. Selecting a dialogue block seeks the source and reveals its line editor.
Advanced operations are grouped by purpose rather than placed before the dialogue.

The reference refinement adds file drop import, whole-dialogue-clip movement,
panel collapse and a toolbar shortcut to the existing split/merge editor. Clip
movement preserves duration, stays within neighbouring dialogue and creates an
unsaved timing draft. It is committed through the existing version-checked line
save, which invalidates affected approvals/takes. It does not move or splice
source video. Splitting still requires explicit text partitioning and review.

All controls share a charcoal/grey surface scale, white text and cyan interaction
states. Status warnings retain amber/red where needed. Dropdowns, fields, buttons,
focus rings and hover states use the same rules in basic and advanced tools.
Tools, dialogue and timeline can collapse without unmounting editing state.

Pane dividers support pointer and keyboard resizing, with bounded side widths and
timeline height to protect the source monitor. Only layout sizes are remembered
in browser storage; project content and unsaved drafts are never stored there.
Saved sizes adapt to smaller windows, the inspector stacks below on tablets and
phones use the existing stacked layout without resize handles. Enter or a
double-click resets a divider. Solid neutral surfaces and opaque clips replace
nested card outlines; cyan remains visible for selection and keyboard focus.

This introduces no provider-quality claim, database migration or deployment requirement. Browser
verification must cover the complete DEMO workflow, keyboard editing, tool-switch
draft preservation and desktop/narrow-screen layouts.

Verification on 2026-10-21: strict TypeScript, ESLint, generated contracts,
10 frontend unit tests and the production build passed. The complete default
browser suite passed 22 tests; seven optional installed-model cases were skipped
by design. The checks ran in isolated copies because a development server was
already running in the main checkout. Desktop (1440px), laptop (1024px) and
phone (390px) screenshots were reviewed. No live provider or listening-quality
acceptance is inferred from these UI checks.

The subsequent reference refinement passed the 25-test default browser suite and
11 frontend unit tests. Its [reference decisions and interaction checks](../evaluations/editor-workspace.md)
record the added upload/clip/panel behaviour and verification boundaries.
