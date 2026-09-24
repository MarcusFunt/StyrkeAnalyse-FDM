import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const frontendDirectory = process.cwd();

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:8012",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] }, testMatch: /gui\.spec\.ts/ },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
      testMatch: /mobile\.spec\.ts/,
    },
  ],
  webServer: {
    command: "uv run --project .. python -m fdm_strength.web",
    url: "http://127.0.0.1:8012/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      FDM_GUI_HOST: "127.0.0.1",
      FDM_GUI_PORT: "8012",
      FDM_GUI_STATIC_DIR: path.join(frontendDirectory, "dist"),
      FDM_GUI_DATA_DIR: path.join(frontendDirectory, ".playwright-data"),
    },
  },
});
