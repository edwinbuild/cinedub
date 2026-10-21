import { expect, test } from "@playwright/test";
import { API, guardPage, openTool, sceneWorkspace } from "./helpers";

test("DEMO workflow runs as one pipeline and waits at every review gate", async ({ page, request }) => {
  test.skip(["SEPARATOR", "ALIGNMENT", "PERFORMANCE", "ADAPTATION", "EMOTION", "TRANSCRIBER"]
    .some((name) => !!process.env[`CINEDUB_E2E_${name}`]), "Runs on the default DEMO providers only");
  test.setTimeout(180_000);
  const noErrors = guardPage(page);
  const id = await sceneWorkspace(page, "Pipeline workflow");
  await openTool(page, "Workflow");
  const workflow = page.getByRole("region", { name: "Dubbing workflow" });
  await expect(workflow.getByText("DEMO", { exact: true })).toBeVisible();
  await workflow.getByLabel("Separate dialogue first").check();
  await workflow.getByRole("button", { name: /^Run dubbing workflow/ }).click();
  const status = workflow.getByRole("status");
  const step = (name: string) => workflow.getByRole("listitem").filter({ hasText: name });
  const proceed = async () => { await openTool(page, "Workflow"); await workflow.getByRole("button", { name: "Continue after review" }).click(); };

  await expect(step("Review: approve stems")).toHaveAttribute("aria-current", "step", { timeout: 60_000 });
  await proceed(); // Refused: nothing has been reviewed yet.
  await expect(workflow.getByRole("alert")).toContainText("approve them");
  const stems = page.getByRole("region", { name: "Separated audio review" });
  await stems.getByLabel("Stem reviewer", { exact: true }).fill("Automated DEMO reviewer");
  await stems.getByRole("checkbox").check();
  await stems.getByRole("button", { name: "Approve and use stems" }).click();
  await expect(stems.getByText("Approved · active source stems")).toBeVisible();
  await proceed();

  await expect(step("Review: speakers & transcript")).toHaveAttribute("aria-current", "step", { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "2 reviewable lines" })).toBeVisible();
  await proceed();

  await expect(step("Review: approve every line")).toHaveAttribute("aria-current", "step", { timeout: 60_000 });
  await expect(status).toContainText("2 lines are not approved");
  const queue = page.locator("details[aria-label='Needs attention']");
  await queue.locator("summary").click();
  await expect(queue.getByText("Line 1: not approved")).toBeVisible();
  for (let index = 1; index <= 2; index++) {
    const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
    await line.getByLabel(`Review state for line ${index}`).selectOption("approved");
    await line.getByRole("button", { name: "Save line" }).click();
    await expect(line.getByRole("button", { name: "Save line" })).toBeDisabled();
  }
  await proceed();

  await expect(step("Review: assign voices")).toHaveAttribute("aria-current", "step", { timeout: 30_000 });
  await openTool(page, "Voices");
  await page.getByLabel("Voice for Speaker A", { exact: true }).selectOption("speaker-a");
  await expect(page.getByLabel("Voice pace for Speaker A")).toBeVisible();
  await page.getByLabel("Voice for Speaker B", { exact: true }).selectOption("speaker-b");
  await expect(page.getByLabel("Voice pace for Speaker B")).toBeVisible();
  await proceed();

  await expect(step("Review: select takes")).toHaveAttribute("aria-current", "step", { timeout: 60_000 });
  for (let index = 1; index <= 2; index++) {
    const line = page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
    await line.getByRole("button", { name: "Use this take", exact: true }).click();
    await expect(line.getByRole("button", { name: "Selected take" })).toBeVisible();
  }
  await expect(page.getByRole("region", { name: "Scene timeline" }).locator(".timelineTake.ready")).toHaveCount(2);
  await proceed();

  await expect(step("Review: accept mix & export")).toHaveAttribute("aria-current", "step", { timeout: 90_000 });
  await openTool(page, "Export");
  const mix = page.getByRole("region", { name: "Retained-background mix and export" });
  const mixDetails = mix.locator("details").first();
  if (!(await mixDetails.evaluate((element) => (element as HTMLDetailsElement).open)))
    await mix.getByText("Mix & export · reviewed stereo delivery", { exact: true }).click();
  await mix.getByLabel("Mix reviewer", { exact: true }).fill("Automated DEMO reviewer");
  await mix.getByLabel("Mix review notes").fill("Fixture acceptance path only");
  await mix.getByLabel("I reviewed dialogue, background leakage, effects, levels and timing against the scene.").check();
  await mix.getByRole("button", { name: "Approve mix and export bundle" }).click();
  await expect(mix.getByRole("link", { name: "Download accepted export bundle", exact: true })).toBeVisible({ timeout: 30_000 });
  await proceed();
  await expect(status).toHaveText("Workflow complete: the accepted export bundle is ready.", { timeout: 30_000 });

  const project = await (await request.get(`${API}/projects/${id}`)).json();
  expect(project.latest_pipeline.status).toBe("completed");
  expect(project.status).toBe("ready");
  const bundle = project.mixes[0].reviews[0].bundle_artifact_id;
  const lineage = await (await request.get(`${API}/artifacts/${bundle}/lineage`)).json();
  expect(lineage.sources.map((source: { id: string }) => source.id)).toEqual([project.assets[0].id]);
  await page.screenshot({ path: "test-results/cinedub-pipeline.png", fullPage: true });
  noErrors();
});
