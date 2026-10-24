/**
 * Acts on the built site, on real records: the dates repeals take effect, partial repeals as EUR-Lex classifies them,
 * provisions whose application date EUR-Lex does not record, and files described by the type of act proposed. See
 * playwright.config.ts to run.
 */
import type { Page } from '@playwright/test';
import { expect, open, test } from './fixtures';

const status = (page: Page) => page.locator('.dz-fact', { hasText: 'Current status' });
// the status itself and the date it holds from, under the title
const statusLine = (page: Page) => page.locator('.dz-statusline');

test.describe('act validity', () => {
  test('a repeal that takes effect on the recorded end of validity is dated from that day', async ({ page }) => {
    // Regulation 543/2014: Regulation (EU) 2015/2219, Art. 40(1), "with effect from 1 July 2016"
    await open(page, 'legislation/2013-0812/');
    await expect(status(page)).toContainText(
      'EUR-Lex gives 1 July 2016 as the end of its validity and records it as repealed by Regulation (EU) 2015/2219 with effect from 1 July 2016.',
    );
    await expect(statusLine(page)).toHaveText(/No longer in force\s*since 1 July 2016/);
  });

  test('a repeal in stages states the recorded dates and no single day', async ({ page }) => {
    // Directive 2014/61/EU: Regulation (EU) 2024/1309, Art. 18
    await open(page, 'legislation/2013-0080/');
    await expect(status(page)).toContainText('with effect from 12 November 2025, except for some provisions');
    await expect(status(page)).toContainText("EUR-Lex gives 12 May 2026 as the end of the act's validity.");
    await expect(statusLine(page)).not.toContainText('since');
  });

  test('a partial repeal is labelled as EUR-Lex’s classification', async ({ page }) => {
    // Decision (EU) 2024/867 has no repeal article (Art. 6: Decision (EU) 2020/1531 "remains applicable ...")
    await open(page, 'legislation/2020-0160/');
    await page.locator('#details summary').click();
    const related = page.locator('#details .dz-sub', { hasText: 'Related legislative files' });
    await expect(related).toContainText('Partly repealed by (EUR-Lex): Decision (EU) 2024/867');
    await expect(page.locator('#details .dz-kv--rel')).toContainText('Partly repealed by (EUR-Lex)');
  });

  test('says when EUR-Lex records no date for the other provisions', async ({ page }) => {
    // Regulation (EU) 2025/12, Art. 46: from "two years from the date on which the router starts operations"; Cellar
    // gives that date (MA, "V ART 46") and the one of Art. 46(b) (MA/PART) as 1001-01-01
    await open(page, 'legislation/2022-0424/');
    const when = page.locator('.dz-when');
    await expect(when.locator('li', { hasText: 'Rules apply from' })).toHaveText(/^Not recorded\s*Rules apply from\s*EUR-Lex gives no date \(it refers to Art\. 46\)\.$/);
    await expect(when.locator('li', { hasText: 'Some provisions apply from' })).toHaveText(
      /^Not recorded\s*Some provisions apply from\s*EUR-Lex gives no date for some provisions \(it refers to Art\. 46\(b\)\)\.$/,
    );
    await expect(status(page)).toContainText('EUR-Lex records no date from which the act in general applies (it refers to Art. 46)');
  });

  test('never reads an application date EUR-Lex gives as not recorded as applying now', async ({ page }) => {
    // ETIAS, Regulation (EU) 2018/1240, Art. 96: "This Regulation shall apply from the date determined by the Commission"
    await open(page, 'legislation/2016-0357A/');
    await expect(page.locator('.dz-when').locator('li', { hasText: 'Rules apply from' })).toHaveText(
      /^Not recorded\s*Rules apply from\s*EUR-Lex gives no date \(it refers to Art\. 96\)\.$/,
    );
    await expect(page.locator('.dz-facts')).toContainText('EUR-Lex records no date from which this regulation in general applies');
  });
});

test.describe('type of act', () => {
  test('an adopted file with no linked act is not described by the type proposed', async ({ page }) => {
    await open(page, 'legislation/2025-0232/'); // signed, awaiting publication; proposed as a directive
    const national = page.locator('#national');
    await expect(national).toContainText('No adopted act is linked to this file in our sources yet');
    await expect(national).toContainText('It was proposed as a directive; the adopted act’s type can differ from the one proposed.');
    await expect(national).not.toContainText('A directive sets goals');
    await expect(national).not.toContainText('Data unavailable');
  });

  test('a file still being decided speaks of the type proposed', async ({ page }) => {
    await open(page, 'legislation/2018-0332/');
    await expect(page.locator('#national')).toContainText(
      'It was proposed as a directive: if adopted in that form, it would have to be turned into national law by a deadline.',
    );
  });

  test('the explorer says which files are counted by the type proposed', async ({ page }) => {
    await open(page, 'legislation/');
    await page.locator('.lx-more summary').click();
    const select = page.getByLabel('Type of act');
    await expect(select.locator('option', { hasText: /^Directive / })).toHaveText(/^Directive \(\d[\d,]*, of which \d[\d,]* as proposed\)$/);
    await expect(page.locator('.lx-field', { has: select })).toContainText('for files without one (proposals, and acts adopted but not yet published or linked)');
  });
});
