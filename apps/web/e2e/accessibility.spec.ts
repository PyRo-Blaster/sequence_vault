import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, user: string) {
  await page.goto("/");
  await page.getByRole("button", { name: user }).click();
  await expect(page.getByRole("link", { name: "上传与任务" })).toBeVisible();
}

/** The pages a tester checked with axe and at phone width, after one upload so lists are
 * not empty. Projects is checked as a project administrator, where it shows the most. */
async function pages(page: Page): Promise<[string, string][]> {
  const name = `a11y-${Date.now().toString(36)}.fasta`;
  await login(page, "alice@example.test");
  await page.goto("/tasks");
  await page
    .locator('input[type="file"]')
    .setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from(">A1\nMKTAYIAKQX\n") });
  const row = page.getByRole("row", { name: new RegExp(name) }).first();
  await expect(row.getByText("待审核")).toBeVisible({ timeout: 30_000 });
  await row.getByRole("link", { name: "审核" }).click();
  await expect(page.getByText("原文证据")).toBeVisible();
  const review = new URL(page.url()).pathname;
  return [
    ["alice@example.test", "/tasks"],
    ["alice@example.test", review],
    ["alice@example.test", "/records"],
    ["admin@example.test", "/projects"],
  ];
}

async function visit(page: Page, user: string, path: string, current: { user: string }) {
  if (current.user !== user) {
    await page.getByRole("button", { name: "切换账号" }).click();
    await login(page, user);
    current.user = user;
  }
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
}

test("pages have a heading and pass axe WCAG 2 A/AA checks", async ({ page }) => {
  const current = { user: "alice@example.test" };
  for (const [user, path] of await pages(page)) {
    await visit(page, user, path, current);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    const found = results.violations.map(
      (v) =>
        `${path} ${v.id}: ` +
        v.nodes.map((n) => `${n.target.join(" ")} (${n.failureSummary ?? ""})`).join("; "),
    );
    expect(found).toEqual([]);
  }
});

test("pages fit a 375 px phone screen", async ({ page }) => {
  const current = { user: "alice@example.test" };
  const paths = await pages(page);
  await page.setViewportSize({ width: 375, height: 812 });
  for (const [user, path] of paths) {
    await visit(page, user, path, current);
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width, path).toBeLessThanOrEqual(375);
  }
});
