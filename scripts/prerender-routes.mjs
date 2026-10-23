// Post-build: make every known route directly loadable on GitHub Pages (HTTP 200, no server rewrites).
// Writes dist/<route>/index.html copies of the SPA shell with a route-specific <title> and description,
// plus dist/404.html as a fallback for anything else. Reads route lists from dist/data/*.json (party pages from
// the party files themselves: two parties without a recorded name are left out of parties.json).
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const DIST = 'dist';
const shell = readFileSync(join(DIST, 'index.html'), 'utf8');
const SITE = 'EU Legislative Intelligence';

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

function page(route, title, description) {
  let html = shell.replace(/<title>[^<]*<\/title>/, `<title>${esc(title ? `${title} – ${SITE}` : SITE)}</title>`);
  if (description) {
    html = html.replace(/<meta name="description" content="[^"]*"\s*\/?>/, `<meta name="description" content="${esc(description)}" />`);
  }
  const out = join(DIST, route, 'index.html');
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, html);
}

const routes = [
  ['legislation', 'Legislation', 'Search and filter EU legislative files: proposals, adopted laws and their status.'],
  ['votes', 'Votes', 'How the European Parliament voted: final votes, close votes, political groups and countries.'],
  ['people', 'People & Parties', 'Members of the European Parliament, political groups and national parties.'],
  ['countries', 'Countries', 'How each EU Member State takes part in EU decisions and applies EU law.'],
  ['how-the-eu-works', 'How the EU Works', 'A plain-language guide to how EU laws are proposed, negotiated, adopted and applied.'],
  ['about', 'About & methodology', 'Data sources, coverage, methodology and limitations.'],
  ['privacy', 'Privacy', 'Privacy notice: no tracking, no cookies, no analytics.'],
  ['following', 'Followed legislation', null],
  ['search', 'Search', null],
];
for (const [r, t, d] of routes) page(r, t, d);

let n = routes.length;
for (const d of readJson('dossiers/index.json')) {
  page(`legislation/${d.id}`, d.title, d.short || `${d.ref}: ${d.status_label}.${d.official_title ? ` ${d.official_title}` : ''}`.slice(0, 300));
  n++;
}
for (const v of readJson('votes/index.json')) {
  // counts the source does not record (a vote by show of hands) are left out, never shown as "?"
  const counts = [
    [v.for, 'for'],
    [v.against, 'against'],
    [v.abstain, 'abstentions'],
  ].filter(([k]) => k != null);
  const result = counts.length
    ? `${counts.map(([k, label]) => `${k} ${label}`).join(', ')}.`
    : `${v.outcome_note ?? `${v.kind_label}.`} No vote counts are recorded.`;
  page(`votes/${v.id}`, v.display_title, `European Parliament vote of ${v.date}: ${result}`);
  n++;
}
for (const m of readJson('people/meps.json')) {
  page(`people/meps/${m.id}`, m.name, `${m.active ? 'Member' : 'Former Member'} of the European Parliament elected in ${inCountry(m.country)}.`);
  n++;
}
for (const g of readJson('people/groups.json')) {
  page(`people/groups/${g.id}`, g.name, null);
  n++;
}
const partyDir = join(DIST, 'data', 'people', 'parties');
for (const f of existsSync(partyDir) ? readdirSync(partyDir).filter((x) => x.endsWith('.json')).sort() : []) {
  const p = JSON.parse(readFileSync(join(partyDir, f), 'utf8'));
  const term = termYears(p.terms);
  page(
    `people/parties/${p.id}`,
    `${p.label} (${countryName(p.country)})`,
    `National party from ${countryName(p.country)} as recorded in the European Parliament's membership data${term ? ` (${term} record)` : ''}: its MEPs and political groups.`,
  );
  n++;
}
for (const c of readJson('countries/index.json')) {
  page(`countries/${c.code}`, c.name, `${c.name} in the EU: MEPs, Council votes and implementation of EU law.`);
  n++;
}
writeFileSync(join(DIST, '404.html'), shell);
console.log(`prerender-routes: wrote ${n} route shells + 404.html`);
