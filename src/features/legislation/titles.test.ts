/**
 * Page titles: cut at a word boundary, the same before and after a page loads (scripts/prerender-routes.mjs writes the title of
 * the shell, useDocumentTitle sets it live), and the topic labels shown when topics.json cannot be loaded.
 * The data tests read the built site (public/data) and are skipped when it has not been built.
 */
import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, DossierSummary, Topic } from '../../types/data';
import { SITE_TITLE, TITLE_MAX, TOPIC_FALLBACK, documentTitle, shortTitle } from './labels';

const ROOT = new URL('../../../', import.meta.url);
const DATA = new URL('public/data/', ROOT);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe('shortTitle', () => {
  it('leaves a title of up to the limit as it is', () => {
    expect(shortTitle('Energy performance of buildings')).toBe('Energy performance of buildings');
    expect(shortTitle('x'.repeat(TITLE_MAX))).toBe('x'.repeat(TITLE_MAX));
  });

  it('cuts a longer one at a word boundary and says so, to at most the limit', () => {
    const t =
      'Amending Regulations (EC) No 1272/2008, (EC) No 1223/2009 and (EU) 2019/1009 as regards simplification of certain requirements and procedures for products';
    const s = shortTitle(t);
    expect(s).toBe('Amending Regulations (EC) No 1272/2008, (EC) No 1223/2009 and (EU) 2019/1009 as regards simplification of certain…');
    expect(s.length).toBeLessThanOrEqual(TITLE_MAX);
    expect(shortTitle(t, 60)).toBe('Amending Regulations (EC) No 1272/2008, (EC) No 1223/2009…');
  });

  it('does not end on a comma, a semicolon, a colon or an opening bracket', () => {
    expect(shortTitle('One two three, four five six', 15)).toBe('One two three…');
    expect(shortTitle('One two three; four five six', 15)).toBe('One two three…');
    expect(shortTitle('One two three: four five six', 15)).toBe('One two three…');
    expect(shortTitle('One two ( three four five six', 12)).toBe('One two…');
  });

  it('cuts a title without spaces', () => {
    expect(shortTitle('x'.repeat(200))).toBe(`${'x'.repeat(TITLE_MAX - 1)}…`);
  });
});

describe('documentTitle', () => {
  it('adds the qualifier, after the shortened title, and the site name', () => {
    expect(documentTitle('Energy performance of buildings', '2021/0426(COD)')).toBe(
      'Energy performance of buildings (2021/0426(COD)) – EU Legislative Intelligence',
    );
    const long = documentTitle(`${'word '.repeat(60)}end`, '2021/0426(COD)');
    expect(long).toMatch(/^(word )*word… \(2021\/0426\(COD\)\) – EU Legislative Intelligence$/);
    expect(long.length).toBeLessThanOrEqual(TITLE_MAX + ' (2021/0426(COD)) – '.length + SITE_TITLE.length);
  });

  it('is the site name without a title', () => {
    expect(documentTitle(null)).toBe(SITE_TITLE);
    expect(documentTitle('')).toBe(SITE_TITLE);
  });
});

describe.skipIf(!built)('on the built data', () => {
  const index = built ? read<DossierSummary[]>('dossiers/index.json') : [];

  it('2017/0230(COD) had a title of 663 characters in the tab, the history and the route announcement', () => {
    const d = read<DossierDetail>('dossiers/2017-0230.json');
    expect(d.title.length).toBeGreaterThan(400);
    const title = documentTitle(d.title, d.ref);
    expect(title.length).toBeLessThan(180);
    expect(title.endsWith(`… (${d.ref}) – ${SITE_TITLE}`)).toBe(true);
  });

  it('gives a file the same title from its index entry (the prerendered page) as from its full title (the loaded page)', () => {
    // dossiers/index.json holds the title cut at 180 characters (pipeline/build.py _truncate); the shell is written from it
    let longer = 0;
    for (const s of index) {
      const full = read<DossierDetail>(`dossiers/${s.id}.json`).title;
      expect(shortTitle(s.title), s.id).toBe(shortTitle(full));
      if (full.length > TITLE_MAX) longer++;
    }
    expect(longer).toBeGreaterThan(100);
  }, 60_000);

  it('has fallback topic labels that are those of topics.json, in its order', () => {
    // TOPIC_FALLBACK is what the pages show when topics.json cannot be loaded: add a new topic there too
    const topics = read<Topic[]>('topics.json');
    expect(TOPIC_FALLBACK).toEqual(topics.map((t) => ({ slug: t.slug, label: t.label })));
  });
});

// scripts/prerender-routes.mjs on a small site: the titles of its shells are those of the loaded pages, a `$` in a title is
// text, and the canonical links and the one noindex are where they should be.
describe('scripts/prerender-routes.mjs', () => {
  const LONG =
    'Proposal for a Regulation of the European Parliament and of the Council amending Regulations (EU) 2016/1011, (EU) 2019/2089 and (EU) 2021/1230 as regards the provision of benchmark methodologies, the administration of benchmarks and the transitional arrangements for third-country benchmarks, and for other purposes';
  const TITLES = ['Mandatory exchange of information', 'US$1 billion and $& more: $\' and $` and $$ and $1', LONG];

  function withSite(siteUrl?: string, runs = 1) {
    const dir = mkdtempSync(join(tmpdir(), 'prerender-'));
    const read = prerenderIn(dir, siteUrl, runs);
    const files = Object.fromEntries(
      [
        'index.html',
        '404.html',
        'legislation/index.html',
        'legislation/2099-0001/index.html',
        'legislation/2099-0002/index.html',
        'legislation/2099-0003/index.html',
        'votes/1/index.html',
        'people/groups/renew/index.html',
        'people/index.html',
        'votes/index.html',
        'how-the-eu-works/index.html',
      ].map((f) => [f, read(f)]),
    );
    rmSync(dir, { recursive: true, force: true });
    return files;
  }

  function prerenderIn(dir: string, siteUrl?: string, runs = 1) {
    const put = (rel: string, body: string) => {
      mkdirSync(join(dir, rel, '..'), { recursive: true });
      writeFileSync(join(dir, rel), body);
    };
    put('dist/index.html', readFileSync(new URL('index.html', ROOT), 'utf8'));
    put(
      'dist/data/dossiers/index.json',
      JSON.stringify(TITLES.map((title, i) => ({ id: `2099-000${i + 1}`, ref: `2099/000${i + 1}(COD)`, title, status_label: 'In force', short: `Costs $& and $' ${i}` }))),
    );
    put('dist/data/votes/index.json', JSON.stringify([{ id: '1', display_title: TITLES[1], date: '2026-07-09', for: 1, against: 2, abstain: 3 }]));
    put('dist/data/people/groups.json', JSON.stringify([{ id: 'renew', code: 'Renew', name: 'Renew Europe Group' }]));
    mkdirSync(join(dir, 'src/lib'), { recursive: true });
    copyFileSync(new URL('src/lib/format.ts', ROOT), join(dir, 'src/lib/format.ts'));
    const env = { ...process.env };
    delete env.SITE_URL;
    if (siteUrl) env.SITE_URL = siteUrl;
    for (let i = 0; i < runs; i++)
      execFileSync(process.execPath, [new URL('scripts/prerender-routes.mjs', ROOT).pathname], { cwd: dir, env, stdio: 'pipe' });
    return (rel: string) => readFileSync(join(dir, 'dist', rel), 'utf8');
  }

  const titleOf = (html: string) => /<title>([^<]*)<\/title>/.exec(html)?.[1];
  const unescape = (s: string | undefined) => s?.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

  it('writes the title the loaded page sets, and keeps a `$` in a title or description as text', () => {
    const f = withSite();
    TITLES.forEach((t, i) => {
      const html = f[`legislation/2099-000${i + 1}/index.html`];
      expect(unescape(titleOf(html))).toBe(documentTitle(t, `2099/000${i + 1}(COD)`));
      expect((html.match(/<title>/g) ?? []).length).toBe(1);
      expect(html.match(/<script type="module"/g) ?? []).toHaveLength(1);
    });
    // `$&`, `$'` and `$$` in a description were replacement patterns: the head was cut and the module script repeated
    expect(f['legislation/2099-0002/index.html']).toContain('<meta name="description" content="Costs $&amp; and $\' 1" />');
    expect(unescape(titleOf(f['votes/1/index.html']))).toBe(documentTitle(TITLES[1], '9 Jul 2026'));
    expect(f['votes/1/index.html']).toContain('European Parliament vote of 9 Jul 2026: 1 for, 2 against, 3 abstentions.');
    expect(unescape(titleOf(f['legislation/2099-0003/index.html']))!.length).toBeLessThan(180);
  });

  it('gives the pages the titles their components set', () => {
    const f = withSite();
    expect(titleOf(f['people/groups/renew/index.html'])).toBe('Renew – Renew Europe Group – EU Legislative Intelligence'); // Group.tsx
    expect(titleOf(f['people/index.html'])).toBe('MEPs – EU Legislative Intelligence'); // People.tsx, before a view is chosen
    expect(titleOf(f['votes/index.html'])).toBe('Parliament votes – EU Legislative Intelligence'); // Votes.tsx
    expect(titleOf(f['how-the-eu-works/index.html'])).toBe('How the EU works – EU Legislative Intelligence'); // HowEuWorks.tsx
  });

  it('writes a canonical link only when SITE_URL is set, and noindex only on the page for unknown addresses', () => {
    const none = withSite();
    for (const html of Object.values(none)) expect(html).not.toContain('rel="canonical"');
    const f = withSite('https://example.org/eu-intel');
    expect(f['legislation/2099-0001/index.html']).toContain('<link rel="canonical" href="https://example.org/eu-intel/legislation/2099-0001/" />');
    expect(f['legislation/index.html']).toContain('<link rel="canonical" href="https://example.org/eu-intel/legislation/" />');
    expect(f['index.html']).toContain('<link rel="canonical" href="https://example.org/eu-intel/" />');
    expect(f['404.html']).not.toContain('rel="canonical"');
    for (const files of [none, f])
      for (const [name, html] of Object.entries(files)) expect(html.includes('name="robots"'), name).toBe(name === '404.html');
    expect(f['404.html']).toContain('<meta name="robots" content="noindex" />');
    // run again on its own output (npm run build starts from a fresh vite build, but the script may be run by hand)
    const twice = withSite('https://example.org/eu-intel', 2);
    for (const [name, html] of Object.entries(twice)) expect((html.match(/rel="canonical"/g) ?? []).length, name).toBe(name === '404.html' ? 0 : 1);
  });
});
