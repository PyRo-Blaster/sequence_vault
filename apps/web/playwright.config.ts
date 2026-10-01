import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:4173", locale: "zh-CN", trace: "retain-on-failure" },
  webServer: [
    {
      command: "uv run python ../../scripts/dev_stack.py",
      url: "http://127.0.0.1:8000/v1/health",
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "pnpm build && pnpm preview --host 127.0.0.1 --strictPort",
      url: "http://127.0.0.1:4173",
      timeout: 180_000,
      reuseExistingServer: false,
    },
  ],
});
