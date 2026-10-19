import assert from "node:assert/strict";
import { test } from "node:test";
import type { ProjectDetail } from "@cinedub/contracts";
import {
  MIN_LINE_MS, buildTracks, clampScroll, formatMs, moveEdge, msToPx, neighboursOf, nextZoom, pxToMs,
  snap, ticks, visibleRange, zoomAround, type View,
} from "./timeline.ts";

const view: View = { pxPerMs: 0.1, scrollMs: 1000, widthPx: 800 };

test("time and pixel conversions are inverse at any zoom and scroll", () => {
  assert.equal(msToPx(1000, view), 0);
  assert.equal(msToPx(2000, view), 100);
  assert.equal(pxToMs(100, view), 2000);
  for (const ms of [0, 1234, 9999]) assert.equal(pxToMs(msToPx(ms, view), view), ms);
  assert.deepEqual(visibleRange(view), { start_ms: 1000, end_ms: 9000 });
});

test("scrolling stays inside the scene", () => {
  assert.equal(clampScroll(-50, 20000, view), 0);
  assert.equal(clampScroll(50000, 20000, view), 12000);
  assert.equal(clampScroll(5000, 3000, view), 0);
});

test("zooming keeps the anchored time under the cursor", () => {
  const zoomed = zoomAround(view, 0.2, 3000, 60000);
  assert.equal(Math.round(msToPx(3000, zoomed)), Math.round(msToPx(3000, view)));
  assert.equal(nextZoom(0.1, 1), 0.2);
  assert.equal(nextZoom(0.1, -1), 0.05);
  assert.equal(nextZoom(0.8, 1), 0.8);
  assert.equal(nextZoom(0.02, -1), 0.02);
});

test("edges snap only within tolerance", () => {
  assert.equal(snap(1010, [1000, 2000], 20), 1000);
  assert.equal(snap(1050, [1000, 2000], 20), 1050);
  assert.equal(snap(1990, [1000, 1995, 2000], 20), 1995);
});

test("moving an edge keeps duration, bounds and neighbour order", () => {
  const line = { start_ms: 1000, end_ms: 2000 };
  const free = { previousEnd: 500, nextStart: 3000 };
  assert.deepEqual(moveEdge(line, "start", 1200, free, 10000), { start_ms: 1200, end_ms: 2000 });
  assert.deepEqual(moveEdge(line, "start", 100, free, 10000), { start_ms: 500, end_ms: 2000 });
  assert.deepEqual(moveEdge(line, "start", 1950, free, 10000), { start_ms: 2000 - MIN_LINE_MS, end_ms: 2000 });
  assert.deepEqual(moveEdge(line, "end", 5000, free, 10000), { start_ms: 1000, end_ms: 3000 });
  assert.deepEqual(moveEdge(line, "end", 1050, free, 10000), { start_ms: 1000, end_ms: 1000 + MIN_LINE_MS });
  assert.deepEqual(moveEdge(line, "end", 99999, { previousEnd: null, nextStart: null }, 2500),
    { start_ms: 1000, end_ms: 2500 });
  const lines = [{ start_ms: 0, end_ms: 900 }, line, { start_ms: 3000, end_ms: 4000 }];
  assert.deepEqual(neighboursOf(lines, 1), { previousEnd: 900, nextStart: 3000 });
  assert.deepEqual(neighboursOf(lines, 0), { previousEnd: null, nextStart: 1000 });
});

test("tracks reflect lines, selected take fit and approved stems", () => {
  const project = {
    assets: [{ id: "a", duration_ms: 8000, active_stem_set_id: "s" }],
    speakers: [{ id: "sp", display_name: "Asha" }],
    segments: [
      { id: "l1", index: 0, start_ms: 0, end_ms: 1000, translated_text: "ഒന്ന്", source_text: "One",
        speaker_id: "sp", status: "approved", retired: false, selected_candidate_id: "c1" },
      { id: "l2", index: 1, start_ms: 1500, end_ms: 2500, translated_text: "", source_text: "Two",
        speaker_id: null, status: "needs_review", retired: false, selected_candidate_id: null },
      { id: "old", index: 2, start_ms: 0, end_ms: 99999, translated_text: "", source_text: "x",
        speaker_id: null, status: "draft", retired: true, selected_candidate_id: null },
    ],
    stem_sets: [{ id: "s", status: "approved", provider: "fake" }],
    artifacts: [
      { id: "c1", kind: "dialogue_candidate", metadata_json: { fit_status: "ready", demo: true, raw_duration_ms: 900 } },
      { id: "p1", kind: "stem_preview", metadata_json: { stem_set_id: "s", stem: "music" } },
    ],
  } as unknown as ProjectDetail;
  const tracks = buildTracks(project, "a");
  assert.equal(tracks.durationMs, 8000);
  assert.deepEqual(tracks.dialogue.map((line) => [line.id, line.label, line.speaker, line.approved]),
    [["l1", "ഒന്ന്", "Asha", true], ["l2", "Two", null, false]]);
  assert.deepEqual(tracks.takes.map((take) => [take.fit, take.demo, take.rawDurationMs]),
    [["ready", true, 900], ["missing", false, null]]);
  assert.deepEqual(tracks.stems, [{ name: "music", artifactId: "p1", demo: true }]);
});

test("labels and ticks stay readable", () => {
  assert.equal(formatMs(61234), "1:01.23");
  assert.equal(formatMs(-5), "0:00.00");
  assert.deepEqual(ticks({ pxPerMs: 0.1, scrollMs: 0, widthPx: 800 }, 3500), [0, 1000, 2000, 3000]);
  assert.deepEqual(ticks({ pxPerMs: 0.02, scrollMs: 0, widthPx: 800 }, 40000), [0, 5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000]);
});
