/**
 * Page titles before and after a page loads, the privacy notice's wording about the page address, link labels,
 * https links to the official hosts, and the labels shown when the group or topic lookup file cannot be loaded.
 * Uses real records (ids below); see playwright.config.ts to run.
 */
import { AI_ACT_ID, BASE_PATH, PAGES_ORIGIN, SITE_NAME } from './env';
import { expect, open, settle, test } from './fixtures';

const pagesUrl = (p: string) => `${PAGES_ORIGIN}${BASE_PATH}${p}`;

test.describe('the title of a prerendered page is the title it has once loaded (GitHub Pages semantics)', () => {
  const routes = [
    'legislation/2017-0230/', // its title was 663 characters long
    'legislation/2022-0089/',
    `legislation/${AI_ACT_ID}/`,
    'legislation/2015-0068/', // the same title as 2013-0188 and 2016-0010
    'votes/199380/', // the same title as 191240, voted on the same file on another day
    'votes/',
    'people/',
    'people/groups/renew/',
    'people/meps/197619/',
    'people/parties/5719/',
    'countries/IE/',
    'how-the-eu-works/',
    'about/',
    'legislation/',
  ];
  for (const route of routes) {
    test(route, async ({ page, request }) => {
      const shell = await request.get(pagesUrl(route));
      expect(shell.status()).toBe(200);
      const shellTitle = /<title>([^<]*)<\/title>/
        .exec(await shell.text())?.[1]
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&');
      await page.goto(pagesUrl(route));
      await settle(page);
      expect(await page.title()).toBe(shellTitle);
    });
  }

  test('a very long title is cut in the tab and the announcement, not in the heading, and files of one title are told apart', async ({ page }) => {
    await page.goto(pagesUrl('legislation/2017-0230/'));
    await settle(page);
    const title = await page.title();
    expect(title.length).toBeLessThan(200);
    expect(title).toMatch(/… \(2017\/0230\(COD\)\) – EU Legislative Intelligence$/);
    expect((await page.locator('main h1').first().innerText()).length).toBeGreaterThan(300);
    const titles = new Set<string>();
    for (const id of ['2015-0068', '2013-0188', '2016-0010']) {
      await page.goto(pagesUrl(`legislation/${id}/`));
      await settle(page);
      titles.add(await page.title());
    }
    expect(titles.size).toBe(3);
    for (const id of ['199380', '191240']) {
      await page.goto(pagesUrl(`votes/${id}/`));
      await settle(page);
      titles.add(await page.title());
    }
    expect(titles.size).toBe(5);
  });

  test('a vote’s description gives its date as the site shows it', async ({ request }) => {
    const html = await (await request.get(pagesUrl('votes/199380/'))).text();
    expect(/<meta name="description" content="([^"]*)"/.exec(html)?.[1]).toMatch(/^European Parliament vote of 22 Oct 2026: /);
  });
});

test.describe('metadata of the shells', () => {
  test('only the page for unknown addresses is noindex, and a build without SITE_URL has no canonical links', async ({ request }) => {
    // the e2e build has no SITE_URL (a local build must not point at another host): tests/test_workflows.py and
    // src/features/legislation/titles.test.ts cover the canonical links
    const home = await (await request.get(pagesUrl('legislation/2017-0230/'))).text();
    expect(home).not.toContain('rel="canonical"');
    const missing = await request.get(pagesUrl('no-such-page/'));
    expect(missing.status()).toBe(404);
    expect(await missing.text()).toContain('<meta name="robots" content="noindex" />');
    expect(home).not.toContain('name="robots"');
  });
});

test.describe('privacy notice and links', () => {
  test('says that search terms and filters are part of the page address, and who receives it', async ({ page }) => {
    await open(page, 'privacy/');
    const main = page.locator('main');
    await expect(main).toContainText('The search terms and filters you use are part of the page address');
    await expect(main).toContainText('they appear in your browser history and in any link you share');
    await expect(main).toContainText('GitHub, the host, receives that address when a page is loaded from it; no other third party does');
    await expect(main).toContainText('(the full address, including any search terms or filters in it)');
    await expect(main).toContainText('when you reload, open a bookmark or restore a tab, or when someone opens a link you shared');
    await expect(main).toContainText('The share link on the Following page is the exception');
  });

  test('the address does carry the search terms and the filters (what the notice says)', async ({ page }) => {
    await open(page, 'legislation/?topic=tech&stage=active');
    expect(new URL(page.url()).search).toBe('?topic=tech&stage=active');
    await open(page, 'search/?q=artificial%20intelligence');
    await expect(page.locator('main')).toContainText('artificial intelligence');
  });

  test('the GitHub privacy statement is not called an official website; official links still are', async ({ page }) => {
    await open(page, 'privacy/');
    const github = page.getByRole('link', { name: /GitHub General Privacy Statement/ });
    await expect(github).toHaveAccessibleName(/GitHub General Privacy Statement.* \(opens in a new tab\)$/);
    await expect(github).not.toHaveAccessibleName(/official/);
    await expect(github).toHaveAttribute('rel', 'noopener noreferrer');
    await open(page, `legislation/${AI_ACT_ID}/`);
    const eu = page.locator('main a[target="_blank"]').first();
    await expect(eu).toHaveAccessibleName(/\(opens official website in a new tab\)$/);
  });

  test('About and Privacy say who maintains the site and where to report an error', async ({ page }) => {
    await open(page, 'about/');
    const contact = page.locator('#contact');
    await expect(contact).toContainText('The site is maintained by RAHV-FB, the GitHub account that owns the project’s public repository');
    await expect(contact).toContainText('To report an error or a missing record');
    const issues = contact.getByRole('link', { name: /issue tracker/ });
    await expect(issues).toHaveAttribute('href', 'https://github.com/RAHV-FB/eu-intel/issues');
    await expect(issues).toHaveAccessibleName('repository’s issue tracker (opens in a new tab)');
    await open(page, 'privacy/');
    const who = page.locator('section', { has: page.getByRole('heading', { name: 'Who “we” are' }) });
    await expect(who).toContainText('“We” on this page means the site’s maintainer, RAHV-FB');
    await expect(who.getByRole('link', { name: 'who maintains the site' })).toHaveAttribute('href', `${BASE_PATH}about#contact`);
    await expect(who.getByRole('link', { name: /issue tracker on GitHub/ })).toHaveAttribute('href', 'https://github.com/RAHV-FB/eu-intel/issues');
  });

  test('no page breaks the Content-Security-Policy, which allows no inline styles; style props still apply', async ({ page }) => {
    // the securitypolicyviolation event is fired in every engine, whether or not it logs the violation to the console
    await page.addInitScript(() => {
      const w = window as unknown as { cspViolations: string[] };
      w.cspViolations = [];
      window.addEventListener('securitypolicyviolation', (e) => w.cspViolations.push(`${e.violatedDirective} ${e.blockedURI}`), true);
    });
    const routes = [
      '', 'legislation/', `legislation/${AI_ACT_ID}/`, 'votes/', 'votes/199380/', 'people/', 'people/groups/renew/',
      'people/meps/197619/', 'people/parties/5719/', 'countries/IE/', 'how-the-eu-works/', 'about/', 'privacy/',
      'following/', 'search/?q=climate',
    ];
    for (const route of routes) {
      await page.goto(pagesUrl(route)); // the prerendered shell, as GitHub Pages serves it
      await settle(page);
      expect(await page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations), route).toEqual([]);
    }
    // a React style prop (set through the CSSOM, which the policy does not restrict): the largest country's share bar
    await page.goto(pagesUrl('people/groups/renew/'));
    await settle(page);
    const bar = page.locator('.share-bar').first();
    await expect(bar).toHaveAttribute('style', /width: 100%/);
    expect((await bar.boundingBox())?.width).toBeGreaterThan(0);
    // an interaction that re-renders with style props: sorting the countries
    await page.getByRole('button', { name: /^Members/ }).first().click();
    expect(await page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations)).toEqual([]);
  });

  test('only links to official EU websites are announced as official', async ({ page }) => {
    // the project's own GitHub pages (editorial policy, data/curated, issues) and GitHub's privacy statement are not
    let others = 0;
    for (const path of ['about/', 'privacy/', `legislation/${AI_ACT_ID}/`]) {
      await open(page, path);
      for (const link of await page.locator('main a[target="_blank"]:visible').all()) {
        const official = /(^|\.)europa\.eu$/.test(new URL((await link.getAttribute('href'))!).hostname);
        if (!official) others++;
        await expect(link).toHaveAccessibleName(official ? / \(opens official website in a new tab\)$/ : / \(opens in a new tab\)$/);
      }
    }
    expect(others).toBe(6);
  });

  test('the Atom feed links say they are for feed readers', async ({ page }) => {
    await open(page, '');
    const feed = page.getByRole('navigation', { name: 'Footer' }).getByRole('link', { name: 'Atom feed (for feed readers)' });
    await expect(feed).toHaveAttribute('href', `${BASE_PATH}data/feeds/updates.xml`);
    await open(page, 'legislation/?topic=environment');
    await expect(page.getByRole('link', { name: 'Atom feed for this topic (for feed readers)' })).toHaveAttribute(
      'href',
      `${BASE_PATH}data/feeds/environment.xml`,
    );
  });

  for (const width of [320, 375]) {
    test(`the topic feed link fits a ${width}px screen`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await open(page, 'legislation/?topic=environment');
      const link = page.getByRole('link', { name: 'Atom feed for this topic (for feed readers)' });
      await link.scrollIntoViewIfNeeded();
      const box = await link.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    });
  }

  test('links to the official hosts that serve https open as https; the identifier is shown as published', async ({ page }) => {
    await open(page, `legislation/${AI_ACT_ID}/`);
    await expect(page.locator('a[href^="http://"]')).toHaveCount(0);
    // the identifier is under "Details & sources", closed until opened: read the DOM
    const eli = page.locator('a[href="https://data.europa.eu/eli/reg/2024/1689/oj"]').first();
    await expect(eli).toHaveCount(1);
    expect(await eli.textContent()).toContain('http://data.europa.eu/eli/reg/2024/1689/oj');
    expect(await page.locator('a[href^="https://www.europarl.europa.eu/RegData/"]').count()).toBeGreaterThan(0);
  });
});

test.describe('group names and topic labels when their files cannot be loaded', () => {
  const fail = (path: string) => async ({ page }: { page: import('@playwright/test').Page }) => {
    await page.route(`**/data/${path}`, (route) => route.fulfill({ status: 500, body: 'unavailable' }));
  };

  test('groups.json: the country and party pages and the MEP filter show codes, and say so', async ({ page, guard }) => {
    guard.ignore(/groups\.json/);
    await fail('people/groups.json')({ page });
    await open(page, 'countries/IE/');
    await expect(page.getByRole('alert')).toContainText('Political group names could not be loaded. The names shown here come from a built-in list');
    const rows = page.locator('#representation table').first();
    await expect(rows).toContainText('Renew');
    await expect(rows).not.toContainText(/\brenew\b/);
    await open(page, 'people/parties/6848/'); // Rassemblement national, current record
    await expect(page.getByRole('alert')).toContainText('Political group names');
    await expect(page.locator('.group-chip').first()).not.toHaveText(/^[a-z-]+$/);
    await open(page, 'people/');
    await expect(page.getByRole('alert')).toContainText('Political group names');
    const options = await page.locator('#mf-group option').allTextContents();
    expect(options).toContain('Renew');
    expect(options).toContain('S&D');
    expect(options.filter((o) => /^[a-z-]+$/.test(o))).toEqual([]);
  });

  test('topics.json: the topic filter lists the topics, and the tags read as words', async ({ page, guard }) => {
    guard.ignore(/topics\.json/);
    await fail('topics.json')({ page });
    await open(page, 'legislation/?topic=environment');
    await expect(page.getByRole('alert')).toContainText('Topic names could not be loaded. The names shown here come from a built-in list');
    const select = page.locator('select').filter({ has: page.locator('option', { hasText: 'All topics' }) });
    await expect(select).toHaveCount(1);
    expect(await select.locator('option').allTextContents()).toEqual(
      expect.arrayContaining([expect.stringMatching(/^Environment & Energy \(/), expect.stringMatching(/^Technology & AI \(/)]),
    );
    await expect(page.locator('.chip, .lx-chips, [class*="chip"]').filter({ hasText: 'Topic: Environment & Energy' }).first()).toBeVisible();
    await open(page, `legislation/${AI_ACT_ID}/`);
    await expect(page.getByRole('alert')).toContainText('Topic names');
    await expect(page.locator('.dz-topics')).toContainText('Technology & AI');
    await expect(page.locator('.dz-topics')).not.toContainText(/\btech\b/);
    await open(page, 'votes/?topic=tech');
    await expect(page.locator('#vf-topic')).toContainText('Technology & AI');
  });

  test('nothing is said when they load', async ({ page }) => {
    for (const path of ['countries/IE/', 'people/', 'people/parties/6848/', 'legislation/?topic=environment', `legislation/${AI_ACT_ID}/`, 'votes/']) {
      await open(page, path);
      await expect(page.getByRole('alert'), path).toHaveCount(0);
    }
  });
});

test('the site name is still in every title', async ({ page }) => {
  await open(page, `legislation/${AI_ACT_ID}/`);
  expect(await page.title()).toContain(SITE_NAME);
});
