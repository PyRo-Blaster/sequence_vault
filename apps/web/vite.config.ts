import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = process.env.SEQUENCE_VAULT_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": api } },
  preview: { port: 4173, proxy: { "/v1": api } },
  build: { sourcemap: true, chunkSizeWarningLimit: 2000 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
