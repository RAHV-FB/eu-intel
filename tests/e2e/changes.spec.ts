/**
 * What changed (/legislation/changes) and the home page's "This week in EU law", lists that name each file's latest
 * step, each file's own Atom feed and the OPML of the files a reader follows, the stuck view, and searches that find
 * nothing. Examples are taken from the data at run time (activity.json, dossiers/index.json), so the tests hold on any
 * snapshot. See playwright.config.ts to run.
 */
import { readFileSync } from 'node:fs';
import type { APIRequestContext, Locator } from '@playwright/test';
import type { ActivityItem, DossierSummary, Meta } from '../../src/types/data';
import { AI_ACT_ID, BASE_PATH, PAGES_ORIGIN } from './env';
import { expect, open, test } from './fixtures';

const DAY = 86_400_000;
const HOUR = 3_600_000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** "4 Nov 2026", as the site writes a date in lists */
const date = (d: string) => {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  return `${day} ${MONTHS[m - 1]} ${y}`;
};
const ACTIVE = ['proposed', 'parliament_position', 'negotiations', 'provisional_agreement'];

const json = async <T>(request: APIRequestContext, path: string): Promise<T> => (await request.get(`data/${path}`)).json();
const pageTop = (l: Locator) => l.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);

test.describe('What changed', () => {
  test('the home page opens with the latest recorded changes, each with its file and official record', async ({ page, request }) => {
    const items = await json<ActivityItem[]>(request, 'activity.json');
    const meta = await json<Meta>(request, 'meta.json');
    const latest = items.reduce((m, i) => (i.detected_at && i.detected_at > m ? i.detected_at : m), '');
    test.skip(!latest, 'no change recorded in this data');
    await open(page, './');
    const strip = page.locator('section.tw');
    // "this week" while the latest refresh is at most a week old on the reader's date (the page's clock: the build)
    const current = Date.parse(meta.built_at) - Date.parse(latest) <= 7 * DAY;
    await expect(strip.getByRole('heading', { level: 2 })).toHaveText(current ? 'This week in EU law' : 'Latest changes in EU law');
    // near the top: before the editorial selection and the generated lists
    expect(await pageTop(strip)).toBeLessThan(await pageTop(page.locator('#featured-title')));
    const rows = strip.locator('.ch');
    expect(await rows.count()).toBeGreaterThan(0);
    for (const row of await rows.all()) {
      await expect(row.locator('.ch__event, .ch__status').first()).not.toBeEmpty();
      await expect(row.locator('.ch__meta a[target="_blank"]').first()).toHaveAttribute('href', /^https:\/\//);
    }
    // the counts by kind lead to the page filtered by that kind
    const count = strip.locator('.tw__counts a').first();
    await expect(count).toHaveAttribute('href', new RegExp(`^${BASE_PATH}legislation/changes\\?kind=\\w+$`));
    await strip.getByRole('link', { name: /^All [\d,]+ changes/ }).click();
    await expect(page).toHaveURL(/\/legislation\/changes$/);
    await expect(page.locator('main h1')).toHaveText('What changed');
  });

  test('on a phone the strip comes after the hero, on the second screen', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, './');
    expect(await pageTop(page.locator('#tw-title'))).toBeLessThan(2 * 844);
    // three changes on a phone; the page lists them all
    await expect(page.locator('section.tw .ch:visible')).toHaveCount(Math.min(3, await page.locator('section.tw .ch').count()));
  });

  test('lists each change by week and by topic, a status change with the step that gave it', async ({ page, request }) => {
    const items = await json<ActivityItem[]>(request, 'activity.json');
    const index = await json<DossierSummary[]>(request, 'dossiers/index.json');
    await open(page, 'legislation/changes/');
    await expect(page.locator('main h1')).toHaveText('What changed');
    // a view of Legislation: its primary destination is the current one
    await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Legislation' })).toHaveAttribute('aria-current', 'page');
    const paired = items.filter((i) => i.step_id && items.some((j) => j.id === i.step_id));
    await expect(page.locator('.chg__count')).toContainText(`${(items.length - paired.length).toLocaleString('en-GB')} changes`);
    const week = page.locator('.chg-week').first();
    await expect(week.locator('h2')).toHaveText(/^Week of \d{1,2} \w+ \d{4} \(/);
    expect(await week.locator('.chg-topic').count()).toBeGreaterThan(0);

    // a status change and its step: one row, saying what happened and the status it gave (the latest recorded one, in
    // the first week listed)
    const s = paired.filter((i) => i.dossier_id).sort((a, b) => (b.detected_at ?? '').localeCompare(a.detected_at ?? ''))[0];
    test.skip(!s, 'no status change paired with its step in this data');
    const step = items.find((i) => i.id === s!.step_id)!;
    const file = index.find((d) => d.id === s!.dossier_id)!;
    const ofFile = page.locator('.ch').filter({ has: page.locator(`.ch__file a[href="${BASE_PATH}legislation/${file.id}"]`) });
    const thatDay = ofFile.filter({ has: page.locator('.ch__date', { hasText: date(s!.date) }) }).filter({ hasText: step.event! });
    expect(await thatDay.count()).toBeGreaterThan(0); // under each topic of the file
    await expect(thatDay.filter({ hasNot: page.locator('.ch__status') })).toHaveCount(0); // the step is not listed alone
    await page.getByLabel('Kind of change').selectOption('status');
    await expect(page).toHaveURL(/kind=status/);
    const row = thatDay.first();
    await expect(row.locator('.ch__event')).toHaveText(step.event!);
    await expect(row.locator('.ch__status')).toContainText('Status now “');
    await expect(row.locator(`.ch__meta a[href="${s!.source!.url}"]`)).toHaveCount(1);
    for (const status of await page.locator('.ch').all()) await expect(status.locator('.ch__status')).toHaveCount(1);

    // one topic: its changes, and its Atom feed
    const topic = file.topics[0];
    test.skip(!topic, 'the file has no topic');
    await page.getByLabel('Topic').selectOption(topic);
    await expect(page).toHaveURL(new RegExp(`topic=${topic}`));
    await expect(page.locator('main h1')).toHaveText(/^What changed: /);
    const feed = page.locator('.chg__feeds a', { hasText: '(Atom)' }).nth(1);
    await expect(feed).toHaveAttribute('href', `${BASE_PATH}data/feeds/${topic}.xml`);
    const xml = await (await request.get(`data/feeds/${topic}.xml`)).text();
    expect(xml).toContain('<feed xmlns="http://www.w3.org/2005/Atom">');
    await page.getByRole('button', { name: 'Show all changes' }).click();
    await expect(page).toHaveURL(/\/legislation\/changes\/?$/);
  });

  test('is reached from the Legislation page and the footer', async ({ page }) => {
    await open(page, 'legislation/');
    await expect(page.getByRole('link', { name: 'What changed recently, week by week' })).toHaveAttribute('href', `${BASE_PATH}legislation/changes`);
    await expect(page.locator('.site-footer').getByRole('link', { name: 'What changed' })).toHaveAttribute('href', `${BASE_PATH}legislation/changes`);
  });
});

test.describe('the latest step', () => {
  test('lists name each file’s latest recorded step, not only its date', async ({ page, request }) => {
    const index = await json<DossierSummary[]>(request, 'dossiers/index.json');
    const d = index.find((x) => x.featured && x.last_step && x.last_event && !x.steps_ahead?.length);
    test.skip(!d, 'no featured file with a named latest step');
    const named = `Latest step: ${d!.last_step!.title} · ${date(d!.last_event!)}`;
    await open(page, `legislation/?q=${encodeURIComponent(d!.ref)}`);
    await expect(page.locator('.drow').first().locator('.drow__step')).toHaveText(named);
    await open(page, `search/?q=${encodeURIComponent(d!.ref)}`);
    await expect(page.locator('.sr-item').first()).toContainText(named);
    // the home page's rows dated by a file's latest step name it
    await open(page, './');
    const rows = page.locator('section[aria-labelledby="hl-under_debate"] .hl__row');
    expect(await rows.count()).toBeGreaterThan(0);
    for (const row of await rows.all()) await expect(row.locator('.hl__step')).not.toBeEmpty();
  });
});

test.describe('the stuck view', () => {
  test('the home page’s “Stalled” list leads to the files still being decided, longest without a recorded step first', async ({ page }) => {
    await open(page, './');
    const more = page.locator('section[aria-labelledby="hl-stalled"] .hl__more');
    await expect(more).toHaveAttribute('href', `${BASE_PATH}legislation?stage=active&type=COD&sort=stuck`);
    await more.click();
    await expect(page).toHaveURL(/stage=active&type=COD&sort=stuck/);
    await expect(page.locator('.lx-count')).toContainText('sorted by longest without a recorded step');
    await expect(page.getByLabel('Sort by')).toHaveValue('stuck');
    const rows = page.locator('.drow');
    const dates = await rows.locator('.drow__step time').evaluateAll((ts) => ts.slice(0, 10).map((t) => t.getAttribute('datetime')!));
    expect(dates.length).toBeGreaterThan(1);
    expect([...dates].sort()).toEqual(dates); // the longest without a recorded step first
    await expect(rows.first().locator('.drow__stuck')).toHaveText(/^No recorded procedural step for [\d,]+ days/);
  });

  test('a file reported as blocked says so, and for how long it has had no recorded step, under its status', async ({ page, request }) => {
    const meta = await json<Meta>(request, 'meta.json');
    const index = await json<DossierSummary[]>(request, 'dossiers/index.json');
    const train = meta.sources.find((s) => s.id === 'train');
    const blocked = index.find((d) => d.officially_blocked && ACTIVE.includes(d.stage));
    test.skip(!train?.fetched_at || train.labels_expire_after_days == null || !blocked, 'no current Legislative Train copy or blocked file');
    const expires = Date.parse(train!.fetched_at!) + train!.labels_expire_after_days! * DAY;
    const line = page.locator('.dz-head .dz-stuck');
    await page.clock.setFixedTime(expires - HOUR);
    await open(page, `legislation/${blocked!.id}/`);
    await expect(line.locator('.dz-stuck__blocked')).toHaveText(/^Officially reported as blocked/);
    await expect(line).toContainText(/No recorded procedural step for [\d,]+ days/);
    await expect(line.getByRole('link', { name: 'Where it is now' })).toHaveAttribute('href', '#where');
    // once our copy of the Train has expired, no file is shown as blocked
    await page.clock.setFixedTime(expires + HOUR);
    await open(page, `legislation/${blocked!.id}/`);
    await expect(page.locator('.dz-stuck__blocked')).toHaveCount(0);
  });
});

test.describe('a search that finds nothing', () => {
  for (const path of ['search/?q=glyphosate', 'legislation/?q=glyphosate'])
    test(`says what the site covers and links the same search on EUR-Lex (${path})`, async ({ page }) => {
      await open(page, path);
      const note = page.locator('.out-of-scope');
      await expect(note).toContainText('What this site covers:');
      for (const out of ['Implementing and delegated acts', 'Non-legislative procedures', 'National law'])
        await expect(note.locator('li', { hasText: out })).toHaveCount(1);
      const eurlex = note.getByRole('link', { name: /^Search EUR-Lex for “glyphosate”/ });
      await expect(eurlex).toHaveAttribute('href', 'https://eur-lex.europa.eu/search.html?scope=EURLEX&text=glyphosate&lang=en&type=quick');
      await expect(eurlex).toHaveAttribute('rel', 'noopener noreferrer');
    });

  test('encodes the words it passes to EUR-Lex', async ({ page }) => {
    await open(page, 'search/?q=glyphosate%20%26%20neonicotinoids');
    await expect(page.locator('.out-of-scope a[href*="eur-lex.europa.eu"]')).toHaveAttribute(
      'href',
      'https://eur-lex.europa.eu/search.html?scope=EURLEX&text=glyphosate%20%26%20neonicotinoids&lang=en&type=quick',
    );
  });
});

test.describe('feeds', () => {
  test('each file has its own Atom feed, linked on its page and in its page’s head', async ({ page, request }) => {
    const index = await json<DossierSummary[]>(request, 'dossiers/index.json');
    const d = index.find((x) => x.id === AI_ACT_ID) ?? index[0];
    const href = `${BASE_PATH}data/feeds/dossiers/${d.id}.xml`;
    // the page GitHub Pages serves, before any script runs
    const html = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}legislation/${d.id}/`)).text();
    const tag = /<link rel="alternate" type="application\/atom\+xml" id="page-feed"[^>]*>/.exec(html)?.[0] ?? '';
    expect(tag).toContain(`href="${href}"`);
    expect(tag).toContain(`title="${d.ref}: updates (Atom)"`);
    const feed = await request.get(`data/feeds/dossiers/${d.id}.xml`);
    expect(feed.ok()).toBe(true);
    const xml = await feed.text();
    expect(xml).toContain(`<id>tag:rahv-fb.github.io,2026:eu-intel/feeds/dossiers/${d.id}.xml</id>`);
    expect(xml).toMatch(new RegExp(`<link rel="alternate" type="text/html" href="[^"]*/legislation/${d.id}/"/>`));

    await open(page, `legislation/${d.id}/`);
    await expect(page.getByRole('link', { name: 'Follow in a feed reader' })).toHaveAttribute('href', href);
    await expect(page.locator('head link#page-feed')).toHaveAttribute('href', href);
    // the next file's page announces its own; another page none
    const other = index.find((x) => x.id !== d.id)!;
    await page.evaluate((to) => {
      window.history.pushState({}, '', to);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, `${BASE_PATH}legislation/${other.id}`);
    await expect(page.locator('head link#page-feed')).toHaveAttribute('href', `${BASE_PATH}data/feeds/dossiers/${other.id}.xml`);
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Votes' }).click();
    await expect(page.locator('head link#page-feed')).toHaveCount(0);
  });

  test('the files a reader follows download as one OPML file, made in the browser', async ({ page }) => {
    await open(page, `legislation/${AI_ACT_ID}/`);
    await page.getByRole('button', { name: 'Follow this legislation' }).click();
    await open(page, 'following/');
    const link = page.getByRole('link', { name: 'Download the feed (OPML)' });
    await expect(link).toHaveAttribute('download', /^eu-legislation-following-\d{4}-\d{2}-\d{2}\.opml$/);
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
    const opml = readFileSync((await download.path())!, 'utf8');
    const origin = new URL(page.url()).origin;
    expect(opml).toContain('<opml version="2.0">');
    expect(opml).toContain(`xmlUrl="${origin}${BASE_PATH}data/feeds/dossiers/${AI_ACT_ID}.xml"`);
    expect(opml).toContain(`htmlUrl="${origin}${BASE_PATH}legislation/${AI_ACT_ID}/"`);
    expect(opml).toMatch(/text="[^"]+ \(2021\/0106\(COD\)\)"/);
  });
});
