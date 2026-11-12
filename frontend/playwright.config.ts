import { defineConfig } from "@playwright/test";

// The e2e run uses its own API (port 8001, throwaway database) and its own
// frontend build (.next-e2e, port 3001), so it can run next to `npm run dev`.
const env = {
  NEXT_PUBLIC_API_URL: "http://localhost:8001",
  NEXT_DIST_DIR: ".next-e2e",
};

export default defineConfig({
  testDir: "./e2e",
  outputDir: "D:/Temp/playwright-results",
  timeout: 90_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3001",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: ".venv\\Scripts\\python.exe -m tests.e2e_server",
      cwd: "../backend",
      url: "http://localhost:8001/api/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npx next build && npx next start -p 3001",
      url: "http://localhost:3001/login",
      env,
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
