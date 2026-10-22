import { expect, test } from "@playwright/test";
import { openTool } from "./helpers";
import { execFileSync } from "node:child_process";

test("private reference drafts survive refresh and navigation refusal without granting consent", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Project name").fill("Private consent draft rehearsal");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  const scene = page.url();
  const buffer = execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=12", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"]);
  await openTool(page, "Media");
  await page.getByLabel("Import scene").setInputFiles({ name: "synthetic-reference.wav", mimeType: "audio/wav", buffer });
  await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible();
  await openTool(page, "Workflow");
  await page.getByRole("button", { name: "Transcribe scene", exact: true }).click();
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
  await openTool(page, "Voices");
  await page.getByText("Voice references & consent", { exact: false }).first().click();
  const form = page.getByRole("form", { name: "Create consented voice reference" });
  const name = form.getByLabel("Reference name", { exact: true });
  await name.fill("Temporary value");
  await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
  await name.fill("");
  await expect(page.getByText("1 unsaved", { exact: true })).toHaveCount(0);
  await name.fill("Unsaved synthetic reference");
  await form.getByLabel("Voice rights holder").fill("Synthetic private draft owner");
  await form.getByLabel("Consent evidence note").fill("Private draft only; not permission to upload.");
  await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
  await expect(page.getByText(/Unsaved reference draft\. Nothing has been saved/)).toBeVisible();
  await Promise.all([
    page.waitForEvent("dialog").then((dialog) => dialog.dismiss()),
    page.getByRole("link", { name: "Projects", exact: true }).click(),
  ]);
  await expect(page).toHaveURL(scene);
  await page.getByRole("button", { name: "Refresh project", exact: true }).click();
  await expect(name).toHaveValue("Unsaved synthetic reference");
  await Promise.all([
    page.waitForEvent("dialog").then(async (dialog) => {
      expect(dialog.type()).toBe("beforeunload"); await dialog.dismiss();
    }),
    page.reload({ timeout: 5000 }).catch(() => undefined),
  ]);
  await expect(name).toHaveValue("Unsaved synthetic reference");
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain("Synthetic private draft owner");

  // This form is project-scoped, unlike revision-scoped dialogue and briefs.
  await openTool(page, "Workflow");
  await page.getByRole("button", { name: "Retranscribe into new revision", exact: true }).click();
  await openTool(page, "Project");
  const activate = page.getByRole("button", { name: "Use this timeline", exact: true });
  await expect(activate).toBeEnabled();
  await activate.click();
  await openTool(page, "Voices");
  await expect(name).toHaveValue("Unsaved synthetic reference");
  await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
  await Promise.all([
    page.waitForEvent("dialog").then((dialog) => dialog.dismiss()),
    form.getByRole("button", { name: "Discard reference draft" }).click(),
  ]);
  await expect(name).toHaveValue("Unsaved synthetic reference");
  await Promise.all([
    page.waitForEvent("dialog").then((dialog) => dialog.accept()),
    form.getByRole("button", { name: "Discard reference draft" }).click(),
  ]);
  await expect(name).toHaveValue("");
  await expect(page.getByText("1 unsaved", { exact: true })).toHaveCount(0);

  // The transcribed scene contains multiple fixture speakers. Use a separate
  // unassigned synthetic recording, just as the consent workflow requires.
  await openTool(page, "Media");
  await page.getByLabel("Import scene").setInputFiles({ name: "clean-synthetic-reference.wav", mimeType: "audio/wav", buffer });
  await openTool(page, "Voices");
  await expect(form.getByLabel("Reference source").getByRole("option", { name: "clean-synthetic-reference.wav", exact: true })).toHaveCount(1);
  await form.getByLabel("Reference speaker").selectOption({ label: "Speaker A" });
  await name.fill("Saved original synthetic reference");
  await form.getByLabel("Reference source").selectOption({ label: "clean-synthetic-reference.wav" });
  await form.getByLabel("Voice rights holder").fill("Synthetic fixture");
  await form.getByLabel("Consent attested by").fill("Synthetic operator");
  await form.getByLabel("Consent evidence note").fill("Synthetic fixture consent rehearsal only");
  for (const checkbox of await form.getByRole("checkbox").all()) await checkbox.check();
  await page.route("**/projects/*/voice-profiles", async (route) => {
    await route.fulfill({ status: 409, json: { detail: "Synthetic consent save conflict" } });
  });
  await form.getByRole("button", { name: "Save consented reference", exact: true }).click();
  await expect(form.locator("..").getByRole("alert")).toContainText("Synthetic consent save conflict");
  await expect(name).toHaveValue("Saved original synthetic reference");
  await expect(page.getByText("1 unsaved", { exact: true })).toBeVisible();
  await page.unroute("**/projects/*/voice-profiles");
  await form.getByRole("button", { name: "Save consented reference", exact: true }).click();
  await expect(page.getByRole("region", { name: "Voice reference Saved original synthetic reference", exact: true })).toBeVisible();
  await expect(name).toHaveValue("");
  await expect(page.getByText("1 unsaved", { exact: true })).toHaveCount(0);
  await expect(form.getByRole("checkbox").first()).not.toBeChecked();
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
});
