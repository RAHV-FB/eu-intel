/**
 * The steps the Council and Parliament have scheduled (pipeline/analysis/scheduled.py): the home page's "Scheduled in
 * the next 3 weeks" and a file's "Scheduled next" (src/features/legislation/dossier/ScheduledNext.tsx), judged on the
 * reader's date. The example is the first step the home page lists, read from the data under test; the tests are
 * skipped when the data has none (the frozen test data predates the source).
 */
import { readFileSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import type { DossierDetail, HomeData } from '../../src/types/data';
import { expect, open, test } from './fixtures';

/** As smoke.spec.ts: no serious or critical axe-core violation of the WCAG 2.2 AA rules. */
async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 5).map((n) => n.target.join(' ')).join(' | ')}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

const DAY = 86_400_000;
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const long = (d: string) => {
  const [y, m, day] = d.split('-').map(Number);
  return `${day} ${MONTHS_LONG[m - 1]} ${y}`;
};

function read<T>(rel: string): T | null {
  try {
    return JSON.parse(readFileSync(`dist/data/${rel}`, 'utf8')) as T;
  } catch {
    return null;
  }
}

const first = read<HomeData>('home.json')?.lists.find((l) => l.id === 'scheduled')?.items[0];
const file = first?.dossier_id ? read<DossierDetail>(`dossiers/${first.dossier_id}.json`) : null;
const step = file?.scheduled?.find((s) => s.date === first?.date);

test.describe('scheduled steps', () => {
  test.skip(!first || !step, 'no scheduled step in the data under test (the frozen test data predates the source)');

  test('the home page lists the next three weeks, each step leading to its file', async ({ page }) => {
    await open(page, './');
    const list = page.locator('section[aria-labelledby="hl-scheduled"]');
    await expect(list.locator('.hl__heading')).toHaveText('Scheduled in the next 3 weeks');
    await expect(list.locator('.hl__desc')).toContainText('Planned dates can change');
    const row = list.locator('.hl__row').first();
    await expect(row.locator('.hl__badge')).toHaveText('Planned');
    await expect(row.locator('time')).toHaveAttribute('datetime', first!.date!);
    await row.locator('.hl__title').click();
    await expect(page).toHaveURL(new RegExp(`/legislation/${first!.dossier_id}/?$`));
    await expect(page.locator('#scheduled-next')).toBeVisible();
  });

  test('the home page’s list leads to every file with a planned step, soonest first', async ({ page }) => {
    await open(page, './');
    const more = page.locator('section[aria-labelledby="hl-scheduled"] .hl__more');
    await expect(more).toHaveText(/All files with a planned step, soonest first/);
    await more.click();
    await expect(page).toHaveURL(/sort=scheduled/);
    await expect(page.getByLabel('Sort by')).toHaveValue('scheduled');
    await expect(page.locator('main')).toContainText('Files with a planned step ahead come first, the soonest first');
    await expect(page.locator('.drow').first()).toContainText(file!.title);
  });

  test('a file’s page gives each step with its date, meeting, documents and source', async ({ page }) => {
    await open(page, `legislation/${first!.dossier_id}`);
    const box = page.locator('#scheduled-next');
    await expect(box.locator('dt')).toHaveText('Scheduled next');
    const li = box.locator('.dz-plan__step').filter({ has: page.locator(`time[datetime="${step!.date}"]`) }).filter({ hasText: step!.label }).first();
    await expect(li.locator('.dz-plan__date')).toHaveText(long(step!.date));
    await expect(li.locator('.dz-plan__passed')).toHaveCount(0);
    if (step!.meeting) await expect(li).toContainText(step!.meeting);
    for (const d of step!.documents.filter((x) => x.url))
      await expect(li.locator(`a[href="${new URL(d.url!).href}"]`)).toHaveCount(1);
    await expect(li.locator('.source a').first()).toHaveAttribute('href', new URL(step!.sources[0].url).href);
    await expect(box).toContainText('Planned dates as the Council and Parliament publish them');
  });

  test('once its day is over, a step is said to have been scheduled and leaves the home page’s list', async ({ page }) => {
    // on its day it is still ahead (the meeting may not have taken place yet)
    await page.clock.setFixedTime(Date.parse(`${step!.date}T18:00:00Z`));
    await open(page, `legislation/${first!.dossier_id}`);
    const li = page.locator('#scheduled-next .dz-plan__step').filter({ has: page.locator(`time[datetime="${step!.date}"]`) }).filter({ hasText: step!.label }).first();
    await expect(li.locator('.dz-plan__passed')).toHaveCount(0);
    // the next day: passed, never shown as done
    await page.clock.setFixedTime(Date.parse(`${step!.date}T18:00:00Z`) + DAY);
    await open(page, `legislation/${first!.dossier_id}`);
    await expect(li.locator('.dz-plan__passed')).toHaveText(`Was scheduled for ${long(step!.date)}; not yet recorded as done.`);
    await open(page, './');
    await expect(page.locator(`section[aria-labelledby="hl-scheduled"] time[datetime="${first!.date}"]`)).toHaveCount(0);
  });

  test('a11y: the home page and a file’s page with its scheduled steps, ahead and passed', async ({ page }) => {
    await open(page, './');
    await expect(page.locator('section[aria-labelledby="hl-scheduled"]')).toBeVisible();
    await expectNoSeriousA11yViolations(page);
    await open(page, `legislation/${first!.dossier_id}`);
    await expect(page.locator('#scheduled-next')).toBeVisible();
    await expectNoSeriousA11yViolations(page);
    await page.clock.setFixedTime(Date.parse(`${step!.date}T18:00:00Z`) + DAY);
    await open(page, `legislation/${first!.dossier_id}`);
    await expect(page.locator('#scheduled-next .dz-plan__passed').first()).toBeVisible();
    await expectNoSeriousA11yViolations(page);
  });
});
