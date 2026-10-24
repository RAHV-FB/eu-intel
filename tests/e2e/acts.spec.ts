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

  test('an act no longer in force has its end as the latest step and in its schedule', async ({ page }) => {
    // Regulation (EU) 2019/982: validity ended 31 October 2023 (Cellar), implicitly repealed by Regulation (EU)
    // 2023/2124; the latest step was its entry into force of 10 July 2019
    await open(page, 'legislation/2018-0069/');
    await expect(statusLine(page)).toHaveText(/No longer in force\s*since 1 November 2023/);
    const latest = page.locator('.dz-fact', { hasText: 'Latest recorded step' });
    await expect(latest).toContainText('1 November 2023');
    await expect(latest).toContainText('No longer in force');
    await expect(latest).not.toContainText('Entered into force');
    const when = page.locator('#when-it-applies');
    await expect(when.locator('.dz-sched li').last()).toContainText('No longer in force');
    await expect(when).not.toContainText('A regulation applies directly');
    await expect(page.locator('#timeline')).toContainText('Its validity ended on 31 October 2023.');
  });

  test('the end of validity is not flagged as a date after it, a date it shares is', async ({ page }) => {
    // Regulation (EU) 2024/2822: validity ended 30 June 2026 (repealed by Regulation (EU) 2026/715); some provisions
    // apply from 1 July 2026, the day it is no longer in force. Also Directive 2014/48/EU (transposition deadline
    // 1 January 2016) and Regulation (EU) 2015/2424 (some provisions apply from 1 October 2017).
    const after = 'A date after the act’s validity ended';
    for (const [file, shared] of [
      ['2022-0391', /Some provisions start(?:ed)? to apply/],
      ['2008-0215', /National transposition deadline/],
      ['2013-0088', /Some provisions start(?:ed)? to apply/],
    ] as const) {
      await open(page, `legislation/${file}/`);
      const rows = page.locator('#when-it-applies .dz-sched li');
      const end = rows.filter({ hasText: 'No longer in force' });
      await expect(end).toHaveCount(1);
      await expect(end).not.toContainText(after);
      await expect(rows.filter({ hasText: shared }).filter({ hasText: after })).toHaveCount(1);
    }
    await open(page, 'legislation/2022-0391/');
    const last = page.locator('#when-it-applies .dz-sched li').last();
    await expect(last).toContainText('No longer in force');
    await expect(last).not.toContainText(after);
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
    const related = page.locator('#details .dz-sub', { hasText: 'Related acts and files' });
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

test.describe('where an act applies', () => {
  test('a regulation is not said to apply in all EU countries, and the Council’s record of who did not take part is given', async ({ page }) => {
    // Return Regulation (EU) 2026/2280, recital 67: Denmark "is not bound by it or subject to its application"; recital
    // 68: Ireland the same; the Council's voting result ST 13916/26 records both as not participating
    await open(page, 'legislation/2025-0059/');
    await expect(page.locator('.dz-facts')).toContainText('As a regulation, it applies directly; no national transposition is needed.');
    const national = page.locator('#national');
    await expect(national).toContainText('in the Member States it binds');
    await expect(national).toContainText('records Denmark and Ireland as not taking part');
    await expect(national).toContainText('says which Member States were not bound by it when it was adopted.');
    await expect(national).toContainText('Our data record no Commission decision confirming that Ireland has taken part since.');
    await expect(page.locator('main')).not.toContainText('all EU countries');
    await expect(page.locator('main')).not.toContainText('applies directly in every Member State');
  });

  test('a regulation Ireland opted into after its adoption says so, with the Commission decision', async ({ page }) => {
    // AMMR, Regulation (EU) 2024/1351, recital 91: Ireland "is not bound by it"; Commission Decision (EU) 2024/2088,
    // Art. 1: "The participation of Ireland in Regulation (EU) 2024/1351 is confirmed." Qualification Regulation (EU)
    // 2024/1347: Commission Decision (EU) 2024/2099
    for (const [id, label] of [
      ['2020-0279', 'Commission Decision (EU) 2024/2088'],
      ['2016-0223', 'Commission Decision (EU) 2024/2099'],
    ]) {
      await open(page, `legislation/${id}/`);
      const national = page.locator('#national');
      await expect(national).toContainText('records Denmark and Ireland as not taking part');
      // (the link's text is followed by the visually hidden "opens official website in a new tab")
      await expect(national).toContainText(`Ireland opted in after its adoption: ${label}`);
      await expect(national).toContainText(
        'of 31 July 2024 confirms its participation in the regulation (Protocol No 21, Article 4).',
      );
      await expect(national.getByRole('link', { name: label })).toHaveAttribute('href', /CELEX:32024D20(88|99)$/);
      await expect(national).not.toContainText('says which Member States it binds');
      await expect(national).not.toContainText('no Commission decision confirming');
    }
  });

  test('a regulation implementing enhanced cooperation binds only the Member States taking part', async ({ page }) => {
    // EPPO, Council Regulation (EU) 2017/1939, recital 110; Art. 20(4) TEU: "shall bind only participating Member States"
    await open(page, 'legislation/2013-0255/');
    await expect(page.locator('.dz-facts')).toContainText('only in the Member States taking part in the enhanced cooperation it implements');
    await expect(page.locator('#national')).toContainText('This one implements enhanced cooperation');
  });

  test('a country with an open non-communication case is not said to have notified incompletely (NIS2, Ireland)', async ({ page }) => {
    // INFR(2024)0279: caseType "Non-communication of transposition measures for directives", no measure notified
    await open(page, 'legislation/2020-0359/');
    const national = page.locator('#national');
    await expect(national).toContainText('Commission case open for non-communication of transposition measures');
    await expect(national).not.toContainText('incomplete notification');
  });

  test('the latest step says that an amending act outside our data is not dated (EUDR)', async ({ page }) => {
    // Commission Delegated Regulation (EU) 2026/2102 of 13 July 2026, in force on 18 September 2026 (Cellar)
    await open(page, 'legislation/2021-0366/');
    await expect(page.locator('.dz-fact', { hasText: 'Latest recorded step' })).toContainText(
      'EUR-Lex also lists Delegated Regulation 2026/2102 as amending this act. That act is not in our data',
    );
  });
});

test.describe('dates checked against the act’s text', () => {
  test('the DSA says that it applied earlier to designated very large platforms and search engines (Art. 92)', async ({ page }) => {
    // Regulation (EU) 2022/2065, Art. 92: from four months after the notification of the designation, "where that date is
    // earlier than 17 February 2024"
    await open(page, 'legislation/2020-0361/');
    const when = page.locator('#when-it-applies');
    await expect(when).toContainText('unless it applied earlier to a designated very large online platform or search engine (Art. 92)');
    await expect(when.locator('.dz-dates__note').first()).toContainText('under Article 92 the Regulation applies to providers of very large online platforms');
    await expect(when.getByRole('link', { name: 'Regulation (EU) 2022/2065, Articles 92 and 93' })).toBeVisible();
  });

  test('the own-resources decision says why it entered into force after it applied (Art. 311 TFEU)', async ({ page }) => {
    // Decision (EU, Euratom) 2020/2053, Art. 12; Art. 311 TFEU, third paragraph
    await open(page, 'legislation/2018-0135/');
    const note = page.locator('#when-it-applies .dz-dates__note').first();
    await expect(note).toContainText('Dates checked against the act’s text.');
    await expect(note).toContainText('third paragraph of Article 311 TFEU');
    await expect(note).toContainText('1 June 2021, as EUR-Lex records');
  });
});
