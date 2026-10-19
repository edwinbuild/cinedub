import assert from "node:assert/strict";
import { test } from "node:test";
import type { ProjectDetail } from "@cinedub/contracts";
import { attentionItems, errorAction } from "./review-queue.ts";

const line = (overrides: Record<string, unknown>) => ({
  id: "l", index: 0, start_ms: 0, end_ms: 1000, translated_text: "ഒന്ന്", speaker_id: "s",
  status: "approved", retired: false, selected_candidate_id: null, warnings_json: [], ...overrides,
});

test("attention items are ordered by urgency then time and skip retired lines", () => {
  const project = {
    segments: [
      line({ id: "b", index: 1, start_ms: 2000, status: "needs_review" }),
      line({ id: "a", index: 0, start_ms: 0, translated_text: " ", speaker_id: null }),
      line({ id: "c", index: 2, start_ms: 4000, selected_candidate_id: "take" }),
      line({ id: "d", index: 3, start_ms: 6000, selected_candidate_id: "gone" }),
      line({ id: "e", index: 4, start_ms: 8000, warnings_json: ["Overlaps line 3"] }),
      line({ id: "r", index: 5, retired: true, status: "draft" }),
    ],
    artifacts: [{ id: "take", kind: "dialogue_candidate", metadata_json: { fit_status: "too_long", demo: true } }],
  } as unknown as ProjectDetail;
  const items = attentionItems(project);
  assert.deepEqual(items.map((item) => [item.kind, item.lineId]), [
    ["untranslated", "a"], ["no_speaker", "a"], ["unapproved", "b"], ["stale_take", "d"],
    ["take_overrun", "c"], ["no_take", "a"], ["no_take", "e"], ["line_warning", "e"], ["demo", null],
  ]);
  assert.match(items.at(-1)!.message, /1 DEMO fixture outputs/);
  assert.equal(items.find((item) => item.kind === "line_warning")!.message, "Line 5: Overlaps line 3");
});

test("no take reminders before any voice candidates exist", () => {
  const project = { segments: [line({})], artifacts: [] } as unknown as ProjectDetail;
  assert.deepEqual(attentionItems(project), []);
});

test("every error code maps to an action and unknown codes are treated as internal", () => {
  assert.match(errorAction("budget_exceeded")!, /budget/);
  assert.match(errorAction("uncertain_submission")!, /billed/);
  assert.equal(errorAction("ValueError"), errorAction("internal"));
  assert.equal(errorAction(null), null);
});
