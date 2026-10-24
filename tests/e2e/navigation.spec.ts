/**
 * Navigation, focus and filter regressions on the built site: filters chosen while a keyword is still being written,
 * the country pages' case search, "Show all" results kept for Back, suggestions kept in view, the header search
 * field's focus indicator, section links, the phone menu on short screens, status messages on the search page,
 * secondary data that fails to load, the Following page's wording, the United Kingdom's page and 320px layouts.
 * Uses real records (ids below); see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { AI_ACT_ID, BASE_PATH } from './env';
import { expect, open, settle, test } from './fixtures';

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

/** Top and bottom of an element in the viewport. */
const box = (l: Locator) => l.evaluate((el) => ({ top: el.getBoundingClientRect().top, bottom: el.getBoundingClientRect().bottom }));
const headerBottom = (page: Page) => page.locator('.site-header').evaluate((el) => el.getBoundingClientRect().bottom);

test.describe('legislation filters chosen while the keyword is being written', () => {
  for (const width of [1280, 390]) {
    test(`a topic chosen 50 ms after typing is kept with the keyword (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await open(page, 'legislation');
      if (width < 640) await page.getByRole('button', { name: 'Filters and sorting' }).click();
      const filters = page.getByRole('search', { name: 'Filter legislation' });
      await filters.getByLabel('Keyword, title or reference').pressSequentially('energy', { delay: 30 });
      await page.waitForTimeout(50);
      await filters.getByLabel('Topic', { exact: true }).selectOption('environment');
      await page.waitForTimeout(700); // past the keyword's write
      await expect(page).toHaveURL(/[?&]q=energy\b/);
      await expect(page).toHaveURL(/[?&]topic=environment\b/);
      await expect(filters.getByLabel('Topic', { exact: true })).toHaveValue('environment');
      await expect(filters.getByLabel('Keyword, title or reference')).toHaveValue('energy');
    });
  }

  test('keyboard: type, Tab to Topic, ArrowDown keeps both; two quick ArrowDowns move two options', async ({ page }) => {
    await open(page, 'legislation');
    const filters = page.getByRole('search', { name: 'Filter legislation' });
    const topic = filters.getByLabel('Topic', { exact: true });
    await filters.getByLabel('Keyword, title or reference').pressSequentially('energy', { delay: 30 });
    await page.keyboard.press('Tab');
    await expect(topic).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await page.waitForTimeout(700);
    const first = await topic.inputValue();
    expect(first).not.toBe('');
    await expect(page).toHaveURL(new RegExp(`[?&]topic=${first}\\b`));
    await expect(page).toHaveURL(/[?&]q=energy\b/);

    await open(page, 'legislation');
    const options = await topic.locator('option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
    await topic.focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await expect(topic).toHaveValue(options[2]);
    await expect(page).toHaveURL(new RegExp(`[?&]topic=${options[2]}\\b`));
  });

  test('a status chosen between two bursts of typing is kept', async ({ page }) => {
    await open(page, 'legislation');
    const filters = page.getByRole('search', { name: 'Filter legislation' });
    const q = filters.getByLabel('Keyword, title or reference');
    await q.pressSequentially('transport', { delay: 30 });
    await page.waitForTimeout(50);
    await filters.getByLabel('Status', { exact: true }).selectOption('active');
    await page.waitForTimeout(300);
    await q.press('End');
    await q.pressSequentially(' rail', { delay: 30 });
    await page.waitForTimeout(700);
    await expect(page).toHaveURL(/[?&]stage=active\b/);
    await expect(page).toHaveURL(/[?&]q=transport\+rail\b/);
  });
});

test.describe('country page infringement case search', () => {
  const count = (page: Page) => page.locator('#inf-q').locator('xpath=ancestor::form/following-sibling::p[1]');
  test("finds Ireland's NIS 2 and Anti-SLAPP cases by the directives' names and numbers, words whole", async ({ page }) => {
    await open(page, 'countries/IE/?inf-status=all');
    const cases = page.locator('#implementation table').last().locator('tbody tr');
    for (const [q, id] of [
      ['NIS2', 'INFR(2024)0279'],
      ['NIS 2', 'INFR(2024)0279'],
      ['Directive 2022/2555', 'INFR(2024)0279'],
      ['Anti-SLAPP', 'INFR(2026)0402'], // titled "Lack of transposition of Directive 32024L1069 by Ireland"
      ['2024/1069', 'INFR(2026)0402'],
    ]) {
      await page.fill('#inf-q', q);
      await expect(count(page), q).toHaveText('1 case');
      await expect(cases.first()).toContainText(id);
    }
    await page.fill('#inf-q', 'ban'); // not "urban waste water"
    await expect(count(page)).toHaveText('0 cases');
    await expect(page.getByText(/No case in this list matches “ban”/)).toBeVisible();
    await page.fill('#inf-q', 'NIS'); // not "organisms" or "Etats-Unis"
    await expect(cases.filter({ hasText: 'INFR(2019)0278' })).toHaveCount(0);
    await expect(cases.filter({ hasText: 'INFR(2005)2037' })).toHaveCount(0);
  });
});

test.describe('search results page', () => {
  for (const [width, height] of [[390, 844], [1280, 900]]) {
    test(`"Show all" results are kept for Back, with the reader's place (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await open(page, 'search?q=energy');
      const group = page.locator('#r-legislation');
      await group.getByRole('button', { name: /^Show all \d+ legislation results$/ }).click();
      await expect(page).toHaveURL(/[?&]all=legislation\b/);
      const n = await group.locator('.sr-item').count();
      expect(n).toBeGreaterThan(20);
      const link = group.locator('.sr-item a').nth(20);
      const href = await link.getAttribute('href');
      await link.scrollIntoViewIfNeeded();
      const before = await box(link);
      await link.click();
      await expect(page).toHaveURL(new RegExp(`${href}/?$`));
      await settle(page);
      await page.goBack();
      await expect(page).toHaveURL(/\/search\/?\?q=energy&all=legislation$/);
      await settle(page);
      await expect(group.locator('.sr-item')).toHaveCount(n);
      await expect(group.getByRole('button', { name: 'Show fewer' })).toHaveAttribute('aria-expanded', 'true');
      const back = page.locator(`#r-legislation a[href="${href}"]`);
      await expect.poll(async () => Math.round((await box(back)).top)).toBe(Math.round(before.top));
    });
  }

  test('a new search from the search page is announced in the same status region, also with no results', async ({ page }) => {
    await open(page, 'search?q=climate');
    const status = page.locator('main [role="status"]');
    await expect(status).toHaveCount(1);
    await expect(status).toHaveText(/^\d+ results? for “climate”/);
    await status.evaluate((el) => ((el as HTMLElement & { marked?: boolean }).marked = true));
    const input = page.getByRole('search').locator('.sr-form__input');
    for (const [q, text] of [
      ['zzqxv', /^No results for “zzqxv”$/],
      ['fisheries', /^\d+ results? for “fisheries”/],
    ] as const) {
      await input.fill(q);
      await input.press('Enter');
      await expect(status).toHaveText(text);
      expect(await status.evaluate((el) => (el as HTMLElement & { marked?: boolean }).marked), 'the same region').toBe(true);
    }
    await input.fill('zzqxv');
    await input.press('Enter');
    await expect(page.getByText('No results for “zzqxv”').first()).toBeAttached();
    await expectNoSeriousA11yViolations(page);
  });
});

test.describe('search suggestions', () => {
  const cases = [
    { path: 'votes/164532/', width: 320, height: 568, panel: true },
    { path: 'votes/164532/', width: 320, height: 256, panel: true },
    { path: './', width: 320, height: 568, panel: false },
    { path: './', width: 1280, height: 720, panel: false },
  ];
  for (const c of cases) {
    test(`the highlighted suggestion is kept on screen (${c.path} ${c.width}x${c.height})`, async ({ page }) => {
      await page.setViewportSize({ width: c.width, height: c.height });
      await open(page, c.path);
      if (c.panel) await page.locator('.search-toggle').click();
      const input = page.locator(c.panel ? '#header-search input' : '.home-hero__search input');
      await input.click();
      await input.pressSequentially('energy', { delay: 20 });
      const options = page.locator('[role="listbox"] [role="option"][id]');
      await expect(options.first()).toBeVisible();
      const n = await options.count();
      for (let i = 0; i < n; i++) {
        await input.press('ArrowDown');
        const id = await input.getAttribute('aria-activedescendant');
        const r = await page.locator(`[id="${id}"]`).evaluate((el) => {
          const o = el.getBoundingClientRect();
          const l = el.parentElement!.getBoundingClientRect();
          return { top: o.top, bottom: o.bottom, height: o.height, listTop: l.top, listBottom: l.bottom, vh: window.innerHeight };
        });
        // the option is inside the list and the screen; one taller than the list shows its start
        expect(r.top, `option ${i} top`).toBeGreaterThanOrEqual(Math.max(r.listTop, 0) - 1);
        if (r.height <= r.listBottom - r.listTop) expect(r.bottom, `option ${i} bottom`).toBeLessThanOrEqual(Math.min(r.listBottom, r.vh) + 1);
        else expect(r.top, `option ${i} top on screen`).toBeLessThan(r.vh);
      }
    });
  }
});

test.describe('header search field focus', () => {
  for (const [width, panel] of [[1280, false], [390, true]] as const) {
    test(`shows a solid focus ring of the focus colour (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await open(page, 'countries');
      if (panel) await page.locator('.search-toggle').click();
      else await page.locator('.site-header__search input').focus();
      const field = page.locator(panel ? '#header-search .searchbox__field' : '.site-header__search .searchbox__field');
      // #1a56db: 6.2:1 against the white header, 5.7:1 against the field
      await expect(field).toHaveCSS('border-top-color', 'rgb(26, 86, 219)');
      await expect(field).toHaveCSS('outline-color', 'rgb(26, 86, 219)');
      await expect(field).toHaveCSS('outline-style', 'solid');
    });
  }
});

test.describe('section links', () => {
  for (const width of [390, 1280]) {
    for (const path of [`legislation/${AI_ACT_ID}/#timeline`, `legislation/${AI_ACT_ID}/#ep-votes`, 'countries/IE/#implementation']) {
      test(`${path} lands on the section, below the header (${width}px)`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await open(page, path);
        const heading = page.locator(`#${path.split('#')[1]}`).locator('h2, h3').first();
        await expect(heading).toBeFocused();
        const top = (await box(heading)).top;
        const header = await headerBottom(page);
        expect(top).toBeGreaterThanOrEqual(header);
        expect(top).toBeLessThan(header + 120);
      });
    }
  }
});

test.describe('phone menu on short screens', () => {
  for (const [width, height] of [[568, 320], [640, 360], [320, 256]]) {
    test(`every menu link can be reached (${width}x${height})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await open(page, 'votes');
      await page.locator('.menu-toggle').click();
      const links = page.locator('#primary-nav a:visible');
      const last = links.last();
      await expect(last).toHaveText('Search');
      await last.focus();
      // Firefox does not scroll a partly visible element on focus: scroll as a visitor would, which still fails if
      // the menu cannot scroll far enough to show the whole link
      await last.scrollIntoViewIfNeeded();
      const r = await box(last);
      expect(r.top).toBeGreaterThanOrEqual(0);
      expect(r.bottom).toBeLessThanOrEqual(height);
      await last.click();
      await expect(page).toHaveURL(/\/search\/?$/);
    });
  }
});

test.describe('secondary data that fails to load', () => {
  test('an MEP page says the vote details could not be loaded, rather than showing them as not recorded', async ({ page, guard }) => {
    guard.ignore(/votes\/titles\.json/);
    await page.route('**/data/votes/titles.json', (r) => r.fulfill({ status: 500, body: 'error' }));
    await open(page, 'people/meps/197619/');
    await expect(page.getByRole('alert')).toContainText('The titles, dates and results of these votes could not be loaded');
    const row = page.locator('section[aria-labelledby="v-h"] tbody tr').first();
    await expect(row).toContainText('Not loaded');
    await expect(row).not.toContainText('—');
    await expectNoSeriousA11yViolations(page);
  });

  test('a group page says when vote details or member names could not be loaded', async ({ page, guard }) => {
    guard.ignore(/votes\/titles\.json|people\/meps\.json/);
    await page.route('**/data/votes/titles.json', (r) => r.fulfill({ status: 500, body: 'error' }));
    await page.route('**/data/people/meps.json', (r) => r.fulfill({ status: 500, body: 'error' }));
    await open(page, 'people/groups/epp/');
    await expect(page.getByRole('alert').filter({ hasText: 'The titles and dates of these votes could not be loaded' })).toHaveCount(1);
    await expect(page.getByRole('alert').filter({ hasText: 'The members’ names could not be loaded' })).toHaveCount(1);
    await expect(page.locator('section[aria-labelledby="gv-h"] tbody tr').first()).toContainText('Not loaded');
  });
});

test.describe('Following page wording', () => {
  test('an empty list does not point to controls that are not shown', async ({ page }) => {
    await open(page, 'following');
    const privacy = page.locator('#about-storage');
    await expect(privacy).not.toContainText('Clear all');
    await expect(privacy).not.toContainText('copy the share link');
    await expect(page.getByRole('button', { name: 'Clear all' })).toHaveCount(0);
    await expectNoSeriousA11yViolations(page);
  });

  test('a shared list does not offer "Clear all"; a list of one’s own does, with its share link', async ({ page }) => {
    await open(page, `following/?ids=${AI_ACT_ID},2022-0155`);
    await expect(page.locator('#about-storage')).not.toContainText('Clear all');
    await expect(page.locator('#about-storage')).toContainText('View my own list');
    await open(page, `legislation/${AI_ACT_ID}/`);
    await page.getByRole('button', { name: /Follow this legislation/ }).first().click();
    await open(page, 'following');
    await expect(page.locator('#about-storage')).toContainText('“Clear all” below');
    await expect(page.getByRole('button', { name: 'Clear all' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Copy link' })).toHaveCount(1);
  });
});

test('the United Kingdom page links to the MEPs elected there and its national parties', async ({ page, request }) => {
  const meps = (await (await request.get(`data/people/meps.json`)).json()) as { country: string; active: boolean }[];
  const uk = meps.filter((m) => m.country === 'GB' && !m.active).length;
  expect(uk).toBeGreaterThan(0);
  await open(page, 'countries/GB/');
  await expect(page.locator('main')).toContainText(`(${uk} in our data)`);
  await expectNoSeriousA11yViolations(page);
  await page.getByRole('link', { name: 'MEPs elected in the United Kingdom' }).click();
  await settle(page);
  await expect(page).toHaveURL(new RegExp(`${BASE_PATH}people\\?country=GB&status=former$`));
  await expect(page.getByText(`${uk} MEPs no longer in office`)).toBeVisible();
  await page.goBack();
  await settle(page);
  await page.getByRole('link', { name: 'National parties of the United Kingdom' }).click();
  await settle(page);
  await expect(page.locator('main table tbody tr').first()).toContainText('United Kingdom');
});

test.describe('320px screens', () => {
  test.beforeEach(async ({ page }) => page.setViewportSize({ width: 320, height: 700 }));

  test('the directives table of a country page fits, with "Measures notified" on screen', async ({ page }) => {
    for (const code of ['LV', 'AT']) {
      await open(page, `countries/${code}/`);
      const wrap = page.locator('#tr-q').locator('xpath=ancestor::form/following-sibling::div[contains(@class, "table-wrap")][1]');
      const [scroll, client] = await wrap.evaluate((el) => [el.scrollWidth, el.clientWidth]);
      expect(scroll, code).toBeLessThanOrEqual(client);
    }
  });

  test('search fields show a placeholder that fits, keeping a reference-format example where there is one', async ({ page }) => {
    const fits = (l: Locator) =>
      l.evaluate((el: HTMLInputElement) => {
        const cs = getComputedStyle(el);
        const ctx = document.createElement('canvas').getContext('2d')!;
        ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        return ctx.measureText(el.placeholder).width <= el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      });
    for (const [path, sel, example] of [
      ['legislation', '.lx-filters__q input', '2021/0106(COD)'],
      ['votes', '#vf-q', '2021/0106(COD)'],
      ['./', '.home-hero__search input', ''],
      ['search', '.sr-form__input', ''],
    ]) {
      await open(page, path);
      const input = page.locator(sel).first();
      expect(await fits(input), path).toBe(true);
      expect(await input.getAttribute('placeholder'), path).toContain(example);
    }
    await open(page, 'countries/');
    await page.locator('.search-toggle').click();
    expect(await fits(page.locator('#header-search input'))).toBe(true);
  });
});
