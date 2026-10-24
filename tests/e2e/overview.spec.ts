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

test.describe('votes list', () => {
  for (const [width, height] of [
    [1440, 900],
    [375, 812],
  ]) {
    test(`the first vote starts on the first screen (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await open(page, 'votes');
      const first = page.locator('.vote-list > li').first();
      await expect(first).toBeVisible();
      expect(await pageTop(first)).toBeLessThan(height - 80);
    });
  }

  test('says where the Council votes are, and keeps "More filters" open while one of them is set', async ({ page }) => {
    await open(page, 'votes');
    await expect(page.locator('.page-header').getByRole('link', { name: 'each country’s page' })).toHaveAttribute('href', `${BASE_PATH}countries`);
    const more = page.locator('form[aria-label="Filter votes"] details.lx-more');
    await expect(more).not.toHaveAttribute('open');
    await more.locator('summary').click();
    await page.locator('#vf-close').check();
    await expect(page).toHaveURL(/close=1/);
    await open(page, 'votes?close=1');
    await expect(more).toHaveAttribute('open');
    await expect(more.locator('summary')).toContainText('(1 active)');
    await expectNoSeriousA11yViolations(page);
  });
});

test.describe('countries list', () => {
  test('gives the period and the number of the Council votes it counts', async ({ page }) => {
    await open(page, 'countries/');
    await expect(page.locator('th[scope="colgroup"]', { hasText: 'Council of the EU votes' })).toHaveText(/^Council of the EU votes, 20\d\d–20\d\d$/);
    const note = page.locator('.note', { hasText: 'How each government voted' });
    const n = Number(/: ([\d,]+) votes with each country’s position recorded, between \d+ \w+ 20\d\d and \d+ \w+ 20\d\d\./.exec(await note.innerText())?.[1].replace(/,/g, ''));
    // each country's four counts add up to the votes counted
    const austria = page.getByRole('row', { name: /^Austria/ });
    const np = await page.locator('thead th', { hasText: 'Did not take part' }).count();
    const cells = (await austria.locator('td').allInnerTexts()).slice(2, np ? 6 : 5).map((t) => Number(t.replace(/,/g, '')));
    expect(cells.reduce((a, b) => a + b, 0)).toBe(n);
    await expectNoSeriousA11yViolations(page);
  });
});
