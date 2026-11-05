/**
 * When new rules apply (/legislation/applies): the dates fixed in law from which rules start to apply, by month, on the
 * reader's date; each with its file, where it applies and its record; filtered by window, topic and Member State, kept
 * in the address; the Atom feed and calendar of the selection; the links that lead to it. Examples are taken from the
 * data at run time (applies.json, meta.json), so the tests hold on any snapshot. See playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { APIRequestContext, Locator, Page } from '@playwright/test';
import type { AppliesData, ApplyingRule, Meta } from '../../src/types/data';
import { AI_ACT_ID, BASE_PATH, PAGES_ORIGIN } from './env';
import { expect, open, test } from './fixtures';

const DAY = 86_400_000;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const json = async <T>(request: APIRequestContext, path: string): Promise<T> => (await request.get(`data/${path}`)).json();
const plus = (d: string, n: number) => new Date(Date.parse(`${d}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);
/** Ahead on `today`: a transposition deadline until its day is over, any other date until its day (src/lib/format.ts). */
const ahead = (r: ApplyingRule, today: string) => (r.kind === 'transposition_deadline' ? r.date >= today : r.date > today);
const monthLabel = (d: string) => `${MONTHS[Number(d.slice(5, 7)) - 1]} ${d.slice(0, 4)}`;
const binds = (r: ApplyingRule, c: string) => !r.where.not_bound.some((x) => x.country === c);

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

/** Characters per rendered line of an element's text (as design.spec.ts counts them). */
const lineLengths = (l: Locator) =>
  l.evaluate((el) => {
    const rows = new Map<number, number>();
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const t = n as Text;
      for (let i = 0; i < t.data.length; i++) {
        const r = document.createRange();
        r.setStart(t, i);
        r.setEnd(t, i + 1);
        const rect = r.getClientRects()[0];
        if (rect) rows.set(Math.round(rect.top), (rows.get(Math.round(rect.top)) ?? 0) + 1);
      }
    }
    return [...rows.values()];
  });

async function setup(request: APIRequestContext) {
  const data = await json<AppliesData>(request, 'applies.json');
  // the page's clock starts at the build (tests/e2e/fixtures.ts), so its date is the build's
  const today = (await json<Meta>(request, 'meta.json')).built_at.slice(0, 10);
  return { data, today };
}

test.describe('When new rules apply', () => {
  test('lists the dates of the next 90 days by month, each with its file, where it applies and its record', async ({ page, request }) => {
    const { data, today } = await setup(request);
    const due = data.rows.filter((r) => ahead(r, today) && r.date <= plus(today, 90));
    test.skip(!due.length, 'no date in the next 90 days in this data');
    await open(page, 'legislation/applies/');
    await expect(page.locator('main h1')).toHaveText('When new rules apply');
    // a view of Legislation: its primary destination is the current one
    await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Legislation' })).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('.chg__count')).toContainText(`${due.length.toLocaleString('en-GB')} ${due.length === 1 ? 'date' : 'dates'} in the next 90 days`);
    const months = [...new Set(due.map((r) => r.date.slice(0, 7)))];
    await expect(page.locator('.chg-week__title')).toHaveText(months.map((m) => new RegExp(`^${monthLabel(m)} \\(`)));
    const rows = page.locator('li.ap');
    await expect(rows).toHaveCount(due.length);
    for (const i of new Set([0, 1, 2, due.length - 1])) {
      const r = due[i];
      if (!r) continue;
      const row = rows.nth(i);
      await expect(row.locator('time')).toHaveAttribute('datetime', r.date);
      await expect(row.locator('.ch__event')).toContainText(r.title);
      await expect(row.locator('.ch__file a')).toHaveAttribute('href', `${BASE_PATH}legislation/${r.dossier_id}`);
      await expect(row.locator('.ch__meta')).toContainText(r.act.label);
      await expect(row.locator('.ch__meta a[target="_blank"]').first()).toHaveAttribute('href', r.source.url);
      await expect(row.locator('.ap__where p')).toHaveText(/^Where: /);
    }
    // running text keeps a readable line length (WCAG 1.4.8), beside the date column and in small print too
    await page.setViewportSize({ width: 1440, height: 900 });
    const text = [
      ...(await page.locator('.page-header p, .ap-sub__note').all()),
      ...(await page.locator('li.ap .ch__body p, li.ap .ap__why li, li.ap .ch__meta').all()).slice(0, 30),
    ];
    for (const l of text) expect(Math.max(...(await lineLengths(l)))).toBeLessThanOrEqual(80);
    await expectNoSeriousA11yViolations(page);
  });

  test('says “All 27 Member States” only when all 27 are bound, and why others are not bound or not known', async ({ page, request }) => {
    const { data, today } = await setup(request);
    const ahead12 = data.rows.filter((r) => ahead(r, today));
    // an act that binds most Member States but not all, or not known to (not a decision, whose addressees are not recorded)
    const partial = ahead12.find((r) => r.where.bound.length > 5 && (r.where.not_bound.length > 0 || r.where.unknown.length > 0));
    test.skip(!partial, 'every date ahead binds all 27 Member States in this data');
    await open(page, 'legislation/applies/?when=all');
    const row = page.locator('li.ap', { has: page.locator(`.ch__file a[href="${BASE_PATH}legislation/${partial!.dossier_id}"]`) }).filter({
      has: page.locator(`time[datetime="${partial!.date}"]`),
    });
    const where = row.first().locator('.ap__where');
    await expect(where.locator('p')).not.toContainText('All 27');
    await expect(where.locator('p')).toContainText(`${partial!.where.bound.length} Member States`);
    for (const x of partial!.where.not_bound) await expect(where.locator('.ap__why')).toContainText(x.reason);
    if (partial!.where.unknown.length) await expect(where.locator('.ap__why')).toContainText('No record in our data');
    const all = ahead12.find((r) => r.where.bound.length === 27);
    if (all) await expect(page.locator('li.ap .ap__where p', { hasText: 'All 27 Member States' }).first()).toBeVisible();
  });

  test('a Member State lists the acts that bind it, or of which it is not known, with its own feed and calendar', async ({ page, request }) => {
    const { data, today } = await setup(request);
    const year = data.rows.filter((r) => ahead(r, today) && r.date <= plus(today, 365));
    // a Member State that some act of the next 12 months does not bind (Denmark, Ireland), else any
    const c = ['DK', 'IE'].find((x) => year.some((r) => !binds(r, x))) ?? 'FR';
    const mine = year.filter((r) => binds(r, c));
    test.skip(!mine.length, 'no date in the next 12 months in this data');
    await open(page, 'legislation/applies/?when=12m');
    await page.getByLabel('Member State').selectOption(c);
    await expect(page).toHaveURL(new RegExp(`country=${c}`));
    await expect(page.locator('main h1')).toHaveText(new RegExp(`^When new rules apply in `));
    await expect(page.locator('li.ap')).toHaveCount(mine.length);
    // its feeds: the Atom feed of the next 90 days and the calendar of every date, announced in <head> too
    const feed = `${BASE_PATH}data/feeds/applies/countries/${c}.xml`;
    await expect(page.locator('.chg__feeds a', { hasText: 'Atom feed' }).last()).toHaveAttribute('href', feed);
    await expect(page.locator('head link#page-feed')).toHaveAttribute('href', feed);
    const ics = page.locator('.chg__feeds a', { hasText: 'calendar (.ics)' }).last();
    await expect(ics).toHaveAttribute('href', `${BASE_PATH}data/feeds/applies/countries/${c}.ics`);
    // as GitHub Pages serves them: a calendar of whole-day events, lines ending in CRLF
    const res = await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/feeds/applies/countries/${c}.ics`);
    expect(res.headers()['content-type']).toMatch(/^text\/calendar/);
    const cal = await res.text();
    expect(cal.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n')).toBe(true);
    expect(cal).toContain('DTSTART;VALUE=DATE:');
    const atom = await (await request.get(`${PAGES_ORIGIN}${feed}`)).text();
    expect(atom).toContain('<feed xmlns="http://www.w3.org/2005/Atom">');
    // the filters are kept in the address: Back returns to the same list
    await page.getByLabel('When').selectOption('30');
    await expect(page).toHaveURL(/when=30/);
    await expectNoSeriousA11yViolations(page);
  });

  test('judges the dates on the reader’s date: a date that has come moves to the last 30 days, in the past tense', async ({ page, request }) => {
    const { data, today } = await setup(request);
    // an entry into force or a date from which rules apply (a deadline passes a day later; a national application date's
    // wording has no tense)
    const r = data.rows.find((x) => ahead(x, today) && (x.kind === 'entry_into_force' || x.kind === 'applies') && x.date <= plus(today, 60));
    test.skip(!r, 'no date within 60 days in this data');
    const id = `${BASE_PATH}legislation/${r!.dossier_id}`;
    const row = () => page.locator('li.ap').filter({ has: page.locator(`time[datetime="${r!.date}"]`) }).filter({ has: page.locator(`.ch__file a[href="${id}"]`) });
    await open(page, 'legislation/applies/');
    await expect(row().first().locator('.ch__event')).toContainText(r!.title);
    // the day after its date, it is no longer ahead
    await page.clock.setFixedTime(Date.parse(`${plus(r!.date, 1)}T12:00:00Z`));
    await open(page, 'legislation/applies/');
    await expect(row()).toHaveCount(0);
    await open(page, 'legislation/applies/?when=past');
    await expect(page.locator('.chg__count')).toContainText('in the last 30 days');
    await expect(row().first().locator('.ch__event')).not.toContainText(r!.title);
    await expect(row().first().locator('.ch__event')).toContainText(/started|Entered/);
  });

  test('narrows the dates by topic and offers the topic’s feed', async ({ page, request }) => {
    const { data, today } = await setup(request);
    const due = data.rows.filter((r) => ahead(r, today) && r.date <= plus(today, 90));
    const topic = due.flatMap((r) => r.topics)[0];
    test.skip(!topic, 'no date with a topic in the next 90 days');
    await open(page, `legislation/applies/?topic=${topic}`);
    await expect(page.locator('li.ap')).toHaveCount(due.filter((r) => r.topics.includes(topic)).length);
    await expect(page.locator('.chg__feeds a', { hasText: 'Atom feed' }).last()).toHaveAttribute('href', `${BASE_PATH}data/feeds/applies/topics/${topic}.xml`);
    await page.getByRole('button', { name: 'Next 90 days, every topic and Member State' }).click();
    await expect(page).toHaveURL(/\/legislation\/applies\/?$/);
  });

  test('is reached from the explorer, the home page’s “Coming up” and a file’s “When it applies”', async ({ page, request }) => {
    await open(page, 'legislation/');
    await expect(page.getByRole('link', { name: 'When new rules apply, by Member State' })).toHaveAttribute('href', `${BASE_PATH}legislation/applies`);
    await open(page, './');
    const upcoming = page.locator('section[aria-labelledby="hl-upcoming"]');
    if (await upcoming.count()) {
      await expect(upcoming.getByRole('link', { name: /^All upcoming dates, by topic and Member State/ })).toHaveAttribute(
        'href',
        `${BASE_PATH}legislation/applies?when=12m`,
      );
    }
    // a file with a date ahead: the AI Act while it has one, else the first file of the list
    const { data, today } = await setup(request);
    const file = data.rows.find((r) => r.dossier_id === AI_ACT_ID && ahead(r, today)) ?? data.rows.find((r) => ahead(r, today));
    test.skip(!file, 'no date ahead in this data');
    await open(page, `legislation/${file!.dossier_id}/`);
    await expect(page.locator('#when-it-applies').getByRole('link', { name: 'When new rules apply' })).toHaveAttribute(
      'href',
      `${BASE_PATH}legislation/applies`,
    );
  });

  test('answers at its own address with its title and its feed in the page’s head', async ({ request }) => {
    const res = await request.get(`${PAGES_ORIGIN}${BASE_PATH}legislation/applies/`);
    expect(res.status()).toBe(200);
    const html = await res.text();
    expect(html).toContain('<title>When new rules apply – Legislation – EU Legislative Intelligence</title>');
    expect(html).toMatch(new RegExp(`<link rel="alternate" type="application/atom\\+xml" id="page-feed"[^>]*href="${BASE_PATH}data/feeds/applies/all\\.xml"`));
  });

  test('fits a phone screen without scrolling sideways', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    await open(page, 'legislation/applies/?when=all');
    const [scroll, client] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    expect(scroll).toBeLessThanOrEqual(client);
  });
});
