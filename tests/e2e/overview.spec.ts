/**
 * The overview pages a first-time visitor starts from: the homepage, the votes list and the countries list. Checks
 * what they say up front (independent, not official; where Council votes are; the period of the Council counts) and
 * that the first content is reachable without scrolling far on a phone. See playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { BASE_PATH } from './env';
import { expect, open, test } from './fixtures';

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

/** Distance from the top of the page, in CSS pixels. */
const pageTop = (l: Locator) => l.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);

test.describe('homepage', () => {
  test('says on the first phone screen that it is not an official EU website, and leads to the guide', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, './');
    const independent = page.locator('.home-hero__independent');
    await expect(independent).toHaveText(/not an official EU website/);
    expect(await pageTop(independent)).toBeLessThan(844 - 40);
    await expect(page.locator('.home-hero').getByRole('link', { name: 'How EU laws are made' })).toHaveAttribute(
      'href',
      `${BASE_PATH}how-the-eu-works`,
    );
    await expectNoSeriousA11yViolations(page);
  });

  test('previews the selected files and puts the topics before the generated lists', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await open(page, './');
    const cards = page.locator('.fcard');
    expect(await cards.count()).toBeGreaterThan(0);
    for (const card of await cards.all()) {
      // an overview: what the file does and what happens next; why it matters and the latest step are on its page
      await expect(card.locator('dt')).toHaveText(['What happens next']);
      await expect(card.locator('a[target="_blank"]')).toHaveCount(1);
      await expect(card.getByRole('link', { name: /^Full details on / })).toBeVisible();
    }
    expect(await pageTop(page.locator('#topics-title'))).toBeLessThan(await pageTop(page.locator('#lists-title')));
    // the whole page in phone screens: 18.8 before the featured cards became an overview (23 October 2026)
    const screens = await page.evaluate(() => document.documentElement.scrollHeight / window.innerHeight);
    expect(screens).toBeLessThan(14);
  });

  test('gives the guide a reading time that matches its length', async ({ page }) => {
    await open(page, 'how-the-eu-works/');
    const words = (await page.locator('main').innerText()).split(/\s+/).filter(Boolean).length;
    await open(page, './');
    const minutes = Number(/about (\d+) minutes/.exec(await page.locator('.home__guide .btn').innerText())?.[1]);
    // 200 to 250 words a minute
    expect(minutes).toBeGreaterThanOrEqual(Math.floor(words / 250));
    expect(minutes).toBeLessThanOrEqual(Math.ceil(words / 200));
  });
});
