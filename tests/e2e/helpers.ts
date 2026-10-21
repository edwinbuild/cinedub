import { expect, type Page } from "@playwright/test";

export const API = "http://127.0.0.1:8011";

/** Switch the visible tool without unmounting forms or changing the dialogue draft. */
export async function openTool(page: Page, name: "Media" | "Workflow" | "Voices" | "Analysis" | "Export" | "Project") {
  const button = page.getByRole("navigation", { name: "Workspace tools" }).getByRole("button", { name, exact: true });
  if (await button.getAttribute("aria-pressed") !== "true") await button.click();
}

/** A synthetic tone WAV (never actor or licensed speech). */
export function wav(seconds = 8) {
  const rate = 16000, samples = rate * seconds, buffer = Buffer.alloc(44 + samples * 2);
  buffer.write("RIFF", 0); buffer.writeUInt32LE(36 + samples * 2, 4); buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(rate, 24); buffer.writeUInt32LE(rate * 2, 28); buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34); buffer.write("data", 36); buffer.writeUInt32LE(samples * 2, 40);
  for (let index = 0; index < samples; index++) buffer.writeInt16LE(Math.round(1800 * Math.sin(index / 9)), 44 + index * 2);
  return buffer;
}

/** Accept confirmations and fail the test on any uncaught page error. */
export function guardPage(page: Page) {
  page.on("dialog", (dialog) => dialog.accept());
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  return () => expect(errors, "uncaught page errors").toEqual([]);
}

/** Create a workspace and import a synthetic scene; returns the project ID. */
export async function sceneWorkspace(page: Page, name: string, seconds = 8) {
  await page.goto("/");
  await page.getByLabel("Project name").fill(name);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/projects\//);
  await page.getByLabel("Import scene").setInputFiles({ name: "scene.wav", mimeType: "audio/wav", buffer: wav(seconds) });
  await expect(page.getByRole("slider", { name: "Seek scene" })).toBeVisible({ timeout: 30_000 });
  return page.url().split("/").at(-1)!;
}
