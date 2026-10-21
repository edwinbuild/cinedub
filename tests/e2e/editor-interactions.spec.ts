import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { API, guardPage, openTool, sceneWorkspace, wav } from "./helpers";

test("file drop uploads a video, panels restore drafts, and controls stay within the viewport", async ({ page, request }) => {
  const noErrors = guardPage(page);
  await page.goto("/");
  await page.getByLabel("Project name").fill("Reference workspace review");
  await expect.poll(() => page.getByLabel("Project name").evaluate((element) => getComputedStyle(element).borderTopColor)).toBe("rgb(66, 203, 237)");
  await page.screenshot({ path: "test-results/editor-home.png", fullPage: true });
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  const id = page.url().split("/").at(-1)!;
  const video = execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
    "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=16000", "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
    "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"], { maxBuffer: 8_000_000 });
  const drop = page.getByLabel("Scene file drop zone", { exact: true });
  const transfer = await page.evaluateHandle((bytes) => {
    const data = new DataTransfer(); data.items.add(new File([Uint8Array.from(bytes)], "original-test-scene.mp4", { type: "video/mp4" })); return data;
  }, Array.from(video));
  await drop.dispatchEvent("dragenter", { dataTransfer: transfer });
  await expect(drop).toHaveClass(/dragOver/);
  await drop.dispatchEvent("drop", { dataTransfer: transfer });
  await transfer.dispose();
  const player = page.getByRole("region", { name: "Source monitor", exact: true }).locator("video");
  await expect(player).toBeVisible({ timeout: 30_000 });
  await player.evaluate((element: HTMLVideoElement) => element.play());
  await expect.poll(() => player.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(.1);
  await player.evaluate((element: HTMLVideoElement) => element.pause());
  expect((await (await request.get(`${API}/projects/${id}`)).json()).assets).toHaveLength(1);
  await openTool(page, "Workflow");
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  const line = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  await line.getByLabel("Malayalam", { exact: true }).fill("Retain this review draft");
  await page.getByRole("button", { name: "Close dialogue inspector", exact: true }).click();
  await expect(line).toBeHidden();
  await page.getByRole("button", { name: "Show dialogue inspector", exact: true }).click();
  await expect(line.getByLabel("Malayalam", { exact: true })).toHaveValue("Retain this review draft");
  await openTool(page, "Export");
  const mix = page.getByRole("region", { name: "Retained-background mix and export", exact: true });
  await mix.locator("summary").first().click();
  await mix.getByLabel("Music gain (dB)").fill("-5");
  await page.getByRole("button", { name: "Close tools panel", exact: true }).click();
  await expect(mix).toBeHidden();
  await page.getByRole("button", { name: "Show tools panel", exact: true }).click();
  await expect(mix.getByLabel("Music gain (dB)")).toHaveValue("-5");
  await page.getByRole("button", { name: "Hide timeline", exact: true }).click();
  await expect(page.getByRole("group", { name: "Dialogue track", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Show timeline", exact: true }).click();
  await expect(page.getByRole("group", { name: "Dialogue track", exact: true })).toBeVisible();
  await openTool(page, "Media");
  const voicesTool = page.getByRole("navigation", { name: "Workspace tools" }).getByRole("button", { name: "Voices", exact: true });
  const resting = await voicesTool.evaluate((element) => getComputedStyle(element).backgroundColor);
  await voicesTool.hover();
  await expect.poll(() => voicesTool.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(resting);
  for (const width of [1440, 1280, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/editor-reference-${width}.png`, fullPage: true });
  }
  noErrors();
});

test("whole dialogue clips move without overlaps, save and reopen, and the timeline split shortcut selects a line", async ({ page, request }) => {
  const noErrors = guardPage(page);
  const id = await sceneWorkspace(page, "Clip movement and split");
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines", exact: true })).toBeVisible();
  const timeline = page.getByRole("region", { name: "Scene timeline", exact: true });
  const line = page.getByRole("article", { name: "Dialogue line 2", exact: true });
  const clip = timeline.locator(".timelineLabel").nth(1);
  const original = await (await request.get(`${API}/projects/${id}`)).json();
  const before = original.segments[1];
  const duration = before.end_ms - before.start_ms;
  const box = (await clip.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 45, box.y + box.height / 2, { steps: 8 });
  await page.mouse.up();
  const movedStart = Number(await line.getByLabel("Start (s)").inputValue());
  await clip.focus(); await clip.press("Shift+ArrowLeft");
  await expect(line.getByLabel("Start (s)")).toHaveValue(String((Math.round(movedStart * 1000) - 100) / 1000));
  const start = Math.round(Number(await line.getByLabel("Start (s)").inputValue()) * 1000);
  const end = Math.round(Number(await line.getByLabel("End (s)").inputValue()) * 1000);
  expect(start).toBeGreaterThan(before.start_ms); expect(end - start).toBe(duration);
  expect(start).toBeGreaterThanOrEqual(original.segments[0].end_ms);
  expect(end).toBeLessThanOrEqual(original.segments[2].start_ms);
  await line.getByRole("button", { name: "Save line", exact: true }).click();
  await expect(line.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await page.reload();
  await expect(line.getByLabel("Start (s)")).toHaveValue(String(start / 1000));
  await expect(line.getByLabel("End (s)")).toHaveValue(String(end / 1000));
  await clip.click();
  await timeline.getByRole("button", { name: "Split / merge", exact: true }).click();
  const structure = page.getByLabel("Split merge and structural history", { exact: true });
  const detail = await (await request.get(`${API}/projects/${id}`)).json();
  await expect(structure.getByLabel("Line to restructure", { exact: true })).toHaveValue(detail.segments[1].id);
  await structure.getByLabel("First part English", { exact: true }).fill("First reviewed half.");
  await structure.getByLabel("Second part English", { exact: true }).fill("Second reviewed half.");
  await structure.getByLabel("Replace the saved lines, clear their selected takes and require approval again").check();
  await structure.getByRole("button", { name: "Split saved line", exact: true }).click();
  await expect(page.getByRole("heading", { name: "5 reviewable lines" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("article", { name: "Dialogue line 2", exact: true }).getByLabel("English", { exact: true })).toHaveValue("First reviewed half.");
  await expect(page.getByRole("article", { name: "Dialogue line 3", exact: true }).getByLabel("English", { exact: true })).toHaveValue("Second reviewed half.");
  noErrors();
});

test("dropping several files is refused without sending an upload", async ({ page }) => {
  await sceneWorkspace(page, "Single scene upload guard");
  let uploads = 0; page.on("request", (request) => { if (request.method() === "POST" && request.url().includes("/uploads")) uploads++; });
  const transfer = await page.evaluateHandle((bytes) => {
    const data = new DataTransfer();
    for (const name of ["one.wav", "two.wav"]) data.items.add(new File([Uint8Array.from(bytes)], name, { type: "audio/wav" }));
    return data;
  }, Array.from(wav(1)));
  await page.getByLabel("Scene file drop zone", { exact: true }).dispatchEvent("drop", { dataTransfer: transfer });
  await transfer.dispose();
  await expect(page.getByLabel("Scene file drop zone", { exact: true }).getByRole("alert")).toHaveText("Import one scene at a time.");
  expect(uploads).toBe(0);
});
