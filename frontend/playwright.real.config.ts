import { defineConfig, devices } from '@playwright/test'

const executablePath = process.env.E2E_BROWSER_EXECUTABLE_PATH

export default defineConfig({
  testDir: './e2e-real',
  fullyParallel: false,
  workers: 1, // Real flows share the seeded environment and risk lifecycle.
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8000',
    launchOptions: executablePath ? { executablePath } : undefined,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },

})
