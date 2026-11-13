import { defineConfig } from "@playwright/test";

// Records the demo video:  npx playwright test -c playwright.video.config.ts
// Uses its own API (port 8002, throwaway database shs_scheduler_video, see backend/tests/video_server.py)
// and its own web build (.next-video, port 3002), so it never touches development or test data.
export default defineConfig({
  testDir: "./video",
  testMatch: "*.video.ts",
  outputDir: "D:/Temp/video-results",
  timeout: 15 * 60_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3002",
    viewport: { width: 1280, height: 720 },
    video: { mode: "on", size: { width: 1280, height: 720 } },
    launchOptions: { slowMo: 120 },
  },
  webServer: [
    {
      command: ".venv\\Scripts\\python.exe -m tests.video_server",
      cwd: "../backend",
      url: "http://localhost:8002/api/health",
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      command: "npx next build && npx next start -p 3002",
      url: "http://localhost:3002/login",
      env: { NEXT_PUBLIC_API_URL: "http://localhost:8002", NEXT_DIST_DIR: ".next-video" },
      reuseExistingServer: false,
      timeout: 300_000,
    },
  ],
});
