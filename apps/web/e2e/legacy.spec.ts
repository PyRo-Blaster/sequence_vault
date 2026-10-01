import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { DEV_STATE } from "../playwright.config";

test("legacy migration: clean rows are published, anomalies wait without fabricated evidence", async ({
  page,
}) => {
  const id = Date.now().toString(36);
  const state = JSON.parse(readFileSync(DEV_STATE, "utf8")) as {
    project_id: string;
    database_url: string;
    local_storage_dir: string;
  };
  const exportFile = join(tmpdir(), `legacy-${id}.json`);
  writeFileSync(
    exportFile,
    JSON.stringify({
      source_system: "LIMS",
      records: [
        {
          legacy_id: `L-${id}-1`,
          project: "Old",
          name: `Legacy_${id}_A`,
          sequence: "MKTAYIAKQRQISFVKSHFSRQ",
        },
        { legacy_id: `L-${id}-2`, project: "Old", name: `Legacy_${id}_B`, sequence: "MKT4AYIAKQ" },
      ],
    }),
  );
  const report = JSON.parse(
    execFileSync(
      "uv",
      [
        "run",
        "python",
        "../../tools/legacy_migration/migrate.py",
        exportFile,
        "--project",
        state.project_id,
        "--legacy-project",
        "Old",
        "--operator",
        "alice@example.test",
      ],
      {
        env: {
          ...process.env,
          SEQUENCE_VAULT_ENV: "development",
          SEQUENCE_VAULT_DATABASE_URL: state.database_url,
          SEQUENCE_VAULT_STORAGE: "local",
          SEQUENCE_VAULT_LOCAL_STORAGE_DIR: state.local_storage_dir,
          SEQUENCE_VAULT_SCANNER: "development",
        },
      },
    ).toString(),
  ) as { balanced: boolean; counts: { committed: number; pending_review: number } };
  expect(report.balanced).toBe(true);
  expect(report.counts).toMatchObject({ committed: 1, pending_review: 1 });

  await page.goto("/");
  await page.getByRole("button", { name: "alice@example.test" }).click();
  await page.getByRole("link", { name: "上传与任务" }).click();
  const row = page.getByRole("row", { name: new RegExp(`legacy-${id}\\.json`) });
  await expect(row.getByText("待审核")).toBeVisible();
  await row.getByRole("link", { name: "审核" }).click();
  await expect(page.getByText(/旧系统迁移批次/)).toBeVisible();
  await expect(page.getByText("没有可显示的证据")).toBeVisible();
  // Legacy candidates have no extraction index; find the anomaly by its name.
  const card = page
    .locator('[data-testid^="candidate-"]')
    .filter({ has: page.locator(".ant-card-head", { hasText: `Legacy_${id}_B` }) });
  await expect(card).toHaveCount(1);
  await expect(card.getByText("旧系统导入（无原文证据）")).toBeVisible();
  await expect(card.locator('li[data-rule="QC03"]')).toBeVisible();

  await page.getByRole("link", { name: "序列检索" }).click();
  await page.getByLabel("名称").fill(`Legacy_${id}`);
  await page.getByRole("button", { name: "检索" }).click();
  await expect(page.getByRole("link", { name: `Legacy_${id}_A` })).toBeVisible();
  await expect(page.getByRole("link", { name: `Legacy_${id}_B` })).toHaveCount(0);
});
