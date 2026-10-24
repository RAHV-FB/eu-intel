/**
 * The law (dossier) and vote pages on the built site: the status on the first screen of every law page, the key
 * facts as labelled rows, "When it applies" in time order, "What is it?" without a summary, the jump navigation on
 * phones and on the vote page, and the route from a vote on to the Council's vote on the same file. Real records;
 * see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { AI_ACT_ID, BASE_PATH } from './env';
import { expect, open, test } from './fixtures';

const PHONE = { width: 375, height: 812 };

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

/** The section's heading sits just below the sticky site header, with keyboard focus on it. */
async function expectLandedOn(page: Page, id: string) {
  await expect(page).toHaveURL(new RegExp(`#${id}$`));
  const heading = page.locator(`#${id}`).locator('h2').first();
  await expect(heading).toBeFocused();
  await expect
    .poll(async () => {
      const header = await page.locator('header').first().boundingBox();
      const box = await heading.boundingBox();
      return box && header ? Math.round(box.y - (header.y + header.height)) : -1;
    })
    .toBeGreaterThanOrEqual(0);
  const box = await heading.boundingBox();
  expect(box!.y).toBeLessThan(200);
}

test.describe('law page: status and key facts', () => {
  // in force, in negotiations, withdrawn, split, consultation, a directive being transposed
  for (const [id, label] of [
    [AI_ACT_ID, 'In force'],
    ['2023-0212', 'Negotiations with the Council'],
    ['2023-0133', 'Withdrawn by the Commission'],
    ['2016-0400', 'Split into separate procedures'],
    ['2023-0441', 'Parliament gave its opinion'],
    ['2020-0359', 'In force'],
  ])
    test(`the status of ${id} is on the first screen of a phone, under the title`, async ({ page }) => {
      await page.setViewportSize(PHONE);
      await open(page, `legislation/${id}/`);
      const badge = page.locator('.dz-head .dz-statusline .badge');
      await expect(badge).toHaveText(new RegExp(`${label}$`));
      expect((await badge.boundingBox())!.y + (await badge.boundingBox())!.height).toBeLessThanOrEqual(PHONE.height);
      // shown once: the "Current status" row explains it
      await expect(page.locator('.dz-facts .badge')).toHaveCount(0);
    });

  test('says since when the status holds', async ({ page }) => {
    await open(page, `legislation/${AI_ACT_ID}/`);
    await expect(page.locator('.dz-statusline')).toHaveText(/In force\s*since 1 August 2024$/);
  });

  test('gives each key fact a full-width row with its label beside it, at a readable line length', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await open(page, `legislation/${AI_ACT_ID}/`);
    const facts = page.locator('.dz-fact');
    await expect(facts.locator('dt')).toHaveText(['Current status', 'Latest recorded step', 'What happens next']);
    const boxes = await Promise.all([0, 1, 2].map((i) => facts.nth(i).locator('dd').boundingBox()));
    expect(new Set(boxes.map((b) => Math.round(b!.x))).size).toBe(1); // one column, stacked
    expect(boxes[0]!.y).toBeLessThan(boxes[1]!.y);
    expect(boxes[1]!.y).toBeLessThan(boxes[2]!.y);
    for (const b of boxes) expect(b!.width).toBeGreaterThan(400); // about 65 characters, not 26
    // one name for the latest step: the key-facts card does not repeat it under another heading
    await expect(page.locator('.dz-keyfacts')).not.toContainText('Latest');
  });

  test('says what happens next for a regulation in force by the dates still to come', async ({ page }) => {
    await open(page, `legislation/${AI_ACT_ID}/`);
    const next = page.locator('.dz-fact', { hasText: 'What happens next' });
    await expect(next).toContainText(/^What happens nextProvisions of the act start to apply on \d/);
    await expect(next).toContainText('As a regulation, it applies directly; no national transposition is needed.');
    await expect(next.getByRole('link', { name: 'When it applies' })).toHaveAttribute('href', '#when-it-applies');
  });

  test('"When it applies" is one schedule in time order', async ({ page }) => {
    await open(page, `legislation/${AI_ACT_ID}/`);
    const dates = await page.locator('.dz-sched li time').evaluateAll((ts) => ts.map((t) => t.getAttribute('datetime') ?? ''));
    expect(dates.length).toBeGreaterThan(5);
    expect(dates).toEqual([...dates].sort());
    await expect(page.locator('.dz-sched li').first()).toContainText(/1 Aug 2024\s*Entered into force/);
  });

  test('"What is it?" without a summary does not repeat the title: it points to the official text', async ({ page }) => {
    // 2023/0437(COD): its title is its official title; a proposal, COM(2023)0753
    await open(page, 'legislation/2023-0437/');
    const what = page.locator('.dz-what');
    await expect(what).toContainText('the heading above is its official title');
    await expect(what.locator('.dz-what__official')).toHaveCount(0);
    const proposal = 'https://www.europarl.europa.eu/RegData/docs_autres_institutions/commission_europeenne/com/2023/0753/COM_COM(2023)0753_EN.pdf';
    await expect(what.getByRole('link', { name: /the Commission proposal, COM\(2023\)0753/ })).toHaveAttribute('href', proposal);
    await expect(page.locator('.dz-official-links').getByRole('link', { name: /Commission proposal \(COM\(2023\)0753\)/ })).toHaveAttribute('href', proposal);
    await expect(page.locator('.dz-official-links')).toContainText('Procedure file (Legislative Observatory)');
    // an adopted act: its text on EUR-Lex (NIS 2 Directive)
    await open(page, 'legislation/2020-0359/');
    await expect(page.locator('.dz-what').getByRole('link', { name: /the adopted act on EUR-Lex/ })).toHaveAttribute('href', /CELEX:32022L2555/);
  });

  test('the Follow button says there are no alerts', async ({ page }) => {
    await open(page, `legislation/${AI_ACT_ID}/`);
    const hint = page.locator('.follow__hint');
    await expect(hint).toHaveText('Saved only in this browser: no account, no alerts, nothing sent anywhere. Check the Following page for changes.');
    await expect(hint.getByRole('link', { name: 'Following page' })).toHaveAttribute('href', `${BASE_PATH}following`);
  });
});

test.describe('law page: on this page', () => {
  test('on a phone, the sections are a row of links under the head that lands on each section', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await open(page, `legislation/${AI_ACT_ID}/`);
    const nav = page.getByRole('navigation', { name: 'On this page' });
    await expect(nav).toHaveCount(1);
    await expect(nav.getByRole('link')).toHaveText(['Timeline', 'Parliament votes', 'Council votes', 'In the Member States', 'Details & sources']);
    // above the summary, on the first screen
    const navBox = (await nav.boundingBox())!;
    expect(navBox.y + navBox.height).toBeLessThanOrEqual(PHONE.height);
    expect(navBox.y).toBeLessThan((await page.locator('.dz-summary').boundingBox())!.y);
    await nav.getByRole('link', { name: 'Council votes' }).click();
    await expectLandedOn(page, 'council-votes');
    await nav.getByRole('link', { name: 'Parliament votes' }).click();
    await expectLandedOn(page, 'ep-votes');
    await expectNoSeriousA11yViolations(page);
  });

  test('a file still being decided starts with "Where it is now"', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await open(page, 'legislation/2023-0212/');
    await expect(page.getByRole('navigation', { name: 'On this page' }).getByRole('link').first()).toHaveText('Where it is now');
  });

  test('on a wide screen, only the sidebar list is shown', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await open(page, `legislation/${AI_ACT_ID}/`);
    const nav = page.getByRole('navigation', { name: 'On this page' });
    await expect(nav).toHaveCount(1);
    await expect(nav).toHaveClass(/dz-toc/);
    await expect(page.locator('.dz-jump')).toBeHidden();
  });
});

test.describe('vote page', () => {
  for (const viewport of [PHONE, { width: 1280, height: 800 }])
    test(`jumps to each breakdown (${viewport.width}px)`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await open(page, 'votes/166051/'); // AI Act, final vote, 13 March 2024
      const nav = page.getByRole('navigation', { name: 'On this page' });
      await expect(nav.getByRole('link')).toHaveText(['By political group', 'By MEPs’ country', 'Individual MEPs']);
      await nav.getByRole('link', { name: 'Individual MEPs' }).click();
      await expectLandedOn(page, 'meps');
      await nav.getByRole('link', { name: 'By political group' }).click();
      await expectLandedOn(page, 'groups');
    });

  test('a shared link to a breakdown opens on it', async ({ page }) => {
    await open(page, 'votes/166051/#countries');
    await expectLandedOn(page, 'countries');
  });

  test('links on to how the Member States voted on the same file in the Council', async ({ page }) => {
    await open(page, 'votes/166051/');
    const link = page.getByRole('link', { name: 'How Member States voted on this file', exact: true });
    await expect(link).toHaveAttribute('href', `${BASE_PATH}legislation/${AI_ACT_ID}#council-votes`);
    await expect(page.locator('.facts div', { has: link })).toContainText('(21 May 2024)');
    await expect(page.locator('#countries').getByRole('link', { name: 'See how Member States voted on this file in the Council' })).toHaveCount(1);
    await link.click();
    await expectLandedOn(page, 'council-votes');
    await expect(page.locator('#council-votes article.cvote').first()).toBeVisible();
    await expectNoSeriousA11yViolations(page);
  });

  test('never links to a Council vote its file does not have, and has no jump links without individual votes', async ({ page }) => {
    await open(page, 'votes/199592/'); // 2026/0325(COD): no Council vote
    await expect(page.locator('main a[href$="#council-votes"]')).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'On this page' })).toHaveCount(1);
    await open(page, 'votes/195653/'); // no roll-call: no breakdowns to jump to
    await expect(page.getByRole('navigation', { name: 'On this page' })).toHaveCount(0);
  });
});
