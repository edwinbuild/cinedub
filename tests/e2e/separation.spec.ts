import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("actual offline separation, explicit review and dialogue-stem recognition", async ({ page, request }) => {
  test.skip(process.env.CINEDUB_E2E_SEPARATOR !== "1" || process.env.CINEDUB_E2E_TRANSCRIBER !== "local",
    "Opt-in: installed MRX/local ASR models, NumPy and eSpeak NG required");
  test.setTimeout(180_000);
  const directory = mkdtempSync(join(tmpdir(), "cinedub-separation-e2e-"));
  try {
    execFileSync(".venv/bin/python", ["scripts/make-separation-fixture.py", "--directory", directory]);
    await page.goto("/");
    await page.getByLabel("Project name").fill("Actual cinematic separator");
    await page.getByRole("button", { name: "Create workspace" }).click();
    await expect(page).toHaveURL(/\/projects\//);
    const projectId = page.url().split("/").at(-1)!;
    const detail = async () => (await request.get(`http://127.0.0.1:8011/projects/${projectId}`)).json();
    await page.getByLabel("Import scene").setInputFiles({ name: "original-mixture.wav", mimeType: "audio/wav", buffer: readFileSync(join(directory, "mixture.wav")) });
    await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
    const separate = page.getByRole("button", { name: "Separate dialogue and background", exact: true });
    await expect(separate).toBeEnabled();
    await separate.click();
    const panel = page.getByRole("region", { name: "Separated audio review" });
    await expect(panel).toBeVisible({ timeout: 100_000 });
    for (const stem of ["dialogue", "music", "effects"]) {
      const player = panel.getByLabel(`${stem} stem preview`);
      await player.evaluate((element: HTMLAudioElement) => element.load());
      await expect.poll(() => player.evaluate((element: HTMLAudioElement) => element.readyState)).toBeGreaterThanOrEqual(1);
      expect(await player.evaluate((element: HTMLAudioElement) => element.duration)).toBeCloseTo(18.644, 2);
    }
    let project = await detail();
    expect(project.assets[0].active_stem_set_id).toBeNull();
    expect(project.stem_sets[0].metadata_json.device).toBe("cpu");
    expect(project.stem_sets[0].metadata_json.peak_rss_mib).toBeLessThan(10 * 1024);
    expect(project.stem_sets[0].metadata_json.source_sha256).toMatch(/^[a-f0-9]{64}$/);
    const approvedId = project.stem_sets[0].id;
    await panel.getByLabel("Stem reviewer", { exact: true }).fill("Automated fixture reviewer");
    await panel.getByLabel("Stem review notes").fill("Workflow test only: checkbox is not a human listening or cinema-quality evaluation.");
    await expect(panel.getByRole("button", { name: "Approve and use stems" })).toBeDisabled();
    await panel.getByLabel("I listened to all three stems and checked leakage, effects and stereo.").check();
    await panel.getByRole("button", { name: "Approve and use stems" }).click();
    await expect(panel.getByText("Approved · active source stems", { exact: true })).toBeVisible();
    await page.getByLabel("Transcription audio").selectOption("dialogue_stem");
    await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
    await expect(page.getByRole("article", { name: "Dialogue line 1", exact: true })).toBeVisible({ timeout: 90_000 });
    await expect(page.getByLabel("English", { exact: true }).first()).toHaveValue(/welcome/i);
    project = await detail();
    const raw = project.artifacts.find((artifact: { kind: string }) => artifact.kind === "raw_transcript");
    expect(raw.metadata_json.stem_set_id).toBe(approvedId);
    const recognition = project.artifacts.find((artifact: { id: string }) => artifact.id === raw.metadata_json.recognition_artifact_id);
    expect(recognition.kind).toBe("stem_recognition_audio");
    await separate.click();
    await expect(panel.getByRole("article")).toHaveCount(2, { timeout: 100_000 });
    project = await detail();
    expect(project.assets[0].active_stem_set_id).toBe(approvedId);
    expect(project.stem_sets.filter((stems: { status: string }) => stems.status === "needs_review")).toHaveLength(1);
    const active = panel.getByRole("article", { name: `Stem set ${approvedId}`, exact: true });
    await active.getByRole("button", { name: "Reject stems" }).click();
    await expect(page.getByLabel("Transcription audio")).toHaveValue("original");
    await page.screenshot({ path: "test-results/cinedub-reviewed-stems.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/cinedub-reviewed-stems-mobile.png", fullPage: true });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
