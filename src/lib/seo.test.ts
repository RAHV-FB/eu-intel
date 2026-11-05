/**
 * scripts/prerender-routes.mjs and scripts/seo.mjs on a small site: the link-preview tags of every page, a legislative
 * file's key facts for readers without JavaScript and its act as schema.org Legislation, the sitemap and robots.txt, with
 * SITE_URL and without. tests/e2e/seo.spec.ts checks the built site, against the pages once loaded.
 */
import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';

const ROOT = new URL('../../', import.meta.url);
const SITE_URL = 'https://example.org/eu-intel/';
const EURLEX = (celex: string) => `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:${celex}`;

// ------------------------------------------------------------------ the site: five files, two votes, a topic

const file = {
  type: 'COD',
  type_label: 'Ordinary legislative procedure',
  official_title: null,
  short: null,
  topics: [],
  celex: [] as string[],
  instrument: 'regulation',
  started: '2099-01-10',
  adopted: null as string | null,
  published: null as string | null,
  known_as: null as unknown,
  related: [] as unknown[],
  documents: [] as unknown[],
  acts: [] as unknown[],
  timeline: [] as unknown[],
  changes: [] as unknown[],
  oeil_url: null as string | null,
  application: null as unknown,
};
const ACT = {
  celex: '32099R0001',
  eli: 'http://data.europa.eu/eli/reg/2099/1/oj',
  act_type: 'regulation',
  title: 'Regulation (EU) 2099/1 of the European Parliament and of the Council of 13 June 2099 on tests </script><!-- & more',
  date_document: '2099-06-13',
  date_publication: '2099-07-12',
  entry_into_force: '2099-08-01',
  eurlex_url: EURLEX('32099R0001'),
};
const FILES = [
  {
    ...file,
    id: '2099-0001',
    ref: '2099/0001(COD)',
    title: 'Rules on <tests> & "quotes"',
    stage: 'in_force',
    status: {
      stage: 'in_force',
      label: 'In force',
      explanation: 'The act has been in force since 1 August 2099. It repeals Regulation (EU) 2050/1 and Regulation (EU) 2051/2.',
      since: '2099-08-01',
      basis: 'source',
      named_acts: [
        { celex: '32050R0001', label: 'Regulation (EU) 2050/1', url: EURLEX('32050R0001'), dossier: '2049-0001' },
        { celex: '32051R0002', label: 'Regulation (EU) 2051/2', url: EURLEX('32051R0002'), dossier: null },
      ],
    },
    next_step: {
      text: 'The regulation applies directly; no national transposition is needed. Later dates from which (parts of) the act apply: 2 December 2099 and 2 August 2100.',
      institution: null,
      basis: 'source',
    },
    adopted: '2099-05-21',
    published: '2099-07-12',
    last_event: '2099-10-01',
    celex: ['32099R0001'],
    known_as: { acts: ['Regulation (EU) 2099/1'], names: ['Test Act'], part_of: [] },
    acts: [ACT],
    oeil_url: 'https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference=2099/0001(COD)',
    // an address on a host that serves it over https: linked as https, as the page links it (src/lib/format.ts safeUrl)
    documents: [{ id: 'COM(2099)0001', kind: 'proposal', url: 'http://www.europarl.europa.eu/RegData/com/2099/0001.pdf' }],
    application: {
      entry_into_force: '2099-08-01',
      application_dates: ['2099-12-02', '2100-08-02'],
      partial_application_dates: ['2099-12-02'],
      application_unrecorded: [],
      transposition_deadlines: [],
      future: true,
    },
    // recorded a day after the step; a change dated after the build is not a last change
    changes: [{ detected_at: '2099-11-02T06:00:00Z' }, { detected_at: '2099-11-09T06:00:00Z' }, { detected_at: null }],
  },
  {
    ...file,
    id: '2099-0002',
    ref: '2099/0002(COD)',
    title: 'A proposal',
    stage: 'proposed',
    status: { stage: 'proposed', label: 'Proposal under examination', explanation: 'Parliament is examining the proposal.', since: '2099-02-01', basis: 'derived' },
    next_step: { text: "Parliament's responsible committee prepares and votes on its report.", institution: 'EP', basis: 'derived' },
    last_event: '2099-09-01',
  },
  {
    ...file,
    id: '2099-0003',
    ref: '2099/0003(COD)',
    title: 'A split proposal',
    stage: 'unknown',
    instrument: null,
    started_from_parts: true,
    status: { stage: 'unknown', label: 'Split into separate procedures', explanation: 'Split.', since: null, basis: 'source' },
    next_step: { text: 'Not determined.', institution: null, basis: 'unknown' },
    related: [{ id: '2099-0003A', title: 'Part A', relation: 'Split into', ref: '2099/0003A(COD)', status_label: 'In force' }],
    last_event: '2099-03-01',
  },
  {
    ...file,
    id: '2099-0004',
    ref: '2099/0004(NLE)',
    title: 'A date fixed in the law, and no step recorded',
    stage: 'parliament_position',
    type_label: 'Non-legislative act',
    status: { stage: 'parliament_position', label: 'Awaiting Council action', explanation: 'The Council has not yet acted.', since: null, basis: 'source' },
    next_step: { text: 'Not determined from the recorded events.', institution: null, basis: 'unknown' },
    timeline: [
      { date: '2099-04-01', kind: 'ep_position', title: 'Parliament adopted its position', institution: 'EP', state: 'done' },
      { date: '2100-01-01', kind: 'application', title: 'Rules start to apply', institution: 'EUR-Lex', state: 'scheduled' },
    ],
    last_event: '2099-04-01',
  },
  {
    ...file,
    id: '2099-0005',
    ref: '2099/0005(COD)',
    title: 'Nothing determined',
    stage: 'parliament_position',
    status: { stage: 'parliament_position', label: 'Awaiting Council action', explanation: 'The Council has not yet acted.', since: null, basis: 'unknown' },
    next_step: { text: 'Not determined from the recorded events.', institution: null, basis: 'unknown' },
    last_event: '2099-04-02',
  },
];
// listed without a data file of its own: its page is written without key facts
const WITHOUT_DATA = { id: '2099-0006', ref: '2099/0006(COD)', title: 'No data file', status_label: 'Proposal under examination', official_title: null, last_event: '2099-08-08' };

function build(dir: string, siteUrl?: string) {
  const put = (rel: string, body: unknown) => {
    mkdirSync(join(dir, rel, '..'), { recursive: true });
    writeFileSync(join(dir, rel), typeof body === 'string' ? body : JSON.stringify(body));
  };
  if (!existsSync(join(dir, 'dist'))) {
    put('dist/index.html', readFileSync(new URL('index.html', ROOT), 'utf8').replace(/%BASE_URL%/g, '/eu-intel/'));
    put('dist/data/meta.json', { built_at: '2099-11-05T10:00:00Z', core_data_at: '2099-11-04T08:00:00Z' });
    put('dist/data/dossiers/index.json', [
      ...FILES.map(({ id, ref, title, status, last_event }) => ({ id, ref, title, status_label: status.label, official_title: null, last_event })),
      WITHOUT_DATA,
    ]);
    for (const d of FILES) put(`dist/data/dossiers/${d.id}.json`, d);
    put('dist/data/votes/index.json', [
      { id: '1', display_title: 'A vote', date: '2099-07-09', for: 1, against: 2, abstain: 3 },
      { id: '2', display_title: 'A vote after the build', date: '2099-12-01', for: 4, against: 5, abstain: 6 },
    ]);
    put('dist/data/topics.json', [{ slug: 'tech', label: 'Technology & AI' }]);
    mkdirSync(join(dir, 'src/lib'), { recursive: true });
    copyFileSync(new URL('src/lib/format.ts', ROOT), join(dir, 'src/lib/format.ts'));
  }
  const env = { ...process.env };
  delete env.SITE_URL;
  if (siteUrl) env.SITE_URL = siteUrl;
  execFileSync(process.execPath, [new URL('scripts/prerender-routes.mjs', ROOT).pathname], { cwd: dir, env, stdio: 'pipe' });
  const read = (rel: string) => readFileSync(join(dir, 'dist', rel), 'utf8');
  const pages = () => {
    const out: string[] = [];
    const walk = (d: string) => {
      for (const e of readdirSync(d, { withFileTypes: true })) {
        if (e.isDirectory() && e.name !== 'data') walk(join(d, e.name));
        else if (e.name.endsWith('.html')) out.push(relative(join(dir, 'dist'), join(d, e.name)));
      }
    };
    walk(join(dir, 'dist'));
    return out.sort();
  };
  return { read, pages, has: (rel: string) => existsSync(join(dir, 'dist', rel)) };
}

const dirs: string[] = [];
function site(siteUrl?: string) {
  const dir = mkdtempSync(join(tmpdir(), 'seo-'));
  dirs.push(dir);
  return { dir, ...build(dir, siteUrl) };
}
afterAll(() => dirs.forEach((d) => rmSync(d, { recursive: true, force: true })));

const unescape = (s: string) => s.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
function meta(html: string) {
  const tags: Record<string, string[]> = {};
  for (const m of html.matchAll(/<meta (?:property|name)="([^"]+)" content="([^"]*)" \/>/g)) (tags[m[1]] ??= []).push(unescape(m[2]));
  return { title: unescape(/<title>([^<]*)<\/title>/.exec(html)?.[1] ?? ''), canonical: /<link rel="canonical" href="([^"]+)"/.exec(html)?.[1], tags };
}
const noscript = (html: string) => /<noscript>([\s\S]*?)<\/noscript>/.exec(html)?.[1] ?? '';
const jsonLd = (html: string) => [...html.matchAll(/<script type="application\/ld\+json">([^<]*)<\/script>/g)].map((m) => JSON.parse(m[1]));

// ------------------------------------------------------------------ the tests

describe('link previews', () => {
  it('give every page its own title and description, and its address with SITE_URL as its canonical link does', () => {
    for (const [s, withUrl] of [
      [site(SITE_URL), true],
      [site(), false],
    ] as const) {
      const pages = s.pages().filter((p) => !p.startsWith('topics/')); // the former topic addresses: a redirect, not a page
      expect(pages.length).toBeGreaterThan(15);
      for (const p of pages) {
        const { title, canonical, tags } = meta(s.read(p));
        expect(tags['og:title'], p).toEqual([title]);
        expect(tags['og:description'], p).toEqual(tags.description);
        expect(tags['og:type'], p).toEqual(['website']);
        expect(tags['og:site_name'], p).toEqual(['EU Legislative Intelligence']);
        expect(tags['og:locale'], p).toEqual(['en_GB']);
        expect(tags['twitter:card'], p).toEqual(['summary']);
        // the page for unknown addresses has no address of its own
        expect(canonical, p).toBe(withUrl && p !== '404.html' ? SITE_URL + p.replace(/index\.html$/, '') : undefined);
        expect(tags['og:url'], p).toEqual(canonical ? [canonical] : undefined);
      }
    }
  });

  it('are written once, also when the script runs again on its own output', () => {
    const s = site(SITE_URL);
    build(s.dir, SITE_URL);
    const home = s.read('index.html');
    for (const tag of ['og:title', 'og:url', 'twitter:card']) expect(home.split(`"${tag}"`).length - 1, tag).toBe(1);
    expect(home.split('rel="canonical"').length - 1).toBe(1);
    expect(meta(s.read('legislation/2099-0001/index.html')).tags['og:url']).toEqual([`${SITE_URL}legislation/2099-0001/`]);
  });
});

describe('a file’s key facts, for readers without JavaScript', () => {
  const s = site(SITE_URL);
  const facts = (id: string) => noscript(s.read(`legislation/${id}/index.html`));

  it('state an act’s status, next step, dates and act, in the page’s words, before the site’s note', () => {
    const f = facts('2099-0001');
    expect(f).toContain('<div class="container page">');
    expect(f).toContain('<h1>Rules on &lt;tests&gt; &amp; &quot;quotes&quot;</h1>');
    expect(f).toContain('<p>Regulation (EU) 2099/1 · also known as Test Act</p>');
    expect(f).toContain('<p><strong>In force</strong> since <time datetime="2099-08-01">1 August 2099</time></p>');
    // the acts the status names, linked as the page links them: to their file here, else to EUR-Lex
    expect(f).toContain(
      `It repeals <a href="/eu-intel/legislation/2049-0001/">Regulation (EU) 2050/1</a> and <a href="${EURLEX('32051R0002')}">Regulation (EU) 2051/2</a>.</p>`,
    );
    // an in-force regulation's next step, led by what is still to come (Summary.tsx regulationNextStep)
    expect(f).toContain(
      '<p>Provisions of the act start to apply on 2 December 2099 and 2 August 2100. As a regulation, it applies directly; no national transposition is needed.</p>',
    );
    expect(f).toMatch(/<dt>Type<\/dt>\s*<dd>Ordinary legislative procedure<\/dd>\s*<dd>Regulation<\/dd>/);
    expect(f).toMatch(/<dt>Proposed<\/dt>\s*<dd><time datetime="2099-01-10">10 Jan 2099<\/time><\/dd>/);
    expect(f).toMatch(/<dt>Adopted<\/dt>\s*<dd><time datetime="2099-05-21">21 May 2099<\/time><\/dd>/);
    expect(f).toMatch(/<dt>Published in the Official Journal<\/dt>\s*<dd><time datetime="2099-07-12">12 Jul 2099<\/time><\/dd>/);
    expect(f).toContain(`<dt>CELEX</dt>\n          <dd><a href="${EURLEX('32099R0001')}">32099R0001</a></dd>`);
    expect(f).toContain('<li><a href="https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference=2099/0001(COD)">Procedure file (Legislative Observatory)</a></li>');
    expect(f).toContain('<li><a href="https://www.europarl.europa.eu/RegData/com/2099/0001.pdf">Commission proposal (COM(2099)0001)</a></li>');
    expect(f).toContain(`<li><a href="${EURLEX('32099R0001')}">Legal text (EUR-Lex)</a></li>`);
    // "When it applies": entry into force, then the dates from which the act applies, without a tense
    const when = f.slice(f.indexOf('<h2>When it applies</h2>'));
    expect(when.match(/<dt>[^<]*<\/dt>/g)).toEqual(['<dt>Entry into force</dt>', '<dt>Rules apply from</dt>', '<dt>Some provisions apply from</dt>']);
    expect(when).toContain('<dt>Rules apply from</dt>\n          <dd><time datetime="2100-08-02">2 Aug 2100</time></dd>');
    expect(when).toContain('<dt>Some provisions apply from</dt>\n          <dd><time datetime="2099-12-02">2 Dec 2099</time></dd>');
    // how current the data is, as the footer says it; then the site's note on JavaScript, with its link to the data
    expect(f).toMatch(/<p>Procedures, votes and acts current to 4 Nov 2099\.<\/p>\s*<p>This site needs JavaScript[^]*<a href="\/eu-intel\/data\/meta.json">data\/meta.json<\/a>/);
    expect(f.indexOf('<h1>')).toBeLessThan(f.indexOf('This site needs JavaScript'));
  });

  it('mark what is derived, name who acts next, and give no act or dates to a proposal', () => {
    const f = facts('2099-0002');
    expect(f).toContain('<p>Parliament is examining the proposal. <span class="basis">Derived from recorded events</span></p>');
    expect(f).toContain(
      "<p>Parliament's responsible committee prepares and votes on its report. <span class=\"basis\">Derived from recorded events</span></p><p>European Parliament</p>",
    );
    expect(f).toContain('<dd>Regulation (as proposed)</dd>');
    for (const absent of ['CELEX', 'Adopted', 'When it applies', 'Legal text']) expect(f).not.toContain(absent);
  });

  it('send a split proposal’s reader to its separate files', () => {
    const f = facts('2099-0003');
    expect(f).toContain('<li><a href="/eu-intel/legislation/2099-0003A/">2099/0003A(COD) Part A</a> (In force)</li>');
    expect(f).toContain('<p>This file was split into separate procedures, listed above; each has its own status.</p>');
    expect(f).toContain('<p>None on this file: each separate file listed above has its own next step.</p>');
    expect(f).toContain('<dt>Proposed (as recorded for its parts)</dt>');
    expect(f).not.toContain('<dd>Regulation');
  });

  it('give the next date fixed in law when no next step is determined, and otherwise say none is recorded', () => {
    expect(facts('2099-0004')).toContain(
      '<p><time datetime="2100-01-01">1 January 2100</time></p><p>Rules start to apply</p><p>Date fixed in the law (EUR-Lex)</p>',
    );
    const f = facts('2099-0005');
    expect(f).toContain('<p>No next step is recorded in the official sources.</p>');
    expect(f).toContain('<p>The Council has not yet acted. <span class="basis">Not determinable</span></p>');
  });

  it('are left out for a file without a data file, and never added to other pages', () => {
    expect(noscript(s.read('legislation/2099-0006/index.html'))).toMatch(/^This site needs JavaScript/);
    expect(noscript(s.read('index.html'))).toMatch(/^This site needs JavaScript/);
    expect(noscript(s.read('votes/1/index.html'))).toMatch(/^This site needs JavaScript/);
  });
});

describe('structured data', () => {
  it('describes a file’s act as schema.org Legislation, with nothing in it able to end the element', () => {
    const html = site(SITE_URL).read('legislation/2099-0001/index.html');
    expect(html).toContain('on tests \\u003c/script>\\u003c!-- & more');
    expect(jsonLd(html)).toEqual([
      {
        '@context': 'https://schema.org',
        '@type': 'Legislation',
        name: ACT.title,
        alternateName: ['Regulation (EU) 2099/1', 'Test Act'],
        legislationIdentifier: '32099R0001',
        legislationType: 'Regulation',
        legislationDate: '2099-06-13',
        datePublished: '2099-07-12',
        legislationLegalForce: { '@id': 'https://schema.org/InForce' },
        url: EURLEX('32099R0001'),
        sameAs: 'http://data.europa.eu/eli/reg/2099/1/oj',
        mainEntityOfPage: `${SITE_URL}legislation/2099-0001/`,
      },
    ]);
  });

  it('gives no page address without SITE_URL, and nothing for a file without an act', () => {
    const s = site();
    expect(jsonLd(s.read('legislation/2099-0001/index.html'))[0].mainEntityOfPage).toBeUndefined();
    for (const id of ['2099-0002', '2099-0003', '2099-0006']) expect(jsonLd(s.read(`legislation/${id}/index.html`)), id).toEqual([]);
  });
});

describe('sitemap and robots.txt', () => {
  const entries = (xml: string) =>
    [...xml.matchAll(/<url><loc>([^<]+)<\/loc>(?:<lastmod>([^<]+)<\/lastmod>)?<\/url>/g)].map((m) => [m[1], m[2] ?? null] as const);

  it('list every page for search engines at its canonical address, with the date of its last change where the data gives one', () => {
    const s = site(SITE_URL);
    const xml = s.read('sitemap.xml');
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')).toBe(true);
    expect(xml.endsWith('</urlset>\n')).toBe(true);
    const listed = new Map(entries(xml));
    expect(listed.size).toBe(entries(xml).length);
    // every page written but those not for search engines: the visitor's own list, the search form, the former topic
    // addresses (noindex) and the page for unknown addresses
    const expected = s
      .pages()
      .filter((p) => p.endsWith('index.html') && !/^(following|search|topics)\//.test(p))
      .map((p) => SITE_URL + p.replace(/index\.html$/, ''));
    expect([...listed.keys()].sort()).toEqual(expected.sort());
    expect([...listed.keys()][0]).toBe(SITE_URL);
    // a file's latest step or the latest change recorded on it (not one dated after the build); a vote's date
    expect(listed.get(`${SITE_URL}legislation/2099-0001/`)).toBe('2099-11-02');
    expect(listed.get(`${SITE_URL}legislation/2099-0002/`)).toBe('2099-09-01');
    expect(listed.get(`${SITE_URL}legislation/2099-0006/`)).toBe('2099-08-08');
    expect(listed.get(`${SITE_URL}votes/1/`)).toBe('2099-07-09');
    expect(listed.get(`${SITE_URL}votes/2/`)).toBeNull();
    expect(listed.get(SITE_URL)).toBeNull();
    expect(listed.get(`${SITE_URL}about/`)).toBeNull();
    expect(s.read('robots.txt')).toBe(`User-agent: *\nAllow: /\n\nSitemap: ${SITE_URL}sitemap.xml\n`);
  });

  it('are written without a sitemap when there is no SITE_URL, and a sitemap of an earlier run is removed', () => {
    const s = site(SITE_URL);
    expect(s.has('sitemap.xml')).toBe(true);
    build(s.dir);
    expect(s.has('sitemap.xml')).toBe(false);
    expect(s.read('robots.txt')).toBe('User-agent: *\nAllow: /\n');
    expect(s.read('index.html')).not.toContain('og:url');
  });

  it('split into several sitemaps and their index past a limit', async () => {
    const { sitemapFiles, SITEMAP_LIMITS } = (await import(new URL('scripts/seo.mjs', ROOT).pathname)) as {
      sitemapFiles: (e: { loc: string; lastmod?: string }[], site: string, limits?: { urls: number; bytes: number }) => { name: string; xml: string }[];
      SITEMAP_LIMITS: { urls: number; bytes: number };
    };
    expect(SITEMAP_LIMITS).toEqual({ urls: 50_000, bytes: 50 * 1024 * 1024 });
    const urls = ['a/', 'b/', 'c/', 'd/', 'e/'].map((p) => ({ loc: SITE_URL + p, lastmod: '2099-01-01' }));
    expect(sitemapFiles(urls, SITE_URL).map((f) => f.name)).toEqual(['sitemap.xml']);
    const files = sitemapFiles(urls, SITE_URL, { urls: 2, bytes: SITEMAP_LIMITS.bytes });
    expect(files.map((f) => f.name)).toEqual(['sitemap.xml', 'sitemap-1.xml', 'sitemap-2.xml', 'sitemap-3.xml']);
    expect(files[0].xml).toBe(
      `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${[1, 2, 3]
        .map((i) => `  <sitemap><loc>${SITE_URL}sitemap-${i}.xml</loc></sitemap>\n`)
        .join('')}</sitemapindex>\n`,
    );
    expect(files.slice(1).map((f) => entries(f.xml).map(([loc]) => loc.slice(SITE_URL.length)))).toEqual([['a/', 'b/'], ['c/', 'd/'], ['e/']]);
    // by size: room for two addresses in each file
    const one = Buffer.byteLength(`  <url><loc>${SITE_URL}a/</loc><lastmod>2099-01-01</lastmod></url>\n`);
    const empty = Buffer.byteLength(sitemapFiles([], SITE_URL)[0].xml);
    const bySize = sitemapFiles(urls, SITE_URL, { urls: SITEMAP_LIMITS.urls, bytes: empty + 2 * one });
    expect(bySize.slice(1).map((f) => entries(f.xml).length)).toEqual([2, 2, 1]);
    for (const f of bySize.slice(1)) expect(Buffer.byteLength(f.xml)).toBeLessThanOrEqual(empty + 2 * one);
  });
});
