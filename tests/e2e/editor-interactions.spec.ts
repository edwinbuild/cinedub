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

test("pane sizing supports dragging, keyboard limits and reload without losing drafts during layout changes", async ({ page }) => {
  const noErrors = guardPage(page);
  await sceneWorkspace(page, "Resizable editor panes");
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  const line = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  await line.getByLabel("Malayalam", { exact: true }).fill("Preserve while resizing");
  const tools = page.getByRole("separator", { name: "Resize tools panel", exact: true });
  const inspector = page.getByRole("separator", { name: "Resize dialogue inspector", exact: true });
  const timeline = page.getByRole("separator", { name: "Resize timeline", exact: true });
  for (const [handle, dx, dy, expected] of [[tools, 80, 0, 390], [inspector, -60, 0, 430], [timeline, 0, -110, 368]] as const) {
    const box = (await handle.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + dx, box.y + box.height / 2 + dy, { steps: 10 });
    await page.mouse.up();
    await expect(handle).toHaveAttribute("aria-valuenow", String(expected));
  }
  expect(Math.round((await page.getByLabel("Scene tools", { exact: true }).boundingBox())!.width)).toBe(390);
  expect(Math.round((await page.getByLabel("Dialogue inspector", { exact: true }).boundingBox())!.width)).toBe(430);
  expect(Math.round((await page.getByLabel("Timeline workspace", { exact: true }).boundingBox())!.height)).toBe(368);
  await expect(line.getByLabel("Malayalam", { exact: true })).toHaveValue("Preserve while resizing");
  await page.getByRole("button", { name: "Close dialogue inspector", exact: true }).click();
  await expect(inspector).toBeHidden();
  await page.getByRole("button", { name: "Show dialogue inspector", exact: true }).click();
  await expect(inspector).toHaveAttribute("aria-valuenow", "430");
  await expect(line.getByLabel("Malayalam", { exact: true })).toHaveValue("Preserve while resizing");
  await page.getByRole("button", { name: "Save line", exact: true }).first().click();
  await expect(line.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await page.screenshot({ path: "test-results/editor-resized.png", fullPage: true });
  await page.reload();
  await expect(tools).toHaveAttribute("aria-valuenow", "390");
  await expect(inspector).toHaveAttribute("aria-valuenow", "430");
  await expect(timeline).toHaveAttribute("aria-valuenow", "368");
  await expect(line.getByLabel("Malayalam", { exact: true })).toHaveValue("Preserve while resizing");
  await tools.focus(); await tools.press("Home");
  for (const tool of ["Workflow", "Voices", "Analysis", "Export", "Project", "Media"]) {
    await openTool(page, tool);
    const panel = page.getByLabel("Scene tools", { exact: true });
    await panel.locator(".toolBody:visible details").evaluateAll((details) => details.forEach((detail) => { (detail as HTMLDetailsElement).open = true; }));
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const clippedFields = await panel.evaluate((element) => {
      const pane = element.getBoundingClientRect();
      return Array.from(element.querySelectorAll("input, select, textarea")).filter((field) => {
        const box = field.getBoundingClientRect();
        return box.width > 0 && (box.left < pane.left || box.right > pane.right);
      }).map((field) => field.getAttribute("aria-label") ?? field.tagName);
    });
    expect(clippedFields, `${tool} fields stay inside the narrowest tools pane`).toEqual([]);
  }
  for (const handle of [tools, inspector, timeline]) {
    await handle.focus(); await handle.press("Home");
    await expect.poll(async () => await handle.getAttribute("aria-valuenow")).toBe(await handle.getAttribute("aria-valuemin"));
    await handle.press("End");
    await expect.poll(async () => await handle.getAttribute("aria-valuenow")).toBe(await handle.getAttribute("aria-valuemax"));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  const monitor = page.getByRole("region", { name: "Source monitor", exact: true });
  expect((await monitor.boundingBox())!.width).toBeGreaterThanOrEqual(320);
  expect((await monitor.boundingBox())!.height).toBeGreaterThanOrEqual(250);
  await page.screenshot({ path: "test-results/editor-sizing-limits.png", fullPage: true });
  await page.setViewportSize({ width: 1120, height: 650 });
  await expect.poll(async () => (await monitor.boundingBox())!.width).toBeGreaterThanOrEqual(320);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const compactTools = Number(await tools.getAttribute("aria-valuenow"));
  const compactInspector = Number(await inspector.getAttribute("aria-valuenow"));
  await tools.focus(); await tools.press("ArrowLeft");
  await expect(tools).toHaveAttribute("aria-valuenow", String(compactTools - 10));
  await expect(inspector).toHaveAttribute("aria-valuenow", String(compactInspector));
  const audio = monitor.locator("audio");
  expect((await audio.boundingBox())!.height).toBeGreaterThanOrEqual(32);
  await expect(audio).toBeInViewport();
  const monitorBox = (await monitor.boundingBox())!;
  const audioBox = (await audio.boundingBox())!;
  expect(audioBox.y).toBeGreaterThanOrEqual(monitorBox.y);
  expect(audioBox.y + audioBox.height).toBeLessThanOrEqual(monitorBox.y + monitorBox.height);
  await page.screenshot({ path: "test-results/editor-compact-sizing.png", fullPage: true });
  await page.setViewportSize({ width: 1024, height: 900 });
  await expect(inspector).toBeHidden();
  await expect(tools).toBeVisible();
  await expect(timeline).toBeVisible();
  await tools.focus(); await tools.press("ArrowLeft");
  await timeline.focus(); await timeline.press("ArrowDown");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const handle of [tools, inspector, timeline]) await expect(handle).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const [handle, expected] of [[tools, 310], [inspector, 370], [timeline, 258]] as const) {
    await handle.focus(); await handle.press("Enter");
    await expect(handle).toHaveAttribute("aria-valuenow", String(expected));
  }
  await tools.press("Shift+ArrowRight");
  await expect(tools).toHaveAttribute("aria-valuenow", "360");
  await tools.dblclick();
  await expect(tools).toHaveAttribute("aria-valuenow", "310");
  await expect(line.getByLabel("Malayalam", { exact: true })).toHaveValue("Preserve while resizing");
  noErrors();
});

test("button explanations work on hover and keyboard focus without clipping or blocking actions", async ({ page }) => {
  const noErrors = guardPage(page);
  await sceneWorkspace(page, "Minimal workspace hints");
  const refresh = page.getByRole("button", { name: "Refresh project", exact: true });
  const tooltip = page.getByRole("tooltip");
  await refresh.hover();
  await expect(tooltip).toContainText("Refresh project");
  await expect(tooltip).toContainText("preserving open drafts");
  await expect(refresh).toHaveAttribute("aria-describedby", (await tooltip.getAttribute("id"))!);
  await tooltip.hover();
  await expect(tooltip).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();
  await refresh.focus();
  await expect(tooltip).toBeVisible();
  await refresh.press("Escape");
  await expect(tooltip).toBeHidden();
  const voices = page.getByRole("navigation", { name: "Workspace tools" }).getByRole("button", { name: "Voices", exact: true });
  await voices.hover();
  await expect(tooltip).toContainText("Cast speakers and choose takes");
  await voices.click();
  await expect(tooltip).toBeHidden();
  await expect(page.getByRole("region", { name: "Voice tools", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Fit timeline to view", exact: true }).hover();
  await expect(tooltip).toContainText("Fit the full scene");
  const bounds = (await tooltip.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(1440);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(1000);
  await page.screenshot({ path: "test-results/editor-tooltip-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(tooltip).toBeHidden();
  await refresh.hover();
  await expect(tooltip).toContainText("Refresh project");
  const narrow = (await tooltip.boundingBox())!;
  expect(narrow.x).toBeGreaterThanOrEqual(0);
  expect(narrow.x + narrow.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/editor-tooltip-phone.png" });
  await refresh.click();
  await expect(tooltip).toBeHidden();
  await expect(page.getByRole("region", { name: "Source monitor", exact: true })).toBeVisible();
  noErrors();
});

test("Escape, scrolling and resizing cancel a tooltip before its hover delay finishes", async ({ page }) => {
  const noErrors = guardPage(page);
  await sceneWorkspace(page, "Pending hint cancellation");
  await page.clock.install();
  const refresh = page.getByRole("button", { name: "Refresh project", exact: true });
  const tooltip = page.getByRole("tooltip");
  for (const action of ["escape", "scroll", "resize"]) {
    await page.mouse.move(2, 2);
    await refresh.hover();
    await page.clock.runFor(100);
    if (action === "escape") await page.keyboard.press("Escape");
    if (action === "scroll") await page.evaluate(() => window.dispatchEvent(new Event("scroll")));
    if (action === "resize") await page.setViewportSize({ width: 1280, height: 900 });
    await page.clock.runFor(500);
    await expect(tooltip, `${action} cancels the pending hint`).toBeHidden({ timeout: 1000 });
  }
  await page.mouse.move(2, 2);
  await refresh.hover();
  await page.clock.runFor(400);
  await expect(tooltip).toContainText("Refresh project");
  await refresh.click();
  await expect(tooltip).toBeHidden();
  noErrors();
});

test("browser shortcut modifiers do not change dialogue clip or trim drafts", async ({ page }) => {
  const noErrors = guardPage(page);
  await sceneWorkspace(page, "Timeline shortcut boundaries");
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  const line = page.getByRole("article", { name: "Dialogue line 2", exact: true });
  const start = line.getByLabel("Start (s)");
  const end = line.getByLabel("End (s)");
  const original = { start: await start.inputValue(), end: await end.inputValue() };
  const timeline = page.getByRole("region", { name: "Scene timeline", exact: true });
  const clip = timeline.locator(".timelineLabel").nth(1);
  const trim = page.getByRole("slider", { name: "Start of line 2 on timeline", exact: true });
  for (const control of [clip, trim]) {
    for (const modifier of ["altKey", "ctrlKey", "metaKey"]) {
      await control.dispatchEvent("keydown", { key: "ArrowRight", [modifier]: true, bubbles: true, cancelable: true });
      await expect(start).toHaveValue(original.start);
      await expect(end).toHaveValue(original.end);
      await expect(line.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
    }
  }
  await clip.focus(); await clip.press("ArrowRight");
  await expect(start).toHaveValue(String((Math.round(Number(original.start) * 1000) + 10) / 1000));
  await trim.focus(); await trim.press("Shift+ArrowRight");
  await expect(start).toHaveValue(String((Math.round(Number(original.start) * 1000) + 110) / 1000));
  await expect(end).toHaveValue(String((Math.round(Number(original.end) * 1000) + 10) / 1000));
  noErrors();
});
