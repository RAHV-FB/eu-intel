/**
 * Analytical view acceptance: real source counts, chart caveats, direct Pages routes and phone layout.
 * The shared fixture also fails third-party requests, console errors and missing data responses.
 */
import AxeBuilder from '@axe-core/playwright';
import { BASE_PATH, PAGES_ORIGIN } from './env';
import { expect, open, test } from './fixtures';

test.describe('source-grounded Insights', () => {
  test('renders all four statistical sections and links to inspect the underlying records', async ({ page }) => {
    await open(page, 'insights');
    await expect(page.getByRole('heading', { name: /Patterns behind the legislative record/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Where tracked files stand' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Proposals and adoptions by year' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Votes on complete texts' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Positions recorded by government' })).toBeVisible();
    expect(await page.locator('.insights-bar-row').count()).toBeGreaterThan(5);
    expect(await page.locator('.insights-council-row').count()).toBeGreaterThan(15);
    await expect(page.getByRole('link', { name: 'Browse and filter every legislative file' })).toHaveAttribute('href', `${BASE_PATH}legislation`);
    await expect(page.getByText(/not a causal study/i).first()).toBeVisible();
  });

  test('prerendered URL responds with the right title', async ({ request }) => {
    const r = await request.get(`${PAGES_ORIGIN}${BASE_PATH}insights/`);
    expect(r.status()).toBe(200);
    expect(await r.text()).toContain('<title>Data insights – EU Legislative Intelligence</title>');
  });

  for (const width of [320, 375, 768, 1280]) {
    test(`fits at ${width}px without horizontal overflow and passes axe checks`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await open(page, 'insights');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
      const { violations } = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    });
  }
});
