/**
 * Search and list-filter regressions on the built site: MEP queries that name no political group, true result
 * counts above 1,000, one status region for a query whose parts find results, the result-group links, a long
 * pasted query on a 320px screen, the vote list's wording for other forms of a word, and accent-insensitive name
 * and party filters. Uses real records (ids below); see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { BASE_PATH } from './env';
import { expect, open, test } from './fixtures';

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

const search = (q: string) => `search?q=${encodeURIComponent(q)}`;
const count = (text: string | null) => Number((text ?? '').replace(/,/g, '').match(/\d+/)?.[0] ?? NaN);

test.describe('MEP queries', () => {
  for (const q of ['European Parliament MEPs', 'members of parliament', 'Parliament members']) {
    test(`"${q}" links the MEP directory, not one political group`, async ({ page }) => {
      await open(page, search(q));
      await expect(page.locator('#r-groups')).toHaveCount(0); // were The Left and S&D, first
      const link = page.locator('main .sr-summary').getByRole('link', { name: /MEP directory/ });
      await expect(link).toHaveAttribute('href', `${BASE_PATH}people`);
      await expect(page.locator('main')).not.toContainText('The Left group');
    });
  }

  test('a group by its name with stop words, and a group whose name starts with "The"', async ({ page }) => {
    await open(page, search('Patriots for Europe MEPs'));
    await expect(page.locator('main .sr-summary').getByRole('link', { name: 'See the current MEPs of the Patriots for Europe Group' })).toHaveAttribute(
      'href',
      `${BASE_PATH}people?group=pfe`,
    );
    await expect(page.locator('.sr-item__approx')).toHaveCount(0);
    await open(page, search('Left MEPs'));
    await expect(page.locator('main .sr-summary').getByRole('link', { name: /MEPs of The Left group/ })).toHaveText(
      'See the current MEPs of The Left group in the European Parliament - GUE/NGL',
    );
  });
});

test('more than 1,000 results: the search page counts them all, as the legislation explorer does', async ({ page }) => {
  await open(page, search('COD'));
  const summary = await page.locator('main .sr-summary').first().textContent();
  expect(summary).not.toContain('showing the best');
  await expect(page.locator('main [role="status"]')).toHaveText(/^[\d,]+ results for “COD”/);
  const files = count(await page.locator('#r-legislation .sr-group__count').textContent());
  expect(files).toBeGreaterThan(1000);
  // the group lists the best 1,000 when opened, and says so
  const all = `Show the best 1,000 of ${files.toLocaleString('en-GB')} legislation results`;
  await page.locator('#r-legislation').getByRole('button', { name: all }).click();
  await expect(page.locator('#r-legislation .sr-item')).toHaveCount(1000);
  await open(page, 'legislation?q=COD');
  await expect(page.locator('.lx-count')).toContainText(`${files.toLocaleString('en-GB')} files match`);
});

test('a query whose parts find results on their own is announced once', async ({ page }) => {
  await open(page, search('NIS2 Ireland'));
  const status = page.locator('main [role="status"]');
  await expect(status).toHaveCount(1);
  await expect(status).toHaveText('No results for “NIS2 Ireland”: nothing matches all of its words. Each part finds results on its own');
  await expect(page.locator('main .sr-summary').first()).toContainText('Each part finds results on its own:');
  await expectNoSeriousA11yViolations(page);
});

test.describe('result groups', () => {
  test('one group of results has no links to the groups', async ({ page }) => {
    await open(page, search('AI Act'));
    await expect(page.locator('#r-legislation')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Result groups' })).toHaveCount(0);
  });

  test('several groups of results keep them', async ({ page }) => {
    await open(page, search('Climate'));
    await expect(page.getByRole('navigation', { name: 'Result groups' }).getByRole('link')).not.toHaveCount(0);
    expect(await page.getByRole('navigation', { name: 'Result groups' }).getByRole('link').count()).toBeGreaterThan(1);
  });

  test('the Search button on an empty field returns to the field', async ({ page }) => {
    await open(page, 'search');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await expect(page.locator('.sr-form__input')).toBeFocused();
    await open(page, './');
    await page.locator('.home-hero__search').getByRole('button', { name: 'Search' }).click();
    await expect(page.locator('.home-hero__search input')).toBeFocused();
  });
});

test.describe('a long pasted query on a 320px screen', () => {
  const url = 'https://www.europarl.europa.eu/legislative-train/theme-a-europe-fit-for-the-digital-age/file-ai-act';
  for (const path of [search(url), search('a'.repeat(60)), `legislation?q=${encodeURIComponent(url)}`]) {
    test(path.slice(0, 40), async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 700 });
      await open(page, path);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
    });
  }
});

test.describe('vote list wording', () => {
  test('a form of a word is not called a word start', async ({ page }) => {
    await open(page, 'votes?q=labeled'); // the votes say "labelling"
    await expect(page.locator('.results-bar__count')).toContainText('these match only another form of a word');
    await expect(page.locator('.results-bar__count')).not.toContainText('start with it');
    await open(page, 'votes?q=artific');
    await expect(page.locator('.results-bar__count')).toContainText('that start with it');
  });
});

test.describe('name and party filters fold accents', () => {
  test('the vote page lists the same MEPs for "Garcia" as for "García"', async ({ page }) => {
    await open(page, 'votes/166051/?bl-q=Garc%C3%ADa'); // AI Act, final vote
    const accented = await page.locator('.results-bar__count').filter({ hasText: 'recorded vote' }).textContent();
    expect(count(accented)).toBeGreaterThan(0);
    await open(page, 'votes/166051/?bl-q=Garcia');
    await expect(page.locator('.results-bar__count').filter({ hasText: 'recorded vote' })).toHaveText(accented!);
    await expect(page.getByRole('row', { name: /Iratxe García Pérez/ })).toBeVisible();
    await expectNoSeriousA11yViolations(page);
  });

  test('People finds "Sinn Féin" for "Sinn Fein" and "Łukasz" for "Lukasz"', async ({ page }) => {
    await open(page, 'people?party=Sinn%20Fein');
    await expect(page.getByRole('row', { name: /Sinn Féin/ }).first()).toBeVisible();
    await open(page, 'people?q=Lukasz&status=all');
    await expect(page.getByRole('row', { name: /Łukasz/ }).first()).toBeVisible();
    await open(page, 'people?view=parties&pq=Sinn%20Fein&pscope=all');
    await expect(page.getByRole('row', { name: /Sinn Féin/ }).first()).toBeVisible();
  });
});
