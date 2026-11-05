/**
 * The law in context on the law page (src/features/legislation/dossier/LawContext.tsx), from EUR-Lex / Cellar: EUR-Lex's
 * official summary where the site has written none and a link to it where it has, the court cases on the law, its
 * consolidated text and the advisory opinions; and the names a file is known by, in the list rows. Each test finds its
 * example in the data and is skipped when the data has none: the frozen test data predates the source.
 */
import AxeBuilder from '@axe-core/playwright';
import type { APIRequestContext } from '@playwright/test';
import type { DossierDetail, DossierSummary } from '../../src/types/data';
import { expect, open, test } from './fixtures';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
/** "24 March 2026", as the site writes a date in full. */
const long = (d: string) => {
  const [y, m, day] = d.split('-').map(Number);
  return `${day} ${MONTHS[m - 1]} ${y}`;
};

async function data<T>(request: APIRequestContext, path: string): Promise<T | null> {
  const res = await request.get(`data/${path}`);
  return res.ok() ? ((await res.json()) as T) : null;
}

/** The first file whose page data satisfies `pred`: the candidates first, then the files of the index with an act. */
async function find(request: APIRequestContext, pred: (d: DossierDetail) => boolean, candidates: string[]) {
  const index = (await data<DossierSummary[]>(request, 'dossiers/index.json')) ?? [];
  const ids = [...candidates, ...index.filter((d) => d.celex.length > 0).map((d) => d.id).slice(0, 60)];
  for (const id of ids) {
    const d = await data<DossierDetail>(request, `dossiers/${id}.json`);
    if (d && pred(d)) return d;
  }
  return null;
}

test('shows EUR-Lex’s official summary, labelled with its date and quoted as text, where the site has written none', async ({ page, request }) => {
  // NIS2 (2020/0359(COD)): no editorial summary; EUR-Lex's summary "Cybersecurity of network and information systems"
  const d = await find(request, (x) => !x.editorial && !!x.official_summaries?.some((s) => s.aim.length > 0), ['2020-0359']);
  test.skip(!d, 'no file without an editorial summary has an official summary in this data');
  const s = d!.official_summaries![0];
  await open(page, `legislation/${d!.id}/`);
  const block = page.locator('#official-summary');
  await expect(block.getByRole('heading', { level: 4 })).toHaveText(`Official summary (EUR-Lex${s.date ? `, last updated ${long(s.date)}` : ''})`);
  // the opening section, as text (no markup from the source), each paragraph or list item in turn
  const quote = block.locator('blockquote');
  await expect(quote).toHaveAttribute('cite', s.url);
  for (const p of s.aim) await expect(quote).toContainText(p);
  await expect(quote.locator('li')).toHaveCount(s.aim_items.length);
  await expect(block).toContainText('Written by the EU Publications Office for EUR-Lex, not by this site.');
  await expect(block.getByRole('link', { name: `Read the full summary on EUR-Lex: “${s.title}”` })).toHaveAttribute('href', s.url);
  // it replaces "We have not written a plain-language summary"
  await expect(page.locator('.dz-summary')).not.toContainText('We have not written a plain-language summary');
  const { violations } = await new AxeBuilder({ page }).include('.dz-summary').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => v.id)).toEqual([]);
});

test('links EUR-Lex’s summary from a file with an editorial summary, without repeating it', async ({ page, request }) => {
  const d = await find(request, (x) => !!x.editorial && !!x.official_summaries?.length, ['2012-0011', '2021-0106']);
  test.skip(!d, 'no file with an editorial summary has an official summary in this data');
  await open(page, `legislation/${d!.id}/`);
  const s = d!.official_summaries![0];
  await expect(page.locator('#official-summary')).toHaveCount(0);
  const link = page.locator('.dz-osum__link');
  await expect(link).toContainText('Official summary on EUR-Lex:');
  await expect(link.getByRole('link', { name: new RegExp(`“${s.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}”`) })).toHaveAttribute('href', s.url);
});

test('lists the court cases on the law, with a badge only where a record states it', async ({ page, request }) => {
  // the GDPR: judgments interpreting it, requests for a preliminary ruling with no decision recorded
  const d = await find(
    request,
    (x) => (x.court?.interpreted_by.length ?? 0) > 8 && !!x.court?.pending.some((k) => k.kind === 'preliminary_reference'),
    ['2012-0011'],
  );
  test.skip(!d, 'no file with both kinds of court records in this data');
  await open(page, `legislation/${d!.id}/`);
  const section = page.locator('#court');
  await expect(section.getByRole('heading', { level: 2 })).toHaveText('Court rulings on this law');
  await expect(page.locator('.dz-toc').getByRole('link', { name: 'Court rulings' })).toHaveAttribute('href', '#court');
  const badges = section.locator('.dz-badges');
  await expect(badges).toContainText('Questions pending before the Court');
  const annulled = d!.acts.some((a) => a.court_rulings.some((r) => r.effect === 'annulment'));
  if (!annulled) await expect(badges).not.toContainText('Annulled');
  // the pending cases, newest first: the six latest, then all on request; each case number links its notice
  const pending = d!.court!.pending;
  const open_ = section.locator('.dz-sub', { hasText: 'Pending before the Court' });
  await expect(open_.locator('li')).toHaveCount(Math.min(pending.length, 6));
  await expect(open_.locator('li').first()).toContainText('— request for a preliminary ruling');
  await expect(open_.locator('li').first().getByRole('link', { name: new RegExp(`^${pending[0].case}`) })).toHaveAttribute('href', pending[0].url);
  if (pending.length > 6) {
    await open_.getByRole('button', { name: `Show all ${pending.length}` }).click();
    await expect(open_.locator('li')).toHaveCount(pending.length);
  }
  // the judgments interpreting it: the eight latest, then all on request
  const decisions = section.locator('.dz-sub', { hasText: 'Judgments and orders interpreting it' });
  await expect(decisions.locator('li')).toHaveCount(8);
  await decisions.getByRole('button', { name: `Show all ${d!.court!.interpreted_by.length}` }).click();
  await expect(decisions.locator('li')).toHaveCount(d!.court!.interpreted_by.length);
  await expect(decisions.locator('li').first()).toContainText(d!.court!.interpreted_by[0].case);
});

test('says when a proposal’s withdrawal is challenged before the Court', async ({ page, request }) => {
  // 2023/0133(COD), standard essential patents: Case C-727/25, the European Parliament's action
  const d = await find(request, (x) => !!x.court?.pending.some((k) => k.kind === 'annulment_of_withdrawal'), ['2023-0133']);
  test.skip(!d, 'no action against a withdrawal in this data');
  const k = d!.court!.pending.find((x) => x.kind === 'annulment_of_withdrawal')!;
  await open(page, `legislation/${d!.id}/`);
  await expect(page.locator('.dz-withdrawal-case')).toContainText(`The Commission’s withdrawal of this proposal is challenged before the ${k.court}`);
  await expect(page.locator('.dz-withdrawal-case').getByRole('link', { name: `Case ${k.case}` })).toHaveAttribute('href', '#court');
  const section = page.locator('#court');
  await expect(section.getByRole('heading', { level: 2 })).toHaveText(d!.acts.length ? 'Court rulings on this law' : 'Court cases on this proposal');
  await expect(section.locator('.dz-badges')).toContainText('Action for annulment pending');
  const item = section.locator('li', { hasText: '— action against the withdrawal of this proposal' });
  await expect(item.getByRole('link', { name: new RegExp(`^${k.case}`) })).toHaveAttribute('href', k.url);
  if (k.applicants?.length) await expect(item).toContainText(`brought by the ${k.applicants.join(' and the ')}`);
});

test('links the current consolidated text and lists the advisory opinions', async ({ page, request }) => {
  // the AI Act: consolidated versions of 12 July 2024 and 27 July 2026; opinions of the EESC and the CoR
  const d = await find(request, (x) => !!x.consolidated?.length && !!x.advisory_opinions?.length, ['2021-0106', '2020-0359']);
  test.skip(!d, 'no file with a consolidated text and an advisory opinion in this data');
  await open(page, `legislation/${d!.id}/`);
  const today = new Date(await page.evaluate(() => Date.now())).toISOString().slice(0, 10);
  const c = d!.consolidated![0];
  const current = [...c.versions].reverse().find((v) => v.date <= today) ?? c.versions[0];
  const section = page.locator('#consolidated');
  await expect(section.getByRole('heading', { level: 2 })).toHaveText(/(Current|Latest) consolidated text/);
  await expect(section.getByRole('link', { name: new RegExp(`as it stands from ${long(current.date)}|version applicable from ${long(current.date)}`) }))
    .toHaveAttribute('href', new RegExp(`CELEX:${current.celex}$`));
  await expect(page.locator('.dz-official-links').getByRole('link', { name: /Consolidated text \(EUR-Lex\)/ })).toHaveAttribute(
    'href',
    new RegExp(`CELEX:${current.celex}$`),
  );
  const opinions = page.locator('#opinions');
  await expect(opinions.locator('li')).toHaveCount(d!.advisory_opinions!.length);
  const o = d!.advisory_opinions![0];
  const body = o.body === 'EESC' ? 'European Economic and Social Committee' : 'European Committee of the Regions';
  await expect(opinions.getByRole('link', { name: new RegExp(`^${body} — opinion`) }).first()).toHaveAttribute('href', o.url);
});

test('gives the names a file is known by in the list rows, as on its page', async ({ page, request }) => {
  const index = (await data<DossierSummary[]>(request, 'dossiers/index.json')) ?? [];
  const named = index.find((d) => d.id === '2020-0359' && d.names?.length) ?? index.find((d) => d.names?.length);
  test.skip(!named, 'no file with a name besides its title in this data');
  await open(page, `legislation/?q=${encodeURIComponent(named!.ref)}`);
  const row = page.locator('.drow', { has: page.locator(`a[href$="/legislation/${named!.id}"]`) }).first();
  await expect(row.locator('.drow__names')).toHaveText(`Also known as ${named!.names!.join(', ')}`);
  await open(page, `legislation/${named!.id}/`);
  await expect(page.locator('.dz-known')).toContainText(named!.names!.join(', '));
});
