/**
 * What link previews, search engines and readers without JavaScript get from the prerendered pages (Plan 3.1), served as
 * GitHub Pages serves them (tests/e2e/pages-server.mjs); scripts/prerender-routes.mjs writes them with scripts/seo.mjs:
 * Open Graph and Twitter tags equal to each page's own title and description; a legislative file's key facts in
 * <noscript>, the same as its page states once loaded and never shown to a reader with JavaScript; its act as schema.org
 * Legislation; the sitemap and robots.txt.
 *
 * The pages are picked from the build's own data when the tests run (dist/data), so the tests hold on the frozen test
 * data and on live data. Absolute addresses (og:url, the sitemap) need a build with SITE_URL; on one without (CI's), the
 * tests check that there are none.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import AxeBuilder from '@axe-core/playwright';
import type { APIRequestContext, Page } from '@playwright/test';
import type { DossierDetail, DossierSummary, Meta } from '../../src/types/data';
import { BASE_PATH, PAGES_ORIGIN, SITE_NAME } from './env';
import { expect, settle, test } from './fixtures';

type Row = Record<string, unknown>;
const read = <T,>(rel: string): T => JSON.parse(readFileSync(`dist/data/${rel}`, 'utf8')) as T;
const pagesUrl = (path: string) => `${PAGES_ORIGIN}${BASE_PATH}${path}`;
/** The site's address in a build with SITE_URL (the home page's canonical link); null in a build without. */
const SITE_URL = /<link rel="canonical" href="([^"]+)"/.exec(readFileSync('dist/index.html', 'utf8'))?.[1] ?? null;
const today = read<Meta>('meta.json').built_at.slice(0, 10);

const index = read<DossierSummary[]>('dossiers/index.json');
const detail = (id: string) => read<DossierDetail>(`dossiers/${id}.json`);
const firstDetail = (pred: (d: DossierDetail) => boolean, from: DossierSummary[] = index) => {
  for (const s of from) {
    const d = detail(s.id);
    if (pred(d)) return d;
  }
  return undefined;
};
const withStage = (...stages: string[]) => index.filter((d) => stages.includes(d.stage));
/** Files of each kind the page states differently, the first of each in the data. */
const FILES: [kind: string, file: DossierDetail | undefined][] = [
  // a regulation with dates still to come: its next step is led by them (Summary.tsx regulationNextStep)
  ['a regulation in force', firstDetail((d) => d.instrument === 'regulation' && !!d.next_date && /^The regulation applies/.test(d.next_step.text), withStage('in_force'))],
  ['a directive in force', firstDetail((d) => d.instrument === 'directive', withStage('in_force'))],
  ['an act published, not yet in force', firstDetail(() => true, withStage('published'))],
  ['an act no longer in force', firstDetail(() => true, withStage('no_longer_in_force'))],
  ['a decision taking effect on notification', firstDetail(() => true, withStage('takes_effect_on_notification'))],
  ['a proposal', firstDetail(() => true, withStage('proposed'))],
  ['a file being negotiated', firstDetail(() => true, withStage('negotiations', 'provisional_agreement'))],
  ['a withdrawn proposal', firstDetail(() => true, withStage('withdrawn'))],
  ['a split proposal', firstDetail((d) => d.related.some((r) => r.relation === 'Split into'), withStage('unknown'))],
  ['a file whose next step is not determined', firstDetail((d) => d.next_step.basis === 'unknown')],
];
const ACT = FILES[0][1] ?? firstDetail((d) => d.acts.length > 0, withStage('in_force'))!;
const PROPOSAL = FILES[5][1]!;

const unescape = (s: string) => s.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
/** The page's title, description, canonical address and its meta tags by property or name: every value of each. */
function head(html: string) {
  const tags: Record<string, string[]> = {};
  for (const m of html.matchAll(/<meta (?:property|name)="([^"]+)" content="([^"]*)" \/>/g)) (tags[m[1]] ??= []).push(unescape(m[2]));
  return {
    title: unescape(/<title>([^<]*)<\/title>/.exec(html)?.[1] ?? ''),
    description: tags.description?.[0],
    canonical: /<link rel="canonical" href="([^"]+)"/.exec(html)?.[1] ?? null,
    tags,
  };
}
async function shell(request: APIRequestContext, path: string) {
  const res = await request.get(pagesUrl(path));
  return { status: res.status(), html: await res.text() };
}
const jsonLd = (html: string) => [...html.matchAll(/<script type="application\/ld\+json">([^<]*)<\/script>/g)].map((m) => JSON.parse(m[1]) as Row);

test.describe('link previews', () => {
  const rows = (rel: string) => read<Row[]>(rel);
  const routes: [kind: string, path: string, status?: number][] = [
    ['the home page', ''],
    ['the legislation list', 'legislation/'],
    ['About', 'about/'],
    ['an act', `legislation/${ACT.id}/`],
    ['a proposal', `legislation/${PROPOSAL.id}/`],
    ['a vote', `votes/${rows('votes/index.json')[0].id}/`],
    ['an MEP', `people/meps/${rows('people/meps.json')[0].id}/`],
    ['a political group', `people/groups/${rows('people/groups.json')[0].id}/`],
    ['a national party', `people/parties/${rows('people/parties.json')[0].id}/`],
    ['a country', `countries/${rows('countries/index.json')[0].code}/`],
    ['the page for unknown addresses', 'no-such-page/', 404],
  ];
  for (const [kind, path, status = 200] of routes) {
    test(`${kind} previews with its own title and description`, async ({ request }) => {
      const res = await shell(request, path);
      expect(res.status).toBe(status);
      const { title, description, canonical, tags } = head(res.html);
      expect(title).toContain(SITE_NAME);
      expect(tags['og:title']).toEqual([title]);
      expect(tags['og:description']).toEqual([description]);
      expect(tags['og:type']).toEqual(['website']);
      expect(tags['og:site_name']).toEqual([SITE_NAME]);
      expect(tags['og:locale']).toEqual(['en_GB']);
      expect(tags['twitter:card']).toEqual(['summary']);
      // the page's absolute address, as its canonical link gives it: only in a build with SITE_URL, never on the 404 page
      if (SITE_URL && status === 200) {
        expect(canonical).toBe(SITE_URL + path);
        expect(tags['og:url']).toEqual([canonical]);
      } else expect(tags['og:url']).toBeUndefined();
    });
  }
});

/** The key facts as a browser without JavaScript renders them: the page's <noscript> block. */
async function factsWithoutScripts(page: Page) {
  return page.evaluate(() => {
    const text = (el: Element | null | undefined) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
    const box = document.querySelector('noscript > div');
    if (!box) return null;
    const rows: Record<string, { text: string[]; dates: string[]; paras: string[] }> = {};
    for (const dt of box.querySelectorAll('dt')) {
      const dds: Element[] = [];
      for (let el = dt.nextElementSibling; el?.tagName === 'DD'; el = el.nextElementSibling) dds.push(el);
      rows[text(dt)] = {
        text: dds.map(text),
        dates: dds.flatMap((dd) => [...dd.querySelectorAll('time')].map((t) => t.getAttribute('datetime') ?? '')),
        paras: dds.flatMap((dd) => [...dd.querySelectorAll('p')].map(text)),
      };
    }
    const heading = [...box.querySelectorAll('h2')].find((h) => text(h) === 'When it applies');
    return {
      title: text(box.querySelector('h1')),
      headings: [...box.querySelectorAll('h1, h2')].map((h) => h.tagName),
      status: text(box.querySelector(':scope > p > strong')),
      since: box.querySelector(':scope > p > strong ~ time')?.getAttribute('datetime') ?? null,
      rows,
      schedule: heading ? [...(heading.nextElementSibling?.querySelectorAll('time') ?? [])].map((t) => t.getAttribute('datetime') ?? '') : null,
      links: [...box.querySelectorAll('a')].map((a) => ({ text: text(a), href: a.getAttribute('href') ?? '' })),
      // the site's note on JavaScript, with its link to the data
      note: text(box.lastElementChild),
    };
  });
}

/** The same facts as the page states them once loaded (src/pages/Dossier.tsx, Summary.tsx). */
async function factsOnThePage(page: Page) {
  return page.evaluate(() => {
    // the text, without what an official link adds to it ("↗", "(opens official website in a new tab)")
    const text = (el: Element | null | undefined) => {
      const copy = el?.cloneNode(true) as Element | undefined;
      copy?.querySelectorAll('.ext, .visually-hidden').forEach((x) => x.remove());
      return (copy?.textContent ?? '').replace(/\s+/g, ' ').trim();
    };
    const fact = (label: string) => [...document.querySelectorAll('.dz-facts .dz-fact')].find((f) => text(f.querySelector('dt')) === label)?.querySelector('dd');
    return {
      title: text(document.querySelector('main h1')),
      status: text(document.querySelector('.dz-statusline .badge')),
      since: document.querySelector('.dz-statusline__since time')?.getAttribute('datetime') ?? null,
      current: text(fact('Current status')?.querySelector('p')),
      // the next step, without the pointer to the dates further down
      next: [...(fact('What happens next')?.querySelectorAll('p') ?? [])].map(text).filter((p) => !p.startsWith('See When it applies')),
      keyFacts: Object.fromEntries([...document.querySelectorAll('.dz-keyfacts > div')].map((div) => [text(div.querySelector('dt')), text(div.querySelector('dd'))])),
      schedule: [...document.querySelectorAll('.dz-sched time')].map((t) => t.getAttribute('datetime') ?? ''),
      hrefs: [...document.querySelectorAll('main a[href]')].map((a) => a.getAttribute('href') ?? ''),
    };
  });
}

test.describe('a legislative file’s key facts, for readers and crawlers without JavaScript', () => {
  for (const [kind, d] of FILES) {
    test(`${kind}: the page without JavaScript states what the page states once loaded, from the file’s data`, async ({ page, browser }) => {
      test.skip(!d, `no such file in this data`);
      const file = d!;
      const path = `legislation/${file.id}/`;
      const ctx = await browser.newContext({ javaScriptEnabled: false });
      const bare = await ctx.newPage();
      await bare.goto(pagesUrl(path));
      const facts = (await factsWithoutScripts(bare))!;
      await expect(bare.locator('h1')).toBeVisible();
      await ctx.close();
      expect(facts, 'a <noscript> block with the key facts').not.toBeNull();

      // from the file's data, with its labels and wording
      const summary = index.find((s) => s.id === file.id)!;
      expect(facts.title).toBe(file.title);
      expect(facts.headings[0]).toBe('H1');
      expect(facts.status).toBe(file.status.label);
      expect(facts.status).toBe(summary.status_label);
      expect(facts.since).toBe(file.status.since ?? null);
      expect(facts.rows['Procedure'].text).toEqual([file.ref]);
      const proposed = Object.keys(facts.rows).find((k) => k.startsWith('Proposed'));
      expect(proposed ? facts.rows[proposed].dates : []).toEqual(file.started ? [file.started] : []);
      expect(facts.rows['Adopted']?.dates ?? []).toEqual(file.adopted ? [file.adopted] : []);
      expect(facts.rows['Published in the Official Journal']?.dates ?? []).toEqual(file.published ? [file.published] : []);
      const act = file.acts[0];
      if (act) {
        expect(facts.rows['CELEX'].text).toEqual([act.celex]);
        expect(facts.links).toContainEqual({ text: 'Legal text (EUR-Lex)', href: act.eurlex_url });
        if (file.application?.entry_into_force) expect(facts.rows['Entry into force'].dates).toEqual([file.application.entry_into_force]);
      } else expect(facts.rows['CELEX']).toBeUndefined();
      const ns = file.next_step;
      const split = file.related.some((r) => r.relation === 'Split into');
      if (!split && ns.basis !== 'unknown' && !/^The regulation applies directly/.test(ns.text))
        expect(facts.rows['What happens next'].paras[0]).toBe(`${ns.text}${ns.basis === 'derived' ? ' Derived from recorded events' : ''}`);
      expect(facts.note).toContain('This site needs JavaScript');
      expect(facts.links).toContainEqual({ text: 'data/meta.json', href: `${BASE_PATH}data/meta.json` });

      // the same as the page states once loaded, on the day the data was built (the page's clock: tests/e2e/fixtures.ts)
      await page.goto(pagesUrl(path));
      await settle(page);
      const shown = await factsOnThePage(page);
      expect(facts.title).toBe(shown.title);
      expect(facts.status).toBe(shown.status);
      expect(facts.since).toBe(shown.since);
      expect(facts.rows['Current status'].paras).toEqual([shown.current]);
      expect(facts.rows['What happens next'].paras).toEqual(shown.next);
      for (const [label, row] of Object.entries(facts.rows)) {
        if (['Procedure', 'Type', 'Adopted', 'Published in the Official Journal'].includes(label) || label.startsWith('Proposed'))
          expect(row.text.join(''), label).toBe(shown.keyFacts[label]);
      }
      if (act) expect(shown.keyFacts['CELEX']).toContain(act.celex);
      // every date of "When it applies" is one the page's schedule gives, and every link one the page has
      if (facts.schedule) for (const date of facts.schedule) expect(shown.schedule, `date ${date}`).toContain(date);
      for (const { href } of facts.links.filter((l) => /^https?:/.test(l.href) && !l.href.startsWith('https://github.com/')))
        expect(shown.hrefs, href).toContain(href);
      for (const { href } of facts.links.filter((l) => l.href.startsWith(`${BASE_PATH}legislation/`)))
        expect(shown.hrefs, href).toContain(href.replace(/\/$/, ''));
    });
  }

  test('a reader with JavaScript never sees them, even before the app has loaded', async ({ page, guard }) => {
    // the app's script does not load: the page stays empty (a <noscript> block is not rendered while scripts run)
    guard.ignore(/ERR_FAILED|Failed to load/);
    await page.route('**/assets/*.js', (route) => route.abort());
    await page.goto(pagesUrl(`legislation/${ACT.id}/`));
    expect(await page.evaluate(() => document.body.innerText.trim())).toBe('');
    await page.unroute('**/assets/*.js');
    // once it has loaded: the page's own heading only
    await page.goto(pagesUrl(`legislation/${ACT.id}/`));
    await settle(page);
    await expect(page.locator('h1')).toHaveCount(1);
    expect(await page.evaluate(() => [...document.querySelectorAll('noscript')].every((n) => n.children.length === 0))).toBe(true);
  });

  test('they are accessible as a browser without JavaScript renders them', async ({ browser }) => {
    // axe-core needs scripts: the <noscript> block's markup is shown as the page's content, under the same style sheet
    for (const d of [ACT, PROPOSAL]) {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();
      const url = pagesUrl(`legislation/${d.id}/`);
      const html = await (await page.request.get(url)).text();
      const bare = html.replace(/<script type="module"[^>]*><\/script>/, '').replace(/<(\/?)noscript>/g, '<$1div>');
      await page.route(url, (route) => route.fulfill({ body: bare, contentType: 'text/html; charset=utf-8' }));
      await page.goto(url);
      await expect(page.locator('h1')).toHaveText(d.title);
      const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
      expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.help}`), d.id).toEqual([]);
      await ctx.close();
    }
  });
});

test.describe('structured data', () => {
  test('a file’s act is schema.org Legislation, as its page states it; a proposal has none', async ({ request }) => {
    const act = ACT.acts[0];
    const [ld, ...more] = jsonLd((await shell(request, `legislation/${ACT.id}/`)).html);
    expect(more).toEqual([]);
    expect(ld['@context']).toBe('https://schema.org');
    expect(ld['@type']).toBe('Legislation');
    expect(ld.name).toBe(act.title);
    expect(ld.legislationIdentifier).toBe(act.celex);
    expect(ld.legislationDate).toBe(act.date_document ?? undefined);
    expect(ld.datePublished).toBe(act.date_publication ?? undefined);
    expect(ld.legislationLegalForce).toEqual({ '@id': 'https://schema.org/InForce' }); // its status: In force
    expect(ld.url).toBe(act.eurlex_url);
    expect(ld.mainEntityOfPage).toBe(SITE_URL ? `${SITE_URL}legislation/${ACT.id}/` : undefined);
    expect(jsonLd((await shell(request, `legislation/${PROPOSAL.id}/`)).html)).toEqual([]);
    // every file page's structured data parses
    for (const [, d] of FILES.filter(([, f]) => f)) for (const x of jsonLd((await shell(request, `legislation/${d!.id}/`)).html)) expect(x['@type']).toBe('Legislation');
  });

  test('is a data block, which the Content-Security-Policy does not block or report', async ({ page }) => {
    await page.addInitScript(() => {
      const w = window as unknown as { cspViolations: string[] };
      w.cspViolations = [];
      window.addEventListener('securitypolicyviolation', (e) => w.cspViolations.push(`${e.violatedDirective} ${e.blockedURI}`), true);
    });
    await page.goto(pagesUrl(`legislation/${ACT.id}/`));
    await settle(page);
    await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(1);
    expect(await page.evaluate(() => (window as unknown as { cspViolations: string[] }).cspViolations)).toEqual([]);
  });
});

/** The prerendered pages (dist/**\/index.html), by path under the site, with whether each is for search engines. */
function shells() {
  const out: { path: string; noindex: boolean }[] = [];
  const walk = (dir: string, path: string) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.isDirectory() && !(path === '' && ['data', 'assets'].includes(e.name))) walk(join(dir, e.name), `${path}${e.name}/`);
      else if (e.name === 'index.html') out.push({ path, noindex: readFileSync(join(dir, e.name), 'utf8').includes('<meta name="robots" content="noindex" />') });
    }
  };
  walk('dist', '');
  return out;
}

test.describe('search engines', () => {
  test('robots.txt lets every crawler read every page, and names the sitemap when there is one', async ({ request }) => {
    const res = await request.get(pagesUrl('robots.txt'));
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('text/plain');
    const lines = (await res.text()).split('\n').filter(Boolean);
    expect(lines.slice(0, 2)).toEqual(['User-agent: *', 'Allow: /']);
    expect(lines.filter((l) => l.startsWith('Sitemap:'))).toEqual(SITE_URL ? [`Sitemap: ${SITE_URL}sitemap.xml`] : []);
  });

  test('the sitemap lists every page for search engines at its canonical address, with the date of its last change', async ({ page, request }) => {
    const res = await request.get(pagesUrl('sitemap.xml'));
    if (!SITE_URL) {
      expect(res.status(), 'no sitemap without SITE_URL: its addresses must be absolute').toBe(404);
      return;
    }
    expect(res.status()).toBe(200);
    const body = await res.text();
    // well-formed XML in the sitemaps.org schema: one file, or an index of files
    const parse = (xml: string) =>
      page.evaluate((x) => {
        const doc = new DOMParser().parseFromString(x, 'application/xml');
        const root = doc.documentElement;
        return {
          error: doc.getElementsByTagName('parsererror').length > 0,
          root: root.localName,
          ns: root.namespaceURI,
          urls: [...root.children].map((u) => ({
            loc: u.getElementsByTagName('loc')[0]?.textContent ?? '',
            lastmod: u.getElementsByTagName('lastmod')[0]?.textContent ?? null,
          })),
        };
      }, xml);
    const top = await parse(body);
    expect(top.error).toBe(false);
    expect(top.ns).toBe('http://www.sitemaps.org/schemas/sitemap/0.9');
    const files = top.root === 'sitemapindex' ? top.urls.map((u) => u.loc) : [`${SITE_URL}sitemap.xml`];
    const urls: { loc: string; lastmod: string | null }[] = [];
    for (const f of files) {
      expect(f.startsWith(SITE_URL)).toBe(true);
      const xml = top.root === 'sitemapindex' ? await (await request.get(pagesUrl(f.slice(SITE_URL.length)))).text() : body;
      expect(Buffer.byteLength(xml)).toBeLessThanOrEqual(50 * 1024 * 1024);
      const one = await parse(xml);
      expect(one.error).toBe(false);
      expect(one.root).toBe('urlset');
      expect(one.urls.length).toBeLessThanOrEqual(50_000);
      urls.push(...one.urls);
    }
    const locs = urls.map((u) => u.loc);
    expect(new Set(locs).size, 'each address once').toBe(locs.length);
    // every prerendered page not marked noindex, but the visitor's own list and the search form; nothing else
    const expected = shells()
      .filter((s) => !s.noindex && !['following/', 'search/'].includes(s.path))
      .map((s) => SITE_URL + s.path);
    expect([...locs].sort(), 'the sitemap lists the pages for search engines (scripts/prerender-routes.mjs page())').toEqual(expected.sort());
    expect(locs[0]).toBe(SITE_URL);
    // the date of the last change where the data gives one: a file's latest step or recorded change, a vote's date
    const lastmod = new Map(urls.map((u) => [u.loc, u.lastmod]));
    const changedOn = (...dates: (string | null | undefined)[]) =>
      dates
        .filter((x): x is string => !!x)
        .map((x) => x.slice(0, 10))
        .filter((x) => x <= today)
        .sort()
        .pop() ?? null;
    for (const d of [ACT, PROPOSAL])
      expect(lastmod.get(`${SITE_URL}legislation/${d.id}/`), d.id).toBe(changedOn(d.last_event, ...d.changes.map((c) => c.detected_at)));
    const vote = read<Row[]>('votes/index.json')[0];
    expect(lastmod.get(`${SITE_URL}votes/${vote.id}/`)).toBe(changedOn(vote.date as string));
    expect(lastmod.get(SITE_URL)).toBeNull();
    for (const m of urls.filter((u) => u.lastmod)) expect(m.lastmod! <= today && /^\d{4}-\d{2}-\d{2}$/.test(m.lastmod!), m.loc).toBe(true);
    // listed pages answer as they are listed
    for (const loc of [SITE_URL, `${SITE_URL}legislation/${ACT.id}/`, locs[locs.length - 1]]) {
      const listed = await request.get(pagesUrl(loc.slice(SITE_URL.length)), { maxRedirects: 0 });
      expect(listed.status(), loc).toBe(200);
    }
  });
});
