import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

/** The dev stack writes its database URL and seeded IDs here (read by e2e/legacy.spec.ts). */
export const DEV_STATE = join(tmpdir(), "sequence-vault-e2e-stack.json");

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
      env: { SEQUENCE_VAULT_DEV_STATE: DEV_STATE },
      url: "http://127.0.0.1:8000/v1/health",
      timeout: 120_000,
      reuseExistingServer: false,
      // The default is SIGKILL, which leaves the stack's PostgreSQL cluster running.
      gracefulShutdown: { signal: "SIGTERM", timeout: 15_000 },
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
