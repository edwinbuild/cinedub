import { expect, test } from "@playwright/test";

test("manual stock variation saves explicitly and retains failed or stale drafts without synthesis", async ({ page }) => {
  const errors: string[] = [];
  let jobRequests = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => { if (request.method() === "POST" && /\/projects\/[^/]+\/jobs$/.test(request.url())) jobRequests++; });
  // UI-only capability override. All project/profile writes use the real local API;
  // synthesis remains fake/unavailable and is never requested by this test.
  await page.route("**/capabilities", async (route) => {
    const response = await route.fetch();
    const values = await response.json();
    for (const value of values) if (value.capability === "voice_synthesizer") {
      value.selected_provider = "sarvam"; value.available = false;
      value.reason = "UI contract check only; live Sarvam not configured";
    }
    await route.fulfill({ response, json: values });
  });
  await page.goto("/");
  await page.getByLabel("Project name").fill("Stock variation UI contract");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines" })).toBeVisible();
  await page.getByLabel("Voice for Speaker A", { exact: true }).selectOption("ritu");
  const field = page.getByLabel("Generation variation for Speaker A", { exact: true });
  const save = page.getByRole("button", { name: "Save generation variation for Speaker A", exact: true });
  const discard = page.getByRole("button", { name: "Discard generation variation draft for Speaker A", exact: true });
  await expect(field).toHaveValue("0.6");
  await field.fill("0");
  await expect(save).toBeDisabled();
  await expect(page.getByRole("alert").filter({ hasText: "Enter a number" })).toBeVisible();
  await discard.click();
  const before = jobRequests;
  await field.fill("0.82");
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(field).toHaveValue("0.82");
  await save.click();
  await expect(discard).toHaveCount(0);
  await page.reload();
  await expect(field).toHaveValue("0.82");
  const id = page.url().split("/").at(-1)!;
  const detail = async () => (await page.request.get(`http://127.0.0.1:8011/projects/${id}`)).json();
  let project = await detail();
  const speaker = project.speakers.find((item: { display_name: string }) => item.display_name === "Speaker A");
  const profile = project.voice_profiles.find((item: { id: string }) => item.id === speaker.voice_profile_id);
  await field.fill("0.93");
  const remote = await page.request.post(`http://127.0.0.1:8011/speakers/${speaker.id}/stock-voice`, { data: {
    provider: "sarvam", voice_id: "ritu", variation: .31,
    expected_profile_id: profile.id, expected_profile_version: profile.version,
  } });
  expect(remote.ok()).toBe(true);
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(field).toHaveValue("0.93");
  await expect(page.getByRole("alert").filter({ hasText: "Saved voice settings changed" })).toBeVisible();
  await expect(save).toBeDisabled();
  await discard.click();
  await expect(field).toHaveValue("0.31");
  await field.fill("0.41");
  await page.route("**/speakers/*/stock-voice", (route) => route.fulfill({ status: 507, json: { detail: "Storage is full" } }));
  await save.click();
  await expect(page.getByRole("alert").filter({ hasText: "Storage is full" })).toBeVisible();
  await expect(field).toHaveValue("0.41");
  await expect(save).toBeEnabled();
  await page.unroute("**/speakers/*/stock-voice");
  await save.click();
  await expect(discard).toHaveCount(0);
  await page.reload();
  await expect(field).toHaveValue("0.41");
  expect(jobRequests).toBe(before);
  project = await detail();
  expect(project.artifacts).toHaveLength(0);
  expect(project.jobs).toHaveLength(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(field).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByLabel("Generation settings for Speaker A", { exact: true }).screenshot({ path: "test-results/cinedub-stock-variation.png" });
  expect(errors).toEqual([]);
});
