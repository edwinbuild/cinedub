import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("real local emotion evidence and separate human review survive reload", async ({ page }) => {
  test.skip(process.env.CINEDUB_E2E_EMOTION !== "1", "Opt-in: installed local emotion models and eSpeak NG");
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const directory = mkdtempSync(join(tmpdir(), "cinedub-emotion-e2e-"));
  try {
    const path = join(directory, "original-speech.wav");
    execFileSync("espeak-ng", ["-v", "en-us", "-s", "135", "-w", path,
      "Please listen carefully. We should leave before the rain starts. We can return tomorrow morning."]);
    await page.goto("/");
    await page.getByLabel("Project name").fill("Original speech performance check");
    await page.getByRole("button", { name: "Create workspace" }).click();
    await expect(page).toHaveURL(/\/projects\//);
    await page.getByLabel("Import scene").setInputFiles({ name: "synthetic-original.wav", mimeType: "audio/wav", buffer: readFileSync(path) });
    await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
    await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
    const first = page.getByRole("article", { name: "Dialogue line 1", exact: true });
    await expect(first).toBeVisible();
    const original = await first.getByLabel("English", { exact: true }).inputValue();
    const panel = page.getByLabel("Speech-emotion hints", { exact: true });
    await panel.locator("summary").click();
    await panel.getByRole("button", { name: "Analyze source speech emotion", exact: true }).click();
    const inspect = panel.getByRole("button", { name: "Inspect emotion report 1", exact: true });
    await expect(inspect).toBeVisible({ timeout: 60_000 });
    await inspect.click();
    const results = panel.getByRole("region", { name: "Speech-emotion results", exact: true });
    await expect(results).toBeVisible();
    const raw = await page.request.get((await panel.getByRole("link", { name: "Download immutable emotion evidence" }).getAttribute("href"))!);
    expect(raw.ok()).toBe(true);
    const report = await raw.json();
    expect(report.model).toContain("wav2vec2-base-superb-er-ONNX@");
    expect(report.metadata.emotion_inference_count).toBeGreaterThan(0);
    expect(report.metadata.peak_rss_mib).toBeLessThan(10 * 1024);
    expect(report.lines.every((line: { review_history: unknown[] }) => line.review_history.length === 0)).toBe(true);
    const window = results.getByRole("article").first();
    await expect(window.getByRole("button", { name: "Save human correction", exact: true })).toBeDisabled();
    await window.getByLabel("Emotion reviewer", { exact: true }).fill("Synthetic fixture reviewer");
    await window.getByLabel("Human emotion label", { exact: true }).selectOption("other");
    await window.getByLabel("Performance direction", { exact: true }).fill("Synthetic speech; this test does not establish acting accuracy.");
    await window.getByLabel("I listened to the source window before reviewing its performance", { exact: true }).check();
    await window.getByRole("button", { name: "Save human correction", exact: true }).click();
    await expect(window.getByText(/Version 1: corrected · other/)).toBeVisible();
    await expect(first.getByLabel("English", { exact: true })).toHaveValue(original);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await panel.screenshot({ path: "test-results/cinedub-speech-emotion-mobile.png" });
    await page.reload();
    const reopened = page.getByLabel("Speech-emotion hints", { exact: true });
    await reopened.locator("summary").click();
    await reopened.getByRole("button", { name: "Inspect emotion report 1", exact: true }).click();
    await expect(reopened.getByText(/Version 1: corrected · other/)).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
