/**
 * Keyboard focus in the glossary popup and the phone menu, distinct landmark names and a name for every table, found by
 * the accessibility audit of 5 Nov 2026. Real records; see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import { AI_ACT_ID } from './env';
import { expect, open, test } from './fixtures';

test('a glossary definition closed with Escape from its "Learn more" link returns focus to its term', async ({ page }) => {
  await open(page, `legislation/${AI_ACT_ID}/`);
  const term = page.locator('main .term__btn').first();
  await term.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('main .term__tip')).toHaveCount(1);
  await page.keyboard.press('Tab');
  await expect(page.locator('main .term__tip a')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('main .term__tip')).toHaveCount(0);
  await expect(term).toBeFocused(); // before the fix: focus fell back to <body>
});

test.describe('phone menu: tabbing out of it', () => {
  // a phone held sideways, and 400% zoom of a 1280x1024 screen: the open menu fills the screen
  for (const [width, height] of [[640, 360], [320, 256]]) {
    test(`closes the menu, so the element focused next is on screen (${width}x${height})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await open(page, 'about');
      const toggle = page.getByRole('button', { name: 'Menu' });
      await toggle.click();
      await page.locator('#primary-nav a').last().focus();
      await page.keyboard.press('Tab');
      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      // the newly focused element is inside the viewport and below the sticky header
      await expect
        .poll(() =>
          page.evaluate(() => {
            const r = document.activeElement!.getBoundingClientRect();
            const header = document.querySelector('.site-header')!.getBoundingClientRect();
            return r.top >= header.bottom - 0.5 && r.bottom <= window.innerHeight + 0.5;
          }),
        )
        .toBe(true);
    });
  }
});

test.describe('landmarks have distinct names (axe landmark-unique)', () => {
  for (const path of ['search?q=climate', 'legislation/changes']) {
    test(path, async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 });
      await open(page, path);
      const { violations } = await new AxeBuilder({ page }).withRules(['landmark-unique']).analyze();
      expect(violations.flatMap((v) => v.nodes.map((n) => n.target.join(' ')))).toEqual([]);
    });
  }
});

test('every table on a law page has a name (caption or label)', async ({ page }) => {
  for (const path of [`legislation/${AI_ACT_ID}/`, 'legislation/2020-0359/']) {
    await open(page, path);
    const unnamed = await page.locator('main table').evaluateAll((ts) =>
      ts
        .filter((t) => !(t.querySelector('caption')?.textContent?.trim() || t.getAttribute('aria-label') || t.getAttribute('aria-labelledby')))
        .map((t) => t.querySelector('th')?.textContent ?? '?'),
    );
    expect(unnamed, path).toEqual([]);
  }
});
