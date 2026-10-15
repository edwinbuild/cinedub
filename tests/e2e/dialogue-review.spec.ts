import { expect, test } from "@playwright/test";

test("save editorial direction, preserve drafts, review glossary and flag stale context", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    // Next's existing empty favicon route is unrelated; retain all application errors.
    if (message.type() === "error" && message.location().url !== "http://127.0.0.1:3011/favicon.ico") errors.push(message.text());
  });
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByLabel("Project name").fill("Editorial brief workflow");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines" })).toBeVisible();
  const panel = page.getByLabel("Dialogue brief and editorial checks", { exact: true });
  await panel.locator("summary").first().click();
  await panel.getByLabel("Scene summary", { exact: true }).fill("An editor explains a new dubbing workspace.");
  await panel.getByLabel("Adaptation notes", { exact: true }).fill("Keep the terminology consistent; never invent plot.");
  await panel.getByLabel("Character intent for Speaker A", { exact: true }).fill("Reassure a skeptical colleague");
  await panel.getByLabel("Delivery notes for Speaker A", { exact: true }).fill("Calm and direct; human direction only");
  await panel.getByRole("button", { name: "Add glossary term", exact: true }).click();
  await panel.getByLabel("Source term 1", { exact: true }).fill("CineDub");
  await panel.getByLabel("Preferred Malayalam 1", { exact: true }).fill("സിനിമാ ഡബ്");
  await panel.getByLabel("Term note 1", { exact: true }).fill("Product name, reviewed preference");
  await expect(panel.getByRole("button", { name: "Check saved dialogue", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(panel.getByLabel("Scene summary", { exact: true })).toHaveValue("An editor explains a new dubbing workspace.");
  await panel.getByRole("button", { name: "Save dialogue brief", exact: true }).click();
  await expect(panel.locator("summary").first()).toHaveText("Dialogue brief & editorial checks · version 1");
  const first = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  const originalText = await first.getByLabel("Malayalam", { exact: true }).inputValue();
  await panel.getByRole("button", { name: "Check saved dialogue", exact: true }).click();
  await panel.getByRole("button", { name: "Inspect editorial checks 1", exact: true }).click();
  const results = panel.getByRole("region", { name: "Editorial review results", exact: true });
  await expect(results).toBeVisible();
  await expect(results.getByText(/Preferred text “സിനിമാ ഡബ്” for “CineDub”/)).toBeVisible();
  await expect(results.getByText(/Intent: Reassure a skeptical colleague/).first()).toBeVisible();
  await expect(results.getByText(/spoken duration is not estimated/).first()).toBeVisible();
  await expect(first.getByLabel("Malayalam", { exact: true })).toHaveValue(originalText);
  const download = await page.request.get((await panel.getByRole("link", { name: "Download editorial review JSON", exact: true }).getAttribute("href"))!);
  expect(download.ok()).toBe(true);
  const report = await download.json();
  expect(report.context_applied_by_model).toBe(false);
  expect(report.brief.version).toBe(1);
  expect(report.lines).toHaveLength(4);
  const reviewedLine = results.getByRole("article", { name: "Editorial checks for line 1", exact: true });
  await reviewedLine.getByText("Surrounding dialogue & preferred terms", { exact: true }).click();
  await expect(reviewedLine.getByText("Before: Start of scene", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/cinedub-dialogue-brief-mobile.png", fullPage: true });
  // A second tab's save must not overwrite this tab's in-progress brief.
  await panel.getByLabel("Scene summary", { exact: true }).fill("This tab's unsaved brief");
  const projectId = page.url().split("/").at(-1)!;
  const detail = await (await page.request.get(`http://127.0.0.1:8011/projects/${projectId}`)).json();
  const saved = await page.request.post(`http://127.0.0.1:8011/projects/${projectId}/revisions/${detail.active_revision_id}/dialogue-brief`, {
    data: { expected_version: 1, content: { ...detail.dialogue_brief.content, scene_summary: "Another tab's saved brief" } },
  });
  expect(saved.ok()).toBe(true);
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(panel.getByText(/Another editor saved a newer brief/)).toBeVisible();
  await expect(panel.getByLabel("Scene summary", { exact: true })).toHaveValue("This tab's unsaved brief");
  await expect(panel.getByRole("button", { name: "Save dialogue brief", exact: true })).toBeDisabled();
  await expect(results.getByText("Saved brief or dialogue context changed; review again", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "Load latest saved brief", exact: true }).click();
  await expect(panel.getByLabel("Scene summary", { exact: true })).toHaveValue("Another tab's saved brief");
  await page.reload();
  await page.getByLabel("Dialogue brief and editorial checks", { exact: true }).locator("summary").first().click();
  await expect(page.getByLabel("Scene summary", { exact: true })).toHaveValue("Another tab's saved brief");
  await page.getByRole("button", { name: "Inspect editorial checks 1", exact: true }).click();
  await expect(page.getByText("Saved dialogue brief changed; review again", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
