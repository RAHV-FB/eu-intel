/**
 * Keyboard focus after "Show more" on every paged list, result counts read out once typing stops, "Copy link"
 * confirmations, the Following page's button names and the heading outline of the legislation list. Real records;
 * see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Locator, Page } from '@playwright/test';
import { AI_ACT_ID } from './env';
import { expect, open, test } from './fixtures';

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

/** The lists (and table bodies) in main, and how many rows each one holds. */
const rowCounts = (page: Page) =>
  page.locator('main').evaluate((m) => [...m.querySelectorAll('tbody, ul.vote-list, ol.drows')].map((l) => l.children.length));

/** Of the focused element: which of those lists it is in (-1: none), the index of its row there, and its tag. */
const focusedRow = (page: Page) =>
  page.locator('main').evaluate((m) => {
    const lists = [...m.querySelectorAll('tbody, ul.vote-list, ol.drows')];
    const a = document.activeElement;
    const list = lists.findIndex((l) => l.contains(a));
    const row = list >= 0 ? [...lists[list].children].findIndex((r) => r.contains(a)) : -1;
    return { list, row, tag: a?.tagName ?? null };
  });

test.describe('"Show more" moves keyboard focus to the first row it shows', () => {
  for (const [path, name] of [
    ['legislation/', /^Show [\d,]+ more$/],
    ['votes/', /^Show \d+ more$/],
    ['votes/166051/', /^Show more MEPs$/],
    // the button goes away with the last rows: focus must not fall back to the page
    ['votes/166051/', /^Show all [\d,]+$/],
    ['people/meps/101039/', /^Show more votes$/],
    ['people/groups/epp/', /^Show more votes$/],
    ['countries/IT/', /^Show more directives$/],
    ['countries/IT/?inf-status=all', /^Show more cases$/],
    ['people/', /^Show \d+ more$/],
    ['people/?view=parties&pscope=all', /^Show \d+ more$/],
  ] as const) {
    test(`${path} "${name.source}"`, async ({ page }) => {
      await open(page, path);
      const before = await rowCounts(page);
      await page.getByRole('button', { name }).press('Enter');
      await expect.poll(async () => (await focusedRow(page)).tag).toBe('A');
      const { list, row } = await focusedRow(page);
      expect(list, 'focus is in a list of the page').toBeGreaterThanOrEqual(0);
      expect(row, 'the first row shown by the button').toBe(before[list]);
      expect((await rowCounts(page))[list]).toBeGreaterThan(before[list]);
      await expect(page.locator(':focus')).toBeInViewport();
    });
  }

  test('on the votes list, focus goes to the title of the first new vote', async ({ page }) => {
    await open(page, 'votes/');
    await page.getByRole('button', { name: /^Show \d+ more$/ }).press('Enter');
    await expect(page.locator('ul.vote-list > li').nth(50).locator('.vote-item__title a')).toBeFocused();
  });
});

/** Every change of a status region's text, from now on (each region: its text after the change). */
async function recordStatus(region: Locator) {
  await region.evaluate((el) => {
    const w = window as unknown as { __said: string[] };
    w.__said = [];
    new MutationObserver(() => w.__said.push(el.textContent ?? '')).observe(el, { childList: true, subtree: true, characterData: true });
  });
  return () => region.page().evaluate(() => (window as unknown as { __said: string[] }).__said);
}

test.describe('a list’s result count is read out once typing stops, never on every key', () => {
  for (const [path, input, text, count] of [
    ['votes/', '#vf-q', 'energy', '.results-bar__count'],
    ['votes/166051/', '#bl-q', 'kelly', '.results-bar__count'],
    // before the fix: "0 files match" while the search index loaded, then the count
    ['legislation/', 'main input[type=search]', 'cyber', '.lx-count'],
    ['people/', '#mf-q', 'garcia', '.results-bar__count'],
  ] as const) {
    test(`${path} typing “${text}”`, async ({ page }) => {
      await open(page, path);
      const shown = page.locator(count);
      // the count shown is not a live region itself; its status region (next to it) starts with the same text
      await expect(shown).not.toHaveAttribute('aria-live');
      await expect(shown).not.toHaveAttribute('role');
      const status = page.locator(`${count} + [role="status"]`);
      await expect(status).toHaveAttribute('aria-atomic', 'true');
      expect(await status.textContent()).toBe(await shown.textContent());
      const said = await recordStatus(status);
      await page.locator(input).first().pressSequentially(text, { delay: 40 });
      // once settled, the status says what the count shows
      await expect.poll(async () => (await status.textContent()) === (await shown.textContent()) && (await said()).length > 0).toBe(true);
      await page.waitForTimeout(1500);
      expect(await said(), 'one announcement, the final count').toEqual([await shown.textContent()]);
    });
  }

  test('each list has one status region for its count', async ({ page }) => {
    await open(page, 'votes/');
    await expect(page.locator('main [role="status"], main [aria-live]')).toHaveCount(1);
    await open(page, 'countries/IT/?inf-status=all');
    await expect(page.locator('main [role="status"], main [aria-live]')).toHaveCount(2); // directives, cases
  });
});

const COPIED_OR_NOT = (fallback: string) => new RegExp(`^(Link copied to your clipboard\\.|The link could not be copied\\. ${fallback})$`);

test('"Copy link to this view" on the legislation list says in a status message whether the link was copied', async ({ page }) => {
  await open(page, 'legislation/?topic=tech');
  const status = page.locator('.lx-results-tools [role="status"]');
  await expect(status).toHaveText('');
  await page.getByRole('button', { name: 'Copy link to this view' }).click();
  await expect(status).toHaveText(COPIED_OR_NOT('Copy it from the browser’s address bar\\.'));
  const copied = (await status.textContent())!.startsWith('Link copied');
  await expect(page.locator('.lx-results-tools button')).toHaveText(copied ? 'Link copied' : 'Could not copy the link');
  await expectNoSeriousA11yViolations(page);
});

test('Following: "Copy link" is confirmed in the status region; the help text under the link is not a status message', async ({ page }) => {
  await open(page, `following/?ids=${AI_ACT_ID},2022-0155`);
  const help = page.getByText('Anyone with this link sees the same files');
  await expect(help).toBeVisible();
  const status = page.locator('main [role="status"]');
  await expect(status).toHaveCount(1);
  await page.getByRole('button', { name: 'Copy link', exact: true }).click();
  await expect(status).toHaveText(COPIED_OR_NOT('Copy it from the link field\\.'));
  if ((await status.textContent())!.startsWith('Link copied')) {
    // the help text comes back, and the confirmation is cleared without another announcement
    await expect(help).toBeVisible();
    await expect(status).toHaveText('');
  }
  await expect(page.getByRole('status').filter({ hasText: 'Anyone with this link' })).toHaveCount(0);
});

test('Following: each "Mark as seen" button names its file', async ({ page }) => {
  await open(page, './');
  await page.evaluate((ids) => {
    const items = ids.map((id) => ({
      id,
      added_at: '2026-01-01T00:00:00Z',
      seen_at: '2026-01-01T00:00:00Z',
      seen: { last_event: '2000-01-01', stage: 'proposal', status_label: 'Commission proposal' },
    }));
    localStorage.setItem('eu-intel.following.v1', JSON.stringify({ v: 1, items }));
  }, [AI_ACT_ID, '2022-0155']);
  await open(page, 'following/');
  const titles = await page.locator('.following__list h3').allTextContents();
  expect(titles).toHaveLength(2);
  for (const t of titles) {
    const button = page.getByRole('button', { name: `Mark as seen: ${t}`, exact: true });
    await expect(button).toHaveCount(1);
    await expect(button).toHaveText('Mark as seen');
  }
  await expectNoSeriousA11yViolations(page);
});

test('legislation list: the files’ titles (h3) come under a Results heading (h2), with no level skipped', async ({ page }) => {
  for (const path of ['legislation/', 'legislation/?topic=tech']) {
    await open(page, path);
    await expect(page.getByRole('heading', { level: 2, name: 'Results', exact: true })).toHaveCount(1);
    const levels = await page.locator('main').evaluate((m) => [...m.querySelectorAll('h1, h2, h3, h4, h5, h6')].map((h) => Number(h.tagName[1])));
    expect(levels.slice(0, 2)).toEqual([1, 2]);
    expect(levels.filter((l, i) => i > 0 && l > levels[i - 1] + 1), 'levels skipped').toEqual([]);
  }
});
