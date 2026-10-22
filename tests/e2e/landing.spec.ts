import { expect, test } from "@playwright/test";
import { API, guardPage } from "./helpers";

test("compact landing preview supports selection, pause, scroll motion and narrow layouts", async ({ page }) => {
  const noErrors = guardPage(page);
  const consoleErrors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  let creates = 0;
  page.on("request", (request) => { if (request.url() === `${API}/projects` && request.method() === "POST") creates++; });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Same story.New language.");
  const mock = page.getByLabel("Illustrative editor preview", { exact: true });
  const image = mock.getByRole("img");
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  const imageBox = (await image.boundingBox())!;
  const timelineBox = (await mock.getByRole("group", { name: "Illustrative timeline", exact: true }).boundingBox())!;
  expect(imageBox.y + imageBox.height).toBeLessThanOrEqual(timelineBox.y);
  await mock.getByRole("button", { name: "Preview line 1", exact: true }).click();
  await expect(mock.getByLabel("Example dialogue", { exact: true })).toContainText("Stay a little longer.");
  await expect(mock.getByRole("button", { name: "Preview line 1", exact: true })).toHaveAttribute("aria-pressed", "true");
  await mock.getByRole("button", { name: "Pause preview animation", exact: true }).click();
  await expect(mock.getByRole("button", { name: "Play preview animation", exact: true })).toBeVisible();
  await expect.poll(() => mock.locator('[class*="previewWave"] i').first().evaluate((element) => getComputedStyle(element).animationPlayState)).toBe("paused");
  await mock.getByRole("button", { name: "Play preview animation", exact: true }).click();
  await page.mouse.wheel(0, 380);
  await expect.poll(() => page.locator("[data-paused]").evaluate((element) => Number(element.style.getPropertyValue("--landing-scroll")))).toBeGreaterThan(0);
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 1000 });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await expect(image).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollHeight / innerHeight)).toBeLessThan(2.4);
    await page.screenshot({ path: `test-results/landing-${width}.png`, fullPage: true, style: "nextjs-portal { display: none; }" });
  }
  expect(creates).toBe(0);
  expect(consoleErrors).toEqual([]);
  noErrors();
});

test("landing stays usable with reduced motion and leads into the real editor", async ({ page }) => {
  const noErrors = guardPage(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Pause preview animation", exact: true })).toBeHidden();
  expect(await page.locator("[data-landing-page]").evaluate((element) => element.getAnimations({ subtree: true }).filter((animation) => animation.playState === "running").length)).toBe(0);
  await page.getByRole("link", { name: "Start a project", exact: true }).click();
  const name = page.getByLabel("Project name", { exact: true });
  await expect(name).toBeFocused();
  await name.fill("A new story from the landing page");
  await page.getByRole("button", { name: "Create workspace", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\//);
  const editor = page.url();
  await expect(page.getByRole("region", { name: "Source monitor", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await page.getByRole("link", { name: /A new story from the landing page/ }).click();
  await expect(page).toHaveURL(editor);
  noErrors();
});

test("API failures preserve the project name while the landing preview remains available", async ({ page }) => {
  const noErrors = guardPage(page);
  let failList = true, failCreate = true;
  await page.route(`${API}/projects`, async (route) => {
    if (route.request().method() === "GET" && failList) await route.fulfill({ status: 503, json: { detail: "Project service temporarily unavailable" } });
    else if (route.request().method() === "POST" && failCreate) await route.fulfill({ status: 503, json: { detail: "Please retry project creation" } });
    else await route.continue();
  });
  await page.goto("/");
  const alert = page.locator("#workspace").getByRole("alert");
  await expect(alert).toContainText("Project service temporarily unavailable");
  await expect(page.getByLabel("Illustrative editor preview", { exact: true })).toBeVisible();
  const name = page.getByLabel("Project name", { exact: true });
  await name.fill("Keep this project name");
  failList = false;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(alert).toBeHidden();
  await expect(name).toHaveValue("Keep this project name");
  await page.getByRole("button", { name: "Create workspace", exact: true }).click();
  await expect(alert).toContainText("Please retry project creation");
  await expect(name).toHaveValue("Keep this project name");
  await expect(page.getByRole("button", { name: "Create workspace", exact: true })).toBeEnabled();
  failCreate = false;
  await page.getByRole("button", { name: "Create workspace", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\//);
  noErrors();
});
