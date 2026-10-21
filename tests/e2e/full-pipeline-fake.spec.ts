import { expect, test } from "@playwright/test";

function wav(seconds = 8) {
  const rate = 16000, samples = rate * seconds, buffer = Buffer.alloc(44 + samples * 2);
  buffer.write("RIFF", 0); buffer.writeUInt32LE(36 + samples * 2, 4); buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(rate, 24); buffer.writeUInt32LE(rate * 2, 28); buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34); buffer.write("data", 36); buffer.writeUInt32LE(samples * 2, 40);
  for (let index = 0; index < samples; index++) buffer.writeInt16LE(Math.round(1800 * Math.sin(index / 9)), 44 + index * 2);
  return buffer;
}

test("complete DEMO workflow from upload to an accepted export bundle without models", async ({ page, request }) => {
  test.skip(["SEPARATOR", "ALIGNMENT", "PERFORMANCE", "ADAPTATION", "EMOTION", "TRANSCRIBER"]
    .some((name) => !!process.env[`CINEDUB_E2E_${name}`]), "Runs on the default DEMO providers only");
  test.setTimeout(180_000);
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByLabel("Project name").fill("DEMO provider workflow");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  const id = page.url().split("/").at(-1)!;
  const detail = async () => (await request.get(`http://127.0.0.1:8011/projects/${id}`)).json();
  await page.getByLabel("Import scene").setInputFiles({ name: "demo-scene.wav", mimeType: "audio/wav", buffer: wav() });
  await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("DEMO fixture stems · no separation")).toBeVisible();

  await page.getByRole("button", { name: "Separate dialogue and background", exact: true }).click();
  const stems = page.getByRole("region", { name: "Separated audio review" });
  await expect(stems.getByText("DEMO STEMS")).toBeVisible({ timeout: 30_000 });
  await stems.getByLabel("Stem reviewer", { exact: true }).fill("Automated DEMO reviewer");
  await stems.getByLabel("Stem review notes").fill("Fixture workflow only; no listening");
  await stems.getByRole("checkbox").check();
  await stems.getByRole("button", { name: "Approve and use stems" }).click();
  await expect(stems.getByText("Approved · active source stems")).toBeVisible();

  await page.getByLabel("Transcription audio").selectOption("dialogue_stem");
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Translate dialogue", exact: true }).click();
  await expect(page.getByLabel("Malayalam", { exact: true }).first()).toHaveValue("സിനിഡബിലേക്ക് സ്വാഗതം.");
  async function approveAll() {
    for (let index = 1; index <= 2; index++) {
      const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
      const state = line.getByLabel(`Review state for line ${index}`);
      if (await state.inputValue() === "approved") continue;
      await state.selectOption("approved");
      await line.getByRole("button", { name: "Save line" }).click();
      await expect(line.getByRole("button", { name: "Save line" })).toBeDisabled();
    }
  }
  await approveAll();

  const adaptation = page.locator("details[aria-label='Model dialogue alternatives']");
  await adaptation.locator("summary").click();
  await adaptation.getByRole("button", { name: "Generate dialogue alternatives" }).click();
  await adaptation.getByRole("button", { name: "Inspect alternatives 1" }).click({ timeout: 30_000 });
  const results = page.getByRole("region", { name: "Model dialogue results" });
  await expect(results.getByText("DEMO", { exact: true })).toBeVisible();
  const owner = results.getByRole("article", { name: "Model alternatives for line 2" });
  const concise = owner.getByRole("button", { name: "Use concise draft" });
  await owner.getByLabel("I checked the Malayalam draft I will apply against the English meaning").check();
  const replace = owner.getByLabel("Replace previously edited or approved text");
  if (await replace.count()) await replace.check();
  const issues = owner.getByLabel("I reviewed the terminology, number and script warnings");
  if (await issues.count()) await issues.check();
  await concise.click();
  await expect(page.getByLabel("Malayalam", { exact: true }).nth(1)).toHaveValue("കയറ്റുമതിക്ക് മുമ്പ് ഓരോ വരിയും");
  await approveAll();

  await page.getByLabel("Voice for Speaker A", { exact: true }).selectOption("speaker-a");
  await expect(page.getByLabel("Voice pace for Speaker A")).toBeVisible();
  await page.getByLabel("Voice for Speaker B", { exact: true }).selectOption("speaker-b");
  await expect(page.getByLabel("Voice pace for Speaker B")).toBeVisible();
  await page.getByRole("button", { name: "Generate voice candidates", exact: true }).click();
  for (let index = 1; index <= 2; index++) {
    const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
    await line.getByRole("button", { name: "Use this take", exact: true }).click({ timeout: 30_000 });
    await expect(line.getByRole("button", { name: "Selected take" })).toBeVisible();
  }

  const alignment = page.locator("details[aria-label='Source timing and performance']");
  await alignment.locator("summary").click();
  await alignment.getByRole("button", { name: "Align source words" }).click();
  await alignment.getByRole("button", { name: "Inspect alignment report 1" }).click({ timeout: 30_000 });
  await expect(alignment.getByText("Placeholder word slots spread evenly across each line", { exact: false })).toBeVisible();

  const performance = page.locator("details[aria-label='Source versus voice performance']");
  await performance.locator("summary").click();
  await performance.getByRole("button", { name: "Analyze take performance" }).click();
  await expect(performance.getByRole("button", { name: "Inspect comparison 1" })).toBeVisible({ timeout: 30_000 });

  const emotion = page.locator("details[aria-label='Speech-emotion hints']");
  await emotion.locator("summary").click();
  await emotion.getByRole("button", { name: "Analyze source speech emotion" }).click();
  await emotion.getByRole("button", { name: "Inspect emotion report 1" }).click({ timeout: 30_000 });
  const emotionResults = page.getByRole("region", { name: "Speech-emotion results" });
  await expect(emotionResults.getByText("DEMO", { exact: true })).toBeVisible();
  await expect(emotionResults.getByText(/not analyzed/).first()).toBeVisible();

  const mix = page.getByRole("region", { name: "Retained-background mix and export" });
  await mix.getByText("Mix & export · reviewed stereo delivery", { exact: true }).click();
  await mix.getByRole("button", { name: "Render retained-background mix", exact: true }).click();
  await expect(mix.getByText(/DEMO TONES/)).toBeVisible({ timeout: 60_000 });
  await mix.getByLabel("Mix reviewer", { exact: true }).fill("Automated DEMO reviewer");
  await mix.getByLabel("Mix review notes").fill("Fixture acceptance path only");
  await mix.getByLabel("I reviewed dialogue, background leakage, effects, levels and timing against the scene.").check();
  await mix.getByRole("button", { name: "Approve mix and export bundle" }).click();
  const download = mix.getByRole("link", { name: "Download accepted export bundle", exact: true });
  await expect(download).toBeVisible({ timeout: 30_000 });
  const bundle = await request.get((await download.getAttribute("href"))!);
  expect((await bundle.body()).subarray(0, 2).toString()).toBe("PK");

  const project = await detail();
  const fakeStages = new Set(project.jobs.filter((job: { provider: string }) => job.provider === "fake").map((job: { stage: string }) => job.stage));
  for (const stage of ["separate", "transcribe", "translate", "adapt_dialogue", "synthesize", "align", "analyze_takes", "analyze_emotion"])
    expect(fakeStages.has(stage), stage).toBe(true);
  expect(project.jobs.every((job: { status: string }) => job.status === "completed")).toBe(true);
  await page.screenshot({ path: "test-results/cinedub-demo-workflow.png", fullPage: true });
});
