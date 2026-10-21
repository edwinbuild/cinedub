import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("real acoustic comparison and experimental Malayalam words preserve take choices", async ({ page, request }) => {
  test.skip(process.env.CINEDUB_E2E_PERFORMANCE !== "1" || !process.env.CINEDUB_E2E_STATE_ROOT,
    "Opt-in: explicit isolated E2E state, NumPy/Malayalam ONNX model and eSpeak NG required");
  test.setTimeout(180_000);
  const directory = mkdtempSync(join(tmpdir(), "cinedub-performance-speech-"));
  page.on("dialog", (dialog) => dialog.accept());
  try {
    const raw = join(directory, "source.wav"), source = join(directory, "source-12s.wav");
    execFileSync("espeak-ng", ["-v", "en-us", "-s", "135", "-w", raw, "Hello world. This is a simple test."]);
    execFileSync("ffmpeg", ["-v", "error", "-i", raw, "-af", "apad=whole_dur=12", "-t", "12", "-ar", "16000", "-ac", "1", source]);
    await page.goto("/");
    await page.getByLabel("Project name").fill("Performance evaluation fixture");
    await page.getByRole("button", { name: "Create workspace" }).click();
    await expect(page).toHaveURL(/\/projects\//);
    const projectId = page.url().split("/").at(-1)!;
    await page.getByLabel("Import scene").setInputFiles({ name: "synthetic-source.wav", mimeType: "audio/wav", buffer: readFileSync(source) });
    await expect(page.getByRole("button", { name: "Transcribe scene", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
    await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
    const candidateId = execFileSync(".venv/bin/python", ["scripts/seed-performance-fixture.py",
      "--state-root", process.env.CINEDUB_E2E_STATE_ROOT!, "--project-id", projectId],
      { env: { ...process.env, PYTHONPATH: "apps/api" } }).toString().trim();
    const detail = async () => (await request.get(`http://127.0.0.1:8011/projects/${projectId}`)).json();
    const before = await detail();
    await page.reload();
    await expect(page.getByText("Synthetic speech fixture 1", { exact: true })).toBeVisible();
    const panel = page.getByLabel("Source versus voice performance");
    await panel.locator("summary").click();
    await panel.getByLabel("Take to analyze", { exact: true }).selectOption(candidateId);
    await panel.getByLabel("Include experimental Malayalam word suggestions").check();
    await panel.getByRole("button", { name: "Analyze take performance", exact: true }).click();
    const inspect = panel.getByRole("button", { name: "Inspect comparison 1", exact: true });
    await expect(inspect).toBeVisible({ timeout: 90_000 });
    await inspect.click();
    await expect(panel.getByRole("region", { name: "Take performance results" })).toBeVisible();
    await expect(panel.getByText(/SYNTHETIC SPEECH FIXTURE/)).toBeVisible();
    await expect(panel.getByRole("img", { name: /Pitch estimate: source in cyan/ })).toBeVisible();
    const after = await detail();
    expect(after.segments).toEqual(before.segments); // No automatic selection/timing/approval edits.
    const artifact = after.artifacts.find((item: { kind: string }) => item.kind === "take_performance_report");
    const response = await request.get(`http://127.0.0.1:8011/take-analysis-reports/${artifact.id}`);
    expect(response.ok()).toBe(true);
    const report = await response.json();
    expect(report.metadata.target_inference_count).toBe(1);
    expect(report.lines[0].target_alignment.model).toContain("trysem/wav2vec2-malayalam-onnx-int8@");
    expect(report.lines[0].target_alignment.words).toHaveLength(6);
    expect(report.lines[0].target_alignment.status).toBe("needs_review");
    expect(report.lines[0].source_performance.rms_dbfs).toBeLessThan(0);
    expect(report.lines[0].target_performance.rms_dbfs).toBeLessThan(0);
    const words = panel.getByRole("group", { name: "Malayalam word suggestions" });
    await words.getByRole("button").first().click();
    await expect.poll(() => panel.getByLabel("Analyzed voice take").evaluate((audio: HTMLAudioElement) => audio.currentTime)).toBeGreaterThanOrEqual(.4);
    await page.getByRole("article", { name: "Dialogue line 1", exact: true }).getByRole("button", { name: "Use this take", exact: true }).click();
    const currentReport = await (await request.get(`http://127.0.0.1:8011/take-analysis-reports/${artifact.id}`)).json();
    expect(currentReport.lines[0].stale_reason).toBeNull();
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/cinedub-take-performance-mobile.png", fullPage: true });
    await page.reload();
    await panel.locator("summary").click();
    await panel.getByRole("button", { name: "Inspect comparison 1", exact: true }).click();
    await expect(words.getByRole("button")).toHaveCount(6);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
