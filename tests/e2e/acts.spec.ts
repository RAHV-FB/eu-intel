/**
 * Acts on the built site, on real records: the dates repeals take effect, partial repeals as EUR-Lex classifies them,
 * provisions whose application date EUR-Lex does not record, and files described by the type of act proposed. See
 * playwright.config.ts to run.
 */
import type { Page } from '@playwright/test';
import { expect, open, test } from './fixtures';

const status = (page: Page) => page.locator('.dz-fact', { hasText: 'Current status' });

test.describe('act validity', () => {
  test('a repeal that takes effect on the recorded end of validity is dated from that day', async ({ page }) => {
    // Regulation 543/2014: Regulation (EU) 2015/2219, Art. 40(1), "with effect from 1 July 2016"
    await open(page, 'legislation/2013-0812/');
    await expect(status(page)).toContainText(
      'EUR-Lex gives 1 July 2016 as the end of its validity and records it as repealed by Regulation (EU) 2015/2219 with effect from 1 July 2016.',
    );
    await expect(status(page)).toContainText('Since 1 Jul 2016');
  });

  test('a repeal in stages states the recorded dates and no single day', async ({ page }) => {
    // Directive 2014/61/EU: Regulation (EU) 2024/1309, Art. 18
    await open(page, 'legislation/2013-0080/');
    await expect(status(page)).toContainText('with effect from 12 November 2025, except for some provisions');
    await expect(status(page)).toContainText("EUR-Lex gives 12 May 2026 as the end of the act's validity.");
    await expect(status(page)).not.toContainText('Since');
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
    // Regulation (EU) 2025/12, Art. 46: from "two years from the date on which the router starts operations"
    await open(page, 'legislation/2022-0424/');
    const when = page.locator('.dz-when');
    await expect(when).toContainText('Some provisions apply from');
    await expect(when.locator('div', { hasText: 'Other provisions apply from' })).toContainText('Not recorded: EUR-Lex gives no date.');
    await expect(status(page)).toContainText('and no date from which the other provisions apply.');
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
