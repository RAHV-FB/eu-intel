// What the prerendered pages (scripts/prerender-routes.mjs) give link previews, search engines and readers without
// JavaScript: Open Graph and Twitter tags; a legislative file's key facts in a <noscript> block and its act as schema.org
// Legislation (JSON-LD); the sitemap and robots.txt.
//
// The key facts state only what the file's page states, in its words and from the same data (src/pages/Dossier.tsx,
// src/features/legislation/dossier/Summary.tsx), as the page reads on the day the data was built: the texts of the data
// are written as of that day (src/lib/format.ts asOfToday leaves them unchanged then). A <noscript> block is not rendered
// when scripts run, so a reader with JavaScript never sees it, not even before the app has loaded. The JSON-LD is a data
// block (<script type="application/ld+json">): a browser never executes it, so the Content-Security-Policy does not apply.

import { readFileSync } from 'node:fs';

export const SITE = 'EU Legislative Intelligence';
/** The language of the site's text (British English, as the dates and numbers it formats: en-GB). */
export const LOCALE = 'en_GB';

export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// "20 Nov 2019", or "20 November 2019" (src/lib/format.ts formatDate)
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export function formatDate(d, long = false) {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  if (!y || !m) return d;
  const mon = (long ? MONTHS_LONG : MONTHS)[m - 1];
  return day ? `${day} ${mon} ${y}` : `${mon} ${y}`;
}

// ------------------------------------------------------------------ link previews

/**
 * Open Graph and Twitter tags of a page: a link preview shows the page's own title and description (plain text, escaped
 * here). `url`, the page's absolute address, only when the build knows it (SITE_URL), as for its canonical link.
 */
export function socialTags(title, description, url) {
  return [
    ['property', 'og:type', 'website'],
    ['property', 'og:site_name', SITE],
    ['property', 'og:locale', LOCALE],
    ['property', 'og:title', title],
    ['property', 'og:description', description],
    ...(url ? [['property', 'og:url', url]] : []),
    ['name', 'twitter:card', 'summary'],
  ]
    .map(([attr, key, value]) => `<meta ${attr}="${key}" content="${esc(value)}" />`)
    .join('\n    ');
}

// ------------------------------------------------------------------ as the file's page states it

// src/lib/format.ts safeUrl: http(s) links only; the official hosts that serve http addresses over https are linked so
const HTTPS_HOSTS = new Set(['www.europarl.europa.eu', 'data.europa.eu']);
function safeUrl(u) {
  if (!u) return undefined;
  try {
    const url = new URL(u);
    if (url.protocol === 'http:' && url.port === '' && HTTPS_HOSTS.has(url.hostname)) url.protocol = 'https:';
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}
/** A flat object of strings in the app's source ("const NAME: … = { key: 'Value', 'two words': 'Value' }"), read as the
 * prerender reads COUNTRY_NAMES, so that the pages without JavaScript name things as the app does. */
function appLabels(file, name, min) {
  const source = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
  const body = new RegExp(`\\b${name}\\b[^=]*=\\s*\\{([^}]*)\\}`).exec(source)?.[1] ?? '';
  const labels = Object.fromEntries([...body.matchAll(/(?:'([^']+)'|([A-Za-z][\w-]*)):\s*'([^']+)'/g)].map((m) => [m[1] ?? m[2], m[3]]));
  if (Object.keys(labels).length < min) throw new Error(`scripts/seo.mjs: could not read ${name} from ${file}`);
  return labels;
}
// src/features/legislation/labels.ts
const EURLEX_CELEX = (celex) => `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:${encodeURIComponent(celex)}`;
const INSTRUMENT_LABEL = appLabels('src/features/legislation/labels.ts', 'INSTRUMENT_LABEL', 5);
const ADOPTED_STAGES = new Set(['adopted', 'published', 'in_force', 'takes_effect_on_notification', 'no_longer_in_force']); // STAGE_GROUPS.law
// src/components/ui.tsx institutionLabel, BasisNote
const INSTITUTION_LABEL = appLabels('src/components/ui.tsx', 'INSTITUTION_LABEL', 9);
const institutionLabel = (i) => INSTITUTION_LABEL[i] ?? i;
const basisNote = (basis) =>
  basis === 'source' ? '' : ` <span class="basis">${basis === 'derived' ? 'Derived from recorded events' : 'Not determinable'}</span>`;

// Summary.tsx regulationNextStep: an in-force regulation's next step led by what is still to come
const APPLIES_DIRECTLY = /^The regulation (applies directly[^;]*); no national transposition is needed\.(.*)$/s;
const LATER_DATES = /^Later dates? from which \(parts of\) the act apply: (.+)\.$/;
function regulationNextStep(text) {
  const m = APPLIES_DIRECTLY.exec(text);
  if (!m) return text;
  const rest = m[2].trim();
  const directly = `As a regulation, it ${m[1]}; no national transposition is needed.`;
  if (!rest) return `No further step in the procedure. ${directly}`;
  const dates = LATER_DATES.exec(rest)?.[1];
  return dates ? `Provisions of the act start to apply on ${dates}. ${directly}` : text;
}

const splitParts = (d) => d.related.filter((r) => r.relation === 'Split into');
// Summary.tsx commissionProposal
const commissionProposal = (d) => d.documents.find((doc) => doc.kind === 'proposal' && /^COM\(/i.test(doc.id) && safeUrl(doc.url));

const time = (date, long = false) => `<time datetime="${esc(date)}">${esc(formatDate(date, long))}</time>`;
// ExtLink: the text alone when the address is not a web link
const link = (href, html) => {
  const url = safeUrl(href);
  return url ? `<a href="${esc(url)}">${html}</a>` : html;
};
/** Summary.tsx ExplanationText: a status explanation or next step, with the acts it names (the repealing act) linked, each
 * once: to its file on this site, else to EUR-Lex. */
function explained(text, acts, base) {
  const named = [...(acts ?? [])].filter((a) => a.label).sort((a, b) => b.label.length - a.label.length);
  if (!named.length) return esc(text);
  const pattern = new RegExp(`(${named.map((a) => a.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`);
  const linked = new Set();
  return text
    .split(pattern)
    .map((part) => {
      const a = named.find((x) => x.label === part);
      if (!a || linked.has(a.label)) return esc(part);
      linked.add(a.label);
      return a.dossier ? `<a href="${esc(`${base}legislation/${encodeURIComponent(a.dossier)}/`)}">${esc(part)}</a>` : link(a.url, esc(part));
    })
    .join('');
}

// [term (text), ...descriptions (HTML)]
const dl = (rows, pad) =>
  `${pad}<dl>\n${rows.map(([term, ...dds]) => `${pad}  <dt>${esc(term)}</dt>\n${dds.map((x) => `${pad}  <dd>${x}</dd>\n`).join('')}`).join('')}${pad}</dl>\n`;

/** Summary.tsx NextStep: the next procedural step when the records establish one, else the next date fixed in law. */
function nextStep(d, today, base) {
  const ns = d.next_step;
  if (splitParts(d).length) return ['<p>None on this file: each separate file listed above has its own next step.</p>'];
  if (ns.basis === 'unknown') {
    // the build marks a step dated in the law "scheduled" while its date is ahead: as on the page, on the build's date
    const sched = d.timeline.find((e) => e.state === 'scheduled' && e.date >= today);
    if (sched)
      return [`<p>${time(sched.date, true)}</p>`, `<p>${esc(sched.title)}</p>`, `<p>Date fixed in the law (${esc(institutionLabel(sched.institution))})</p>`];
    return [`<p>${esc(ns.text.startsWith('Not determined:') ? ns.text : 'No next step is recorded in the official sources.')}</p>`];
  }
  return [
    `<p>${explained(regulationNextStep(ns.text), d.status.named_acts, base)}${basisNote(ns.basis)}</p>`,
    ...(ns.institution ? [`<p>${esc(institutionLabel(ns.institution))}</p>`] : []),
  ];
}

const DATE_LABELS = [
  'Entry into force',
  'Takes effect',
  'Rules apply from',
  'Some provisions apply from',
  'Other provisions apply from',
  'National transposition deadline',
  'Transposition deadline for specific provisions',
  'Application date for national measures',
];
/**
 * Summary.tsx KeyDates, "When it applies": the dates EUR-Lex records for the act, by what they are, with what the page
 * says of each; the labels without a tense ("Rules apply from", as the page names a step without a date), since the
 * dates are read after the build too. A date EUR-Lex records for after the act's validity ended is left out.
 */
function applicationRows(app) {
  const groups = new Map();
  const ended = new Set(app.after_end_of_validity ?? []);
  const put = (label, item) => {
    if (item.date && ended.has(item.date)) return;
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(item);
  };
  if (app.entry_into_force) put('Entry into force', { date: app.entry_into_force });
  else if (app.entry_into_force_pending)
    put('Entry into force', {
      when: 'Not yet',
      note: `EUR-Lex records no date. ${app.entry_into_force_condition ?? 'The act enters into force once a condition it sets is met.'}`,
    });
  else if (app.effect_on_notification)
    put('Takes effect', {
      when: 'Not recorded',
      note: 'On notification to those to whom the decision is addressed, according to EUR-Lex, which does not record the date of notification.',
    });
  const unrecorded = (partial) => app.application_unrecorded?.find((x) => x.partial === partial);
  const refersTo = (articles) => (articles.length ? ` (it refers to ${articles.join(', ')})` : '');
  const plain = (ds) => [...new Set(ds)].sort().map((date) => ({ date }));
  const noGeneral = unrecorded(false);
  const noPartial = unrecorded(true);
  if (app.application_detail?.length) {
    for (const x of app.application_detail)
      put(x.partial ? 'Some provisions apply from' : 'Rules apply from', { date: x.date, note: x.provisions ?? undefined });
  } else if (app.application_dates.length || app.partial_on_entry_into_force || noGeneral || noPartial) {
    const partialSet = new Set(app.partial_application_dates ?? []);
    const general = app.application_dates.filter((x) => !partialSet.has(x));
    const partial = app.application_dates.filter((x) => partialSet.has(x));
    const onEif = app.partial_on_entry_into_force && app.entry_into_force ? [{ date: app.entry_into_force, note: 'On entry into force' }] : [];
    for (const it of plain(general)) put('Rules apply from', it);
    if (!general.length && noGeneral) put('Rules apply from', { when: 'Not recorded', note: `EUR-Lex gives no date${refersTo(noGeneral.articles)}.` });
    for (const it of [...onEif, ...plain(partial)]) put('Some provisions apply from', it);
    if (noPartial) put('Some provisions apply from', { when: 'Not recorded', note: `EUR-Lex gives no date for some provisions${refersTo(noPartial.articles)}.` });
    if (onEif.length && !app.application_dates.length && !noGeneral)
      put('Other provisions apply from', { when: 'Not recorded', note: 'EUR-Lex gives no date.' });
  }
  // a directive's transposition dates (Summary.tsx transpositionDates; data without the classification counts as deadlines)
  const tr = app.transposition ?? app.transposition_deadlines.map((date, i) => ({ date, kind: i ? 'further_deadline' : 'deadline', articles: [] }));
  for (const [kind, label] of [
    ['deadline', 'National transposition deadline'],
    ['further_deadline', 'Transposition deadline for specific provisions'],
    ['application', 'Application date for national measures'],
  ])
    for (const x of tr.filter((t) => t.kind === kind)) put(label, { date: x.date, note: [x.articles.join(', '), x.exceptions].filter(Boolean).join('. ') || undefined });
  // in this order, and within each the dated steps in time order, then those without a date
  return [...groups].sort(([a], [b]) => DATE_LABELS.indexOf(a) - DATE_LABELS.indexOf(b)).map(([label, items]) => [
    label,
    ...[...items]
      .sort((a, b) => (a.date ? 0 : 1) - (b.date ? 0 : 1) || (a.date ?? '').localeCompare(b.date ?? ''))
      .map((it) => (it.date ? `${time(it.date)}${it.note ? `: ${esc(it.note)}` : ''}` : `${esc(it.when)}. ${esc(it.note)}`)),
  ]);
}

/**
 * A legislative file's key facts, for readers and crawlers without JavaScript: its title and other names, its status,
 * the next step, the procedure, the key dates (proposal, adoption, publication, entry into force, application), the
 * act with its EUR-Lex link and the official records. `base`: the site's base path; `today`: the build's date (the
 * date the data's texts are written for); `dataNote`: how current the data is, as the footer says it.
 * Returns the inside of the page's <noscript> block, ending with `notice` (the site's note on JavaScript).
 */
export function keyFacts(d, { base, today, dataNote, notice }) {
  const pad = '        ';
  const parts = splitParts(d);
  const act = d.acts[0];
  let out = `${pad}<h1>${esc(d.title)}</h1>\n`;
  // Dossier.tsx KnownAs: "Regulation (EU) 2022/2555 · also known as NIS 2 Directive · part of the Pact on …"
  const k = d.known_as;
  if (k) {
    const names = [...k.acts];
    if (k.names.length) names.push(`${names.length ? 'also' : 'Also'} known as ${k.names.join(', ')}`);
    if (k.part_of?.length) names.push(`${names.length ? 'part' : 'Part'} of the ${k.part_of[0]}`);
    out += `${pad}<p>${esc(names.join(' · '))}</p>\n`;
  }
  // the status line: the label, and since when (a decision taking effect on notification: its publication)
  const since = d.status.since ? ` ${d.status.stage === 'takes_effect_on_notification' ? 'published' : 'since'} ${time(d.status.since, true)}` : '';
  out += `${pad}<p><strong>${esc(d.status.label)}</strong>${since}</p>\n`;
  if (parts.length) {
    out += `${pad}<h2>This proposal was split into</h2>\n${pad}<ul>\n`;
    for (const r of parts)
      out += `${pad}  <li><a href="${esc(`${base}legislation/${encodeURIComponent(r.id)}/`)}">${r.ref ? `${esc(r.ref)} ` : ''}${esc(r.title)}</a>${r.status_label ? ` (${esc(r.status_label)})` : ''}</li>\n`;
    out += `${pad}</ul>\n`;
  }
  out += dl(
    [
      [
        'Current status',
        parts.length
          ? '<p>This file was split into separate procedures, listed above; each has its own status.</p>'
          : `<p>${explained(d.status.explanation, d.status.named_acts, base)}${basisNote(d.status.basis)}</p>`,
      ],
      ['What happens next', nextStep(d, today, base).join('')],
    ],
    pad,
  );
  // the page's "Key facts": Dossier.tsx dz-keyfacts and dz-official-links
  const facts = [['Procedure', esc(d.ref)]];
  const instrument =
    d.instrument && d.instrument !== 'other'
      ? [`${INSTRUMENT_LABEL[d.instrument]}${d.acts.some((a) => a.act_type === d.instrument) ? '' : ' (as proposed)'}`]
      : [];
  facts.push(['Type', esc(d.type_label), ...instrument.map((x) => esc(x))]);
  if (d.started) facts.push([`Proposed${d.started_from_parts ? ' (as recorded for its parts)' : ''}`, time(d.started)]);
  if (d.adopted) facts.push(['Adopted', time(d.adopted)]);
  if (d.published) facts.push(['Published in the Official Journal', time(d.published)]);
  const actUrl = act && (act.eurlex_url || EURLEX_CELEX(act.celex));
  if (act) facts.push(['CELEX', link(actUrl, esc(act.celex))]);
  out += `${pad}<h2>Key facts</h2>\n${dl(facts, pad)}`;
  const proposal = commissionProposal(d);
  const official = [
    ...(d.oeil_url ? [link(d.oeil_url, 'Procedure file (Legislative Observatory)')] : []),
    ...(proposal ? [link(proposal.url, `Commission proposal (${esc(proposal.id)})`)] : []),
    ...(act ? [link(actUrl, 'Legal text (EUR-Lex)')] : []),
  ];
  if (official.length) out += `${pad}<ul>\n${official.map((x) => `${pad}  <li>${x}</li>\n`).join('')}${pad}</ul>\n`;
  if (ADOPTED_STAGES.has(d.stage) && d.application) {
    const rows = applicationRows(d.application);
    out += `${pad}<h2>When it applies</h2>\n${rows.length ? dl(rows, pad) : `${pad}<p>No application dates are recorded for this act in EUR-Lex.</p>\n`}`;
  }
  if (dataNote) out += `${pad}<p>${esc(dataNote)}.</p>\n`;
  return `${out}${pad}<p>${notice}</p>\n`;
}

// ------------------------------------------------------------------ structured data

// schema.org LegalForceStatus, from the status the page gives the file (not EUR-Lex's own flag, which the page shows
// apart: it can mark an act in force before the date it enters into force); none where the status does not say
const LEGAL_FORCE = { in_force: 'InForce', adopted: 'NotInForce', published: 'NotInForce', no_longer_in_force: 'NotInForce' };

/**
 * The file's act (the first, which the page's key facts give) as schema.org Legislation (https://schema.org/Legislation),
 * with only what the page states of it: its title, number and names, CELEX number, type, date, publication, legal force,
 * EUR-Lex page and ELI. `pageUrl`: the page's absolute address, if known. '' for a file without an act.
 */
export function legislationJsonLd(d, pageUrl) {
  const a = d.acts[0];
  if (!a) return '';
  const force = LEGAL_FORCE[d.status.stage];
  // the names the page gives the act: its number and the file's other names, when the file has no other act
  const names = d.acts.length === 1 && d.known_as ? [...d.known_as.acts, ...d.known_as.names] : [];
  const ld = {
    '@context': 'https://schema.org',
    '@type': 'Legislation',
    name: a.title,
    ...(names.length ? { alternateName: names } : {}),
    legislationIdentifier: a.celex,
    ...(a.act_type && a.act_type !== 'other' ? { legislationType: INSTRUMENT_LABEL[a.act_type] } : {}),
    ...(a.date_document ? { legislationDate: a.date_document } : {}),
    ...(a.date_publication ? { datePublished: a.date_publication } : {}),
    ...(force ? { legislationLegalForce: { '@id': `https://schema.org/${force}` } } : {}),
    url: safeUrl(a.eurlex_url) ?? EURLEX_CELEX(a.celex),
    // the ELI as EUR-Lex publishes it (an identifier, "http://data.europa.eu/eli/reg/2024/1689/oj")
    ...(safeUrl(a.eli) ? { sameAs: a.eli } : {}),
    ...(pageUrl ? { mainEntityOfPage: pageUrl } : {}),
  };
  // nothing in the text can end the element or open a comment: "<" is written as its JSON escape
  const json = JSON.stringify(ld).replace(/</g, '\\u003c');
  return `<script type="application/ld+json">${json}</script>`;
}

// ------------------------------------------------------------------ sitemap and robots.txt

/** The limits of one sitemap file (sitemaps.org): beyond either, the URLs go into several files and an index. */
export const SITEMAP_LIMITS = { urls: 50_000, bytes: 50 * 1024 * 1024 };
const xmlEsc = (s) => esc(s).replace(/'/g, '&apos;');
const XML = '<?xml version="1.0" encoding="UTF-8"?>\n';
const NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"';

/**
 * The sitemap files for `entries` ({ loc, lastmod? }: absolute addresses, and the date of the page's last change where
 * the data gives one): sitemap.xml, or, past a limit, sitemap.xml as the index of sitemap-1.xml, sitemap-2.xml, ….
 * Returns [{ name, xml }].
 */
export function sitemapFiles(entries, siteUrl, limits = SITEMAP_LIMITS) {
  const head = `${XML}<urlset ${NS}>\n`;
  const tail = '</urlset>\n';
  const chunks = [[]];
  let bytes = Buffer.byteLength(head + tail);
  for (const { loc, lastmod } of entries) {
    const line = `  <url><loc>${xmlEsc(loc)}</loc>${lastmod ? `<lastmod>${lastmod}</lastmod>` : ''}</url>\n`;
    const n = Buffer.byteLength(line);
    const last = chunks[chunks.length - 1];
    if (last.length && (last.length >= limits.urls || bytes + n > limits.bytes)) {
      chunks.push([]);
      bytes = Buffer.byteLength(head + tail);
    }
    chunks[chunks.length - 1].push(line);
    bytes += n;
  }
  if (chunks.length === 1) return [{ name: 'sitemap.xml', xml: head + chunks[0].join('') + tail }];
  const files = chunks.map((c, i) => ({ name: `sitemap-${i + 1}.xml`, xml: head + c.join('') + tail }));
  const index = `${XML}<sitemapindex ${NS}>\n${files.map((f) => `  <sitemap><loc>${xmlEsc(siteUrl + f.name)}</loc></sitemap>\n`).join('')}</sitemapindex>\n`;
  return [{ name: 'sitemap.xml', xml: index }, ...files];
}

/** robots.txt: every crawler may read every page; the sitemap's address when there is one (it must be absolute). */
export function robotsTxt(sitemapUrl) {
  return `User-agent: *\nAllow: /\n${sitemapUrl ? `\nSitemap: ${sitemapUrl}\n` : ''}`;
}
