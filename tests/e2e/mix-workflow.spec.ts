import { expect, test } from "@playwright/test";
import { openTool } from "./helpers";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("actual separation through reviewed stereo export and hash-verifiable accepted bundle", async ({ page, request }) => {
  test.skip(process.env.CINEDUB_E2E_SEPARATOR !== "1" || !!process.env.CINEDUB_E2E_TRANSCRIBER,
    "Opt-in: installed MRX, NumPy/eSpeak NG; fixture speech/translation providers remain explicit");
  test.setTimeout(180_000);
  const directory = mkdtempSync(join(tmpdir(), "cinedub-mix-e2e-"));
  try {
    execFileSync(".venv/bin/python", ["scripts/make-separation-fixture.py", "--directory", directory]);
    const videoPath = join(directory, "original-scene.mp4");
    execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=1440x810:r=12", "-i", join(directory, "mixture.wav"),
      "-map", "0:v", "-map", "1:a", "-t", "18.644", "-c:v", "libx264", "-threads", "4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", videoPath]);
    await page.goto("/");
    await page.getByLabel("Project name").fill("Reviewed stereo export workflow");
    await page.getByRole("button", { name: "Create workspace" }).click();
    await expect(page).toHaveURL(/\/projects\//);
    const id = page.url().split("/").at(-1)!;
    const detail = async () => (await request.get(`http://127.0.0.1:8011/projects/${id}`)).json();
    await openTool(page, "Media");
    await page.getByLabel("Import scene").setInputFiles({ name: "original-scene.mp4", mimeType: "video/mp4", buffer: readFileSync(videoPath) });
    await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
    await openTool(page, "Workflow");
    await page.getByRole("button", { name: "Separate dialogue and background", exact: true }).click();
    const stems = page.getByRole("region", { name: "Separated audio review" });
    await expect(stems).toBeVisible({ timeout: 90_000 });
    await stems.getByLabel("Stem reviewer", { exact: true }).fill("Automated fixture reviewer");
    await stems.getByLabel("Stem review notes").fill("Automated integration only; not human listening acceptance");
    await stems.getByRole("checkbox").check();
    await stems.getByRole("button", { name: "Approve and use stems" }).click();
    await expect(stems.getByText("Approved · active source stems")).toBeVisible();
    await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
    await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
    await page.getByRole("button", { name: "Translate dialogue", exact: true }).click();
    await expect(page.getByLabel("Malayalam", { exact: true }).first()).toHaveValue("സിനിഡബിലേക്ക് സ്വാഗതം.");
    for (let index = 1; index <= 2; index++) {
      const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
      await line.getByLabel(`Review state for line ${index}`).selectOption("approved");
      await line.getByRole("button", { name: "Save line" }).click();
      await expect(line.getByRole("button", { name: "Save line" })).toBeDisabled();
    }
    await openTool(page, "Voices");
    await page.getByLabel("Voice for Speaker A", { exact: true }).selectOption("speaker-a");
    await expect(page.getByLabel("Voice pace for Speaker A")).toBeVisible();
    await page.getByLabel("Voice for Speaker B", { exact: true }).selectOption("speaker-b");
    await expect(page.getByLabel("Voice pace for Speaker B")).toBeVisible();
    await page.getByRole("button", { name: "Generate voice candidates", exact: true }).click();
    for (let index = 1; index <= 2; index++) {
      const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
      await line.getByRole("button", { name: "Use this take", exact: true }).click();
      await expect(line.getByRole("button", { name: "Selected take" })).toBeVisible();
    }
    await openTool(page, "Export");
    const panel = page.getByRole("region", { name: "Retained-background mix and export" });
    await panel.getByText("Mix & export · reviewed stereo delivery", { exact: true }).click();
    await panel.getByLabel("Music gain (dB)").fill("-3");
    await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
    await page.route("**/projects/*/jobs", async (route) => {
      if (route.request().method() === "POST" && route.request().postDataJSON().stage === "render_mix")
        await route.fulfill({ status: 422, json: { detail: "Synthetic mix start refused" } });
      else await route.continue();
    });
    await panel.getByRole("button", { name: "Render retained-background mix", exact: true }).click();
    await expect(page.getByText("Synthetic mix start refused", { exact: true })).toBeVisible();
    await expect(panel.getByLabel("Music gain (dB)")).toHaveValue("-3");
    await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
    await page.unroute("**/projects/*/jobs");
    await panel.getByRole("button", { name: "Render retained-background mix", exact: true }).click();
    await expect(panel.getByLabel("Retained-background video preview")).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText("1 unsaved", { exact: true })).toHaveCount(0);
    const project = await detail();
    expect(project.mixes[0].quality_json.audio_master.sample_count).toBe(project.assets[0].duration_ms * 48);
    expect(project.mixes[0].quality_json.video.width).toBe(1440); // Not the 1280px browser proxy.
    expect(project.mixes[0].status).toBe("needs_review");
    await expect(panel.getByText(/DEMO TONES/)).toBeVisible();
    await panel.getByLabel("Mix reviewer", { exact: true }).fill("Automated fixture reviewer");
    await panel.getByLabel("Mix review notes").fill("Automated acceptance path, not language or listening quality evidence");
    await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Refresh project", exact: true }).click();
    await expect(panel.getByLabel("Mix review notes")).toHaveValue("Automated acceptance path, not language or listening quality evidence");
    await expect(panel.getByRole("button", { name: "Approve mix and export bundle" })).toBeDisabled();
    await panel.getByLabel("I reviewed dialogue, background leakage, effects, levels and timing against the scene.").check();
    await page.route("**/mixes/*/review", (route) => route.fulfill({ status: 409, json: { detail: "Synthetic mix review conflict" } }));
    await panel.getByRole("button", { name: "Approve mix and export bundle" }).click();
    await expect(panel.getByRole("alert")).toContainText("Synthetic mix review conflict");
    await expect(panel.getByLabel("Mix reviewer", { exact: true })).toHaveValue("Automated fixture reviewer");
    await expect(panel.getByLabel("I reviewed dialogue, background leakage, effects, levels and timing against the scene.")).toBeChecked();
    await page.unroute("**/mixes/*/review");
    await panel.getByRole("button", { name: "Approve mix and export bundle" }).click();
    await expect(panel.getByLabel("Mix reviewer", { exact: true })).toHaveValue("");
    await expect(page.getByText("1 unsaved", { exact: true })).toHaveCount(0);
    const download = panel.getByRole("link", { name: "Download accepted export bundle", exact: true });
    await expect(download).toBeVisible({ timeout: 30_000 });
    const response = await request.get((await download.getAttribute("href"))!);
    expect(response.ok()).toBeTruthy();
    expect((await response.body()).subarray(0, 2).toString()).toBe("PK");
    const acceptanceCount = (await detail()).mixes[0].reviews.length;
    await panel.getByLabel("Mix reviewer", { exact: true }).fill("Discarded synthetic review draft");
    await panel.getByLabel("Mix review notes").fill("Not a new acceptance event");
    await Promise.all([
      page.waitForEvent("dialog").then((dialog) => dialog.accept()),
      panel.getByRole("button", { name: "Discard mix review draft", exact: true }).click(),
    ]);
    await expect(panel.getByLabel("Mix reviewer", { exact: true })).toHaveValue("");
    await expect(page.getByText("1 unsaved", { exact: true })).toHaveCount(0);
    expect((await detail()).mixes[0].reviews.length).toBe(acceptanceCount);
    await page.reload();
    await openTool(page, "Export");
    await expect(panel.getByLabel("Music gain (dB)")).toHaveValue("-3");
    await expect(panel.getByRole("link", { name: "Download accepted export bundle", exact: true })).toBeVisible();
    const player = panel.getByLabel("Retained-background video preview");
    await expect.poll(() => player.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2);
    await player.evaluate(async (element: HTMLVideoElement) => { element.muted = true; await element.play(); });
    await expect.poll(() => player.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0.2);
    await player.evaluate((element: HTMLVideoElement) => { element.pause(); element.muted = false; });
    await download.scrollIntoViewIfNeeded();
    await page.screenshot({ path: "test-results/cinedub-retained-background-mix.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: "test-results/cinedub-retained-background-mix-mobile.png", fullPage: true });
    await panel.getByLabel("Mix reviewer", { exact: true }).fill("Preserved remote-review draft");
    await panel.getByLabel("Mix review notes").fill("Keep this unsaved listening note");
    await panel.getByLabel("I reviewed dialogue, background leakage, effects, levels and timing against the scene.").check();
    const other = await page.context().newPage();
    await other.goto(page.url());
    await openTool(other, "Workflow");
    await other.getByRole("button", { name: "Retranscribe into new revision", exact: true }).click();
    await openTool(other, "Project");
    await other.getByRole("button", { name: "Use this timeline", exact: true }).click();
    await expect(other.getByRole("button", { name: "Use this timeline", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Refresh project", exact: true }).click();
    const warning = page.getByRole("alert").filter({ hasText: "Another tab changed the active timeline" });
    await expect(warning).toBeVisible();
    await expect(panel.getByLabel("Mix review notes")).toHaveValue("Keep this unsaved listening note");
    await expect(panel.getByLabel("I reviewed dialogue, background leakage, effects, levels and timing against the scene.")).toBeChecked();
    await expect(panel.getByRole("button", { name: "Approve mix and export bundle" })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await Promise.all([page.waitForEvent("dialog").then((dialog) => dialog.accept()),
      warning.getByRole("button", { name: "Discard review drafts and load current timeline", exact: true }).click()]);
    await expect(warning).toHaveCount(0);
    await expect(panel.getByLabel("Mix review notes")).toHaveCount(0);
    expect((await detail()).mixes.find((mix: { id: string }) => mix.id === project.mixes[0].id).reviews.length).toBe(acceptanceCount);
    await other.close();
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
