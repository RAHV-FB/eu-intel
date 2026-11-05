/**
 * How fresh the data is, on the reader's date. The data is rebuilt weekly but read for a week or more, so whether a
 * source is up to date, and whether the Legislative Train's "blocked" is still shown, is judged against the reader's
 * clock from the dates and thresholds meta.json gives (src/lib/freshness.ts). Each test reads meta.json and sets its
 * own clock from it, so it holds whatever snapshot it runs against and whatever day it is run.
 */
import type { APIRequestContext } from '@playwright/test';
import type { DossierSummary, Meta } from '../../src/types/data';
import { BASE_PATH } from './env';
import { expect, open, test } from './fixtures';

const DAY = 86_400_000;
const HOUR = 3_600_000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
/** "22 Oct 2026" (or "22 October 2026"), as the site writes the date of a retrieval. */
const date = (ts: string, long = false) => {
  const [y, m, d] = ts.slice(0, 10).split('-').map(Number);
  return `${d} ${(long ? MONTHS_LONG : MONTHS)[m - 1]} ${y}`;
};

const json = async <T>(request: APIRequestContext, path: string): Promise<T> => (await request.get(`data/${path}`)).json();

/** The sources not up to date at `now`, by the data's own thresholds; a source never retrieved is not up to date. */
const staleAt = (meta: Meta, now: number) =>
  meta.sources.filter((s) => s.stale_after_days != null && (!s.fetched_at || now - Date.parse(s.fetched_at) > s.stale_after_days * DAY));
/** "Not up to date: A and B (last retrieved 2 Nov 2026); C (last retrieved 22 Oct 2026)" */
const noteAt = (meta: Meta, now: number) => {
  const byDay = new Map<string, string[]>();
  for (const s of staleAt(meta, now)) {
    const when = s.fetched_at ? `last retrieved ${date(s.fetched_at)}` : 'never retrieved';
    byDay.set(when, [...(byDay.get(when) ?? []), s.short_name || s.name]);
  }
  const join = (n: string[]) => (n.length > 1 ? `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}` : n[0]);
  return `Not up to date: ${[...byDay].map(([when, names]) => `${join(names)} (${when})`).join('; ')}`;
};

test('names the sources not up to date on the reader’s date, on home and in the footer, as the About page does', async ({ page, request }) => {
  const meta = await json<Meta>(request, 'meta.json');
  // the first moment a retrieved source passes its threshold: an hour before it only sources never retrieved are
  // stale; an hour after, that source is too
  const due = Math.min(
    ...meta.sources.filter((s) => s.fetched_at && s.stale_after_days != null).map((s) => Date.parse(s.fetched_at!) + s.stale_after_days! * DAY),
  );
  const [before, after] = [due - HOUR, due + HOUR];
  expect(staleAt(meta, after).length).toBeGreaterThan(staleAt(meta, before).length);

  const hero = page.locator('.home-hero');
  const footer = page.locator('.site-footer');
  await page.clock.setFixedTime(before);
  await open(page, './');
  // the headline date is the oldest retrieval of the core sources, never the newest of any source
  expect(meta.core_data_at).toBeTruthy();
  await expect(hero.locator('.home-hero__fresh')).toContainText(`Procedures, votes and acts current to ${date(meta.core_data_at!)}`);
  await expect(footer).toContainText(`Procedures, votes and acts current to ${date(meta.core_data_at!)}`);
  if (staleAt(meta, before).length) await expect(hero.locator('.home-hero__stale')).toHaveText(noteAt(meta, before));
  else {
    await expect(hero.locator('.home-hero__stale')).toHaveCount(0);
    await expect(footer).not.toContainText('Not up to date');
  }

  await page.clock.setFixedTime(after);
  await open(page, './');
  const note = hero.locator('.home-hero__stale');
  await expect(note).toHaveText(noteAt(meta, after));
  await expect(footer.getByRole('link', { name: noteAt(meta, after) })).toHaveAttribute('href', `${BASE_PATH}about#sources`);
  await note.getByRole('link').click();
  await expect(page).toHaveURL(/\/about\/?#sources$/);
  const stale = new Set(staleAt(meta, after).map((s) => s.id));
  for (const s of meta.sources) {
    const card = page.locator('.source-card', { has: page.locator(`#src-${s.id}`) });
    if (stale.has(s.id)) await expect(card.locator('.source-card__stale'), s.id).toHaveText('· Not up to date');
    else await expect(card.locator('.source-card__stale'), s.id).toHaveCount(0);
  }
});

test('stops showing the Legislative Train’s “blocked” as current once its copy is older than its limit', async ({ page, request }) => {
  const meta = await json<Meta>(request, 'meta.json');
  const train = meta.sources.find((s) => s.id === 'train');
  const index = await json<DossierSummary[]>(request, 'dossiers/index.json');
  const active = ['proposed', 'parliament_position', 'negotiations', 'provisional_agreement'];
  const blocked = index.find((d) => d.officially_blocked && active.includes(d.stage));
  test.skip(!train?.fetched_at || train.labels_expire_after_days == null || !blocked, 'no current Legislative Train copy or blocked file');
  const expires = Date.parse(train!.fetched_at!) + train!.labels_expire_after_days! * DAY;
  const status = page.locator('.dz-official-status');
  const badge = page.locator('.dz-statusline .badge');

  await page.clock.setFixedTime(expires - HOUR);
  await open(page, `legislation/${blocked!.id}/`);
  await expect(status).toHaveClass(/is-blocked/);
  await expect(status).toContainText('Officially reported as blocked');
  await expect(status).toContainText(`Legislative Train, as retrieved ${date(train!.fetched_at!, true)}`);
  await expect(badge).toHaveClass(/badge--alert/);

  await page.clock.setFixedTime(expires + HOUR);
  await open(page, `legislation/${blocked!.id}/`);
  await expect(status).not.toHaveClass(/is-blocked/);
  await expect(status).toContainText(
    `classification of this file is not shown: our latest copy of the Legislative Train was retrieved on ${date(train!.fetched_at!, true)}`,
  );
  await expect(badge).not.toHaveClass(/badge--alert/);
  // the explorer's filter and the home page's "Stalled" list agree
  await open(page, 'legislation/?blocked=1');
  await expect(page.locator('.lx-count')).toContainText('0 files match');
  await expect(page.locator('main .callout')).toContainText('reports as blocked are not shown');
  await open(page, './');
  const stalled = page.locator('section[aria-labelledby="hl-stalled"]'); // none once only blocked files were in it
  if (await stalled.count()) await expect(stalled.locator('.hl__desc')).toContainText('reports as blocked are not listed');
  await expect(page.locator('.hl__badge', { hasText: 'Officially blocked' })).toHaveCount(0);
  await expect(page.locator('.fcard .badge--alert')).toHaveCount(0);
});

test('does not say that no file is blocked when it cannot read the Legislative Train’s classifications', async ({ page, guard }) => {
  // without meta.json the page cannot tell whether its copy of the Train is current: it shows no file as blocked and
  // says why, instead of "No file is officially reported as blocked" (15 were on 5 November 2026)
  guard.ignore(/meta\.json|Failed to load resource|net::ERR_FAILED/);
  await page.route('**/data/meta.json', (route) => route.abort());
  await open(page, 'legislation/?blocked=1');
  const note = 'The Legislative Train Schedule’s classifications could not be loaded, so no file is shown as officially blocked.';
  await expect(page.locator('main .callout')).toContainText(note);
  await expect(page.locator('main')).not.toContainText('No file is officially reported as blocked');
  await open(page, 'legislation/');
  await expect(page.locator('main')).not.toContainText('No file is officially reported as blocked');
  await expect(page.locator('main')).toContainText(note);
});
