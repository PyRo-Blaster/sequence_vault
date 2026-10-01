import { expect, test, type Page } from "@playwright/test";

const unique = () => Date.now().toString(36);

async function login(page: Page, user: string) {
  await page.goto("/");
  await page.getByRole("button", { name: user }).click();
  await expect(page.getByRole("link", { name: "上传与任务" })).toBeVisible();
}

async function upload(page: Page, name: string, content: string) {
  await page.goto("/tasks");
  await page
    .locator('input[type="file"]')
    .setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from(content) });
  await expect(page.getByText(`${name}：已提交处理`)).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(name) }).first();
  await expect(row.getByText("待审核")).toBeVisible({ timeout: 30_000 });
  await row.getByRole("link", { name: "审核" }).click();
  await expect(page.getByText("原文证据")).toBeVisible();
}

test("T02: upload, review, resolve, approve, commit, search and export", async ({ page }) => {
  const id = unique();
  await login(page, "alice@example.test");
  await upload(
    page,
    `batch-${id}.fasta`,
    `>Heavy_${id}\nmktayiakqr\nqisfvkshfs\n>Light_${id}\nDIQMTQSPXS\n`,
  );

  const heavy = page.getByTestId("candidate-0");
  const light = page.getByTestId("candidate-1");
  await expect(heavy.locator(".ant-card-head")).toContainText(`Heavy_${id}`);
  await expect(heavy.getByLabel("序列")).toContainText("MKTAYIAKQR");

  // Locate issue evidence in the source panel.
  await light.locator('li[data-rule="QC04"]').getByRole("button", { name: "定位" }).click();
  await expect(page.locator(".sv-mark-issue").first()).toHaveText("X");

  // Extended residue X must be confirmed before approval.
  await expect(light.getByRole("button", { name: "批准" })).toBeDisabled();
  await light.getByLabel("处理 QC04").click();
  await page.getByTitle("已确认残基含义").click();
  await expect(light.locator(".ant-tag-success")).toHaveText("已确认残基含义");

  await page.getByRole("button", { name: /批量批准/ }).click();
  await expect(page.getByText("已批准 2 条")).toBeVisible();
  await page.getByRole("button", { name: "全选已批准" }).click();
  await page.getByRole("button", { name: "提交入库（已选 2）" }).click();
  const dialog = page.getByRole("dialog", { name: "提交入库" });
  await expect(dialog.getByText("新记录")).toBeVisible();
  await dialog.getByRole("button", { name: "确认提交" }).click();
  await expect(dialog.getByText("全部 2 条已入库")).toBeVisible();
  await dialog.getByRole("button", { name: "完成" }).click();

  await page.getByRole("link", { name: "序列检索" }).click();
  await page.getByLabel("精确序列").fill("mktay iakqr QISFVKSHFS");
  await page.getByRole("button", { name: "检索" }).click();
  await page.getByRole("link", { name: `Heavy_${id}` }).click();
  await expect(page.getByText("版本 v1")).toBeVisible();
  await expect(page.getByText(`来源：batch-${id}.fasta`)).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 FASTA" }).click();
  const file = await download;
  const text = await (await file.createReadStream())!.toArray();
  expect(Buffer.concat(text).toString()).toMatch(
    new RegExp(`^>Heavy_${id} record=\\S+ version=1\\nMKTAYIAKQRQISFVKSHFS\\n$`),
  );
});

test("T12: a concurrent edit is reported instead of overwritten", async ({ page }) => {
  const id = unique();
  await login(page, "alice@example.test");
  await upload(page, `Conc_${id}.fasta`, `>Conc_${id}\nMKTAYIAKQR\n`);
  const card = page.getByTestId("candidate-0");
  await expect(card.getByText("修订 1")).toBeVisible();

  // Someone else renames the candidate behind this page's back.
  const candidateId = await page.evaluate(async (taskUrl) => {
    const taskId = taskUrl.split("/").pop();
    const response = await fetch(`/v1/jobs/${taskId}/candidates`, {
      headers: { "X-Dev-User": "bob@example.test" },
    });
    return (await response.json()).items[0].candidate.candidate_id as string;
  }, page.url());
  const other = await page.request.patch(`/v1/candidates/${candidateId}`, {
    headers: {
      "X-Dev-User": "bob@example.test",
      "X-Requested-With": "sequence-vault",
      "If-Match": '"1"',
    },
    data: { name: `Bob_${id}` },
  });
  expect(other.status()).toBe(200);

  await card.getByLabel("名称").fill(`Alice_${id}`);
  await card.getByRole("button", { name: "保存名称" }).click();
  const warning = page.getByRole("dialog").filter({ hasText: "内容已被修改" });
  await expect(warning).toBeVisible();
  await warning.getByRole("button", { name: "刷新并比较" }).click();
  await expect(page.getByTestId("candidate-0").locator(".ant-card-head")).toContainText(
    `Bob_${id}`,
  );
});

test("T09: a name without a sequence waits for content and can be archived", async ({ page }) => {
  const id = unique();
  await login(page, "alice@example.test");
  await upload(page, `pending-${id}.fasta`, `>Only_${id}\n`);
  const card = page.getByTestId("candidate-0");
  await expect(card.getByText("待补充内容")).toBeVisible();
  await card.getByRole("button", { name: "归档（待补充资料）" }).click();
  await expect(card.getByText("已归档")).toBeVisible();
});

test("viewers can search but not upload or review", async ({ page }) => {
  await login(page, "victor@example.test");
  await expect(page.getByText("您在此项目中没有上传权限")).toBeVisible();
  await page.getByRole("link", { name: "序列检索" }).click();
  await expect(page.getByRole("button", { name: "检索" })).toBeVisible();
});
