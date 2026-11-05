/**
 * The deploy's smoke test of the site it is about to publish (.github/workflows/pages.yml, before the upload): pages
 * picked from that build's own data (dist/data) when the test runs, opened in Chromium on the reader's real clock. The
 * other browser tests run on the frozen test data (tests/frozen-data.txt) as of its build time; this one checks that the
 * data being deployed renders: legislative files of every stage, votes of every kind, MEPs, groups and parties, every
 * country, search and the main pages. A page fails on a console error, an uncaught exception, a failed or third-party
 * request (the guard of tests/e2e/fixtures.ts), the error page, a "not found" page or an empty heading. The sitemap,
 * which only the deploy's build (with SITE_URL) has, must list those pages.
 *
 *   python -m pipeline build && BASE_PATH=/eu-intel/ npm run build && E2E_LIVE=1 npx playwright test --project=chromium
 *
 * The pages come from tests/e2e/pages-server.mjs, which answers as GitHub Pages does (a prerendered page per route).
 */
import { readFileSync } from 'node:fs';
import type { Page } from '@playwright/test';
import { BASE_PATH, PAGES_ORIGIN } from './env';
import { evenSample, expect, settle, test } from './fixtures';

test.use({ clockAtBuild: false }); // the reader's clock: the deployed data is read for a week or more after its build

type Row = Record<string, unknown>;

/** A list file of the build (dist/data/<rel>); [] when it cannot be read, which the first test reports. */
function rows(rel: string): Row[] {
  try {
    const data: unknown = JSON.parse(readFileSync(`dist/data/${rel}`, 'utf8'));
    return Array.isArray(data) ? (data as Row[]) : [];
  } catch {
    return [];
  }
}

/** `n` rows: the first row with each value of `key`, so that every kind is opened, then an even sample of the rest. */
function spread(all: Row[], key: string, n: number): Row[] {
  const first = new Map<unknown, Row>();
  for (const r of all) if (!first.has(r[key])) first.set(r[key], r);
  const picked = [...first.values()];
  return [...picked, ...evenSample(all.filter((r) => !picked.includes(r)), Math.max(0, n - picked.length))];
}

const data = {
  dossiers: rows('dossiers/index.json'),
  votes: rows('votes/index.json'),
  meps: rows('people/meps.json'),
  groups: rows('people/groups.json'),
  parties: rows('people/parties.json'),
  countries: rows('countries/index.json'),
};

const PAGES: [name: string, path: string][] = [
  ['home', ''],
  ['legislation', 'legislation/'],
  ['when new rules apply', 'legislation/applies/'], // applies.json, read on the real clock
  ['votes', 'votes/'],
  ['people', 'people/'],
  ['countries', 'countries/'],
  ['insights', 'insights/'],
  ['about', 'about/'],
  ['how the EU works', 'how-the-eu-works/'],
  ...spread(data.dossiers, 'stage', 20).map((d): [string, string] => [`file ${d.id} (${d.stage})`, `legislation/${d.id}/`]),
  ...spread(data.votes, 'kind', 10).map((v): [string, string] => [`vote ${v.id} (${v.kind})`, `votes/${v.id}/`]),
  ...spread(data.meps, 'active', 5).map((m): [string, string] => [`MEP ${m.id}`, `people/meps/${m.id}/`]),
  ...evenSample(data.groups, 3).map((g): [string, string] => [`group ${g.id}`, `people/groups/${g.id}/`]),
  ...evenSample(data.parties, 3).map((p): [string, string] => [`party ${p.id}`, `people/parties/${p.id}/`]),
  ...data.countries.map((c): [string, string] => [`country ${c.code}`, `countries/${c.code}/`]),
];

async function openLive(page: Page, path: string) {
  const res = await page.goto(`${PAGES_ORIGIN}${BASE_PATH}${path}`);
  expect(res?.status(), `HTTP status of ${path || 'the homepage'}`).toBe(200);
  await settle(page);
}

/** Rendered: a heading, and neither the error page, a "not found" page nor an error message. */
async function expectRendered(page: Page) {
  const h1 = page.locator('main h1').first();
  await expect(h1).not.toBeEmpty();
  await expect(h1).not.toHaveText(/could not be (displayed|loaded)|couldn.t find this/i);
  await expect(page.locator('.state--error'), 'an error message on the page').toHaveCount(0);
}

test('the build lists files, votes, people and countries to open', () => {
  for (const [name, list] of Object.entries(data)) expect(list.length, `dist/data rows: ${name}`).toBeGreaterThan(0);
});

for (const [name, path] of PAGES) {
  test(`renders: ${name}`, async ({ page }) => {
    await openLive(page, path);
    await expectRendered(page);
  });
}

test('the sitemap lists the pages opened above, and robots.txt names it', async ({ page, request }) => {
  // only a build with SITE_URL (the deploy's) has a sitemap: its addresses are absolute, from the canonical links
  const site = /<link rel="canonical" href="([^"]+)"/.exec(readFileSync('dist/index.html', 'utf8'))?.[1];
  test.skip(!site, 'built without SITE_URL: no sitemap');
  const get = async (path: string) => {
    const res = await request.get(`${PAGES_ORIGIN}${BASE_PATH}${path}`);
    expect(res.status(), path).toBe(200);
    return res.text();
  };
  expect(await get('robots.txt')).toContain(`Sitemap: ${site}sitemap.xml`);
  // the addresses of a sitemap file, or of the files a sitemap index lists; null when it is not well-formed XML
  const locs = (xml: string) =>
    page.evaluate((x) => {
      const doc = new DOMParser().parseFromString(x, 'application/xml');
      if (doc.getElementsByTagName('parsererror').length) return null;
      return { index: doc.documentElement.localName === 'sitemapindex', locs: [...doc.getElementsByTagName('loc')].map((l) => l.textContent ?? '') };
    }, xml);
  const top = await locs(await get('sitemap.xml'));
  expect(top, 'sitemap.xml is well-formed').not.toBeNull();
  const listed: string[] = [];
  for (const f of top!.index ? top!.locs : []) listed.push(...((await locs(await get(f.slice(site!.length))))?.locs ?? []));
  if (!top!.index) listed.push(...top!.locs);
  for (const [name, path] of PAGES) expect(listed, name).toContain(site + path);
});

test('search finds a file by its procedure reference', async ({ page }) => {
  const d = data.dossiers.find((x) => typeof x.ref === 'string');
  expect(d, 'a file with a procedure reference').toBeTruthy();
  await openLive(page, `search/?q=${encodeURIComponent(String(d!.ref))}`);
  await expectRendered(page);
  await expect(page.locator(`.sr-item__title[href$="legislation/${d!.id}"]`).first()).toBeVisible();
});
