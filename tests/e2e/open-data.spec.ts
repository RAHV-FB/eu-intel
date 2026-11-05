/**
 * Reuse: "Download CSV" on the vote page's tables and the legislation list (a file made in the browser, no request),
 * and About's "Reuse the data" with the open dataset of the build (data/open/). The examples are picked from the built
 * data when the tests run (dist/data), so they hold on the frozen test data and on newer data alike.
 */
import { readFileSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { BASE_PATH, PAGES_ORIGIN } from './env';
import { expect, open, test } from './fixtures';

interface VoteEntry {
  id: string;
  has_ballots: boolean;
}
interface VoteDetail {
  groups: unknown[];
  countries: unknown[];
  ballots: { mep: string; pos: string }[];
}

const data = (rel: string) => JSON.parse(readFileSync(`dist/data/${rel}`, 'utf8'));

/** RFC 4180 read back (fields in double quotes may hold commas, doubled quotes and line breaks); the byte-order mark,
 * which the file starts with for spreadsheet applications, is checked and removed. */
function parseCsv(text: string): string[][] {
  expect(text.charCodeAt(0), 'a UTF-8 byte-order mark').toBe(0xfeff);
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 1; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\r' && text[i + 1] === '\n') {
      rows.push([...row, field]);
      row = [];
      field = '';
      i++;
    } else field += c;
  }
  expect(row.length === 0 && field === '', 'the file ends with a line end').toBe(true);
  return rows;
}

/** Press a "Download CSV" button: the file's name and rows, and the requests the page made meanwhile (none). */
async function download(page: Page, button: Locator): Promise<{ name: string; rows: string[][]; requests: string[] }> {
  const requests: string[] = [];
  const record = (r: { url(): string }) => {
    if (!/^(?:blob|data):/.test(r.url())) requests.push(r.url());
  };
  page.on('request', record);
  const [file] = await Promise.all([page.waitForEvent('download'), button.click()]);
  const text = readFileSync((await file.path())!, 'utf8');
  page.off('request', record);
  return { name: file.suggestedFilename(), rows: parseCsv(text), requests };
}

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

/** The latest vote with each MEP's recorded vote, and its record. */
function aVoteWithBallots(): { id: string; detail: VoteDetail } {
  const vote = (data('votes/index.json') as VoteEntry[]).find((v) => v.has_ballots)!;
  return { id: vote.id, detail: data(`votes/${vote.id}.json`) as VoteDetail };
}

test.describe('Download CSV on a vote page', () => {
  test('each table downloads as it is shown: its columns, all its rows, in its order, without a request', async ({ page }) => {
    const { id, detail } = aVoteWithBallots();
    await open(page, `votes/${id}/`);

    const groups = page.locator('section#groups');
    const g = await download(page, groups.getByRole('button', { name: 'Download CSV of the votes by political group' }));
    expect(g.name).toBe(`ep-vote-${id}-groups.csv`);
    expect(g.rows[0]).toEqual(['Group', 'Group name', 'For', 'Against', 'Abstained', 'Recorded', 'Group majority', 'Cohesion']);
    const groupRows = groups.locator('tbody tr.has-more');
    expect(g.rows.length - 1).toBe(await groupRows.count());
    expect(g.rows.length - 1).toBe(detail.groups.length);
    // the first row as the table shows it: the group, its counts, its majority in words
    const first = groupRows.first();
    expect(g.rows[1][0]).toBe((await first.locator('th a').innerText()).trim());
    expect(g.rows[1][2]).toBe((await first.locator('td.num').first().innerText()).replace(/,/g, ''));
    expect(['For', 'Against', 'Abstained', 'None (tie)', 'Not a group: non-attached MEPs do not act together', '']).toContain(g.rows[1][6]);
    expect(g.requests, 'requests made for the download').toEqual([]);

    const countries = page.locator('section#countries');
    const c = await download(page, countries.getByRole('button', { name: 'Download CSV of the votes by MEPs’ country' }));
    expect(c.name).toBe(`ep-vote-${id}-countries.csv`);
    expect(c.rows[0]).toEqual(['MEPs from', 'Country code', 'For', 'Against', 'Abstained', 'Recorded', 'Share for']);
    expect(c.rows.length - 1).toBe(await countries.locator('tbody tr.has-more').count());
    expect(c.rows.length - 1).toBe(detail.countries.length);
    expect(c.rows[1][0]).toBe((await countries.locator('tbody tr.has-more th a').first().innerText()).trim());
    for (const r of c.rows.slice(1)) expect(r[1]).toMatch(/^[A-Z]{2}$/); // the ISO code beside the name

    const meps = page.locator('section#meps');
    const count = Number((await meps.locator('.results-bar__count').innerText()).match(/^([\d,]+) MEPs with a recorded vote$/)![1].replace(/,/g, ''));
    expect(count).toBe(detail.ballots.length);
    const m = await download(page, meps.getByRole('button', { name: `Download CSV of the ${count.toLocaleString('en-GB')} MEPs listed` }));
    expect(m.name).toBe(`ep-vote-${id}-meps.csv`);
    expect(m.rows[0]).toEqual(['MEP', 'MEP ID', 'Group', 'Country', 'Country code', 'Recorded vote', 'Later stated intention']);
    expect(m.rows.length - 1).toBe(count); // every MEP, not only the first page of the list
    expect(await meps.locator('tbody tr').count()).toBeLessThanOrEqual(count);
    const pos = new Map(detail.ballots.map((b) => [b.mep, b.pos]));
    const label: Record<string, string> = { for: 'For', against: 'Against', abstain: 'Abstained' };
    for (const r of m.rows.slice(1)) expect(r[5], r[1]).toBe(label[pos.get(r[1])!]);
    // in the list's order: the first MEP shown is the first row
    expect(m.rows[1][0]).toBe((await meps.locator('tbody tr th a').first().innerText()).trim());
    expect(m.requests).toEqual([]);
  });

  test('the MEPs downloaded are those the filters keep', async ({ page }) => {
    const { id, detail } = aVoteWithBallots();
    const position = (['against', 'abstain', 'for'] as const).find((p) => detail.ballots.some((b) => b.pos === p))!;
    const kept = detail.ballots.filter((b) => b.pos === position).length;
    await open(page, `votes/${id}/?bl-pos=${position}`);
    const meps = page.locator('section#meps');
    await expect(meps.locator('.results-bar__count')).toHaveText(
      `${kept.toLocaleString('en-GB')} of ${detail.ballots.length.toLocaleString('en-GB')} MEPs with a recorded vote`,
    );
    const m = await download(page, meps.getByRole('button', { name: /^Download CSV of the [\d,]+ MEPs listed$/ }));
    expect(m.rows.length - 1).toBe(kept);
    const label = { for: 'For', against: 'Against', abstain: 'Abstained' }[position];
    expect(new Set(m.rows.slice(1).map((r) => r[5]))).toEqual(new Set([label]));
  });

  test('the buttons pass the accessibility checks and fit a phone', async ({ page }) => {
    const { id } = aVoteWithBallots();
    await page.setViewportSize({ width: 375, height: 812 });
    await open(page, `votes/${id}/`);
    for (const name of [/votes by political group$/, /votes by MEPs’ country$/, /MEPs listed$/]) {
      const button = page.getByRole('button', { name });
      await expect(button).toBeVisible();
      // the visible label, which starts the accessible name (the rest is for screen readers only)
      expect(await button.evaluate((b) => b.firstChild?.textContent)).toBe('Download CSV');
      await expect(button.locator('.visually-hidden')).toHaveText(/^ of the /);
      expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(24); // WCAG 2.5.8 target size
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
    await page.setViewportSize({ width: 1280, height: 900 });
    await expectNoSeriousA11yViolations(page);
  });
});

test.describe('Download CSV of the legislation list', () => {
  const HEADER = [
    'Title', 'Description', 'Procedure reference', 'File ID', 'Procedure type', 'Type of act', 'Status',
    'Officially reported as blocked', 'Proposed', 'Latest recorded step', 'Adopted', 'Published', 'Next legal date',
    'Topics', 'CELEX', 'Page',
  ];

  test('downloads every file the list holds, as its rows show them', async ({ page }) => {
    // a topic of the build with more files than one page of the list shows
    const topics = data('topics.json') as { slug: string; label: string; count: number }[];
    const topic = [...topics].sort((a, b) => a.count - b.count).find((t) => t.count > 25)!;
    await open(page, `legislation/?topic=${topic.slug}`);
    const count = Number((await page.locator('.lx-count strong').innerText()).replace(/,/g, ''));
    expect(count).toBe(topic.count);
    const shown = await page.locator('ol.drows > li').count();
    expect(shown).toBeLessThan(count);
    const f = await download(page, page.getByRole('button', { name: `Download CSV of the ${count.toLocaleString('en-GB')} files listed` }));
    expect(f.name).toBe(`legislation-${topic.slug}.csv`);
    expect(f.rows[0]).toEqual(HEADER);
    expect(f.rows.length - 1).toBe(count);
    expect(f.requests).toEqual([]);
    const col = (name: string) => HEADER.indexOf(name);
    // the rows in the list's order, as the list words them
    const firstRow = page.locator('ol.drows > li').first();
    expect(f.rows[1][col('Title')]).toBe((await firstRow.locator('.drow__title a').innerText()).trim());
    expect(f.rows[1][col('Procedure reference')]).toBe((await firstRow.locator('.drow__meta .ref').innerText()).trim());
    expect((await firstRow.locator('.badge').innerText()).trim()).toContain(f.rows[1][col('Status')]);
    for (const r of f.rows.slice(1)) {
      expect(r[col('Topics')].split('; ')).toContain(topic.label);
      expect(r[col('Page')]).toMatch(new RegExp(`${BASE_PATH}legislation/${r[col('File ID')]}/$`));
      expect(r[col('Officially reported as blocked')]).toMatch(/^(Yes|No|)$/);
      for (const d of ['Proposed', 'Latest recorded step', 'Adopted', 'Published', 'Next legal date']) {
        expect(r[col(d)]).toMatch(/^(\d{4}-\d{2}-\d{2})?$/);
      }
    }
    await expectNoSeriousA11yViolations(page);
  });
});

test.describe('About: reuse the data', () => {
  test('lists the open dataset of this build, its files and its licence', async ({ page, request }) => {
    const dp = data('open/datapackage.json') as { as_of: string; resources: { path: string; title: string; rows: number }[] };
    await open(page, 'about/');
    const section = page.locator('#reuse');
    await expect(section.getByRole('heading', { name: 'Reuse the data', level: 2 })).toBeVisible();
    const rows = section.locator('table tbody tr');
    await expect(rows).toHaveCount(dp.resources.length);
    for (const [i, r] of dp.resources.entries()) {
      const row = rows.nth(i);
      await expect(row.locator('th a')).toHaveText(r.path);
      await expect(row.locator('td').last()).toHaveText(r.rows.toLocaleString('en-GB'));
      const href = (await row.locator('th a').getAttribute('href'))!;
      expect(href).toBe(`${BASE_PATH}data/open/${r.path}`);
      const res = await request.get(`${PAGES_ORIGIN}${href}`);
      expect(res.status(), href).toBe(200);
      const header = (await res.text()).split('\r\n')[0];
      expect(header.length, href).toBeGreaterThan(0);
    }
    for (const file of ['README.md', 'datapackage.json']) {
      await expect(section.locator(`a[href="${BASE_PATH}data/open/${file}"]`)).toBeVisible();
      expect((await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/open/${file}`)).status()).toBe(200);
    }
    await expect(section.getByRole('link', { name: /^releases/ })).toHaveAttribute('href', 'https://github.com/RAHV-FB/eu-intel/releases');
    await expect(section.getByRole('link', { name: /^CC BY 4\.0/ })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by/4.0/');
    await expect(section.getByRole('link', { name: 'Atom feed of all recorded steps' })).toHaveAttribute('href', `${BASE_PATH}data/feeds/updates.xml`);
    await expect(section).toContainText('nothing is sent');
    await expectNoSeriousA11yViolations(page);
  });
});
