import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";

const web = process.env.CINEDUB_SMOKE_WEB;
const api = process.env.CINEDUB_SMOKE_API;
assert(web?.startsWith("http://127.0.0.1:"));
assert(api?.startsWith("http://127.0.0.1:"));
const browser = await chromium.launch({ channel: "chrome" });
try {
  const context = await browser.newContext();
  const external = [], errors = [];
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if ([web, api].includes(url.origin)) return route.continue();
    external.push(url.origin); return route.abort();
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(web);
  await page.getByLabel("Project name").fill("Clean base installation rehearsal");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  const projectId = page.url().split("/").at(-1);
  const rate = 16000, frames = rate * 4, wav = Buffer.alloc(44 + frames * 2);
  wav.write("RIFF", 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36);
  wav.writeUInt32LE(frames * 2, 40);
  for (let i = 0; i < frames; i++) wav.writeInt16LE(Math.round(2000 * Math.sin(i * 2 * Math.PI * 220 / rate)), 44 + i * 2);
  await page.getByLabel("Import scene").setInputFiles({ name: "original-synthetic.wav", mimeType: "audio/wav", buffer: wav });
  await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Translate dialogue", exact: true }).click();
  const first = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  const target = first.getByLabel("Malayalam", { exact: true });
  await expect(target).toHaveValue("സിനിഡബിലേക്ക് സ്വാഗതം.", { timeout: 30000 });
  await target.fill("പരിശോധിച്ച പരീക്ഷണ വരി");
  await first.getByRole("button", { name: "Save line", exact: true }).click();
  await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Export Malayalam subtitles", exact: true }).click();
  const download = page.getByRole("link", { name: /demo-malayalam.srt/ });
  await expect(download).toBeVisible({ timeout: 30000 });
  const url = new URL(await download.getAttribute("href"));
  assert.equal(url.origin, api);
  const response = await context.request.get(url.href);
  assert(response.ok()); assert((await response.text()).includes("പരിശോധിച്ച പരീക്ഷണ വരി"));
  const capabilities = await (await context.request.get(`${api}/capabilities`)).json();
  for (const name of ["stem_separator", "timing_aligner", "target_timing_aligner", "performance_analyzer", "dialogue_adapter", "emotion_analyzer"]) {
    assert.equal(capabilities.find((item) => item.capability === name)?.available, false, `${name} must fail closed without optional packages/weights`);
  }
  const project = await (await context.request.get(`${api}/projects/${projectId}`)).json();
  assert(project.jobs.every((job) => ["fake", "local"].includes(job.provider)));
  assert.equal(project.spent_estimate_inr, 0);
  await page.reload();
  await expect(target).toHaveValue("പരിശോധിച്ച പരീക്ഷണ വരി");
  await page.screenshot({ path: "smoke.png", fullPage: true });
  assert.deepEqual(external, []); assert.deepEqual(errors, []);
  process.stdout.write(JSON.stringify({ project_id: projectId, edited_subtitles: true, reload_persisted: true, optional_models_unavailable: true, external_browser_requests: external.length, paid_requests: 0 }) + "\n");
} finally {
  await browser.close();
}
