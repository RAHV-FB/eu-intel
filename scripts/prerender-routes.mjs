// Post-build: make every known route directly loadable on GitHub Pages (HTTP 200, no server rewrites).
// Writes dist/<route>/index.html copies of the SPA shell with a route-specific <title> and description (and, for a
// legislative file, a <link rel="alternate"> to its own Atom feed), plus dist/404.html as a fallback for anything else. Reads route lists from dist/data/*.json (party pages from
// the party files themselves: two parties without a recorded name are left out of parties.json).
// SITE_URL (the Pages URL, as the data build takes it for the Atom feeds) gives each page its canonical address,
// <SITE_URL><route>/; without it a page has none (a local or fork build must not point at another host).
// Every page written by page() also gets Open Graph and Twitter tags (its title and description; with SITE_URL, its
// address and the site's image) and, with SITE_URL, a place in sitemap.xml; a legislative file's page gets its key facts
// for readers without JavaScript (<noscript>) and its act as schema.org Legislation (JSON-LD). robots.txt names the
// sitemap. See scripts/seo.mjs.
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { SITE, esc, formatDate, keyFacts, legislationJsonLd, robotsTxt, sitemapFiles, socialTags } from './seo.mjs';

const DIST = 'dist';
// (the home page's canonical link and preview tags are written into dist/index.html below: a second run starts without them)
const shell = readFileSync(join(DIST, 'index.html'), 'utf8')
  .replace(/\s*<link rel="canonical"[^>]*>/g, '')
  .replace(/\s*<meta (?:property="og:|name="twitter:)[^>]*>/g, '');
const SITE_URL = process.env.SITE_URL ? `${process.env.SITE_URL.replace(/\/+$/, '')}/` : null;

const unesc = (s) => s.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
// A directory name taken from the data (an id, a slug, a country code) must be one plain name inside dist/, whatever a
// source sends: an id "../x" would write outside it, ".." over another page. Anything else stops the build.
const segment = (s) => {
  const v = String(s);
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(v) || v.includes('..')) {
    throw new Error(`prerender-routes: ${JSON.stringify(v)} is not a safe path segment for a page address`);
  }
  return v;
};
const readJson = (p) => {
  const f = join(DIST, 'data', p);
  return existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : [];
};

// Country names as the app shows them (src/lib/format.ts COUNTRY_NAMES, which includes the United Kingdom)
const COUNTRY = Object.fromEntries(
  [...(/COUNTRY_NAMES[^=]*=\s*\{([^}]*)\}/.exec(readFileSync('src/lib/format.ts', 'utf8'))?.[1] ?? '').matchAll(/([A-Z]{2}): '([^']+)'/g)].map(
    (m) => [m[1], m[2]],
  ),
);
if (Object.keys(COUNTRY).length < 28) throw new Error('prerender-routes: could not read COUNTRY_NAMES from src/lib/format.ts');
const countryName = (code) => COUNTRY[code] ?? code;
const inCountry = (code) => (['NL', 'GB'].includes(code) ? `the ${countryName(code)}` : countryName(code));
// "2019–2024 term" (as search subtitles and party pages name a party record's term)
const termYears = (terms) =>
  terms?.length ? `${terms.map((t) => `${1979 + 5 * (t - 1)}–${1984 + 5 * (t - 1)}`).join(' and ')} term${terms.length > 1 ? 's' : ''}` : '';
// a party page's title, as partyRecordTitle (src/features/people/labels.ts) gives it: records of the same name and
// country (the same party in other terms) are told apart by their term, and by their period when they share the term
const partyTitle = (p) => {
  const term = termYears(p.terms);
  const others = p.same_name ?? [];
  if (!others.length || !term) return `${p.label} (${countryName(p.country)})`;
  const sameTerm = others.some((r) => termYears(r.terms) === term);
  const period = !p.start ? 'dates not recorded' : p.end ? `${formatDate(p.start)} – ${formatDate(p.end)}` : `from ${formatDate(p.start)}`;
  return `${p.label} (${countryName(p.country)}, ${term}${sameTerm ? `, ${period}` : ''})`;
};

// A page title as useDocumentTitle (src/features/legislation/labels.ts: TITLE_MAX, shortTitle, documentTitle) sets it once
// the page has loaded: cut at a word boundary, so that the title before and after loading is the same. The title in
// dossiers/index.json is already cut at 180 characters by the same rule (pipeline/build.py _truncate), which leaves the
// cut at 120 unchanged.
const TITLE_MAX = 120;
const shortTitle = (title, max = TITLE_MAX) => {
  if (title.length <= max) return title;
  const head = title.slice(0, max);
  const space = head.lastIndexOf(' ');
  const cut = space > 0 ? head.slice(0, space) : title.slice(0, max - 1);
  return `${cut.replace(/[\s,;:(]+$/, '')}…`;
};
const documentTitle = (title, qualifier) => (title ? `${shortTitle(title)}${qualifier ? ` (${qualifier})` : ''} – ${SITE}` : SITE);

// Replacement functions, not strings: `$&`, `$'` or a `$$` in a title or description is text, not a replacement pattern.
const withHead = (html, ...tags) => {
  const tag = tags.filter(Boolean).join('\n    ');
  return tag ? html.replace('</head>', () => `  ${tag}\n  </head>`) : html;
};
// a page's absolute address, as its canonical link, og:url and the sitemap give it; null without SITE_URL
const pageUrl = (route) => (SITE_URL ? SITE_URL + (route ? `${route.split('/').map(encodeURIComponent).join('/')}/` : '') : null);
const canonical = (route) => (SITE_URL ? `<link rel="canonical" href="${esc(pageUrl(route))}" />` : '');
// The image of every page's link preview, the site's icon (public/og-image.png, which Vite copies into the site; made by
// scripts/render-og-image.mjs): only with SITE_URL, since its address must be absolute too; its size from the PNG itself
const IMAGE = 'og-image.png';
const png = SITE_URL && existsSync(join(DIST, IMAGE)) ? readFileSync(join(DIST, IMAGE)) : null;
const image = png && { url: SITE_URL + IMAGE, width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
// the shell's own title and description (the home page's), and its note for browsers without JavaScript
const shellTitle = unesc(/<title>([^<]*)<\/title>/.exec(shell)?.[1] ?? SITE);
const shellDescription = unesc(/<meta name="description" content="([^"]*)"/.exec(shell)?.[1] ?? '');
const NOSCRIPT = /<noscript>([\s\S]*?)<\/noscript>/;
const notice = NOSCRIPT.exec(shell)?.[1];
if (!shellDescription || !notice) throw new Error('prerender-routes: no description or <noscript> note in dist/index.html');
// The data's date: its texts (statuses, next steps) are written as of it, and the key facts are stated as of it
const meta = readJson('meta.json');
const today = (meta.built_at ?? new Date().toISOString()).slice(0, 10);
// how current the data is, as the footer says it (src/components/Layout.tsx)
const dataNote = !meta.built_at
  ? null
  : meta.core_data_at
    ? `Procedures, votes and acts current to ${formatDate(meta.core_data_at)}`
    : `Data built ${formatDate(meta.built_at)}`;
// the date of a page's last change where the data gives one (the sitemap's lastmod), never after the data's date
const changedOn = (...dates) =>
  dates
    .filter(Boolean)
    .map((x) => x.slice(0, 10))
    .filter((x) => x <= today)
    .sort()
    .pop();
// The base path the site is built for, from the shell's link to the site-wide Atom feed ("/eu-intel/data/feeds/updates.xml").
const BASE = /<link rel="alternate" type="application\/atom\+xml"[^>]*href="([^"]*)data\/feeds\/updates\.xml"/.exec(shell)?.[1];
if (BASE == null) throw new Error('prerender-routes: no link to data/feeds/updates.xml in dist/index.html');
// A file's own Atom feed (data/feeds/dossiers/<id>.xml), announced to browsers and feed readers as the app announces it
// once the page has loaded (src/components/useFeedLink.ts: the same id and title).
const feedLink = (d) =>
  `<link rel="alternate" type="application/atom+xml" id="page-feed" title="${esc(`${d.ref}: updates (Atom)`)}" href="${esc(`${BASE}data/feeds/dossiers/${encodeURIComponent(d.id)}.xml`)}" />`;

// The pages search engines may index, in the order written, each with the date of its last change where the data gives
// one (the sitemap's entries): the home page (written last) and every page written by page(), but the visitor's own list
// and the search form, which have nothing of their own to index.
const listed = [['', undefined]];
const UNLISTED = new Set(['following', 'search']);

// `facts`: what the page's <noscript> block shows before the shell's note on JavaScript (scripts/seo.mjs keyFacts)
function page(route, title, description, qualifier, head = '', { lastmod, facts } = {}) {
  const pageTitle = documentTitle(title, qualifier);
  let html = shell.replace(/<title>[^<]*<\/title>/, () => `<title>${esc(pageTitle)}</title>`);
  if (description) {
    html = html.replace(/<meta name="description" content="[^"]*"\s*\/?>/, () => `<meta name="description" content="${esc(description)}" />`);
  }
  html = withHead(html, canonical(route), socialTags(pageTitle, description || shellDescription, pageUrl(route), image), head);
  if (facts) html = html.replace(NOSCRIPT, () => `<noscript>\n      <div class="container page">\n${facts}      </div>\n    </noscript>`);
  const out = join(DIST, route, 'index.html');
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, html);
  if (!UNLISTED.has(route)) listed.push([route, lastmod]);
}

const routes = [
  ['legislation', 'Legislation', 'Search and filter EU legislative files: proposals, adopted laws and their status.'],
  [
    'legislation/changes',
    'What changed – Legislation',
    'Steps, votes and status changes recorded on EU legislative files, week by week and by topic, each linked to its official record.',
  ],
  [
    'legislation/transposition',
    'Directives into national law – Legislation',
    'Each directive due in the last three years or the next twelve months, with every Member State’s notified national measures and the Commission’s open cases.',
  ],
  ['insights', 'Data insights', 'Evidence-led analysis of tracked EU legislative files, Parliament votes and Council positions, with careful limitations.'],
  ['votes', 'Parliament votes', 'How the European Parliament voted: final votes, close votes, political groups and countries.'],
  ['people', 'MEPs', 'Members of the European Parliament, political groups and national parties.'],
  ['countries', 'Countries', 'How each EU Member State takes part in EU decisions and applies EU law.'],
  ['how-the-eu-works', 'How the EU works', 'A plain-language guide to how EU laws are proposed, negotiated, adopted and applied.'],
  ['about', 'About & methodology', 'Data sources, coverage, methodology and limitations.'],
  ['privacy', 'Privacy', 'Privacy notice: no tracking, no cookies, no analytics.'],
  ['following', 'Followed legislation', 'The EU legislative files you follow: their status and what changed since you last looked. The list is kept only in your browser.'],
  ['search', 'Search', 'Search EU legislation, MEPs, political groups, national parties, countries, topics and guides. Parliament votes are searched on the votes page.'],
];
// titles as the pages set them with useDocumentTitle (/people/ is the MEPs view until a view is chosen in the address)
for (const [r, t, d] of routes) page(r, t, d);
// When new rules apply, with its Atom feed of every date announced as the page announces it (src/pages/Applies.tsx:
// useFeedLink, the same id and title)
page(
  'legislation/applies',
  'When new rules apply – Legislation',
  'Dates set in EU law from which rules start to apply, by topic and Member State: entry into force, application, transposition deadlines. With Atom feeds and calendars.',
  undefined,
  `<link rel="alternate" type="application/atom+xml" id="page-feed" title="When new rules apply (Atom)" href="${esc(`${BASE}data/feeds/applies/all.xml`)}" />`,
);

let n = routes.length + 1;
for (const d of readJson('dossiers/index.json')) {
  const route = `legislation/${segment(d.id)}`;
  const data = readJson(`dossiers/${d.id}.json`);
  const file = Array.isArray(data) ? null : data; // (readJson gives [] for a missing file: the page then has no key facts)
  // the procedure reference tells apart files of the same title (Energy performance of buildings: 2021/0426(COD), 2016/0381(COD))
  page(
    route,
    d.title,
    d.short || `${d.ref}: ${d.status_label}.${d.official_title ? ` ${d.official_title}` : ''}`.slice(0, 300),
    d.ref,
    [feedLink(d), file && legislationJsonLd(file, pageUrl(route))].filter(Boolean).join('\n    '),
    {
      // its latest recorded step, or the latest change a refresh recorded on it (recorded days after the step, at times)
      lastmod: changedOn(d.last_event, ...(file?.changes ?? []).map((c) => c.detected_at)),
      facts: file && keyFacts(file, { base: BASE, today, dataNote, notice }),
    },
  );
  n++;
}
for (const v of readJson('votes/index.json')) {
  // counts the source does not record (a vote by show of hands) are left out, never shown as "?"
  const counts = [
    [v.for, 'for'],
    [v.against, 'against'],
    [v.abstain, v.abstain === 1 ? 'abstention' : 'abstentions'],
  ].filter(([k]) => k != null);
  const result = counts.length
    ? `${counts.map(([k, label]) => `${k} ${label}`).join(', ')}.`
    : `${v.outcome_note ?? `${v.kind_label}.`} No vote counts are recorded.`;
  // the date tells apart votes of the same title (a motion to reject on a file, voted twice)
  page(`votes/${segment(v.id)}`, v.display_title, `European Parliament vote of ${formatDate(v.date)}: ${result}`, formatDate(v.date), '', {
    lastmod: changedOn(v.date),
  });
  n++;
}
for (const m of readJson('people/meps.json')) {
  page(`people/meps/${segment(m.id)}`, m.name, `${m.active ? 'Member' : 'Former Member'} of the European Parliament elected in ${inCountry(m.country)}.`);
  n++;
}
for (const g of readJson('people/groups.json')) {
  // as the page's header puts it (Group.tsx): the non-attached members form no group, and a group has no vote of its own
  const terms = termYears(g.terms);
  const description =
    g.id === 'ni'
      ? `Members of the European Parliament who belong to no political group${terms ? ` (${terms})` : ''}: by country and national party, and how they voted.`
      : g.active
        ? `Political group in the European Parliament${terms ? ` (${terms})` : ''}: its members by country and national party, and how they voted.`
        : `Political group in the European Parliament${terms ? ` in the ${terms}` : ''}, not a group in the current term: how its members voted.`;
  page(`people/groups/${segment(g.id)}`, `${g.code} – ${g.name}`, description);
  n++;
}
const partyDir = join(DIST, 'data', 'people', 'parties');
for (const f of existsSync(partyDir) ? readdirSync(partyDir).filter((x) => x.endsWith('.json')).sort() : []) {
  const p = JSON.parse(readFileSync(join(partyDir, f), 'utf8'));
  const term = termYears(p.terms);
  page(
    `people/parties/${segment(p.id)}`,
    partyTitle(p),
    `National party from ${countryName(p.country)} as recorded in the European Parliament's membership data${term ? ` (record for the ${term})` : ''}: its MEPs and political groups.`,
  );
  n++;
}
for (const c of readJson('countries/index.json')) {
  // its own Atom feed (data/feeds/countries/<code>.xml), as the page announces it once loaded (src/pages/Country.tsx)
  const countryFeed = `<link rel="alternate" type="application/atom+xml" id="page-feed" title="${esc(`${c.name}: applying EU directives (Atom)`)}" href="${esc(`${BASE}data/feeds/countries/${encodeURIComponent(c.code)}.xml`)}" />`;
  page(`countries/${segment(c.code)}`, c.name, `${c.name} in the EU: MEPs, Council votes and implementation of EU law.`, undefined, countryFeed);
  n++;
}
// Former topic addresses (/topics/<slug>/, now /legislation/?topic=<slug>): a page with status 200 that redirects without
// a script (relative, so it holds under any base path), points search engines at the new address and is not indexed
// itself. The app redirects these addresses too (App.tsx TopicRedirect), for one opened from the 404.html fallback.
// (the shell's CSP and icon: without an icon link a browser asks for /favicon.ico, outside the site)
const csp = /<meta http-equiv="Content-Security-Policy"[^>]*>/.exec(shell)?.[0];
const icon = /<link rel="icon"[^>]*>/.exec(shell)?.[0];
if (!csp || !icon) throw new Error('prerender-routes: no Content-Security-Policy meta or icon link in dist/index.html');
for (const t of readJson('topics.json')) {
  const target = `legislation/?topic=${encodeURIComponent(t.slug)}`;
  const out = join(DIST, 'topics', segment(t.slug), 'index.html');
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(
    out,
    `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    ${csp}
    ${icon}
    <meta name="robots" content="noindex" />
    <title>${esc(documentTitle(`${t.label} – Legislation`))}</title>${SITE_URL ? `
    <link rel="canonical" href="${esc(SITE_URL + target)}" />` : ''}
    <meta http-equiv="refresh" content="0; url=../../${esc(target)}" />
  </head>
  <body>
    <p>This page has moved: <a href="../../${esc(target)}">${esc(t.label)} – Legislation</a>.</p>
  </body>
</html>
`,
  );
  n++;
}
// the home page keeps its address; the fallback for unknown addresses (served with status 404) is not for search engines
writeFileSync(join(DIST, 'index.html'), withHead(shell, canonical(''), socialTags(shellTitle, shellDescription, pageUrl(''), image)));
writeFileSync(join(DIST, '404.html'), withHead(shell, '<meta name="robots" content="noindex" />', socialTags(shellTitle, shellDescription, null, image)));
// The sitemap, whose addresses must be absolute (only with SITE_URL), and robots.txt, which names it. Crawlers read
// robots.txt only at the root of a host, so under a project site's path it applies once the site has a domain of its own
// (docs/DEPLOYMENT.md, "Search engines and link previews"). A sitemap of an earlier run is removed first.
for (const f of readdirSync(DIST)) if (/^sitemap(-\d+)?\.xml$/.test(f)) rmSync(join(DIST, f));
const sitemaps = SITE_URL ? sitemapFiles(listed.map(([route, lastmod]) => ({ loc: pageUrl(route), lastmod })), SITE_URL) : [];
for (const { name, xml } of sitemaps) writeFileSync(join(DIST, name), xml);
writeFileSync(join(DIST, 'robots.txt'), robotsTxt(SITE_URL && `${SITE_URL}sitemap.xml`));
const listing = SITE_URL ? `${listed.length} pages in ${sitemaps.length > 1 ? `${sitemaps.length - 1} sitemaps and their index` : 'sitemap.xml'}` : 'no sitemap (no SITE_URL)';
console.log(`prerender-routes: wrote ${n} route shells + 404.html; ${listing}; robots.txt`);
