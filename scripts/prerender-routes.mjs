// Post-build: make every known route directly loadable on GitHub Pages (HTTP 200, no server rewrites).
// Writes dist/<route>/index.html copies of the SPA shell with a route-specific <title> and description,
// plus dist/404.html as a fallback for anything else. Reads route lists from dist/data/*.json (party pages from
// the party files themselves: two parties without a recorded name are left out of parties.json).
// SITE_URL (the Pages URL, as the data build takes it for the Atom feeds) gives each page its canonical address,
// <SITE_URL><route>/; without it a page has none (a local or fork build must not point at another host).
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const DIST = 'dist';
// (the home page's canonical link is written into dist/index.html below: a second run starts without it)
const shell = readFileSync(join(DIST, 'index.html'), 'utf8').replace(/\s*<link rel="canonical"[^>]*>/g, '');
const SITE = 'EU Legislative Intelligence';
const SITE_URL = process.env.SITE_URL ? `${process.env.SITE_URL.replace(/\/+$/, '')}/` : null;

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
// "20 Nov 2019" (src/lib/format.ts formatDate)
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const formatDate = (d) => {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  return `${day} ${MONTHS[m - 1]} ${y}`;
};
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
const withHead = (html, tag) => (tag ? html.replace('</head>', () => `  ${tag}\n  </head>`) : html);
const canonical = (route) => (SITE_URL ? `<link rel="canonical" href="${esc(SITE_URL + (route ? `${route.split('/').map(encodeURIComponent).join('/')}/` : ''))}" />` : '');

function page(route, title, description, qualifier) {
  let html = shell.replace(/<title>[^<]*<\/title>/, () => `<title>${esc(documentTitle(title, qualifier))}</title>`);
  if (description) {
    html = html.replace(/<meta name="description" content="[^"]*"\s*\/?>/, () => `<meta name="description" content="${esc(description)}" />`);
  }
  html = withHead(html, canonical(route));
  const out = join(DIST, route, 'index.html');
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, html);
}

const routes = [
  ['legislation', 'Legislation', 'Search and filter EU legislative files: proposals, adopted laws and their status.'],
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

let n = routes.length;
for (const d of readJson('dossiers/index.json')) {
  // the procedure reference tells apart files of the same title (Energy performance of buildings: 2021/0426(COD), 2016/0381(COD))
  page(`legislation/${d.id}`, d.title, d.short || `${d.ref}: ${d.status_label}.${d.official_title ? ` ${d.official_title}` : ''}`.slice(0, 300), d.ref);
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
  page(`votes/${v.id}`, v.display_title, `European Parliament vote of ${formatDate(v.date)}: ${result}`, formatDate(v.date));
  n++;
}
for (const m of readJson('people/meps.json')) {
  page(`people/meps/${m.id}`, m.name, `${m.active ? 'Member' : 'Former Member'} of the European Parliament elected in ${inCountry(m.country)}.`);
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
  page(`people/groups/${g.id}`, `${g.code} – ${g.name}`, description);
  n++;
}
const partyDir = join(DIST, 'data', 'people', 'parties');
for (const f of existsSync(partyDir) ? readdirSync(partyDir).filter((x) => x.endsWith('.json')).sort() : []) {
  const p = JSON.parse(readFileSync(join(partyDir, f), 'utf8'));
  const term = termYears(p.terms);
  page(
    `people/parties/${p.id}`,
    partyTitle(p),
    `National party from ${countryName(p.country)} as recorded in the European Parliament's membership data${term ? ` (record for the ${term})` : ''}: its MEPs and political groups.`,
  );
  n++;
}
for (const c of readJson('countries/index.json')) {
  page(`countries/${c.code}`, c.name, `${c.name} in the EU: MEPs, Council votes and implementation of EU law.`);
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
  const out = join(DIST, 'topics', t.slug, 'index.html');
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
writeFileSync(join(DIST, 'index.html'), withHead(shell, canonical('')));
writeFileSync(join(DIST, '404.html'), withHead(shell, '<meta name="robots" content="noindex" />'));
console.log(`prerender-routes: wrote ${n} route shells + 404.html`);
