import { defineConfig, devices } from '@playwright/test'

const executablePath = process.env.E2E_BROWSER_EXECUTABLE_PATH

export default defineConfig({
  testDir: './e2e-real',
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173',
    launchOptions: executablePath ? { executablePath } : undefined,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
  },
})
