// Post-build: make every known route directly loadable on GitHub Pages (HTTP 200, no server rewrites).
// Writes dist/<route>/index.html copies of the SPA shell with a route-specific <title> and description,
// plus dist/404.html as a fallback for anything else. Reads route lists from dist/data/*.json.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const DIST = 'dist';
const shell = readFileSync(join(DIST, 'index.html'), 'utf8');
const SITE = 'EU Legislative Intelligence';

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const readJson = (p) => {
  const f = join(DIST, 'data', p);
  return existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : [];
};

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
  page(`legislation/${d.id}`, d.title, d.short || `${d.ref}: ${d.status_label}. ${d.official_title}`.slice(0, 300));
  n++;
}
for (const v of readJson('votes/index.json')) {
  page(`votes/${v.id}`, v.display_title, `European Parliament vote of ${v.date}: ${v.for ?? '?'} for, ${v.against ?? '?'} against, ${v.abstain ?? '?'} abstentions.`);
  n++;
}
for (const m of readJson('people/meps.json')) {
  page(`people/meps/${m.id}`, m.name, `Member of the European Parliament for ${m.country}.`);
  n++;
}
for (const g of readJson('people/groups.json')) {
  page(`people/groups/${g.id}`, g.name, null);
  n++;
}
for (const p of readJson('people/parties.json')) {
  page(`people/parties/${p.id}`, p.label, null);
  n++;
}
for (const c of readJson('countries/index.json')) {
  page(`countries/${c.code}`, c.name, `${c.name} in the EU: MEPs, Council votes and implementation of EU law.`);
  n++;
}
writeFileSync(join(DIST, '404.html'), shell);
console.log(`prerender-routes: wrote ${n} route shells + 404.html`);
