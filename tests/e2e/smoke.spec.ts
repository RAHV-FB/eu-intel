/**
 * Smoke, deep-link, search, privacy and accessibility checks on the built site under the Pages subpath.
 * See playwright.config.ts for how to build and run; tests/e2e/fixtures.ts for the automatic
 * third-party-request and console-error guard applied to every test.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { AI_ACT_ID, BASE_PATH, PAGES_ORIGIN, SITE_NAME } from './env';
import { evenSample, expect, expectHealthy, indexIds, open, settle, test } from './fixtures';

const PRIMARY = [
  { path: './', label: 'Discover' },
  { path: 'legislation', label: 'Legislation' },
  { path: 'votes', label: 'Votes' },
  { path: 'people', label: 'People & Parties' },
  { path: 'countries', label: 'Countries' },
  { path: 'how-the-eu-works', label: 'How the EU Works' },
];
const SECONDARY = ['about', 'privacy', 'following', 'search?q=climate'];
const AI_ACT_TITLE = /artificial intelligence|\bAI Act\b/i;

// ------------------------------------------------------------------ routes

test.describe('routes render (vite preview)', () => {
  for (const r of PRIMARY) {
    test(`primary route: ${r.label}`, async ({ page }) => {
      await open(page, r.path);
      await expectHealthy(page);
      await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: r.label })).toHaveAttribute(
        'aria-current',
        'page',
      );
    });
  }
  for (const p of SECONDARY) {
    test(`secondary route: ${p}`, async ({ page }) => {
      await open(page, p);
      await expectHealthy(page);
    });
  }

  test('primary navigation works client-side', async ({ page }) => {
    await open(page, './');
    const nav = page.getByRole('navigation', { name: 'Primary' });
    for (const r of PRIMARY.slice(1)) {
      await nav.getByRole('link', { name: r.label }).click();
      await expect(page).toHaveURL(new RegExp(`${BASE_PATH}${r.path}/?$`));
      await settle(page);
      await expectHealthy(page);
    }
  });

  test('skip link moves focus to the main content', async ({ page }) => {
    await open(page, 'legislation');
    await page.keyboard.press('Tab');
    const skip = page.getByRole('link', { name: 'Skip to content' });
    await expect(skip).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#main')).toBeFocused();
  });
});

// ------------------------------------------------------------------ GitHub Pages semantics

test.describe('direct navigation on a plain static server (GitHub Pages semantics)', () => {
  const pagesUrl = (p: string) => `${PAGES_ORIGIN}${BASE_PATH}${p}`;
  const routes = ['', 'legislation/', 'votes/', 'people/', 'countries/', 'how-the-eu-works/', 'about/', 'privacy/', 'search/', 'following/'];

  for (const p of routes) {
    test(`direct load /${p} returns 200`, async ({ page }) => {
      const res = await page.goto(pagesUrl(p));
      expect(res?.status()).toBe(200);
      await settle(page);
      await expectHealthy(page);
    });
  }

  test(`deep link to the AI Act (legislation/${AI_ACT_ID}/) returns 200 and renders it`, async ({ page }) => {
    const res = await page.goto(pagesUrl(`legislation/${AI_ACT_ID}/`));
    expect(res?.status()).toBe(200);
    await settle(page);
    await expectHealthy(page);
    await expect(page.locator('main h1').first()).toContainText(AI_ACT_TITLE);
    await expect(page).toHaveTitle(AI_ACT_TITLE);
  });

  test('deep link without trailing slash redirects like Pages and renders', async ({ page }) => {
    const res = await page.goto(pagesUrl(`legislation/${AI_ACT_ID}`));
    expect(res?.status()).toBe(200);
    expect(res?.request().redirectedFrom()?.url()).toBe(pagesUrl(`legislation/${AI_ACT_ID}`));
    await expect(page).toHaveURL(pagesUrl(`legislation/${AI_ACT_ID}/`));
    await settle(page);
    await expect(page.locator('main h1').first()).toContainText(AI_ACT_TITLE);
  });

  test('unknown URL gets 404.html (status 404) and the app shows its not-found page', async ({ page, guard }) => {
    guard.ignore(/404/);
    const res = await page.goto(pagesUrl('no-such-section/really-not-here/'));
    expect(res?.status()).toBe(404);
    await settle(page);
    await expect(page.getByText(/We couldn.t find this/)).toBeVisible();
  });

  test('prerendered shells carry route-specific titles', async ({ request }) => {
    const res = await request.get(pagesUrl('legislation/'));
    expect(res.status()).toBe(200);
    expect(await res.text()).toContain(`<title>Legislation – ${SITE_NAME}</title>`);
  });

  test('every entity in the published indexes has a directly loadable page', async ({ request }) => {
    const groups: [string, string, string, number][] = [
      ['dossiers/index.json', 'id', 'legislation', Infinity],
      ['votes/index.json', 'id', 'votes', 200],
      ['people/meps.json', 'id', 'people/meps', 100],
      ['people/groups.json', 'id', 'people/groups', Infinity],
      ['people/parties.json', 'id', 'people/parties', 50],
      ['countries/index.json', 'code', 'countries', Infinity],
    ];
    const missing: string[] = [];
    let checked = 0;
    for (const [file, key, prefix, n] of groups) {
      for (const id of evenSample(await indexIds(request, PAGES_ORIGIN, file, key), n)) {
        const res = await request.head(pagesUrl(`${prefix}/${encodeURIComponent(id)}/`));
        checked++;
        if (res.status() !== 200) missing.push(`${res.status()} ${prefix}/${id}/`);
      }
    }
    expect(checked, 'no entity indexes found in dist/data').toBeGreaterThan(0);
    expect(missing, 'routes that would 404 on GitHub Pages').toEqual([]);
  });
});

// ------------------------------------------------------------------ search

test.describe('search', () => {
  test('typing "AI Act" on the homepage suggests the AI Act and opens it', async ({ page }) => {
    await open(page, './');
    const box = page.getByRole('combobox').first();
    await box.click();
    await box.fill('AI Act');
    const option = page
      .getByRole('option')
      .filter({ hasText: /^Legislation/ })
      .filter({ hasText: AI_ACT_TITLE })
      .first();
    await expect(option).toBeVisible();
    await option.click();
    await expect(page).toHaveURL(new RegExp(`${BASE_PATH}legislation/${AI_ACT_ID}/?$`));
    await settle(page);
    await expect(page.locator('main h1').first()).toContainText(AI_ACT_TITLE);
  });

  test('submitting "AI Act" lists the AI Act on the results page', async ({ page }) => {
    await open(page, './');
    const box = page.getByRole('combobox').first();
    await box.fill('AI Act');
    await box.press('Enter');
    await expect(page).toHaveURL(/\/search\?q=AI(%20|\+)Act/);
    await settle(page);
    const hit = page.locator(`main a[href$="/legislation/${AI_ACT_ID}"], main a[href$="/legislation/${AI_ACT_ID}/"]`).first();
    await expect(hit).toBeVisible();
    await hit.click();
    await expect(page).toHaveURL(new RegExp(`legislation/${AI_ACT_ID}/?$`));
    await settle(page);
    await expect(page.locator('main h1').first()).toContainText(AI_ACT_TITLE);
  });
});

// ------------------------------------------------------------------ privacy

test('browsing sets no cookies and stores nothing locally without an explicit action', async ({ page, context }) => {
  for (const p of ['./', 'legislation', `legislation/${AI_ACT_ID}`, 'votes', 'people', 'countries', 'search?q=climate']) {
    await open(page, p);
  }
  expect(await context.cookies()).toEqual([]);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
});

// ------------------------------------------------------------------ accessibility

const A11Y_PAGES = [
  './',
  'legislation',
  `legislation/${AI_ACT_ID}`,
  'votes',
  'people',
  'countries',
  'how-the-eu-works',
  'about',
  'privacy',
  'search?q=climate',
];

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  const serious = violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 5).map((n) => n.target.join(' ')).join(' | ')}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

test.describe('accessibility (axe-core, WCAG 2.2 AA rules)', () => {
  for (const p of A11Y_PAGES) {
    test(`a11y: ${p}`, async ({ page }) => {
      await open(page, p);
      await expectNoSeriousA11yViolations(page);
    });
  }

  for (const [file, key, prefix] of [
    ['votes/index.json', 'id', 'votes'],
    ['people/meps.json', 'id', 'people/meps'],
    ['countries/index.json', 'code', 'countries'],
  ] as const) {
    test(`a11y: first ${prefix} detail page`, async ({ page, request, baseURL }) => {
      const [id] = await indexIds(request, new URL(baseURL!).origin, file, key);
      test.skip(!id, `${file} is empty or missing`);
      await open(page, `${prefix}/${encodeURIComponent(id)}`);
      await expectHealthy(page);
      await expectNoSeriousA11yViolations(page);
    });
  }
});

// ------------------------------------------------------------------ mobile

test.describe('mobile layout', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });

  test('menu button reveals the primary navigation', async ({ page }) => {
    await open(page, 'about');
    await page.getByRole('button', { name: 'Menu' }).click();
    const link = page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Legislation' });
    await expect(link).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(new RegExp(`${BASE_PATH}legislation/?$`));
  });

  for (const p of ['./', 'legislation', `legislation/${AI_ACT_ID}`, 'votes', 'people', 'countries']) {
    test(`no horizontal overflow: ${p}`, async ({ page }) => {
      await open(page, p);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, 'page is wider than the viewport').toBeLessThanOrEqual(1);
    });
  }
});
