import { expect, test } from "@playwright/test";
import { API, guardPage, sceneWorkspace } from "./helpers";

test("timeline zoom, keyboard nudge and drag edit line drafts that save through the line editor", async ({ page, request }) => {
  const noErrors = guardPage(page);
  const id = await sceneWorkspace(page, "Timeline editing");
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible({ timeout: 30_000 });
  const timeline = page.getByRole("region", { name: "Scene timeline" });
  await expect(timeline).toBeVisible();
  const content = timeline.locator(".timelineContent");
  // The timeline's own scale (style width), not its CSS minimum width, reflects the zoom.
  const scale = () => content.evaluate((element) => parseFloat((element as HTMLElement).style.width));
  const before = await scale();
  await timeline.getByRole("button", { name: "Zoom timeline in" }).click();
  await expect.poll(scale).toBeGreaterThan(before);

  const line1 = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  const end = timeline.getByRole("slider", { name: "End of line 1 on timeline" });
  await expect(end).toHaveAttribute("aria-valuenow", "4000");
  await end.focus();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Shift+ArrowLeft");
  await expect(line1.getByLabel("End (s)")).toHaveValue("3.89");
  await expect(end).toHaveAttribute("aria-valuenow", "3890");
  await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
  await expect(timeline.getByText(/Line 1 draft end 0:03\.89; save the line to keep it/)).toBeAttached();

  // Another editor changes line 1 meanwhile: the draft survives and cannot overwrite blindly.
  const detail = await (await request.get(`${API}/projects/${id}`)).json();
  const saved = detail.segments[0];
  await request.patch(`${API}/segments/${saved.id}`, { data: { expected_version: saved.version, translated_text: "Remote correction" } });
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(line1.getByLabel("End (s)")).toHaveValue("3.89");
  await expect(line1.getByRole("button", { name: "Save line" })).toBeDisabled();
  // Discard by reloading, then edit again on the current version and save.
  await page.reload();
  await expect(line1.getByLabel("End (s)")).toHaveValue("4");
  const start2 = timeline.getByRole("slider", { name: "Start of line 2 on timeline" });
  const box = (await start2.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2, { steps: 5 });
  await page.mouse.up();
  const line2 = page.getByRole("article", { name: "Dialogue line 2", exact: true });
  const draftedStart = Number(await line2.getByLabel("Start (s)").inputValue());
  expect(draftedStart).toBeGreaterThan(4);
  await expect(timeline.locator(".timelineBlock.drafted")).toHaveCount(1);
  await line2.getByRole("button", { name: "Save line" }).click();
  await expect(line2.getByRole("button", { name: "Save line" })).toBeDisabled();
  await expect(timeline.locator(".timelineBlock.drafted")).toHaveCount(0);
  const stored = (await (await request.get(`${API}/projects/${id}`)).json()).segments[1];
  expect(stored.start_ms).toBe(Math.round(draftedStart * 1000));
  await page.screenshot({ path: "test-results/cinedub-timeline.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(timeline).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/cinedub-timeline-mobile.png", fullPage: true });
  noErrors();
});
