import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("real offline English ASR and manual speaker review", async ({ page }) => {
  test.skip(process.env.CINEDUB_E2E_TRANSCRIBER !== "local", "Opt-in: installed local model and eSpeak NG required");
  test.setTimeout(120_000);
  page.on("dialog", (dialog) => dialog.accept(dialog.type() === "prompt" ? "Narrator" : undefined));
  const directory = mkdtempSync(join(tmpdir(), "cinedub-spoken-e2e-"));
  try {
    const path = join(directory, "original-speech.wav");
    execFileSync("espeak-ng", ["-v", "en-us", "-s", "135", "-w", path,
      "Welcome to our cinema workshop. Please review every line before export."]);
    await page.goto("/");
    await page.getByLabel("Project name").fill("Real local inference");
    await page.getByRole("button", { name: "Create workspace" }).click();
    await expect(page).toHaveURL(/\/projects\//);
    await page.getByLabel("Import scene").setInputFiles({ name: "original-speech.wav", mimeType: "audio/wav", buffer: readFileSync(path) });
    await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
    await expect(page.getByText("Local English ASR · manual speakers", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Expected speakers")).toHaveCount(0);
    await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
    const line = page.getByRole("article", { name: "Dialogue line 1", exact: true });
    await expect(line).toBeVisible({ timeout: 90_000 });
    await expect(line.getByLabel("English", { exact: true })).toHaveValue(/welcome/i);
    const projectId = page.url().split("/").at(-1)!;
    const detail = await (await page.request.get(`http://127.0.0.1:8011/projects/${projectId}`)).json();
    const artifact = detail.artifacts.find((item: { kind: string }) => item.kind === "raw_transcript");
    const raw = await (await page.request.get(`http://127.0.0.1:8011${artifact.content_url}`)).json();
    const metadata = raw.local_metadata;
    expect(metadata.asr_profile.version).toBe("english-asr-v1");
    expect(metadata.asr_profile.transcribe_options.initial_prompt).toBeNull();
    expect(metadata.decoder_segments).toHaveLength(raw.diarized_transcript.entries.length);
    expect(metadata.decoder_segments.every((item: { temperature: number }) => metadata.asr_profile.transcribe_options.temperature.includes(item.temperature))).toBe(true);
    expect(metadata.sampling_segments).toBe(metadata.decoder_segments.filter((item: { temperature: number }) => item.temperature > 0).length);
    await expect(page.getByText("DEMO FIXTURE", { exact: true })).toHaveCount(0);
    await expect(line.getByLabel("Speaker for line 1")).toHaveValue("");
    await page.getByRole("button", { name: "Add speaker", exact: true }).click();
    await expect(line.getByLabel("Speaker for line 1").getByRole("option", { name: "Narrator" })).toHaveCount(1);
    await line.getByLabel("Speaker for line 1").selectOption({ label: "Narrator" });
    await line.getByRole("button", { name: "Save line" }).click();
    await expect(line.getByRole("button", { name: "Save line" })).toBeDisabled();
    await expect(line.getByText("Speaker unassigned; review this line")).toHaveCount(0);
    await page.reload();
    await expect(page.getByLabel("Speaker for line 1").locator("option:checked")).toHaveText("Narrator");
    await page.screenshot({ path: "test-results/cinedub-local-asr.png", fullPage: true });
    await expect(page.getByText("Some lines have no speaker assignment", { exact: true })).toHaveCount(1); // Historical job warning only.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByLabel("English", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/cinedub-local-asr-mobile.png", fullPage: true });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
