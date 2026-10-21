import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("real local source alignment, acoustic review and explicit timing application", async ({ page, request }) => {
  test.skip(process.env.CINEDUB_E2E_ALIGNMENT !== "1" || process.env.CINEDUB_E2E_TRANSCRIBER !== "local",
    "Opt-in: installed local ASR and alignment models plus eSpeak NG required");
  test.setTimeout(180_000);
  page.on("dialog", (dialog) => dialog.accept());
  const directory = mkdtempSync(join(tmpdir(), "cinedub-alignment-e2e-"));
  try {
    const speech = join(directory, "speech.wav"), source = join(directory, "scene.wav");
    const text = "Hello world. This is a simple test.";
    execFileSync("espeak-ng", ["-v", "en-us", "-s", "135", "-w", speech, text]);
    execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-i", speech,
      "-af", "adelay=1000:all=1,apad=pad_dur=1", "-ar", "16000", "-ac", "1", source]);
    await page.goto("/");
    await page.getByLabel("Project name").fill("Real source alignment");
    await page.getByRole("button", { name: "Create workspace" }).click();
    await expect(page).toHaveURL(/\/projects\//);
    const projectId = page.url().split("/").at(-1)!;
    await page.getByLabel("Import scene").setInputFiles({ name: "scene.wav", mimeType: "audio/wav", buffer: readFileSync(source) });
    await expect(page.getByRole("button", { name: "Transcribe scene", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
    const line = page.getByRole("article", { name: "Dialogue line 1", exact: true });
    await expect(line).toBeVisible({ timeout: 90_000 });
    // Align the human-corrected actual script, not an invented fixture transcript.
    await line.getByLabel("English", { exact: true }).fill(text.toUpperCase());
    await line.getByRole("button", { name: "Save line" }).click();
    await expect(line.getByRole("button", { name: "Save line" })).toBeDisabled();
    const panel = page.getByLabel("Source timing and performance");
    await panel.locator("summary").click();
    await panel.getByRole("button", { name: "Align source words", exact: true }).click();
    const inspect = panel.getByRole("button", { name: "Inspect alignment report 1", exact: true });
    await expect(inspect).toBeVisible({ timeout: 90_000 });
    await inspect.click();
    const evidence = panel.getByRole("article", { name: "Alignment line 1", exact: true });
    await expect(evidence.getByText("RMS level", { exact: true })).toBeVisible();
    await expect(evidence.getByRole("group", { name: "Aligned words" })).toBeVisible();
    const detail = await (await request.get(`http://127.0.0.1:8011/projects/${projectId}`)).json();
    const artifact = detail.artifacts.find((item: { kind: string }) => item.kind === "alignment_report");
    const report = await (await request.get(`http://127.0.0.1:8011/alignment-reports/${artifact.id}`)).json();
    expect(report.model).toContain("wav2vec2-base-960h-ONNX@");
    expect(report.lines[0].words.length).toBe(7);
    expect(report.lines[0].status).toBe("aligned");
    expect(report.lines[0].performance.rms_dbfs).toBeLessThan(0);
    expect(report.metadata.peak_rss_mib).toBeLessThan(4096);
    expect(report.lines[0].words[0].start_ms).toBeGreaterThanOrEqual(800);
    await evidence.getByRole("group", { name: "Aligned words" }).getByRole("button").first().click();
    await expect.poll(async () => Number(await page.getByRole("slider", { name: "Seek scene" }).inputValue())).toBeGreaterThanOrEqual(800);
    await evidence.getByRole("button", { name: /Apply suggested timing/ }).click();
    await expect(evidence.getByText("Saved line changed; align this line again", { exact: true })).toBeVisible();
    await expect(line.getByLabel("Start (s)")).toHaveValue(String(report.lines[0].words[0].start_ms / 1000));
    await expect(line.getByLabel("Review state for line 1")).toHaveValue("needs_review");
    await page.screenshot({ path: "test-results/cinedub-alignment.png", fullPage: true });
    await page.reload();
    await expect(line.getByLabel("Start (s)")).toHaveValue(String(report.lines[0].words[0].start_ms / 1000));
    await page.setViewportSize({ width: 390, height: 844 });
    await panel.locator("summary").click();
    await panel.getByRole("button", { name: "Inspect alignment report 1", exact: true }).click();
    await expect(panel.getByRole("region", { name: "Alignment results" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/cinedub-alignment-mobile.png", fullPage: true });
    // Counterfactual script must not turn forced placement into accepted evidence.
    await line.getByLabel("English", { exact: true }).fill("The elephant carried a refrigerator through the desert.");
    await line.getByRole("button", { name: "Save line" }).click();
    await expect(line.getByRole("button", { name: "Save line" })).toBeDisabled();
    await panel.getByRole("button", { name: "Align source words", exact: true }).click();
    const weakInspect = panel.getByRole("button", { name: "Inspect alignment report 2", exact: true });
    await expect(weakInspect).toBeVisible({ timeout: 90_000 });
    await weakInspect.click();
    await expect(evidence.getByRole("button", { name: /Apply suggested timing/ })).toBeDisabled();
    await expect(evidence.getByText("Weak acoustic/text agreement; timing application disabled", { exact: true })).toBeVisible();
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
