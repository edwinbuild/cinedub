import { expect, test } from "@playwright/test";
import { openTool } from "./helpers";
import { readFileSync } from "node:fs";

test("split merge reversible history reload and current subtitles", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByLabel("Project name").fill("Original structure correction");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await openTool(page, "Media");
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines" })).toBeVisible();
  let panel = page.getByLabel("Split merge and structural history", { exact: true });
  await panel.locator("summary").first().click();
  const original = await page.getByRole("article", { name: "Dialogue line 1", exact: true }).getByLabel("English", { exact: true }).inputValue();
  await panel.getByLabel("First part English", { exact: true }).fill("First manually divided sentence.");
  await panel.getByLabel("First part Malayalam", { exact: true }).fill("ആദ്യ വിഭജിച്ച വരി");
  await panel.getByLabel("Second part English", { exact: true }).fill("Second manually divided sentence.");
  await panel.getByLabel("Second part Malayalam", { exact: true }).fill("രണ്ടാം വിഭജിച്ച വരി");
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(panel.getByLabel("Second part English", { exact: true })).toHaveValue("Second manually divided sentence.");
  await expect(panel.getByRole("button", { name: "Split saved line", exact: true })).toBeDisabled();
  await panel.getByLabel("Replace the saved lines, clear their selected takes and require approval again", { exact: true }).check();
  await panel.getByRole("button", { name: "Split saved line", exact: true }).click();
  await expect(page.getByRole("heading", { name: "5 reviewable lines" })).toBeVisible();
  const first = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  await expect(first.getByLabel("English", { exact: true })).toHaveValue("First manually divided sentence.");
  await expect(first.getByLabel("Review state for line 1", { exact: true })).toHaveValue("needs_review");
  await expect(panel.getByRole("article", { name: "Structural edit 1", exact: true })).toContainText(original);
  await page.reload();
  panel = page.getByLabel("Split merge and structural history", { exact: true });
  await panel.locator("summary").first().click();
  await panel.getByLabel("Structure operation", { exact: true }).selectOption("merge");
  await expect(panel.getByLabel("Merged English", { exact: true })).toHaveValue("First manually divided sentence. Second manually divided sentence.");
  await panel.getByLabel("Replace the saved lines, clear their selected takes and require approval again", { exact: true }).check();
  await panel.getByRole("button", { name: "Merge saved lines", exact: true }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines" })).toBeVisible();
  await expect(panel.getByRole("article", { name: "Structural edit 2", exact: true })).toBeVisible();
  await panel.getByRole("article", { name: "Structural edit 2", exact: true }).getByRole("button", { name: "Reverse structural edit", exact: true }).click();
  await expect(page.getByRole("heading", { name: "5 reviewable lines" })).toBeVisible();
  await openTool(page, "Export");
  await page.getByRole("button", { name: "Export Malayalam subtitles", exact: true }).click();
  await openTool(page, "Project");
  const link = page.getByRole("link", { name: /demo-malayalam.srt/ });
  await expect(link).toBeVisible();
  const response = await page.request.get((await link.getAttribute("href"))!);
  expect(response.ok()).toBe(true);
  const subtitle = await response.text();
  expect(subtitle).toContain("ആദ്യ വിഭജിച്ച വരി");
  expect(subtitle).toContain("രണ്ടാം വിഭജിച്ച വരി");
  await page.reload();
  panel = page.getByLabel("Split merge and structural history", { exact: true });
  await panel.locator("summary").first().click();
  await expect(panel.getByRole("article", { name: "Structural edit 3", exact: true })).toBeVisible();
  await panel.getByRole("article", { name: "Structural edit 3", exact: true }).getByRole("button", { name: "Reverse structural edit", exact: true }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await panel.screenshot({ path: "test-results/cinedub-structure-mobile.png" });
  expect(errors).toEqual([]);
});

test("another editor replacing a line preserves an unsaved structure form", async ({ page }) => {
  let accept = true;
  page.on("dialog", (dialog) => accept ? dialog.accept() : dialog.dismiss());
  await page.goto("/");
  await page.getByLabel("Project name").fill("Structure form conflict fixture");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await openTool(page, "Media");
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines" })).toBeVisible();
  const panel = page.getByLabel("Split merge and structural history", { exact: true });
  await panel.locator("summary").first().click();
  await panel.getByLabel("First part English", { exact: true }).fill("Do not discard this structure draft.");
  const projectId = page.url().split("/").at(-1)!;
  const detail = await (await page.request.get(`http://127.0.0.1:8011/projects/${projectId}`)).json();
  const saved = detail.segments[0];
  const response = await page.request.post(`http://127.0.0.1:8011/segments/${saved.id}/split`, { data: {
    revision_id: detail.active_revision_id, expected_version: saved.version,
    split_ms: Math.round((saved.start_ms + saved.end_ms) / 2),
    first: { source_text: "Another editor's first half" },
    second: { source_text: "Another editor's second half" }, replacement_confirmed: true,
  } });
  expect(response.ok()).toBe(true);
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "5 reviewable lines" })).toBeVisible();
  await expect(panel.getByLabel("First part English", { exact: true })).toHaveValue("Do not discard this structure draft.");
  await expect(panel.getByText("Saved lines changed. This form is preserved; load current lines before applying.")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Split saved line", exact: true })).toBeDisabled();
  const options = panel.getByLabel("Line to restructure", { exact: true });
  accept = false;
  await options.selectOption({ label: "Line 1 · Another editor's first half" });
  await expect(options).toHaveValue(saved.id);
  await expect(panel.getByLabel("First part English", { exact: true })).toHaveValue("Do not discard this structure draft.");
  accept = true;
  await options.selectOption({ label: "Line 1 · Another editor's first half" });
  await expect(panel.getByLabel("First part English", { exact: true })).toHaveValue("Another editor's first half");
});

test("unsaved dialogue displaced by another editor stays recoverable", async ({ page }) => {
  let accept = true;
  page.on("dialog", (dialog) => accept ? dialog.accept() : dialog.dismiss());
  await page.goto("/");
  await page.getByLabel("Project name").fill("Displaced dialogue draft fixture");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await openTool(page, "Media");
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  await expect(page.getByRole("heading", { name: "4 reviewable lines" })).toBeVisible();
  const original = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  await original.getByLabel("English", { exact: true }).fill("Do not lose my unsaved English dialogue.");
  await original.getByLabel("Malayalam", { exact: true }).fill("നഷ്ടപ്പെടുത്തരുതാത്ത തിരുത്തൽ");
  const projectId = page.url().split("/").at(-1)!;
  const detail = await (await page.request.get(`http://127.0.0.1:8011/projects/${projectId}`)).json();
  const saved = detail.segments[0];
  const response = await page.request.post(`http://127.0.0.1:8011/segments/${saved.id}/split`, { data: {
    revision_id: detail.active_revision_id, expected_version: saved.version,
    split_ms: Math.round((saved.start_ms + saved.end_ms) / 2),
    first: { source_text: "Remote new first line" }, second: { source_text: "Remote new second line" },
    replacement_confirmed: true,
  } });
  expect(response.ok()).toBe(true);
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "5 reviewable lines" })).toBeVisible();
  const preserved = page.getByRole("article", { name: "Preserved draft for removed line 1", exact: true });
  await expect(preserved.getByLabel("English", { exact: true })).toHaveValue("Do not lose my unsaved English dialogue.");
  await expect(preserved.getByLabel("Malayalam", { exact: true })).toHaveValue("നഷ്ടപ്പെടുത്തരുതാത്ത തിരുത്തൽ");
  await expect(preserved.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(preserved.getByLabel("English", { exact: true })).toHaveValue("Do not lose my unsaved English dialogue.");
  const downloaded = page.waitForEvent("download");
  await preserved.getByRole("button", { name: "Download preserved dialogue draft", exact: true }).click();
  const file = await downloaded;
  const payload = JSON.parse(readFileSync((await file.path())!, "utf-8"));
  expect(payload.segment_id).toBe(saved.id);
  expect(payload.source_text).toBe("Do not lose my unsaved English dialogue.");
  expect(payload.translated_text).toBe("നഷ്ടപ്പെടുത്തരുതാത്ത തിരുത്തൽ");
  expect(payload.warning).toContain("not saved dialogue");
  accept = false;
  await preserved.getByRole("button", { name: "Discard preserved dialogue draft", exact: true }).click();
  await expect(preserved).toBeVisible();
  accept = true;
  await preserved.getByRole("button", { name: "Discard preserved dialogue draft", exact: true }).click();
  await expect(preserved).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Dialogue line 1", exact: true }).getByLabel("English", { exact: true })).toHaveValue("Remote new first line");
});
