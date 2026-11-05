/**
 * Shared e2e fixtures and helpers. Every test using this `test` automatically fails on:
 *   - a request to any origin other than the site's own (CSP-blocked loads surface as console errors), and
 *   - console errors, uncaught exceptions, or failed (>= 400) same-origin requests.
 * Every page sees the moment its data was built on its clock (`buildClock`).
 */
import { readFileSync } from 'node:fs';
import { expect, test as base, type APIRequestContext, type Page } from '@playwright/test';
import { BASE_PATH, SITE_NAME } from './env';

export { expect };

export interface Guard {
  /** Ignore console/response errors matching this pattern for the current test (e.g. an expected 404). */
  ignore(re: RegExp): void;
}

/** `built_at` of the site under test (dist/data/meta.json), in ms; undefined if it cannot be read. */
function builtAt(): number | undefined {
  try {
    const t = Date.parse((JSON.parse(readFileSync('dist/data/meta.json', 'utf8')) as { built_at: string }).built_at);
    return Number.isNaN(t) ? undefined : t;
  } catch {
    return undefined;
  }
}

export const test = base.extend<{ guard: Guard; buildClock: void; clockAtBuild: boolean }, { builtAt: number | undefined }>({
  builtAt: [async ({}, use) => use(builtAt()), { scope: 'worker' }],
  /** Whether each page's clock starts at the build time (below); `test.use({ clockAtBuild: false })` keeps the real one. */
  clockAtBuild: [true, { option: true }],
  /**
   * The page's clock starts at the moment the data was built (meta.json `built_at`) and runs on from there, so that the
   * pages read as the build wrote them, whatever day the tests run: in CI the frozen test data, built as of the moment
   * in tests/frozen-data.txt. A test that installs its own clock (`page.clock.install`) replaces this one.
   */
  buildClock: [
    async ({ page, builtAt, clockAtBuild }, use) => {
      if (clockAtBuild && builtAt !== undefined) await page.clock.install({ time: builtAt });
      await use();
    },
    { auto: true },
  ],
  guard: [
    async ({ page }, use) => {
      const errors: string[] = [];
      const external: string[] = [];
      const ignored: RegExp[] = [];
      let siteOrigin: string | null = null;
      const skip = (u: URL) => u.protocol === 'data:' || u.protocol === 'blob:' || u.protocol === 'about:';

      page.on('request', (req) => {
        const u = new URL(req.url());
        if (skip(u)) return;
        if (siteOrigin === null && req.isNavigationRequest() && req.frame() === page.mainFrame()) siteOrigin = u.origin;
        if (u.origin !== siteOrigin) external.push(`${req.resourceType()} ${req.url()}`);
      });
      page.on('response', (res) => {
        const u = new URL(res.url());
        if (skip(u) || u.origin !== siteOrigin) return;
        if (res.status() >= 400) errors.push(`HTTP ${res.status()} ${res.url()}`);
        // `vite preview` answers a missing data file with index.html (SPA fallback, 200): catch that too.
        else if (/\.json$/.test(u.pathname) && (res.headers()['content-type'] ?? '').includes('text/html')) {
          errors.push(`HTML served for missing data file ${res.url()}`);
        }
      });
      page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(`console.error: ${msg.text()} (${msg.location().url})`);
      });
      page.on('pageerror', (err) => errors.push(`uncaught: ${err.message}`));

      await use({ ignore: (re) => ignored.push(re) });

      expect(external, 'requests to third-party origins').toEqual([]);
      expect(
        errors.filter((e) => !ignored.some((re) => re.test(e))),
        'console errors, uncaught exceptions or failed same-origin requests',
      ).toEqual([]);
    },
    { auto: true },
  ],
});

/** Wait until the page has loaded its data and rendered a heading. */
export async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('.state--loading')).toHaveCount(0);
  await expect(page.locator('main h1').first()).toBeVisible();
}

/** Navigate relative to the base URL ("legislation", not "/legislation", which would drop the subpath). */
export async function open(page: Page, path: string) {
  const res = await page.goto(path);
  await settle(page);
  return res;
}

export async function expectHealthy(page: Page) {
  await expect(page).toHaveTitle(new RegExp(SITE_NAME));
  await expect(page.locator('main h1').first()).not.toBeEmpty();
  await expect(page.locator('.state--error'), 'error state rendered').toHaveCount(0);
  await expect(page.getByText(/We couldn.t find this/), 'not-found page rendered').toHaveCount(0);
}

export async function indexIds(request: APIRequestContext, origin: string, file: string, key: string): Promise<string[]> {
  const res = await request.get(`${origin}${BASE_PATH}data/${file}`);
  if (!res.ok()) return [];
  const rows = (await res.json()) as Record<string, unknown>[];
  return rows.map((r) => String(r[key]));
}

export const evenSample = <T,>(xs: T[], n: number) =>
  xs.length <= n ? xs : Array.from({ length: n }, (_, i) => xs[Math.floor((i * xs.length) / n)]);
