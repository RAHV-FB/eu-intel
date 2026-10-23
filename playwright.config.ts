import { defineConfig, devices } from '@playwright/test';
import { BASE_PATH, PAGES_ORIGIN, PREVIEW_ORIGIN } from './tests/e2e/env';

/**
 * End-to-end smoke, accessibility and privacy tests against the *built* site, served under the GitHub Pages
 * project subpath. Build first, then run:
 *
 *   python -m pipeline build && BASE_PATH=/eu-intel/ npm run build
 *   npx playwright test                      # both servers below are started automatically
 *
 * Two servers:
 *   - `vite preview` (port 4173) for general navigation tests (it has an SPA fallback);
 *   - tests/e2e/pages-server.mjs (port 4174), a plain static server with GitHub Pages semantics (no rewrites,
 *     301 to trailing slash, 404.html with status 404) for direct deep-link tests.
 * In CI the e2e job is opt-in (see .github/workflows/ci.yml and docs/DEPLOYMENT.md).
 */
const CI = !!process.env.CI;

export default defineConfig({
  testDir: 'tests/e2e',
  testMatch: '**/*.spec.ts',
  outputDir: 'test-results/e2e',
  globalSetup: './tests/e2e/global-setup.ts',
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  workers: CI ? 2 : undefined,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: CI ? [['github'], ['html', { open: 'never', outputFolder: 'playwright-report' }]] : [['list']],
  use: {
    baseURL: PREVIEW_ORIGIN + BASE_PATH,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'en-GB',
    timezoneId: 'Europe/Brussels',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `npx vite preview --host 127.0.0.1 --port ${new URL(PREVIEW_ORIGIN).port} --strictPort`,
      url: PREVIEW_ORIGIN + BASE_PATH,
      env: { BASE_PATH },
      reuseExistingServer: !CI,
      timeout: 60_000,
    },
    {
      command: `node tests/e2e/pages-server.mjs dist ${new URL(PAGES_ORIGIN).port}`,
      url: PAGES_ORIGIN + BASE_PATH,
      env: { BASE_PATH },
      reuseExistingServer: !CI,
      timeout: 30_000,
    },
  ],
});
