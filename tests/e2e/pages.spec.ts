/**
 * Page-level regressions on the built site: party records by term, country directive search, filters kept in the
 * address for Back, split parents and Parliament reports, the Following page's keyboard focus, not-found titles,
 * prerendered metadata and phone layouts. Uses real records (ids below); see playwright.config.ts to run.
 */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { BASE_PATH, PAGES_ORIGIN, SITE_NAME } from './env';
import { expect, open, settle, test } from './fixtures';

async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`);
  expect(serious, 'serious/critical axe-core violations').toEqual([]);
}

test.describe('party records', () => {
  test('a 2019–2024 record says so, links the current record and calls sitting MEPs current', async ({ page }) => {
    await open(page, 'people/parties/5494/'); // Rassemblement national, 2019–2024 record (EP corporate body 5494)
    await expect(page.locator('.eyebrow')).toHaveText('National party · France · 2019–2024 term');
    await expect(page.locator('.facts')).not.toContainText('Current MEPs');
    await expect(page.locator('.party-record').getByRole('link', { name: 'Rassemblement national' })).toHaveAttribute('href', `${BASE_PATH}people/parties/6848`);
    const bardella = page.getByRole('row', { name: /Jordan Bardella/ });
    await expect(bardella).toContainText('Current MEP');
    await expect(bardella).not.toContainText('Former MEP');
    await expect(bardella.getByRole('link', { name: 'Rassemblement national' })).toHaveAttribute('href', `${BASE_PATH}people/parties/6848`);
    await expectNoSeriousA11yViolations(page);
  });

  for (const width of [320, 390]) {
    test(`the MEP table fits a ${width}px screen with the period on screen`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await open(page, 'people/parties/5218/');
      const wrap = page.locator('section[aria-labelledby="pm-h"] .table-wrap');
      const [scroll, client] = await wrap.evaluate((el) => [el.scrollWidth, el.clientWidth]);
      expect(scroll).toBeLessThanOrEqual(client);
      await expect(page.getByRole('row', { name: /Laura Huhtasaari/ })).toContainText('2 Jul 2019 – 11 Apr 2023');
    });
  }
});

test.describe('country page directive search', () => {
  test('finds a directive by its number or common name and keeps the search for Back', async ({ page }) => {
    await open(page, 'countries/IE/');
    const count = page.locator('#tr-q').locator('xpath=ancestor::form/following-sibling::p[1]');
    for (const q of ['NIS2', '2022/2555', 'Directive (EU) 2022/2555']) {
      await page.fill('#tr-q', q);
      await expect(count).toHaveText('1 directive');
      await expect(page.locator('td.impl-dir').first()).toContainText('· Directive (EU) 2022/2555 (NIS 2 Directive)');
    }
    await page.fill('#tr-q', '2022/2464');
    await expect(page.locator('td.impl-dir').first()).toContainText('Corporate Sustainability Reporting Directive');
    await expect(page.locator('td.impl-dir', { hasText: '2025/794' })).toContainText('its title cites 2022/2464');
    await page.locator('td.impl-dir a', { hasText: 'Corporate Sustainability Reporting Directive' }).click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('#tr-q')).toHaveValue('2022/2464');
    await expect(page.locator('td.impl-dir').first()).toContainText('Corporate Sustainability Reporting Directive');
    await expectNoSeriousA11yViolations(page);
  });

  test('a directive row says when the country is in an open non-communication case for it, as the law page does', async ({ page }) => {
    // NIS2, France: 15 measures, "Measures notified", and INFR(2024)0274 (non-communication) referred to the Court
    await open(page, 'countries/FR/?tr-q=2022%2F2555');
    const row = page.locator('tr', { has: page.locator('td.impl-dir', { hasText: 'Directive (EU) 2022/2555' }) });
    await expect(row).toContainText('Measures notified');
    await expect(row.locator('td.hide-narrow').last()).toContainText('Commission case open for non-communication of transposition measures');
    await open(page, 'legislation/2020-0359/');
    const fr = page.locator('#national tr', { has: page.getByRole('link', { name: 'France', exact: true }) });
    await expect(fr).toContainText('Commission case open for non-communication of transposition measures');
  });

  test('says when nothing matches and offers the site search', async ({ page }) => {
    await open(page, 'countries/IE/?tr-q=zzqx');
    await expect(page.getByRole('link', { name: 'Search the whole site' })).toHaveAttribute('href', `${BASE_PATH}search?q=zzqx`);
  });

  test('shows no empty indicators section', async ({ page }) => {
    await open(page, 'countries/LV/');
    await expect(page.locator('#implementation h3')).toHaveText(['National measures for directives', 'Infringement cases']);
  });
});

test.describe('Back returns to the same list', () => {
  test('ballot filters on a vote page', async ({ page }) => {
    await open(page, 'votes/154623/');
    await page.selectOption('#bl-country', 'GR');
    await expect(page).toHaveURL(/bl-country=GR/);
    const counter = page.locator('.results-bar__count', { hasText: 'MEPs with a recorded vote' });
    const filtered = await counter.textContent();
    await page.locator('table a[href*="/people/meps/"]').first().click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('#bl-country')).toHaveValue('GR');
    await expect(counter).toHaveText(filtered!);
  });

  test('the opened list of MEPs on a country page', async ({ page }) => {
    await open(page, 'countries/MT/');
    await page.getByRole('button', { name: /Show all \d+ current MEPs from Malta/ }).click();
    await page.locator('#country-meps a[href*="/people/meps/"]').first().click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('#country-meps')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Hide the list of MEPs' })).toHaveAttribute('aria-expanded', 'true');
  });

  test('"Show more" on the votes list', async ({ page }) => {
    await open(page, 'votes');
    await page.getByRole('button', { name: /^Show \d+ more$/ }).click();
    await expect(page).toHaveURL(/show=100/);
    const last = page.locator('main a[href*="/votes/1"]').last();
    const href = await last.getAttribute('href');
    await last.click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator(`main a[href="${href}"]`)).toHaveCount(1);
  });
});

test.describe('split parents and Parliament reports', () => {
  test('a split parent does not present its generated name as an official title, and its part links differ', async ({ page }) => {
    await open(page, 'legislation/2016-0400/');
    await expect(page.locator('.dz-what')).not.toContainText('Its official title is');
    const parts = page.locator('.dz-what a');
    await expect(parts).toHaveText([/^2016\/0400A\(COD\) Adapting/, /^2016\/0400B\(COD\) Adapting/]);
    await expect(page.locator('.dz-parts li').nth(1)).toContainText('Withdrawn by the Commission');
    await expectNoSeriousA11yViolations(page);
  });

  test('a split parent lists its separate files once; the other sections point to that list', async ({ page }) => {
    await open(page, 'legislation/2016-0400/');
    await expect(page.locator('.dz-what .dz-label')).toHaveText(['This proposal was split into']);
    // the parts are linked from the list only (Details & sources is collapsed and lists the related files on request)
    await expect(page.locator('main a[href$="/legislation/2016-0400A"]:not(#details a)')).toHaveCount(1);
    await expect(page.locator('main a[href$="/legislation/2016-0400B"]:not(#details a)')).toHaveCount(1);
    for (const id of ['ep-votes', 'council-votes', 'national']) {
      const note = page.locator(`#${id} .dz-none`);
      await expect(note).toContainText('This proposal was split');
      await expect(note.getByRole('link', { name: 'See the separate files' })).toHaveAttribute('href', '#split-parts');
    }
    await expect(page.locator('.dz-fact', { hasText: 'What happens next' })).toContainText('None on this file: each separate file listed above has its own next step.');
  });

  test('a split parent gives the proposal date and document that all its parts record', async ({ page }) => {
    await open(page, 'legislation/2016-0224/'); // 2016/0224A and B(COD): COM(2016)0467 of 13 July 2016
    await page.locator('#details summary').click();
    const proposed = page.locator('#details .dz-kv > div', { has: page.locator('dt', { hasText: /^Proposed/ }) });
    await expect(proposed.locator('dt')).toHaveText('Proposed (as recorded for its parts)');
    await expect(proposed.locator('dd')).toHaveText('13 July 2016');
    await expect(page.locator('#details')).toContainText('COM(2016)0467');
  });

  test('a report links its main file in the status and the next step', async ({ page }) => {
    await open(page, 'legislation/2020-0112R/');
    const facts = page.locator('.dz-facts');
    await expect(facts.getByRole('link', { name: '2020/0112(APP)' })).toHaveCount(2);
    await expect(facts.getByRole('link', { name: '2020/0112(APP)' }).first()).toHaveAttribute('href', `${BASE_PATH}legislation/2020-0112`);
  });

  test('the latest development is the milestone of the same day', async ({ page }) => {
    await open(page, 'legislation/2025-0418/');
    await expect(page.locator('.dz-fact', { hasText: 'Latest recorded step' })).toContainText(
      'Parliament sent the file back to committee to negotiate with the Council',
    );
  });
});

test.describe('Following', () => {
  test('the Follow toggle keeps its name; Unfollow and Clear all keep keyboard focus on the page', async ({ page }) => {
    for (const id of ['2021-0106', '2022-0047', '2020-0374']) {
      await open(page, `legislation/${id}/`);
      const toggle = page.getByRole('button', { name: 'Follow this legislation' });
      await toggle.click();
      await expect(toggle).toHaveAttribute('aria-pressed', 'true');
      await expect(toggle).toHaveText(/Follow this legislation/);
    }
    await open(page, 'following');
    await expect(page.locator('.following__privacy')).toContainText('when you followed it and when you last viewed it');
    const titles = await page.locator('.following__list h3').allTextContents();
    await page.getByRole('button', { name: `Unfollow ${titles[1]}` }).press('Enter');
    await expect(page.locator(':focus')).toHaveText(titles[2]);
    await expect(page.getByRole('status').filter({ hasText: `Removed ${titles[1]}` })).toHaveCount(1);
    await page.getByRole('button', { name: 'Clear all' }).press('Enter');
    await expect(page.locator(':focus')).toHaveText('Cancel');
    await page.keyboard.press('Enter');
    await expect(page.locator(':focus')).toHaveText('Clear all');
    await page.keyboard.press('Enter');
    await page.getByRole('button', { name: /Yes, remove all/ }).press('Enter');
    await expect(page.locator(':focus')).toContainText('You are not following any legislation yet');
    await expectNoSeriousA11yViolations(page);
  });
});

test.describe('not-found pages say so in their title', () => {
  for (const [path, title] of [
    ['nope-not-here/', 'Page not found'],
    ['votes/999999999/', 'Vote not found'],
    ['people/meps/1/', 'MEP not found'],
    ['people/groups/xyz/', 'Political group not found'],
    ['people/parties/1/', 'National party not found'],
    ['countries/XX/', 'Country not found'],
    ['legislation/garbage/', 'Legislative file not found'],
  ]) {
    test(path, async ({ page, guard }) => {
      guard.ignore(/404|missing data file/); // the entity's data file does not exist
      await open(page, path);
      await expect(page).toHaveTitle(`${title} – ${SITE_NAME}`);
    });
  }
});

test.describe('prerendered metadata (GitHub Pages semantics)', () => {
  const get = async (request: import('@playwright/test').APIRequestContext, p: string) => {
    const res = await request.get(`${PAGES_ORIGIN}${BASE_PATH}${p}`);
    return { status: res.status(), html: await res.text() };
  };
  test('former MEPs, votes without counts and unnamed parties', async ({ request }) => {
    expect((await get(request, 'people/meps/197619/')).html).toContain(
      '<meta name="description" content="Former Member of the European Parliament elected in Italy." />',
    );
    const vote = /<meta name="description" content="([^"]*)"/.exec((await get(request, 'votes/195653/')).html)?.[1];
    expect(vote).toBe(
      "European Parliament vote of 9 Jul 2026: Parliament approved the committee's decision to enter into negotiations with the Council. No vote counts are recorded.",
    );
    const party = await get(request, 'people/parties/5719/');
    expect(party.status).toBe(200);
    expect(party.html).toContain('<title>Party name not recorded (Croatia) – EU Legislative Intelligence</title>');
  });

  test('one abstention is "1 abstention"', async ({ request }) => {
    const vote = /<meta name="description" content="([^"]*)"/.exec((await get(request, 'votes/139917/')).html)?.[1];
    expect(vote).toBe('European Parliament vote of 16 Feb 2022: 688 for, 6 against, 1 abstention.');
  });
});

test.describe('what a vote decided', () => {
  test('a motion of censure states both conditions; the vote bar says "1 abstention"', async ({ page }) => {
    await open(page, 'votes/179569/');
    await expect(page.locator('.margin-box')).toContainText(
      'Votes in favour needed: 372. Both conditions must be met: two thirds of the 557 votes cast for or against (372; abstentions do not count) and a majority of the 719 Members in office on the day of the vote (360)',
    );
    await open(page, 'votes/139917/');
    await expect(page.locator('.vote-summary [role="img"]')).toHaveAttribute('aria-label', 'Official result: 688 for, 1 abstention, 6 against');
  });

  test('a second-reading approval without a vote says so instead of "No roll-call vote is matched"', async ({ page }) => {
    await open(page, 'legislation/2018-0198/');
    const section = page.locator('#ep-votes');
    await expect(section).toContainText('Parliament approved the Council’s position at second reading without a vote on the text');
    await expect(section).toContainText('“Approval without vote”');
    await expect(section).not.toContainText('No roll-call vote is matched');
  });

  test('on a phone, group votes on one file show what each vote was', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, 'people/groups/s-d/');
    // 22 Oct 2026, 2026/0325(COD): the negotiating mandate (199592) and the motion to reject the proposal (199567)
    const row = (id: string) => page.locator('tr', { has: page.locator(`a[href$="/votes/${id}"]`) }).locator('.vote-row-meta');
    await expect(row('199592')).toHaveText("Vote on Parliament's negotiating mandate · 2026/0325(COD)");
    await expect(row('199567')).toHaveText('Vote on a motion to reject the Commission proposal · 2026/0325(COD)');
  });
});

test.describe('vote tables of MEP and group pages', () => {
  // They read votes/titles.json (the votes of the index with only the fields they show), not the 2.5 MB votes/index.json
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const RESULT: Record<string, string> = { adopted: 'Adopted', rejected: 'Rejected', lapsed: 'Lapsed' };
  type Row = { id: string; date: string; display_title: string; kind_label: string; procedure_ref?: string | null; distinction?: string; outcome: string };

  for (const [path, section, mep] of [
    ['people/meps/124858/', 'v-h', true],
    ['people/groups/s-d/', 'gv-h', false],
  ] as const) {
    test(`${path} shows each vote’s date, title, line and result without requesting votes/index.json`, async ({ page, request }) => {
      const requested: string[] = [];
      page.on('request', (r) => requested.push(new URL(r.url()).pathname));
      await open(page, path);
      expect(requested.filter((p) => p.endsWith('/data/votes/index.json'))).toEqual([]);
      expect(requested.filter((p) => p.endsWith('/data/votes/titles.json'))).toHaveLength(1);

      const index = (await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/votes/index.json`)).json()) as Row[];
      const byId = new Map(index.map((v) => [v.id, v]));
      const rows = page.locator(`section[aria-labelledby="${section}"] tbody tr`);
      await expect(rows.first()).toBeVisible();
      for (let i = 0; i < 6; i++) {
        const row = rows.nth(i);
        const href = (await row.locator('a[href*="/votes/"]').first().getAttribute('href')) ?? '';
        const v = byId.get(decodeURIComponent(href.split('/votes/')[1]));
        expect(v, `vote of row ${i} (${href}) is in the index`).toBeDefined();
        const [y, m, d] = v!.date.split('-').map(Number);
        await expect(row.locator('a[href*="/votes/"]').first()).toHaveText(v!.display_title);
        // innerText: the MEP table's cells carry a label for phones, hidden here
        await expect(row.locator('td').first()).toHaveText(`${d} ${MONTHS[m - 1]} ${y}`, { useInnerText: true });
        const line = [v!.kind_label, v!.procedure_ref, v!.distinction].filter(Boolean).join(' · ');
        if (line) await expect(row.locator('.vote-row-meta')).toHaveText(line);
        else await expect(row.locator('.vote-row-meta')).toHaveCount(0);
        if (mep) await expect(row.locator('td').last()).toContainText(RESULT[v!.outcome] ?? '—');
        // no placeholder where the vote's details belong (a title may itself end in "…")
        await expect(row.locator('.muted').filter({ hasText: /^(…|Not loaded)$/ })).toHaveCount(0);
      }
    });
  }
});

test('an MEP’s membership data links the EP Open Data API record', async ({ page }) => {
  await open(page, 'people/meps/124858/');
  await expect(page.getByRole('link', { name: /EP Open Data API – MEP 124858/ })).toHaveAttribute(
    'href',
    'https://data.europarl.europa.eu/api/v2/meps/124858?format=application%2Fld%2Bjson',
  );
});

test('home cards do not scroll sideways at 320px with increased text spacing (WCAG 1.4.12)', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await open(page, './');
  await page.addStyleTag({ content: '*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important} p{margin-bottom:2em!important}' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test.describe('filters kept in the address keep what is typed', () => {
  // React Router renders a new address after the keystroke: a box that read its text back from the address moved
  // the caret to the end and dropped keys typed in between ("network and information security" became "er fraiy")
  for (const [path, box, param] of [
    ['countries/IE/', '#tr-q', 'tr-q'],
    ['countries/IE/', '#inf-q', 'inf-q'],
    ['votes/199592/', '#bl-q', 'bl-q'],
    ['votes', '#vf-q', 'q'],
    ['people', '#mf-q', 'q'],
    ['people?view=parties', '#pf-q', 'pq'],
  ]) {
    test(`${path} ${box}`, async ({ page }) => {
      await open(page, path);
      const input = page.locator(box);
      await input.click();
      await page.keyboard.type('abcd', { delay: 30 });
      await input.evaluate((el: HTMLInputElement) => el.setSelectionRange(1, 1));
      await page.keyboard.type('XY', { delay: 30 });
      await expect(input).toHaveValue('aXYbcd');
      await input.fill('');
      await page.keyboard.type('network and information security', { delay: 0 });
      await expect(input).toHaveValue('network and information security');
      await expect(page).toHaveURL(new RegExp(`[?&]${param}=network\\+and\\+information\\+security`));
    });
  }

  test('a search typed and left at once is kept for Back', async ({ page }) => {
    await open(page, 'countries/IE/');
    await page.locator('#tr-q').click();
    await page.keyboard.type('cyber', { delay: 0 });
    await page.locator('td.impl-dir a[href*="/legislation/"]').first().click(); // before the pause that writes it
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('#tr-q')).toHaveValue('cyber');
  });

  test('a checkbox or a list keeps the choice at once', async ({ page }) => {
    await open(page, 'countries/IE/');
    await page.locator('#inf-nc').check(); // failed with "did not change its state" while the address caught up
    await expect(page).toHaveURL(/inf-nc=1/);
    await open(page, 'votes');
    await page.locator('form[aria-label="Filter votes"] .lx-more summary').click(); // "Close votes only" is under "More filters"
    await page.locator('#vf-close').check();
    await expect(page).toHaveURL(/close=1/);
    await page.locator('#vf-year').focus();
    for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowDown');
    await expect(page.locator('#vf-year')).toHaveJSProperty('selectedIndex', 3);
  });
});

test.describe('votes list', () => {
  test('"All votes" returns to the list as filtered; options count the votes the other filters leave', async ({ page }) => {
    await open(page, 'votes?kind=final&year=2024&sort=margin');
    const count = (await page.locator('.results-bar__count').textContent())!;
    expect(await page.locator('#vf-kind option[value="final"]').textContent()).toBe(`Final vote (${/^([\d,]+)/.exec(count)![1]})`);
    await expect(page.locator('main h2', { hasText: 'Results' })).toHaveCount(1); // between the h1 and the votes' h3
    await page.locator('main .vote-item__title a').first().click();
    await settle(page);
    await page.getByRole('link', { name: '← All votes' }).click();
    await settle(page);
    await expect(page).toHaveURL(/votes\?kind=final&year=2024&sort=margin$/);
    await expect(page.locator('.results-bar__count')).toHaveText(count);
    await open(page, 'votes?kind=mandate');
    await expect(page.locator('#vf-outcome option[value="rejected"]')).toHaveText('Rejected (0)');
    await expectNoSeriousA11yViolations(page);
  });
});

test.describe('party records: figures, titles and links', () => {
  test('the current MEPs of a record and those now under another record add up to its “Current MEP” rows', async ({ page }) => {
    await open(page, 'people/parties/6703/'); // Platforma Obywatelska: 18 now under Koalicja Obywatelska
    await expect(page).toHaveTitle(`Platforma Obywatelska (Poland, 2024–2029 term) – ${SITE_NAME}`);
    const facts = page.locator('.facts');
    await expect(facts).toContainText('Current MEPs in this record');
    // said once, in the note under the figures
    await expect(page.locator('.facts + .note')).toContainText('18 of the MEPs listed here sit in Parliament today under another party record');
    await expect(page.locator('section[aria-labelledby="pm-h"] tbody tr', { hasText: 'Current MEP' })).toHaveCount(18);
    await expectNoSeriousA11yViolations(page);
  });

  test('a membership outside the record’s period is stated as such (PSD 5320, Dan Nica)', async ({ page }) => {
    await open(page, 'people/parties/5320/');
    await expect(page.locator('.party-record')).toContainText(
      'Parliament’s membership data also lists Dan Nica from 16 Jul 2024 in this record, after that period ended.',
    );
  });

  test('records of the same party have their own titles, and a “Now” link to one names its term', async ({ page, request }) => {
    await open(page, 'people/parties/6103/');
    await expect(page).toHaveTitle(`Azione (Italy, 2019–2024 term, 20 Nov 2019 – 8 Nov 2022) – ${SITE_NAME}`);
    const prerendered = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}people/parties/6478/`)).text();
    expect(prerendered).toContain(`<title>Azione (Italy, 2019–2024 term, 6 Dec 2023 – 15 Jul 2024) – ${SITE_NAME}</title>`);
    await open(page, 'people/parties/5288/'); // 6685's name differs only in spacing: "…Latvijai!" - "Tēvzemei…"
    await expect(page.getByRole('row', { name: /Roberts Zīle/ }).locator('.party-now').first()).toContainText('(2024–2029 term)');
  });

  test('the MEP table’s order is kept for Back', async ({ page }) => {
    await open(page, 'people/parties/5494/');
    const name = page.getByRole('button', { name: /^Name/ });
    await name.click();
    await name.click();
    await expect(page).toHaveURL(/sort=name-desc/);
    const first = page.locator('section[aria-labelledby="pm-h"] tbody tr th a').first();
    const who = (await first.textContent())!;
    await first.click();
    await settle(page);
    await page.goBack();
    await settle(page);
    await expect(page.locator('section[aria-labelledby="pm-h"] tbody tr th a').first()).toHaveText(who);
  });
});

test('a shared list: Unfollow keeps focus on the file’s button and says what changed', async ({ page }) => {
  await open(page, 'following/?ids=2021-0106,2020-0359,2016-0400');
  await page.getByRole('button', { name: 'Follow these 3 files in this browser' }).click();
  await page.getByRole('button', { name: 'Unfollow Artificial Intelligence Act' }).press('Enter');
  await expect(page.locator(':focus')).toHaveAccessibleName('Follow Artificial Intelligence Act in this browser');
  await expect(page.getByRole('status').filter({ hasText: 'You no longer follow Artificial Intelligence Act in this browser.' })).toHaveCount(1);
  await expect(page.locator('.following__item')).toHaveCount(3);
  await page.keyboard.press('Enter');
  await expect(page.locator(':focus')).toHaveAccessibleName('Unfollow Artificial Intelligence Act');
  await expect(page.getByRole('status').filter({ hasText: 'Now following Artificial Intelligence Act in this browser.' })).toHaveCount(1);
});

test('"Show all … Council votes" moves focus to the first vote it adds; the sources name no indicators', async ({ page }) => {
  await open(page, 'countries/IE/');
  await page.getByRole('button', { name: /^Show all [\d,]+ Council votes$/ }).press('Enter');
  await expect(page).toHaveURL(/cvotes=all/);
  await expect(page.locator(':focus')).toHaveCount(1);
  const index = await page.evaluate(() => {
    const tr = document.activeElement?.closest('tr');
    return tr ? [...tr.parentElement!.children].indexOf(tr) : -1;
  });
  expect(index).toBe(20);
  await expect(page.locator('#implementation .note', { hasText: 'Sources:' })).toHaveText(
    /^Sources: European Commission \/ EUR-Lex – national transposition measures and infringements/,
  );
});

test('a country page counts the Council votes that record its position out of all those listed', async ({ page, request }) => {
  // 748 votes listed (About, council/index.json), 746 with positions: the two voting-result documents that could not
  // be read record none, so Ireland's counts add up to 746, and the page said "746 in total"
  const meta = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/meta.json`)).json();
  const ie = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/countries/IE.json`)).json();
  const n = (x: number) => x.toLocaleString('en-GB');
  const counted = Object.values(ie.council_positions as Record<string, number>).reduce((a, b) => a + b, 0);
  expect(counted).toBeLessThan(meta.counts.council_votes);
  await open(page, 'countries/IE/');
  await expect(page.locator('#participation .note', { hasText: /^Counts of / })).toHaveText(
    `Counts of the ${n(counted)} Council votes in our dataset that record Ireland’s position (of ${n(meta.counts.council_votes)} votes in total), by that position.`,
  );
});

test.describe('legislative files', () => {
  test('a rapporteur’s committee is the one OEIL names, never "null"', async ({ page }) => {
    await open(page, 'legislation/2021-0240/');
    await page.locator('#details summary').click();
    await expect(page.locator('#details li', { hasText: 'José Manuel Fernandes' })).toContainText('Rapporteur for an opinion (CONT)');
    await open(page, 'legislation/2025-0045/');
    await page.locator('#details summary').click();
    await expect(page.locator('#details li', { hasText: 'Barry Andrews' })).toContainText('Rapporteur for an opinion (AFET)');
  });

  test('a rapporteur with no MEP page here is named without a link; one OEIL links under another id is listed once', async ({ page }) => {
    await open(page, 'legislation/2011-0023/'); // Timothy Kirkhope (4542) sat before 2019: people/meps/4542 is not written
    await page.locator('#details summary').click();
    const kirkhope = page.locator('#details li', { hasText: 'Timothy Kirkhope' });
    await expect(kirkhope).toContainText('Rapporteur (LIBE)');
    await expect(kirkhope.getByRole('link')).toHaveCount(0);
    await expect(page.locator('#details')).toContainText('A name without a link has no MEP page on this site');
    await open(page, 'legislation/2026-0172/'); // OEIL: "CHRIST Marie-Sophie (EPP)" under 10006693; EP Open Data: 277057
    await page.locator('#details summary').click();
    const christ = page.locator('#details li', { hasText: /CHRIST Marie-Sophie|Marie-Sophie Christ/ });
    await expect(christ).toHaveCount(1);
    await expect(christ.getByRole('link', { name: 'Marie-Sophie Christ' })).toHaveAttribute('href', `${BASE_PATH}people/meps/277057`);
  });

  test('a Council title printed without a space is shown with it (ST 14021/20)', async ({ page }) => {
    await open(page, 'legislation/2018-0135/');
    await expect(page.locator('#council-votes')).toContainText('Council Decision on the system of own resources');
    await expect(page.locator('main')).not.toContainText('Decisionon');
  });

  test('the transposition summary counts Member States, beside a column that counts measures (NIS2)', async ({ page, request }) => {
    // the chip read "25 Measures notified" next to the "Measures notified" column, which adds up to 301 measures
    const d = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/dossiers/2020-0359.json`)).json();
    const notified = (d.implementation.countries as { status: string }[]).filter((c) => c.status === 'measures_notified').length;
    await open(page, 'legislation/2020-0359/');
    const summary = page.getByRole('list', { name: 'Member States by status' });
    await expect(summary.getByRole('button', { name: `${notified} Member States: Measures notified` })).toHaveCount(1);
    const chips = await summary.getByRole('button').allTextContents();
    expect(chips.length).toBeGreaterThan(1);
    for (const t of chips) expect(t).toMatch(/^\d+ Member States?: /);
  });

  test('a committee of an earlier term is former, not joint; a joint debate names the other files', async ({ page }) => {
    await open(page, 'legislation/2023-0131/'); // OEIL: "Committee responsible SANT", "Former committee responsible ENVI"
    await page.locator('#details summary').click();
    await expect(page.locator('#details li', { hasText: /^SANT/ })).toContainText('(committee responsible)');
    await expect(page.locator('#details li', { hasText: /^ENVI/ })).toContainText('(former committee responsible)');
    await expect(page.locator('#details')).not.toContainText('joint committee responsible');
    await expect(page.locator('#details li', { hasText: 'Tiemo Wölken' }).first()).toContainText('Rapporteur (SANT)');
    await open(page, 'legislation/2023-0112/');
    await page.getByRole('button', { name: /^Show all \d+ recorded events$/ }).click();
    const step = page.locator('.tl__item', { hasText: 'Joint debate in Parliament' });
    await expect(step).toContainText('Debated together with: 2023/0111(COD) – ');
    await expect(step.getByRole('link', { name: /^2023\/0115\(COD\) – / })).toHaveAttribute('href', `${BASE_PATH}legislation/2023-0115`);
    await expect(step.locator('.tl__docs')).not.toContainText('A10-0067/2026');
    await expect(step.locator('.tl__docs')).toContainText('A10-0066/2026');
  });

  test('a report and its main file link each other by procedure reference', async ({ page }) => {
    await open(page, 'legislation/2020-0112/');
    await page.locator('#details summary').click();
    await expect(page.locator('#details li', { hasText: 'interim report' }).getByRole('link')).toHaveText(/^2020\/0112R\(APP\) – /);
    await open(page, 'legislation/2020-0112R/');
    await page.locator('#details summary').click();
    await expect(page.locator('#details li', { hasText: 'Report on' }).getByRole('link')).toHaveText(/^2020\/0112\(APP\) – /);
    await expect(page.locator('#details')).toContainText('None: Parliament’s report is a resolution of Parliament, not a legislative act');
  });

  test('the days without a recorded step are counted on the visitor’s date, never fewer than the build counted', async ({ page, request }) => {
    // the singular ("1 day") is covered by src/lib/format.test.ts (noUpdateText); here the count follows the
    // visitor's clock from the build's own count, whichever day the data was built
    const d = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/dossiers/2026-0325.json`)).json();
    const last: string = d.stall.last_event_date;
    const built: number = d.stall.days_since_last_event;
    const day = (n: number) => new Date(Date.parse(`${last}T12:00:00Z`) + n * 86_400_000);
    const long = new Date(`${last}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
    const text = (n: number) => `No recorded procedural step for ${n} ${n === 1 ? 'day' : 'days'}; the last was recorded on ${long}.`;
    await page.clock.install({ time: day(built) });
    await open(page, 'legislation/2026-0325/');
    await expect(page.locator('.dz-where')).toContainText(text(built));
    await page.clock.setSystemTime(day(built + 40));
    await open(page, 'legislation/2026-0325/');
    await expect(page.locator('.dz-where')).toContainText(text(built + 40));
  });
});

test.describe('About and the guide', () => {
  test('About states the selection criteria and the hand-checked corrections, not "never written by hand"', async ({ page }) => {
    await open(page, 'about/');
    await expect(page.locator('.prose')).not.toContainText('never written by hand');
    const selection = page.locator('#selection');
    await expect(selection).toContainText('Each meets at least two of these criteria');
    await expect(selection).toContainText('officially recognised delay');
    await expect(selection).toContainText('at least one adopted act and at least one pending proposal');
    await expect(selection).toContainText('no more than two on the same topic');
    await expect(selection).toContainText('reviewed at least every three months');
    const corrections = page.locator('#corrections');
    await expect(corrections.getByRole('heading', { name: 'Corrections checked against official texts' })).toBeVisible();
    await expect(corrections).toContainText('Dates checked against the act’s text');
    await expect(corrections).toContainText('The day the Council adopted an act');
    await expect(corrections.getByRole('link', { name: /data\/curated folder/ })).toHaveAttribute(
      'href',
      'https://github.com/RAHV-FB/eu-intel/tree/main/data/curated',
    );
    // the selection text links to it
    await selection.getByRole('link', { name: 'Corrections checked against official texts' }).click();
    await expect(page).toHaveURL(/about\/?#corrections$/);
    await expect(corrections.getByRole('heading', { name: 'Corrections checked against official texts' })).toBeInViewport();
  });

  test('the file count and the Parliament vote count on About say what they count', async ({ page, request }) => {
    const meta = await (await request.get(`${PAGES_ORIGIN}${BASE_PATH}data/meta.json`)).json();
    await open(page, 'about/');
    const n = (x: number) => x.toLocaleString('en-GB');
    const row = page.getByRole('row', { name: /^Legislative files/ });
    await expect(row).toContainText(n(meta.counts.dossiers));
    await expect(page.locator('#coverage')).toContainText(`The ${n(meta.counts.dossiers)} legislative files in the table below are`);
    // the source card gives the votes listed first, and the snapshot they are chosen from
    const card = page.locator('article', { has: page.getByRole('heading', { name: /plenary votes/ }) });
    await expect(card).toContainText(`${n(meta.counts.ep_votes)} plenary votes from`);
    await expect(card).toContainText('are listed');
    await expect(card).toContainText('They are chosen from the');
    await expect(page.locator('#coverage')).toContainText(`Adopted acts: ${n(meta.counts.legal_acts)} legal acts`);
  });

  test('the guide separates signature and publication from entry into force and application', async ({ page }) => {
    await open(page, 'how-the-eu-works/');
    const steps = page.locator('.pathway__steps li');
    await expect(steps.filter({ hasText: 'Signature & publication' })).toContainText('Entry into force is a separate step.');
    await expect(steps.filter({ hasText: 'Entry into force & application' })).toContainText('twentieth day after publication');
    await expect(page.locator('.prose')).not.toContainText(/it is EU law|applicable law|legally exists/);
    await expect(page.locator('#olp')).toContainText('Article 297(1) TFEU');
  });

  test('the guide explains the status labels, and About links to the explanation', async ({ page }) => {
    await open(page, 'about/');
    await page.locator('#methodology').getByRole('link', { name: /guide explains each label/ }).click();
    await expect(page).toHaveURL(/how-the-eu-works\/?#status-labels$/);
    const section = page.locator('#status-labels');
    await expect(section.getByRole('heading', { name: 'Status labels on this site', level: 2 })).toBeInViewport();
    for (const label of ['Provisional agreement reached', 'Signed, awaiting publication', 'Published, not yet in force', 'In force', 'No longer in force']) {
      await expect(section.locator('.badge', { hasText: new RegExp(`^\\W*${label}$`) })).toBeVisible();
    }
    await expect(section.getByRole('heading', { name: 'Not adopted: not law yet' })).toBeVisible();
    await expect(section.getByRole('link', { name: 'the legislation explorer' })).toHaveAttribute('href', `${BASE_PATH}legislation`);
    await expectNoSeriousA11yViolations(page);
  });

  test('"former" rapporteurs are explained as the Observatory lists them, also within the current term', async ({ page }) => {
    // 2025/0429(COD), proposed 19 December 2025: OEIL "Former rapporteur SIPPEL Birgit (S&D) 15/01/2026"; EP API term ep-10
    await open(page, 'legislation/2025-0429/');
    await page.locator('#details summary').click();
    await expect(page.locator('#details li', { hasText: 'Birgit Sippel' })).toContainText('Former rapporteur (LIBE)');
    const note = page.locator('#details .dz-sub', { has: page.getByRole('heading', { name: 'Rapporteurs and shadow rapporteurs' }) }).locator('p.meta');
    await expect(note).toContainText('lists the MEP only under a “Former …” heading for this file, in the current parliamentary term or an earlier one');
    await expect(note).not.toContainText('marks an appointment in an earlier parliamentary term');
  });
});
