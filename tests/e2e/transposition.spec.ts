/**
 * The implementation tracker (plan item 2.5): one address per directive (/legislation/<id>/#national, with ?country=XX
 * highlighting a Member State's row), on the preview server and with GitHub Pages semantics; the time since a deadline on
 * the reader's date; the "Directives into national law" page (/legislation/transposition) and its filters; the country
 * pages' links and Atom feeds. Every example is picked from the data under test (dist/data/transposition.json), so the
 * tests hold on the frozen test data and on live data alike.
 */
import { readFileSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import type { DossierDetail, Meta, TrackedDirective, TranspositionStatus, TranspositionTracker } from '../../src/types/data';
import { BASE_PATH, PAGES_ORIGIN, SITE_NAME } from './env';
import { expect, open, settle, test } from './fixtures';

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 5).map((n) => n.target.join(' ')).join(' | ')}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

function read<T>(rel: string): T | null {
  try {
    return JSON.parse(readFileSync(`dist/data/${rel}`, 'utf8')) as T;
  } catch {
    return null;
  }
}

const DAY = 86_400_000;
const addDays = (d: string, n: number) => new Date(Date.parse(`${d}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);
/** The same day `n` months later, or the month's last day (as src/lib/deadline.ts addMonths). */
const addMonths = (d: string, n: number) => {
  const [y, m, day] = d.split('-').map(Number);
  const i = y * 12 + (m - 1) + n;
  const ty = Math.floor(i / 12);
  const tm = i - ty * 12;
  const last = new Date(Date.UTC(ty, tm + 1, 0)).getUTCDate();
  return new Date(Date.UTC(ty, tm, Math.min(day, last))).toISOString().slice(0, 10);
};
// as the site names the Member States (src/lib/format.ts COUNTRY_NAMES)
const NAMES: Record<string, string> = {
  AT: 'Austria', BE: 'Belgium', BG: 'Bulgaria', HR: 'Croatia', CY: 'Cyprus', CZ: 'Czechia', DK: 'Denmark', EE: 'Estonia',
  FI: 'Finland', FR: 'France', DE: 'Germany', GR: 'Greece', HU: 'Hungary', IE: 'Ireland', IT: 'Italy', LV: 'Latvia',
  LT: 'Lithuania', LU: 'Luxembourg', MT: 'Malta', NL: 'Netherlands', PL: 'Poland', PT: 'Portugal', RO: 'Romania',
  SK: 'Slovakia', SI: 'Slovenia', ES: 'Spain', SE: 'Sweden',
};

const meta = read<Meta>('meta.json');
const tracker = read<TranspositionTracker>('transposition.json');
/** The page's clock starts at the build (tests/e2e/fixtures.ts): the reader's date is the build's. */
const today = meta?.built_at.slice(0, 10) ?? '';
/** A status as the page states it on `on`: no measures is "Deadline not yet reached" until the deadline's day is over. */
const statusOn = (s: TranspositionStatus, deadline: string, on: string): TranspositionStatus =>
  s === 'deadline_not_reached' && deadline < on ? 'none_found' : s === 'none_found' && deadline >= on ? 'deadline_not_reached' : s;
const inWindow = (tracker?.directives ?? []).filter((d) => d.deadline >= addMonths(today, -36) && d.deadline <= addMonths(today, 12));

/** A directive whose file shows it as its (first) table, so that #national is its table. */
function mainTable(d: TrackedDirective): boolean {
  if (!d.dossier_id) return false;
  return read<DossierDetail>(`dossiers/${d.dossier_id}.json`)?.implementation?.celex === d.celex;
}
// a deadline passed by the build, with Member States without measures and others with them
const passed = inWindow.find(
  (d) =>
    d.deadline < today &&
    d.countries.some((c) => c.status === 'none_found' && !c.participation_unknown) &&
    d.countries.some((c) => c.status === 'measures_notified' && c.cases?.length) &&
    mainTable(d),
);
// a deadline still ahead at the build, with Member States without measures yet
const ahead = inWindow.find((d) => d.deadline > today && d.countries.some((c) => c.status === 'deadline_not_reached') && mainTable(d));
// a Member State with an open case on a directive of the window (its row in the tracker's country view)
const withCase = passed?.countries.find((c) => c.status === 'measures_notified' && c.cases?.length);
const name = (code: string) => NAMES[code] ?? code;

const headerBottom = (page: Page) => page.locator('.site-header').evaluate((el) => el.getBoundingClientRect().bottom);
const top = (l: Locator) => l.evaluate((el) => el.getBoundingClientRect().top);

test.describe('one address per directive: its table on its file’s page', () => {
  test.skip(!passed || !withCase, 'no directive with a passed deadline and a notifying Member State with a case in this data');

  for (const width of [390, 1280]) {
    test(`/legislation/<id>/#national lands on the table once the page has loaded (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await open(page, `legislation/${passed!.dossier_id}/#national`);
      const heading = page.locator('#national h2');
      await expect(heading).toHaveText('How it applies in the Member States');
      await expect(heading).toBeFocused();
      await page.waitForTimeout(1200); // past the second for which the page keeps the target in place (useHashScroll)
      const header = await headerBottom(page);
      expect(await top(heading)).toBeGreaterThanOrEqual(header - 1);
      expect(await top(heading)).toBeLessThan(header + 120);
    });
  }

  test('with GitHub Pages semantics: ?country=XX#national answers 200 and highlights that row; without the slash, the redirect keeps both', async ({
    page,
    request,
  }) => {
    const code = withCase!.country;
    const path = `${PAGES_ORIGIN}${BASE_PATH}legislation/${passed!.dossier_id}`;
    const direct = await request.get(`${path}/?country=${code}`);
    expect(direct.status()).toBe(200);
    const redirect = await request.get(`${path}?country=${code}`, { maxRedirects: 0 });
    expect(redirect.status()).toBe(301);
    expect(redirect.headers()['location']).toBe(`${BASE_PATH}legislation/${passed!.dossier_id}/?country=${code}`);
    for (const url of [`${path}/?country=${code}#national`, `${path}?country=${code}#national`]) {
      await page.goto(url);
      await settle(page);
      await expect(page).toHaveURL(`${path}/?country=${code}#national`);
      await expect(page.locator('#national h2')).toBeFocused();
      const row = page.locator('#national tr.tp-row--linked');
      await expect(row).toHaveCount(1);
      await expect(row.locator('th')).toContainText(name(code));
      await expect(row.locator('th')).toContainText('Highlighted by the link');
    }
  });

  test('“Link to this table” gives its address, and the Member State it highlights', async ({ page }) => {
    const code = withCase!.country;
    await open(page, `legislation/${passed!.dossier_id}/`);
    const link = page.getByLabel('Link to this table');
    const address = `${new URL(page.url()).origin}${BASE_PATH}legislation/${passed!.dossier_id}/`;
    await expect(link).toHaveValue(`${address}#national`);
    await expect(page.locator('#national tr.tp-row--linked')).toHaveCount(0);
    await page.getByLabel('Highlight a Member State').selectOption(code);
    await expect(page).toHaveURL(new RegExp(`\\?country=${code}$`));
    await expect(link).toHaveValue(`${address}?country=${code}#national`);
    await expect(page.locator('#national tr.tp-row--linked th')).toContainText(name(code));
    // the row's case, at its latest decision, as on the tracker
    const k = withCase!.cases![0];
    await expect(page.locator('#national tr.tp-row--linked')).toContainText(k.id);
    await expectNoSeriousA11yViolations(page);
    await page.getByLabel('Highlight a Member State').selectOption('');
    await expect(link).toHaveValue(`${address}#national`);
  });
});

test.describe('time since the deadline, on the reader’s date', () => {
  test('the deadline says how long ago it passed, and a row without measures how long after the deadline the reader is', async ({ page }) => {
    test.skip(!passed, 'no directive with a passed deadline in this data');
    // the reader's clock 15 months and 5 days after the deadline, whatever the build's date
    const on = addDays(addMonths(passed!.deadline, 15), 5);
    await page.clock.install({ time: new Date(`${on}T12:00:00Z`) });
    await open(page, `legislation/${passed!.dossier_id}/`);
    await expect(page.locator('#national .dz-deadline').first()).toContainText('(15 months ago)');
    const none = passed!.countries.filter((c) => c.status === 'none_found');
    const since = page.locator('#national .tp-since');
    await expect(since).toHaveCount(none.length);
    for (const t of await since.allTextContents()) expect(t).toBe('15 months after the deadline');
    // the caveat stays with the table
    await expect(page.locator('#national .dz-caveat')).toContainText('is not proof that a country has failed to act');
  });

  test('a deadline that passes after the build: no measures reads “No measures found” once its day is over, not before', async ({ page }) => {
    test.skip(!ahead, 'no directive whose deadline is ahead in this data');
    const waiting = ahead!.countries.filter((c) => c.status === 'deadline_not_reached').length;
    const chip = (status: string) => page.getByRole('list', { name: 'Member States by status' }).getByRole('button', { name: new RegExp(`: ${status}$`) });
    // on the deadline's day: still ahead
    await page.clock.install({ time: new Date(`${ahead!.deadline}T12:00:00Z`) });
    await open(page, `legislation/${ahead!.dossier_id}/`);
    await expect(page.locator('#national .dz-deadline').first()).toContainText('(today)');
    await expect(chip('Deadline not yet reached')).toHaveText(new RegExp(`^${waiting} Member States?: Deadline not yet reached$`));
    await expect(page.locator('#national .tp-since')).toHaveCount(0);
    // ten days later, on the same build
    await page.clock.setFixedTime(new Date(`${addDays(ahead!.deadline, 10)}T12:00:00Z`));
    await page.reload();
    await settle(page);
    await expect(page.locator('#national .dz-deadline').first()).toContainText('(10 days ago)');
    await expect(chip('No measures found in the available dataset')).toHaveText(
      new RegExp(`^${waiting} Member States?: No measures found in the available dataset$`),
    );
    await expect(chip('Deadline not yet reached')).toHaveCount(0);
    for (const t of await page.locator('#national .tp-since').allTextContents()) expect(t).toBe('10 days after the deadline');
  });
});

test.describe('Directives into national law (/legislation/transposition)', () => {
  test.skip(!tracker || !inWindow.length, 'no transposition.json, or no directive in its window, in this data');

  test('lists the directives in the window on the reader’s date, deadlines ahead then passed, with Member States by status', async ({ page }) => {
    await open(page, 'legislation/transposition/');
    await expect(page.locator('main h1')).toHaveText('Directives into national law');
    await expect(page).toHaveTitle(`Directives into national law – Legislation – ${SITE_NAME}`);
    // a view of Legislation, as What changed is
    await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Legislation' })).toHaveAttribute('aria-current', 'page');
    const n = inWindow.length;
    await expect(page.locator('.tt-count')).toHaveText(`${n.toLocaleString('en-GB')} ${n === 1 ? 'directive' : 'directives'}`);
    const sections = page.locator('.tt-section h2');
    const nAhead = inWindow.filter((d) => d.deadline >= today).length;
    await expect(sections).toHaveText([...(nAhead ? [`Deadline ahead ${nAhead}`] : []), ...(n - nAhead ? [`Deadline passed ${n - nAhead}`] : [])]);
    // no ranking: nothing to sort by
    await expect(page.locator('main .sort-btn, main [aria-sort]')).toHaveCount(0);

    // one directive's row: its link to the table, its deadline, its bound Member States by status, the others named
    const d = inWindow.find((x) => x.dossier_id && x.countries.some((c) => c.status === 'not_participating')) ?? inWindow.find((x) => x.dossier_id)!;
    const row = page.locator('.tt-table tbody tr').filter({ has: page.locator(`a[href="${BASE_PATH}legislation/${d.dossier_id}#national"]`) });
    await expect(row).toHaveCount(1);
    const counts = new Map<TranspositionStatus, number>();
    for (const c of d.countries) {
      const s = statusOn(c.status, d.deadline, today);
      if (s !== 'not_participating' && s !== 'not_required' && !c.participation_unknown) counts.set(s, (counts.get(s) ?? 0) + 1);
    }
    const label: Partial<Record<TranspositionStatus, string>> = {
      measures_notified: 'Measures notified',
      none_found: 'No measures found in the available dataset',
      deadline_not_reached: 'Deadline not yet reached',
      no_deadline: 'No transposition deadline recorded',
      unavailable: 'Data unavailable',
    };
    const expected = (['measures_notified', 'none_found', 'deadline_not_reached', 'no_deadline', 'unavailable'] as const)
      .filter((s) => counts.get(s))
      .map((s) => `${counts.get(s)} Member State${counts.get(s) === 1 ? '' : 's'}: ${label[s]}`);
    if (d.countries.every((c) => c.status === 'unavailable')) await expect(row).toContainText('not in this release’s data');
    else await expect(row.locator('.tt-counts__row')).toHaveText(expected);
    const notBound = d.countries.filter((c) => c.status === 'not_participating');
    if (notBound.length) await expect(row).toContainText('Not bound (did not take part in adoption)');
    const open_ = d.countries.reduce((k, c) => k + (c.cases ?? []).filter((x) => x.non_communication).length, 0);
    // (the cell's text starts with its label on phones, hidden on wider screens)
    await expect(row.locator('td.num')).toHaveText(new RegExp(`(^|\\D)${open_}$`));
    await expectNoSeriousA11yViolations(page);

    // the row leads to the directive's table
    await row.getByRole('link').first().click();
    await settle(page);
    await expect(page).toHaveURL(new RegExp(`/legislation/${d.dossier_id}#national$`));
    await expect(page.locator('#national h2')).toBeFocused();
  });

  test('a Member State’s view: its status on each directive, its open cases, its page and its feed', async ({ page, request }) => {
    test.skip(!passed || !withCase, 'no Member State with a case on a directive of the window');
    const code = withCase!.country;
    await open(page, `legislation/transposition/?country=${code}`);
    await expect(page.locator('main h1')).toHaveText(`Directives into national law: ${name(code)}`);
    await expect(page.getByLabel('Member State')).toHaveValue(code);
    await expect(page.locator('.tt-table thead').first()).toContainText(`${name(code)}’s status in the dataset`);
    const row = page.locator('.tt-table tbody tr').filter({ has: page.locator(`a[href="${BASE_PATH}legislation/${passed!.dossier_id}?country=${code}#national"]`) });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText('Measures notified');
    const k = withCase!.cases![0];
    await expect(row.getByRole('link', { name: new RegExp(k.id.replace(/[()]/g, '\\$&')) })).toHaveAttribute('href', k.url);
    if (k.stage) await expect(row).toContainText(k.stage);
    const context = page.locator('.tt-country');
    await expect(context.getByRole('link', { name: `${name(code)}’s country page` })).toHaveAttribute('href', `${BASE_PATH}countries/${code}`);
    const feed = context.getByRole('link', { name: `Follow ${name(code)} in a feed reader (Atom)` });
    await expect(feed).toHaveAttribute('href', `${BASE_PATH}data/feeds/countries/${code}.xml`);
    const xml = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/feeds/countries/${code}.xml`)).text();
    expect(xml).toContain('<feed xmlns="http://www.w3.org/2005/Atom">');
    expect(xml).toContain(`<link rel="alternate" type="text/html" href=`);
    expect((xml.match(/<entry>/g) ?? []).length).toBeGreaterThan(0);
    expect((xml.match(/<entry>/g) ?? []).length).toBeLessThanOrEqual(100);
    await expectNoSeriousA11yViolations(page);
    // the row leads to the directive's table with that row highlighted
    await row.getByRole('link').first().click();
    await settle(page);
    await expect(page.locator('#national tr.tp-row--linked th')).toContainText(name(code));
  });

  test('filters by topic and by deadline passed or ahead, kept in the address', async ({ page }) => {
    const topic = [...new Set(inWindow.flatMap((d) => d.topics))].sort()[0];
    test.skip(!topic, 'no topic on the directives of the window');
    await open(page, 'legislation/transposition/');
    await page.getByLabel('Topic').selectOption(topic);
    await expect(page).toHaveURL(new RegExp(`topic=${topic}`));
    const withTopic = inWindow.filter((d) => d.topics.includes(topic));
    await expect(page.locator('.tt-table tbody tr')).toHaveCount(withTopic.length);
    await page.getByLabel('Deadline', { exact: true }).selectOption('passed');
    await expect(page).toHaveURL(/when=passed/);
    await expect(page.locator('.tt-table tbody tr')).toHaveCount(withTopic.filter((d) => d.deadline < today).length);
    await expect(page.locator('.tt-section h2', { hasText: 'Deadline ahead' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Show all directives' }).click();
    await expect(page).toHaveURL(/\/legislation\/transposition\/?$/);
    await expect(page.locator('.tt-table tbody tr')).toHaveCount(inWindow.length);
  });

  test('is reached from the explorer and the country pages; a country page announces its feed', async ({ page, request }) => {
    await open(page, 'legislation/');
    await expect(page.getByRole('link', { name: 'Directives into national law' })).toHaveAttribute('href', `${BASE_PATH}legislation/transposition`);
    await open(page, 'countries/IE/');
    const links = page.locator('#implementation .country-impl-links');
    await expect(links.getByRole('link', { name: 'Directives into national law' })).toHaveAttribute('href', `${BASE_PATH}legislation/transposition?country=IE`);
    await expect(links.getByRole('link', { name: 'Follow in a feed reader' })).toHaveAttribute('href', `${BASE_PATH}data/feeds/countries/IE.xml`);
    await expect(page.locator('head link#page-feed')).toHaveAttribute('href', `${BASE_PATH}data/feeds/countries/IE.xml`);
    // the prerendered page announces it too, for a feed reader that reads the page without running it
    const html = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}countries/IE/`)).text();
    expect(html).toContain(`href="${BASE_PATH}data/feeds/countries/IE.xml"`);
    // a deadline on the country page is told from the reader's date
    await expect(page.locator('#implementation td.nowrap .meta').first()).toHaveText(/^(in \d+ (days?|months?)|today|\d+ (days?|months?) ago|in \d+ years?( and \d+ months?)?|\d+ years?( and \d+ months?)? ago)$/);
  });

  test('is prerendered for GitHub Pages', async ({ request }) => {
    const res = await request.get(`${PAGES_ORIGIN}${BASE_PATH}legislation/transposition/`);
    expect(res.status()).toBe(200);
    expect(await res.text()).toContain(`<title>Directives into national law – Legislation – ${SITE_NAME}</title>`);
  });

  for (const width of [320, 390]) {
    test(`fits a ${width}px screen, in both views`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      for (const path of ['legislation/transposition/', `legislation/transposition/?country=${withCase?.country ?? 'FR'}`]) {
        await open(page, path);
        const [scroll, inner] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
        expect(scroll, path).toBeLessThanOrEqual(inner);
      }
    });
  }
});
