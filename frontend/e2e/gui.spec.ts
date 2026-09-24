import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { clearBrowserTestStudies } from "./helpers";

const modulusCsv = Buffer.from([
  "force_N,displacement_mm",
  "0,0",
  "12,0.0125",
  "24,0.025",
  "36,0.0375",
  "48,0.05",
  "60,0.0625",
  "72,0.075",
].join("\n"));
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

async function importFixture(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Data and setup" }).click();
  await page.locator('input[accept=".csv,.tsv,text/csv,text/tab-separated-values"]').setInputFiles({
    name: "modulus.csv",
    mimeType: "text/csv",
    buffer: modulusCsv,
  });
  await expect(page.locator(".loaded-file-row")).toContainText("modulus.csv");
  await page.getByLabel("Width").fill("12");
  await page.getByLabel("Thickness").fill("1");
  await page.getByLabel("Gauge length").fill("25");
  await page.getByText("Campaign, test, and print metadata").click();
  await page.getByLabel("Displacement sensor source").selectOption("extensometer");
}

async function expectNoSeriousA11yViolations(page: Page): Promise<void> {
  await page.mouse.move(0, 0);
  await page.waitForTimeout(200);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""));
  const summary = serious.map((violation) =>
    `${violation.id} (${violation.nodes.length}): ${violation.nodes.slice(0, 35).map((node) => {
      const contrast = node.any.find((check) => check.id === "color-contrast")?.data as { fgColor?: string; bgColor?: string } | undefined;
      return `${node.target.join(" ")} ${contrast?.fgColor ?? ""}/${contrast?.bgColor ?? ""}`;
    }).join("; ")}${violation.nodes.length > 35 ? "; …" : ""}`,
  );
  expect(summary).toEqual([]);
}

test("import, analyse, save, reload, and check accessibility", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Study overview" })).toBeVisible();
  await expectNoSeriousA11yViolations(page);

  await importFixture(page);
  await expect(page.getByRole("heading", { name: "Ready to analyse" })).toBeVisible();
  await expectNoSeriousA11yViolations(page);

  await page.getByRole("button", { name: "Run tensile baseline" }).click();
  await expect(page.getByRole("heading", { name: "Results explorer" })).toBeVisible();
  await expect(page.getByText("Campaign modulus summary")).toBeVisible();
  await expect(page.getByText("Mean modulus")).toBeVisible();
  const tensileRunLink = page.getByRole("link", { name: "Open tensile Run record" });
  const campaignRunLink = page.getByRole("link", { name: "Open campaign Run record" });
  await expect(tensileRunLink).toBeVisible();
  await expect(campaignRunLink).toBeVisible();
  const tensileRunPath = await tensileRunLink.getAttribute("href");
  const campaignRunPath = await campaignRunLink.getAttribute("href");
  expect(tensileRunPath).toMatch(/^\/api\/runs\/[0-9a-f-]{36}$/);
  expect(campaignRunPath).toMatch(/^\/api\/runs\/[0-9a-f-]{36}$/);
  const tensileResponse = await request.get(tensileRunPath!);
  const tensileRun = (await tensileResponse.json()).run;
  const sourceDigest = tensileRun.input_artifacts[0].sha256 as string;
  expect(await (await request.get(`/api/artifacts/${sourceDigest}`)).body()).toEqual(modulusCsv);
  expect(tensileRun.stages[0].output_artifacts).toHaveLength(2);
  const resultResponse = await request.get(`/api/artifacts/${tensileRun.result_artifact.sha256}`);
  const resultArtifact = JSON.parse((await resultResponse.body()).toString());
  const replayResponse = await request.post(`${tensileRunPath}/replay`, { data: {} });
  const replay = await replayResponse.json();
  expect(replay.result).toEqual(resultArtifact.result);
  const campaignResponse = await request.get(campaignRunPath!);
  const campaignRun = (await campaignResponse.json()).run;
  expect(campaignRun.upstream_run_ids).toEqual([tensileRun.id]);
  await expectNoSeriousA11yViolations(page);

  await page.getByRole("button", { name: "Save on desktop" }).click();
  await page.getByRole("button", { name: "Open on desktop" }).click();
  await expect(page.getByRole("region", { name: "Desktop study storage" })).toBeVisible();
  await expectNoSeriousA11yViolations(page);
  const savedStudies = (await (await request.get("/api/studies")).json()).studies as Array<{ id: string }>;
  const savedWorkspace = await (await request.get(`/api/studies/${savedStudies[0].id}`)).json();
  expect(savedWorkspace.specimens[0].test_runs[0].run_id).toBe(tensileRun.id);
  expect(savedWorkspace.campaign.reduction_run_id).toBe(campaignRun.id);
  const savedStudy = page.locator(".desktop-study-open").first();
  await expect(savedStudy).toContainText("modulus.csv");
  await savedStudy.click();
  await page.getByRole("button", { name: "Results" }).click();
  await expect(page.getByRole("heading", { name: "Results explorer" })).toBeVisible();
});

test("save conflicts preserve the draft and allow a copy", async ({ page, request }) => {
  await page.goto("/");
  await importFixture(page);
  await page.getByRole("button", { name: "Overview" }).click();
  await page.getByLabel("Study name").fill("Conflict baseline");
  await page.getByRole("button", { name: "Save on desktop" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Study saved on the desktop" })).toBeVisible();

  await page.getByRole("button", { name: "Open on desktop" }).click();
  await page.locator(".desktop-study-open").filter({ hasText: "Conflict baseline" }).click();
  await page.getByLabel("Study name").fill("Second device draft");
  const indexResponse = await request.get("/api/studies");
  const index = (await indexResponse.json()).studies as Array<{ id: string; revision: number }>;
  const savedStudy = await request.get(`/api/studies/${index[0].id}`);
  const currentWorkspace = await savedStudy.json();
  const competingWrite = await request.put(`/api/studies/${index[0].id}`, {
    headers: { "If-Match": `"${index[0].revision}"` },
    data: {
      ...currentWorkspace,
      study_name: "First device update",
      campaign: { ...currentWorkspace.campaign, name: "First device update" },
    },
  });
  expect(competingWrite.ok()).toBeTruthy();

  await page.getByRole("button", { name: "Save on desktop" }).click();
  const dialog = page.getByRole("dialog", { name: "This study changed on another device" });
  await expect(dialog).toBeVisible();
  await expectNoSeriousA11yViolations(page);
  await expect(dialog.getByRole("button", { name: "Reload and discard local draft" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Keep working on local draft" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Reload and discard local draft" })).toBeFocused();
  await dialog.getByRole("button", { name: "Save local draft as a copy" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("alert").filter({ hasText: "saved as a separate study" })).toBeVisible();
});

test("trash, retention, restore, and permanent deletion are accessible", async ({ page }) => {
  await page.goto("/");
  await importFixture(page);
  await page.getByRole("button", { name: "Overview" }).click();
  await page.getByLabel("Study name").fill("Retention check");
  await page.getByRole("button", { name: "Save on desktop" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Study saved on the desktop" })).toBeVisible();
  await page.getByRole("button", { name: "Open on desktop" }).click();
  await page.getByLabel("Keep deleted studies for").selectOption("7");
  await page.getByRole("button", { name: "Move Retention check to trash" }).click();
  await expect(page.getByText("Trash (1)")).toBeVisible();
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByText("Trash (0)")).toBeVisible();
  await page.getByRole("button", { name: "Move Retention check to trash" }).click();
  await page.getByRole("button", { name: "Delete permanently" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Delete this study permanently?" });
  await expect(dialog).toBeVisible();
  await expectNoSeriousA11yViolations(page);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: "Delete permanently" }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Delete permanently" }).click();
  await expect(page.getByText("Trash (0)")).toBeVisible();
});
