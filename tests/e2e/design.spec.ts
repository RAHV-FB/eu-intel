/**
 * Shared visual patterns on the built site: status icons drawn in CSS (not font characters), status tags that wrap
 * cleanly, one section-title style, column headings on one line, metadata separators that never open a line,
 * readable line lengths, monospace only for identifiers, the footer kept out of view while a page loads (no layout
 * shift), and the not-found page. Uses real records; see playwright.config.ts to run.
 */
import type { Locator } from '@playwright/test';
import { AI_ACT_ID } from './env';
import { expect, open, settle, test } from './fixtures';

/** Files whose status covers every kind of stage (in progress, agreement, done, inactive, rejected, blocked),
 * including the longest status labels. */
const STAGE_SAMPLE = [
  '2018-0332', // blocked, the longest label
  '2023-0265', // in progress, long label
  '2025-0422', // proposal under examination
  '2026-0044', // provisional agreement
  '2013-0072', // in force
  '2024-0060', // withdrawn
  '2023-0413', // rejected
  '2025-0571R', // not a legislative act
];

/** Characters per rendered line of an element's text. */
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

test.describe('status tags', () => {
  for (const width of [320, 768, 1440]) {
    test(`every stage's icon is drawn in CSS, centred on the first line, and the tag fits (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await open(page, `following/?ids=${STAGE_SAMPLE.join(',')}`);
      const badges = page.locator('main .badge');
      await expect(badges).toHaveCount(STAGE_SAMPLE.length);
      const rows = await badges.evaluateAll((els) =>
        els.map((b) => {
          const r = b.getBoundingClientRect();
          const cs = getComputedStyle(b);
          const icon = b.querySelector<HTMLElement>('.status-icon');
          const ir = icon?.getBoundingClientRect();
          const firstLine = r.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop) + parseFloat(cs.lineHeight) / 2;
          const col = b.closest('.container')!;
          const colRight = col.getBoundingClientRect().right - parseFloat(getComputedStyle(col).paddingRight);
          return {
            label: b.textContent,
            iconText: icon?.textContent ?? null,
            iconSize: ir ? [Math.round(ir.width), Math.round(ir.height)] : null,
            iconOffset: ir ? Math.abs(ir.top + ir.height / 2 - firstLine) : null,
            radius: cs.borderTopLeftRadius,
            fits: r.right <= colRight + 0.5,
          };
        }),
      );
      for (const b of rows) {
        expect(b.iconText, b.label!).toBe(''); // no font character
        expect(b.iconSize, b.label!).toEqual([10, 10]);
        expect(b.iconOffset!, b.label!).toBeLessThanOrEqual(1.5);
        expect(b.radius, b.label!).toBe('4px'); // a tag, not a pill that turns into a lozenge when it wraps
        expect(b.fits, b.label!).toBe(true);
      }
      // the six shapes are different
      const shapes = await page.locator('main .status-icon').evaluateAll((els) =>
        [...new Set(els.map((e) => [...e.classList].find((c) => c.startsWith('status-icon--'))))].sort(),
      );
      expect(shapes).toEqual(['status-icon--agreement', 'status-icon--alert', 'status-icon--critical', 'status-icon--done', 'status-icon--inactive', 'status-icon--progress']);
    });
  }

  test('vote outcomes and Council outcomes use the same drawn icons', async ({ page }) => {
    await open(page, 'votes');
    await expect(page.locator('main .vote-item .badge .status-icon').first()).toHaveText('');
    await open(page, `legislation/${AI_ACT_ID}/`);
    const outcome = page.locator('.cvote__outcome .status-icon').first();
    await expect(outcome).toHaveText('');
    await expect(outcome).toHaveClass(/status-icon--done/);
  });
});

test.describe('section titles', () => {
  test('section titles look the same on the law, vote, MEP, group, country, guide and search pages', async ({ page }) => {
    const styles = new Set<string>();
    for (const path of [`legislation/${AI_ACT_ID}/`, 'votes/166051/', 'people/meps/124867/', 'people/groups/epp/', 'countries/ES/', 'how-the-eu-works', 'about', 'search?q=climate']) {
      await open(page, path);
      const found = await page.locator('main h2:visible').evaluateAll((hs) =>
        hs
          .filter((h) => h.matches('.section-title, .section > h2, .dz-section > h2, .csection > h2, .prose > section > h2, .sr-group__title'))
          .map((h) => {
            const s = getComputedStyle(h);
            return [s.fontFamily, s.fontSize, s.fontWeight, s.color, s.borderBottomWidth, s.borderBottomStyle, s.borderBottomColor].join(' | ');
          }),
      );
      expect(found.length, path).toBeGreaterThan(0);
      found.forEach((s) => styles.add(s));
    }
    expect([...styles]).toHaveLength(1);
  });
});

test.describe('tables', () => {
  test('sortable and plain column headings share one line, and an inactive sort mark is quieter', async ({ page }) => {
    await open(page, 'votes/166051/');
    const table = page.locator('section[aria-labelledby="groups-h"] table');
    // the bottom of each single-line heading's text: a sort button and plain text end on the same line
    const bottoms = await table.locator('thead th').evaluateAll((ths) =>
      ths
        .map((th) => {
          const range = document.createRange();
          range.selectNodeContents(th.querySelector('.sort-btn > span') ?? th);
          const rects = [...range.getClientRects()].filter((r) => r.width > 1);
          return rects.length === 1 ? Math.round(rects[0].bottom) : null; // skip two-line headings
        })
        .filter((b): b is number => b !== null),
    );
    expect(bottoms.length).toBeGreaterThan(3);
    expect(Math.max(...bottoms) - Math.min(...bottoms)).toBeLessThanOrEqual(1);
    const inactive = await table.locator('.sort-btn:not(.is-active) .sort-btn__icon').first().evaluate((e) => getComputedStyle(e).opacity);
    const active = await table.locator('.sort-btn.is-active .sort-btn__icon').first().evaluate((e) => getComputedStyle(e).opacity);
    expect(Number(inactive)).toBeLessThan(0.5);
    expect(Number(active)).toBe(1);
  });
});

test.describe('metadata separators', () => {
  for (const [path, sel] of [
    ['legislation', '.drow__meta'],
    ['votes', '.vote-item__meta'],
    ['search?q=climate', '.sr-item__meta'],
  ]) {
    test(`a wrapped line never starts with a separator: ${path} at 768px and 320px`, async ({ page }) => {
      for (const width of [768, 320]) {
        await page.setViewportSize({ width, height: 900 });
        await open(page, path);
        const starts = await page.locator(`main ${sel}`).evaluateAll((lists) =>
          lists.flatMap((list) => {
            // the clipped band on the left: the dot of an item that opens a line falls inside it
            const clip = /inset\(\S+ \S+ \S+ ([\d.]+)px\)/.exec(getComputedStyle(list).clipPath);
            const band = list.getBoundingClientRect().left + (clip ? parseFloat(clip[1]) : 0);
            let top = -1;
            const out: { visibleDot: boolean }[] = [];
            for (const item of list.children) {
              const r = item.getBoundingClientRect();
              if (Math.round(r.top) !== top) {
                top = Math.round(r.top);
                const dot = getComputedStyle(item, '::before');
                const dotWidth = parseFloat(dot.width) || 0;
                out.push({ visibleDot: dot.content !== 'none' && r.left + dotWidth > band + 0.5 });
              }
            }
            return out;
          }),
        );
        expect(starts.length, `${path} ${width}`).toBeGreaterThan(0);
        expect(starts.filter((s) => s.visibleDot), `${path} ${width}`).toEqual([]);
      }
    });
  }
});

test.describe('typography', () => {
  test('summaries keep a readable line length (law page, guide, lead)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, `legislation/${AI_ACT_ID}/`);
    // the measure is set in em, so how many characters fit depends on the system font each engine resolves (WebKit's
    // on Linux sets about 5% more than Chromium's): the bound is WCAG 1.4.8's 80 characters, which holds in each
    for (const l of await page.locator('.dz-what__text, .dz-block p').all()) expect(Math.max(...(await lineLengths(l)))).toBeLessThanOrEqual(80);
    await open(page, 'how-the-eu-works');
    expect(Math.max(...(await lineLengths(page.locator('.prose > section > p').first())))).toBeLessThanOrEqual(85);
    expect(Math.max(...(await lineLengths(page.locator('.page-header .lead'))))).toBeLessThanOrEqual(80);
  });

  test('monospace only for identifiers: readable labels and procedure references use the body font', async ({ page }) => {
    const mono = (l: Locator) => l.evaluate((el) => /mono|Menlo|Consolas|Courier/i.test(getComputedStyle(el).fontFamily));
    await open(page, 'votes/166051/');
    const facts = page.locator('section[aria-labelledby="what-h"] dl');
    expect(await mono(facts.locator('dt', { hasText: 'Text voted on' }).locator('xpath=following-sibling::dd'))).toBe(false);
    expect(await mono(facts.locator('dt', { hasText: 'Procedure' }).locator('xpath=following-sibling::dd'))).toBe(false);
    expect(await mono(facts.locator('dt', { hasText: 'Documents' }).locator('xpath=following-sibling::dd'))).toBe(true);
    await open(page, `legislation/${AI_ACT_ID}/`);
    expect(await mono(page.locator('.dz-crumbs [aria-current="page"]'))).toBe(false);
    const label = page.locator('.tl__docs li > span:not(.meta)', { hasText: 'Minutes of the sitting' }).first();
    expect(await mono(label)).toBe(false);
    expect(await mono(label.locator('xpath=following-sibling::span[contains(@class, "meta")]'))).toBe(true);
    await open(page, 'legislation');
    expect(await mono(page.locator('.drow__meta .ref').first())).toBe(false);
  });
});

test.describe('pages while they load', () => {
  for (const width of [1280, 390]) {
    test(`the footer stays below the screen while a law page loads, so it does not jump away (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      let release!: () => void;
      const held = new Promise<void>((r) => (release = r));
      await page.route(`**/data/dossiers/${AI_ACT_ID}.json`, async (route) => {
        await held;
        await route.continue();
      });
      await page.goto(`legislation/${AI_ACT_ID}/`);
      await expect(page.locator('.state--loading')).toBeVisible();
      const top = await page.locator('.site-footer').evaluate((el) => el.getBoundingClientRect().top);
      expect(top).toBeGreaterThanOrEqual(800);
      release();
      await settle(page);
    });
  }

  test('the homepage keeps the loading text in view and the guide teaser in place while its data loads', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    let release!: () => void;
    const held = new Promise<void>((r) => (release = r));
    await page.route('**/data/home.json', async (route) => {
      await held;
      await route.continue();
    });
    await page.goto('./');
    const loading = page.locator('.state--loading');
    await expect(loading).toBeVisible();
    await expect(loading).toBeInViewport();
    const text = await loading.evaluate((el) => {
      const r = document.createRange();
      r.selectNodeContents(el);
      return [...r.getClientRects()].filter((x) => x.width > 1).map((x) => x.bottom);
    });
    expect(Math.max(...text)).toBeLessThan(800);
    const before = await page.locator('.home__guide').evaluate((el) => el.getBoundingClientRect().top);
    expect(before).toBeGreaterThanOrEqual(800);
    release();
    await settle(page);
  });
});

test('the not-found page offers a search and the six main sections', async ({ page, guard }) => {
  guard.ignore(/404/);
  await open(page, 'this-page-does-not-exist/');
  await expect(page.locator('main h1')).toHaveText('We couldn’t find this page');
  await expect(page.locator('main .not-found__search input[type="search"]')).toBeVisible();
  await expect(page.locator('main .not-found__links a')).toHaveText(['Discover', 'Legislation', 'Votes', 'People & Parties', 'Countries', 'How the EU Works']);
});
