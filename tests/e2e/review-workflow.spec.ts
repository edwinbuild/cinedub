import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";

function wav(seconds = 4) {
  const rate = 16000, frames = rate * seconds;
  const buffer = Buffer.alloc(44 + frames * 2);
  buffer.write("RIFF", 0); buffer.writeUInt32LE(buffer.length - 8, 4);
  buffer.write("WAVEfmt ", 8); buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(rate, 24); buffer.writeUInt32LE(rate * 2, 28);
  buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36); buffer.writeUInt32LE(frames * 2, 40);
  for (let i = 0; i < frames; i++) buffer.writeInt16LE(Math.round(3000 * Math.sin(i * 2 * Math.PI * 220 / rate)), 44 + i * 2);
  return buffer;
}

test("upload, seek, review, preserve drafts, revise and export", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByLabel("Project name").fill("Browser verified scene");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await page.getByLabel("Import scene").setInputFiles({ name: "synthetic-scene.wav", mimeType: "audio/wav", buffer: wav() });
  await expect(page.locator("audio")).toBeVisible();
  await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
  await page.getByRole("button", { name: "Translate dialogue", exact: true }).click();
  const first = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  const malayalam = first.getByLabel("Malayalam", { exact: true });
  await expect(malayalam).toHaveValue("സിനിഡബിലേക്ക് സ്വാഗതം.");
  await first.getByRole("button", { name: "Play this line" }).click();
  await expect.poll(() => page.locator("audio").evaluate((audio: HTMLAudioElement) => audio.currentTime)).toBeGreaterThan(.1);
  await expect(first).toHaveClass(/playing/);
  await expect.poll(() => page.locator("audio").evaluate((audio: HTMLAudioElement) => audio.paused)).toBe(true);
  expect(await page.locator("audio").evaluate((audio: HTMLAudioElement) => audio.currentTime)).toBeLessThan(2.5);
  await malayalam.fill("ബ്രൗസറിൽ തിരുത്തിയ വരി");
  await page.getByRole("button", { name: "Refresh project" }).click();
  await expect(malayalam).toHaveValue("ബ്രൗസറിൽ തിരുത്തിയ വരി");
  await page.getByRole("button", { name: "approved", exact: true }).click();
  await expect(first).toBeHidden();
  await page.getByRole("button", { name: "all", exact: true }).click();
  await expect(malayalam).toHaveValue("ബ്രൗസറിൽ തിരുത്തിയ വരി");
  await first.getByRole("button", { name: "Save line" }).click();
  await expect(first.getByRole("button", { name: "Save line" })).toBeDisabled();
  await first.getByLabel("Review state for line 1").selectOption("approved");
  await first.getByRole("button", { name: "Save line" }).click();
  await expect(page.getByText("1/2 approved")).toBeVisible();
  await page.screenshot({ path: "test-results/cinedub-v02-editor.png", fullPage: true });
  await page.getByRole("button", { name: "Export Malayalam subtitles" }).click();
  const link = page.getByRole("link", { name: /demo-malayalam.srt/ });
  await expect(link).toBeVisible();
  const response = await page.request.get((await link.getAttribute("href"))!);
  expect(response.ok()).toBeTruthy();
  expect(await response.text()).toContain("ബ്രൗസറിൽ തിരുത്തിയ വരി");
  await page.getByRole("button", { name: "Retranscribe into new revision" }).click();
  await expect(page.getByRole("button", { name: "Use this timeline" })).toHaveCount(1);
  await expect(malayalam).toHaveValue("ബ്രൗസറിൽ തിരുത്തിയ വരി");
  await page.getByRole("button", { name: "Use this timeline" }).click();
  await expect(page.getByRole("article", { name: "Dialogue line 1", exact: true }).getByLabel("Malayalam", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Use this timeline" }).click();
  await expect(page.getByRole("article", { name: "Dialogue line 1", exact: true }).getByLabel("Malayalam", { exact: true })).toHaveValue("ബ്രൗസറിൽ തിരുത്തിയ വരി");
  await page.reload();
  await expect(page.getByRole("article", { name: "Dialogue line 1", exact: true }).getByLabel("Malayalam", { exact: true })).toHaveValue("ബ്രൗസറിൽ തിരുത്തിയ വരി");
  expect(errors).toEqual([]);
});

test("video proxy playback and a usable narrow screen", async ({ page }) => {
  const video = execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
    "color=c=blue:s=320x180:r=24", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
    "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags",
    "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"], { maxBuffer: 5_000_000 });
  await page.goto("/");
  await page.getByLabel("Project name").fill("Synthetic video scene");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await page.getByLabel("Import scene").setInputFiles({ name: "synthetic-video.mp4", mimeType: "video/mp4", buffer: video });
  await expect(page.locator("video")).toBeVisible();
  await expect.poll(() => page.locator("video").evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2);
  await page.locator("video").evaluate((element: HTMLVideoElement) => { element.currentTime = 1; });
  await expect.poll(() => page.locator("video").evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThanOrEqual(1);
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Translate dialogue", exact: true })).toBeVisible();
  await expect(page.getByRole("article", { name: "Dialogue line 1", exact: true }).getByLabel("English", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/cinedub-v02-mobile.png", fullPage: true });
});

test("assign voices, review candidates and render a dialogue-only preview", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByLabel("Project name").fill("Voice preview workflow");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await page.getByLabel("Import scene").setInputFiles({ name: "eight-seconds.wav", mimeType: "audio/wav", buffer: wav(8) });
  await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
  await page.getByRole("button", { name: "Translate dialogue", exact: true }).click();
  const first = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  await expect(first.getByLabel("Malayalam", { exact: true })).toHaveValue("സിനിഡബിലേക്ക് സ്വാഗതം.");
  for (let index = 1; index <= 2; index++) {
    const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
    await line.getByLabel(`Review state for line ${index}`).selectOption("approved");
    await line.getByRole("button", { name: "Save line" }).click();
    await expect(line.getByRole("button", { name: "Save line" })).toBeDisabled();
  }
  await expect(page.getByText("2/2 approved")).toBeVisible();
  await page.getByLabel("Voice for Speaker A", { exact: true }).selectOption("speaker-a");
  await expect(page.getByLabel("Voice pace for Speaker A", { exact: true })).toBeVisible();
  await page.getByLabel("Voice for Speaker B", { exact: true }).selectOption("speaker-b");
  await expect(page.getByLabel("Voice pace for Speaker B", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Generate voice candidates", exact: true }).click();
  for (let index = 1; index <= 2; index++) {
    const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
    await line.getByRole("button", { name: "Use this take", exact: true }).click();
    await expect(line.getByRole("button", { name: "Selected take" })).toBeVisible();
  }
  await page.getByRole("button", { name: "Render dialogue preview", exact: true }).click();
  const preview = page.getByRole("region", { name: "Dialogue-only preview" });
  await expect(preview.getByRole("heading", { name: "Demo-tone preview" })).toBeVisible();
  const download = preview.getByRole("link", { name: "Download dialogue preview" });
  const response = await page.request.get((await download.getAttribute("href"))!);
  expect(response.ok()).toBeTruthy();
  expect((await response.body()).subarray(0, 4).toString()).toBe("RIFF");
  await expect(page.getByText("2/2 approved")).toBeVisible();
  await page.screenshot({ path: "test-results/cinedub-voice-preview.png", fullPage: true });
});

test("consented reference, explicit demo enrollment and revocation", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept(dialog.type() === "prompt" ? "Synthetic test operator" : undefined));
  await page.goto("/");
  await page.getByLabel("Project name").fill("Consent workflow");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await page.getByLabel("Import scene").setInputFiles({ name: "scene.wav", mimeType: "audio/wav", buffer: wav(12) });
  await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
  // Separate synthetic reference avoids knowingly crossing the two fixture speakers.
  await page.getByLabel("Import scene").setInputFiles({ name: "original-reference.wav", mimeType: "audio/wav", buffer: wav(12) });
  await expect(page.getByRole("button", { name: "Transcribe scene", exact: true })).toBeEnabled();
  await page.getByText("Voice references & consent", { exact: false }).first().click();
  const form = page.getByRole("form", { name: "Create consented voice reference" });
  await form.getByLabel("Reference speaker").selectOption({ label: "Speaker A" });
  await form.getByLabel("Reference name", { exact: true }).fill("Original synthetic reference");
  await form.getByLabel("Reference source").selectOption({ label: "original-reference.wav" });
  await form.getByLabel("Voice rights holder").fill("Synthetic fixture");
  await form.getByLabel("Consent attested by").fill("Synthetic test operator");
  await form.getByLabel("Consent evidence note").fill("No actor recording; generated test tone only");
  await form.getByRole("checkbox").nth(0).check();
  await form.getByRole("checkbox").nth(1).check();
  await form.getByRole("checkbox").nth(2).check();
  await form.getByRole("button", { name: "Save consented reference" }).click();
  const card = page.getByRole("region", { name: "Voice reference Original synthetic reference" });
  await expect(card.getByText(/unprepared/)).toBeVisible();
  await card.getByRole("button", { name: "Prepare reference", exact: true }).click();
  await expect(card.getByLabel("Reference audio Original synthetic reference")).toBeVisible();
  await expect(card.getByRole("button", { name: "Register demo reference" })).toBeDisabled();
  await card.getByLabel("Reviewed reference Original synthetic reference").check();
  await card.getByRole("button", { name: "Register demo reference" }).click();
  await expect(card.getByRole("button", { name: "Use demo profile" })).toBeEnabled();
  await card.getByRole("button", { name: "Use demo profile" }).click();
  await expect(card.getByRole("button", { name: "Selected voice", exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Show consent history" }).click();
  await expect(card.getByRole("listitem")).toContainText("approved");
  await page.screenshot({ path: "test-results/cinedub-clone-consent.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/cinedub-clone-consent-mobile.png", fullPage: true });
  await card.getByRole("button", { name: "Revoke consent" }).click();
  await expect(card.getByText(/Consent: revoked/)).toBeVisible();
  await expect(card.locator("audio")).toHaveCount(0);
  await expect(card.getByText(/quarantined/)).toBeVisible();
  await card.getByRole("button", { name: "Delete provider copy" }).click();
  await expect(card.getByText(/deleted/)).toBeVisible();
  await page.reload();
  await page.getByText("Voice references & consent", { exact: false }).first().click();
  await expect(card.getByText(/Consent: revoked/)).toBeVisible();
});
