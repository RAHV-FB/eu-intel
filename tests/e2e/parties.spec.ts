/**
 * How a country's national parties voted: the vote page's table by national party, with the country filter it shares
 * with the list of individual MEPs, and the votes on whole texts on a party page; the link from a vote to the same vote
 * on HowTheyVote.eu, an independent site. Real records (the Nature Restoration Law's final vote, 164499, 27 Feb 2024);
 * see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { BASE_PATH } from './env';
import { expect, open, test } from './fixtures';

const PHONE = { width: 390, height: 844 };
const byName = (a: string, b: string) => a.localeCompare(b, 'en', { sensitivity: 'base' });

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

async function expectNoSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, 'horizontal overflow (px)').toBeLessThanOrEqual(0);
}

/** The row of the party whose code the table gives in brackets after its name ("(CDU)"). */
const partyRow = (section: Locator, code: string) => section.locator('tbody tr').filter({ hasText: `(${code})` });

test.describe('vote page: by national party', () => {
  test('answers how CDU and CSU voted on the Nature Restoration Law, among Germany’s parties only', async ({ page }) => {
    await open(page, 'votes/164499/?bl-country=DE');
    const section = page.locator('#parties');
    await expect(section.getByRole('heading', { level: 2 })).toHaveText('By national party');
    await expect(section.getByLabel('MEPs from')).toHaveValue('DE');
    // country, group, for, against, abstained, did not vote
    await expect(partyRow(section, 'CDU').locator('td')).toHaveText(['Germany', 'EPP', '0', '19', '0', '4']);
    await expect(partyRow(section, 'CSU').locator('td')).toHaveText(['Germany', 'EPP', '0', '6', '0', '0']);
    await expect(partyRow(section, 'CDU').getByRole('link')).toHaveAttribute('href', `${BASE_PATH}people/parties/5195`);
    // Germany's parties only, by name: never by how many voted one way
    const rows = section.locator('tbody tr');
    expect(new Set(await rows.locator('td:nth-child(2)').allInnerTexts())).toEqual(new Set(['Germany']));
    const names = await rows.locator('th a').allInnerTexts();
    expect(names.length).toBeGreaterThan(10);
    expect(names).toEqual([...names].sort(byName));
    await expect(section.locator('.party-tally')).toHaveText(`MEPs from Germany: ${names.length} national parties`);
    // the list of individual MEPs below is filtered to the same country
    await expect(page.locator('#bl-country')).toHaveValue('DE');
    await expectNoSeriousA11yViolations(page);
  });

  test('the country chosen above the table also filters the list of MEPs; all countries are shown 40 rows at a time', async ({ page }) => {
    await open(page, 'votes/164499/');
    const section = page.locator('#parties');
    const rows = section.locator('tbody tr');
    await expect(section.locator('.party-tally')).toHaveText(/^\d+ national parties from 27 countries/);
    await expect(rows).toHaveCount(40);
    const all = Number(/of ([\d,]+);/.exec(await section.locator('.more .meta').innerText())![1].replace(/,/g, ''));
    expect(all).toBeGreaterThan(200);
    await section.getByRole('button', { name: 'Show all parties' }).click();
    await expect(rows).toHaveCount(all);
    await expect(rows.nth(40).getByRole('link').first()).toBeFocused(); // keyboard focus moves to the first new row
    await section.getByLabel('MEPs from').selectOption('PL');
    await expect(page).toHaveURL(/[?&]bl-country=PL(&|$)/);
    await expect(page.locator('#bl-country')).toHaveValue('PL');
    expect(new Set(await rows.locator('td:nth-child(2)').allInnerTexts())).toEqual(new Set(['Poland']));
    // and the list's own filter moves the table
    await page.locator('#bl-country').selectOption('FR');
    await expect(section.getByLabel('MEPs from')).toHaveValue('FR');
    expect(new Set(await rows.locator('td:nth-child(2)').allInnerTexts())).toEqual(new Set(['France']));
  });

  test('does not say who did not vote on a day the membership records do not give the Members in office', async ({ page }) => {
    await open(page, 'votes/108563/?bl-country=ES'); // 17 September 2019
    const section = page.locator('#parties');
    await expect(section.getByText('“Did not vote” is not given for this vote')).toBeVisible();
    const lastCells = await section.locator('tbody tr td:last-child').allInnerTexts();
    expect(lastCells.length).toBeGreaterThan(0);
    expect(new Set(lastCells)).toEqual(new Set(['—']));
  });

  test('says when Parliament’s data lists an MEP in a party record outside the record’s own period', async ({ page }) => {
    await open(page, 'votes/199592/?bl-country=RO'); // 22 October 2026: Dan Nica under PSD's 2019–2024 record
    const row = page.locator('#parties tbody tr', { has: page.locator(`a[href="${BASE_PATH}people/parties/5320"]`) });
    await expect(row.locator('th')).toContainText(
      'Parliament’s membership data lists this MEP in this party record outside its period (2 Jul 2019 – 15 Jul 2024).',
    );
  });

  test('on a phone, each party’s country, group and counts are under its name, and nothing scrolls sideways', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await open(page, 'votes/164499/?bl-country=DE');
    const cdu = partyRow(page.locator('#parties'), 'CDU');
    await expect(cdu.locator('th')).toContainText('Germany · EPP');
    await expect(cdu.locator('.party-counts')).toHaveText('For 0 · Against 19 · Abstained 0 · Did not vote 4');
    await expect(cdu.locator('td').first()).toBeHidden();
    await expectNoSidewaysScroll(page);
  });

  test('links to the same vote on HowTheyVote.eu, said to be an independent site, without contacting it', async ({ page }) => {
    await open(page, 'votes/164499/');
    const link = page.locator('#meps').getByRole('link', { name: /HowTheyVote\.eu/ });
    await expect(link).toHaveAttribute('href', 'https://howtheyvote.eu/votes/164499');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    await expect(page.locator('#meps p', { has: page.getByRole('link', { name: /HowTheyVote\.eu/ }) })).toContainText(
      'an independent website that is not an official source',
    );
    // a vote without individual votes has no such link
    await open(page, 'votes/195653/');
    await expect(page.getByRole('link', { name: /HowTheyVote/ })).toHaveCount(0);
  });
});

test.describe('party page: votes on whole texts', () => {
  const votesOf = (page: Page) => page.locator('section', { has: page.getByRole('heading', { name: 'How its MEPs voted on whole texts' }) });

  test('lists how CDU’s MEPs voted, newest first, 40 at a time', async ({ page }) => {
    await open(page, 'people/parties/5195/');
    const rows = votesOf(page).locator('tbody tr');
    await expect(rows).toHaveCount(40);
    const dates = (await rows.locator('td:first-child').allInnerTexts()).map((d) => Date.parse(d));
    expect(dates.every((d) => !Number.isNaN(d))).toBe(true);
    expect(dates).toEqual([...dates].sort((a, b) => b - a));
    await votesOf(page).getByRole('button', { name: 'Show more votes' }).click();
    await expect(rows).toHaveCount(80);
    await expect(rows.nth(40).getByRole('link').first()).toBeFocused();
    await expect(page).toHaveURL(/[?&]show=80(&|$)/);
    await expectNoSeriousA11yViolations(page);
  });

  test('gives the Nature Restoration Law’s final vote with its counts, the vote and the file', async ({ page }) => {
    await open(page, 'people/parties/5195/?show=2000');
    const row = votesOf(page).locator('tbody tr', { has: page.locator(`a[href="${BASE_PATH}votes/164499"]`) });
    await expect(row.locator('td.num')).toHaveText(['0', '19', '0', '4']);
    await expect(row.getByRole('link', { name: '2022/0195(COD)' })).toHaveAttribute('href', `${BASE_PATH}legislation/2022-0195`);
    // the oldest votes, before 13 January 2020, cannot say who did not vote
    await expect(votesOf(page).getByText('“—” under “Did not vote”: not known for that vote')).toBeVisible();
    await expect(votesOf(page).locator('tbody tr').last().locator('td.num').last()).toHaveText('—');
  });

  test('says which votes fall outside the record’s own period, and whom they count (PSD 5320, Dan Nica)', async ({ page }) => {
    await open(page, 'people/parties/5320/');
    const section = votesOf(page);
    await expect(section.getByText('On days outside this record’s period (2 Jul 2019 – 15 Jul 2024)')).toContainText('Dan Nica');
    await expect(section.locator('tbody tr').first()).toContainText('On a day outside this record’s period');
  });

  test('on a phone, each vote’s counts are under its title, and nothing scrolls sideways', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await open(page, 'people/parties/5195/');
    const first = votesOf(page).locator('tbody tr').first();
    await expect(first.locator('.party-counts')).toHaveText(/^For \d+ · Against \d+ · Abstained \d+ · Did not vote (\d+|not known)$/);
    await expect(first.locator('td.num').first()).toBeHidden();
    await expectNoSidewaysScroll(page);
  });
});
