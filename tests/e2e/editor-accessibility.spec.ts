import { expect, test } from "@playwright/test";

test("keyboard save keeps editing focus and never steals a deliberate focus move", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Project name").fill("Keyboard editing rehearsal");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  const line = (index: number) => page.getByRole("article", { name: `Dialogue line ${index}`, exact: true });
  const first = line(1), english = first.getByLabel("English", { exact: true });
  await expect(english).toBeVisible();
  await english.fill("A keyboard correction that must retain focus.");
  await english.press("Control+Enter");
  await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await expect(english).toBeFocused();
  await expect(first.getByRole("status")).toHaveText("Line saved. Review is still required.");

  let release!: () => void;
  let requested!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const captured = new Promise<void>((resolve) => { requested = resolve; });
  await page.route(/\/segments\/[^/]+$/, async (route) => {
    if (route.request().method() === "PATCH") { requested(); await pending; }
    await route.continue();
  });
  await english.fill("A second correction with a deliberately delayed response.");
  await english.press("Control+Enter");
  await captured;
  const secondEnglish = line(2).getByLabel("English", { exact: true });
  await secondEnglish.focus();
  release();
  await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await expect(english).toBeEnabled();
  await expect(secondEnglish).toBeFocused();
  await page.unroute(/\/segments\/[^/]+$/);
  await page.route(/\/segments\/[^/]+$/, async (route) => {
    if (route.request().method() === "PATCH") await route.fulfill({ status: 409, json: { detail: "Synthetic save conflict" } });
    else await route.continue();
  });
  await english.fill("Keep this draft after a save conflict.");
  await english.press("Control+Enter");
  await expect(first.getByRole("alert")).toContainText("Synthetic save conflict");
  await expect(english).toBeFocused();
  await expect(english).toHaveValue("Keep this draft after a save conflict.");
  await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeEnabled();
  await page.unroute(/\/segments\/[^/]+$/);
  await page.route(/\/segments\/[^/]+$/, async (route) => {
    if (route.request().method() === "PATCH") await route.fulfill({ status: 507, json: {
      detail: "Storage capacity exhausted. Free space or resolve the quota, then restart CineDub.",
    } });
    else await route.continue();
  });
  await english.fill("Keep this draft after a storage-capacity failure.");
  await english.press("Control+Enter");
  await expect(first.getByRole("alert")).toContainText("Storage capacity exhausted. Free space");
  await expect(english).toBeFocused();
  await expect(english).toHaveValue("Keep this draft after a storage-capacity failure.");
  await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeEnabled();
  await page.unroute(/\/segments\/[^/]+$/);
  await english.press("Control+Enter");
  await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await expect(first.getByRole("status")).toHaveText("Line saved. Review is still required.");
  await page.reload();
  await expect(english).toHaveValue("Keep this draft after a storage-capacity failure.");
});

test("composition and native select keys stay native and dialogue can be skipped to", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Project name").fill("Input method rehearsal");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.getByRole("button", { name: /^Build demo timeline/ }).click();
  const first = page.getByRole("article", { name: "Dialogue line 1", exact: true });
  const target = first.getByLabel("Malayalam", { exact: true });
  await expect(target).toBeVisible();
  await target.fill("മലയാളം തിരുത്തിയ വരി");
  let patches = 0;
  page.on("request", (request) => { if (request.method() === "PATCH" && /\/segments\//.test(request.url())) patches++; });
  for (const composition of [{ isComposing: true, keyCode: 13 }, { isComposing: false, keyCode: 229 }]) {
    await target.dispatchEvent("keydown", { key: "Enter", ctrlKey: true, bubbles: true, cancelable: true, ...composition });
    await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeEnabled();
    await expect(target).toHaveValue("മലയാളം തിരുത്തിയ വരി");
    expect(patches).toBe(0);
  }
  await target.dispatchEvent("keydown", { key: "ArrowDown", altKey: true, isComposing: true, bubbles: true });
  await expect(target).toBeFocused();
  const speaker = first.getByLabel("Speaker for line 1", { exact: true });
  await speaker.focus();
  await speaker.press("Alt+ArrowDown");
  await expect(speaker).toBeFocused();
  await speaker.press("Escape");
  await target.focus();
  await target.press("Control+Enter");
  await expect(first.getByRole("button", { name: "Save line", exact: true })).toBeDisabled();
  await page.reload();
  const skip = page.getByRole("link", { name: "Skip to dialogue editor", exact: true });
  await expect(skip).toBeAttached();
  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await skip.press("Enter");
  await expect(page.getByRole("region", { name: "Dialogue editor", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Previous line", exact: true })).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await skip.focus();
  await expect(skip).toBeInViewport();
  await page.screenshot({ path: "test-results/cinedub-keyboard-skip-mobile.png" });
});
