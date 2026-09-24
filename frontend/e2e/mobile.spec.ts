import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { clearBrowserTestStudies } from "./helpers";

const browserErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page, request }) => {
  await clearBrowserTestStudies(request);
  const errors: string[] = [];
  browserErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.message));
});

test.afterEach(async ({ page }) => {
  expect(browserErrors.get(page) ?? []).toEqual([]);
});

test("mobile navigation and storage fit the viewport and remain accessible", async ({ page }) => {
  await page.goto("/");
  for (const name of ["Overview", "Data and setup", "Results"]) {
    await page.getByRole("button", { name }).click();
    const width = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(width.content, `horizontal overflow on ${name}: ${JSON.stringify(width)}`).toBeLessThanOrEqual(width.viewport);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(200);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const serious = results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""));
    const summary = serious.map((violation) =>
      `${violation.id} (${violation.nodes.length}): ${violation.nodes.slice(0, 25).map((node) => {
        const contrast = node.any.find((check) => check.id === "color-contrast")?.data as { fgColor?: string; bgColor?: string } | undefined;
        return `${node.target.join(" ")} ${contrast?.fgColor ?? ""}/${contrast?.bgColor ?? ""}`;
      }).join("; ")}${violation.nodes.length > 25 ? "; …" : ""}`,
    );
    expect(summary).toEqual([]);
  }
  await page.getByRole("button", { name: "Open on desktop" }).click();
  await expect(page.getByRole("region", { name: "Desktop study storage" })).toBeVisible();
  const width = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(width.content).toBeLessThanOrEqual(width.viewport);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(200);
  const storageA11y = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(storageA11y.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? "")).map((violation) => violation.id)).toEqual([]);
});
