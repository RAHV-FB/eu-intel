/**
 * Page-level regressions on the built site: party records by term, country directive search, filters kept in the
 * address for Back, split parents and Parliament reports, the Following page's keyboard focus, not-found titles,
 * prerendered metadata and phone layouts. Uses real records (ids below); see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { BASE_PATH, PAGES_ORIGIN, SITE_NAME } from './env';
import { expect, open, settle, test } from './fixtures';

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

test.describe('party records', () => {
  test('a 2019–2024 record says so, links the current record and calls sitting MEPs current', async ({ page }) => {
    await open(page, 'people/parties/5494/'); // Rassemblement national, 2019–2024 record (EP corporate body 5494)
    await expect(page.locator('.eyebrow')).toHaveText('National party · France · 2019–2024 term');
    await expect(page.locator('.facts')).not.toContainText('Current MEPs');
    await expect(page.locator('.party-record').getByRole('link', { name: 'Rassemblement national' })).toHaveAttribute('href', `${BASE_PATH}people/parties/6848`);
    const bardella = page.getByRole('row', { name: /Jordan Bardella/ });
    await expect(bardella).toContainText('Current MEP');
    await expect(bardella).not.toContainText('Former MEP');
    await expect(bardella.getByRole('link', { name: 'Rassemblement national' })).toHaveAttribute('href', `${BASE_PATH}people/parties/6848`);
    await expectNoSeriousA11yViolations(page);
  });

  for (const width of [320, 390]) {
    test(`the MEP table fits a ${width}px screen with the period on screen`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await open(page, 'people/parties/5218/');
      const wrap = page.locator('section[aria-labelledby="pm-h"] .table-wrap');
      const [scroll, client] = await wrap.evaluate((el) => [el.scrollWidth, el.clientWidth]);
      expect(scroll).toBeLessThanOrEqual(client);
      await expect(page.getByRole('row', { name: /Laura Huhtasaari/ })).toContainText('2 Jul 2019 – 11 Apr 2023');
    });
  }
});

test.describe('country page directive search', () => {
  test('finds a directive by its number or common name and keeps the search for Back', async ({ page }) => {
    await open(page, 'countries/IE/');
    const count = page.locator('#tr-q').locator('xpath=ancestor::form/following-sibling::p[1]');
    for (const q of ['NIS2', '2022/2555', 'Directive (EU) 2022/2555']) {
      await page.fill('#tr-q', q);
      await expect(count).toHaveText('1 directive');
      await expect(page.locator('td.impl-dir').first()).toContainText('· Directive (EU) 2022/2555 (NIS 2 Directive)');
    }
    await page.fill('#tr-q', '2022/2464');
    await expect(page.locator('td.impl-dir').first()).toContainText('Corporate Sustainability Reporting Directive');
    await expect(page.locator('td.impl-dir', { hasText: '2025/794' })).toContainText('its title cites 2022/2464');
    await page.locator('td.impl-dir a', { hasText: 'Corporate Sustainability Reporting Directive' }).click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('#tr-q')).toHaveValue('2022/2464');
    await expect(page.locator('td.impl-dir').first()).toContainText('Corporate Sustainability Reporting Directive');
    await expectNoSeriousA11yViolations(page);
  });

  test('says when nothing matches and offers the site search', async ({ page }) => {
    await open(page, 'countries/IE/?tr-q=zzqx');
    await expect(page.getByRole('link', { name: 'Search the whole site' })).toHaveAttribute('href', `${BASE_PATH}search?q=zzqx`);
  });

  test('shows no empty indicators section', async ({ page }) => {
    await open(page, 'countries/LV/');
    await expect(page.locator('#implementation h3')).toHaveText(['National measures for directives', 'Infringement cases']);
  });
});

test.describe('Back returns to the same list', () => {
  test('ballot filters on a vote page', async ({ page }) => {
    await open(page, 'votes/154623/');
    await page.selectOption('#bl-country', 'GR');
    await expect(page).toHaveURL(/bl-country=GR/);
    const counter = page.locator('.results-bar__count', { hasText: 'MEPs with a recorded vote' });
    const filtered = await counter.textContent();
    await page.locator('table a[href*="/people/meps/"]').first().click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('#bl-country')).toHaveValue('GR');
    await expect(counter).toHaveText(filtered!);
  });

  test('the opened list of MEPs on a country page', async ({ page }) => {
    await open(page, 'countries/MT/');
    await page.getByRole('button', { name: /Show all \d+ current MEPs from Malta/ }).click();
    await page.locator('#country-meps a[href*="/people/meps/"]').first().click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('#country-meps')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Hide the list of MEPs' })).toHaveAttribute('aria-expanded', 'true');
  });

  test('"Show more" on the votes list', async ({ page }) => {
    await open(page, 'votes');
    await page.getByRole('button', { name: /^Show \d+ more$/ }).click();
    await expect(page).toHaveURL(/show=100/);
    const last = page.locator('main a[href*="/votes/1"]').last();
    const href = await last.getAttribute('href');
    await last.click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator(`main a[href="${href}"]`)).toHaveCount(1);
  });
});

test.describe('split parents and Parliament reports', () => {
  test('a split parent does not present its generated name as an official title, and its part links differ', async ({ page }) => {
    await open(page, 'legislation/2016-0400/');
    await expect(page.locator('.dz-what')).not.toContainText('Its official title is');
    const parts = page.locator('.dz-what a');
    await expect(parts).toHaveText([/^2016\/0400A\(COD\) – Adapting/, /^2016\/0400B\(COD\) – Adapting/]);
    await expect(page.locator('.dz-what')).toContainText('(Withdrawn by the Commission)');
    await expectNoSeriousA11yViolations(page);
  });

  test('a report links its main file in the status and the next step', async ({ page }) => {
    await open(page, 'legislation/2020-0112R/');
    const facts = page.locator('.dz-facts');
    await expect(facts.getByRole('link', { name: '2020/0112(APP)' })).toHaveCount(2);
    await expect(facts.getByRole('link', { name: '2020/0112(APP)' }).first()).toHaveAttribute('href', `${BASE_PATH}legislation/2020-0112`);
  });

  test('the latest development is the milestone of the same day', async ({ page }) => {
    await open(page, 'legislation/2025-0418/');
    await expect(page.locator('.dz-fact', { hasText: 'Latest verified development' })).toContainText(
      'Parliament sent the file back to committee to negotiate with the Council',
    );
  });
});

test.describe('Following', () => {
  test('the Follow toggle keeps its name; Unfollow and Clear all keep keyboard focus on the page', async ({ page }) => {
    for (const id of ['2021-0106', '2022-0047', '2020-0374']) {
      await open(page, `legislation/${id}/`);
      const toggle = page.getByRole('button', { name: 'Follow this legislation' });
      await toggle.click();
      await expect(toggle).toHaveAttribute('aria-pressed', 'true');
      await expect(toggle).toHaveText(/Follow this legislation/);
    }
    await open(page, 'following');
    await expect(page.locator('.following__privacy')).toContainText('when you followed it and when you last viewed it');
    const titles = await page.locator('.following__list h3').allTextContents();
    await page.getByRole('button', { name: `Unfollow ${titles[1]}` }).press('Enter');
    await expect(page.locator(':focus')).toHaveText(titles[2]);
    await expect(page.getByRole('status').filter({ hasText: `Removed ${titles[1]}` })).toHaveCount(1);
    await page.getByRole('button', { name: 'Clear all' }).press('Enter');
    await expect(page.locator(':focus')).toHaveText('Cancel');
    await page.keyboard.press('Enter');
    await expect(page.locator(':focus')).toHaveText('Clear all');
    await page.keyboard.press('Enter');
    await page.getByRole('button', { name: /Yes, remove all/ }).press('Enter');
    await expect(page.locator(':focus')).toContainText('You are not following any legislation yet');
    await expectNoSeriousA11yViolations(page);
  });
});

test.describe('not-found pages say so in their title', () => {
  for (const [path, title] of [
    ['nope-not-here/', 'Page not found'],
    ['votes/999999999/', 'Vote not found'],
    ['people/meps/1/', 'MEP not found'],
    ['people/groups/xyz/', 'Political group not found'],
    ['people/parties/1/', 'National party not found'],
    ['countries/XX/', 'Country not found'],
    ['legislation/garbage/', 'Legislative file not found'],
  ]) {
    test(path, async ({ page, guard }) => {
      guard.ignore(/404|missing data file/); // the entity's data file does not exist
      await open(page, path);
      await expect(page).toHaveTitle(`${title} – ${SITE_NAME}`);
    });
  }
});

test.describe('prerendered metadata (GitHub Pages semantics)', () => {
  const get = async (request: import('@playwright/test').APIRequestContext, p: string) => {
    const res = await request.get(`${PAGES_ORIGIN}${BASE_PATH}${p}`);
    return { status: res.status(), html: await res.text() };
  };
  test('former MEPs, votes without counts and unnamed parties', async ({ request }) => {
    expect((await get(request, 'people/meps/197619/')).html).toContain(
      '<meta name="description" content="Former Member of the European Parliament elected in Italy." />',
    );
    const vote = /<meta name="description" content="([^"]*)"/.exec((await get(request, 'votes/195653/')).html)?.[1];
    expect(vote).toBe(
      "European Parliament vote of 2026-07-09: Parliament approved the committee's decision to enter into negotiations with the Council. No vote counts are recorded.",
    );
    const party = await get(request, 'people/parties/5719/');
    expect(party.status).toBe(200);
    expect(party.html).toContain('<title>Party name not recorded (Croatia) – EU Legislative Intelligence</title>');
  });
});

test('an MEP’s membership data links the EP Open Data API record', async ({ page }) => {
  await open(page, 'people/meps/124858/');
  await expect(page.getByRole('link', { name: /EP Open Data API – MEP 124858/ })).toHaveAttribute(
    'href',
    'https://data.europarl.europa.eu/api/v2/meps/124858?format=application%2Fld%2Bjson',
  );
});

test('home cards do not scroll sideways at 320px with increased text spacing (WCAG 1.4.12)', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await open(page, './');
  await page.addStyleTag({ content: '*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important} p{margin-bottom:2em!important}' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});
