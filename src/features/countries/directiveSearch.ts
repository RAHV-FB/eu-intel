/**
 * Keyword search over a country page's directives: by title, by the directive's own number however it is written
 * ("2022/2555", "Directive (EU) 2022/2555", "Directive 2014/35/EU", the CELEX id 32022L2555), and by the names
 * its file is known by ("NIS 2 Directive", also typed "NIS2"). The files the site search finds for the query (by
 * their common names and aliases) match as well, as in the legislation explorer.
 */
import { normalize } from '../../lib/search';

export interface DirectiveRow {
  celex: string;
  title: string;
  act?: string | null;
  names?: string[];
  dossier_id?: string | null;
}

/** "2022/2555" for a directive's CELEX id (32022L2555); directives are numbered year/number. */
export function directiveNumber(celex: string): string | null {
  const m = /^3(\d{4})L0*(\d{1,4})$/.exec(celex);
  return m ? `${m[1]}/${m[2]}` : null;
}

/** The act number a query names, if any: "Directive (EU) 2022/2555", "2022/2555" or "32022L2555" -> "2022/2555";
 * "Directive 93/13/EEC" -> "1993/13" (directives had two-digit years until 1998). */
export function queryNumber(query: string): string | null {
  const n = normalize(query);
  const celex = /(?:^|\s)3(\d{4})l0*(\d{1,4})(?:\s|$)/.exec(n);
  if (celex) return `${celex[1]}/${celex[2]}`;
  const m = /(?:^|[^\d/])(\d{4}|\d{2})\/0*(\d{1,4})(?:\/[a-z]+)?(?=$|[^\d/])/.exec(n);
  if (!m) return null;
  return `${m[1].length === 2 ? `19${m[1]}` : m[1]}/${m[2]}`;
}

/** The number as a title may cite it: "2022/2555", or "93/13" for a directive of 1993. */
function citationRe(number: string): RegExp {
  const [year, num] = number.split('/');
  const years = Number(year) < 1999 ? `(?:${year}|${year.slice(2)})` : year;
  return new RegExp(`(?:^|[^\\d/])${years}/0*${num}(?=$|[^\\d])`);
}

const compact = (s: string) => s.replace(/[\s.-]+/g, '');

export interface DirectiveMatches<T> {
  /** the matching rows, in the given order */
  rows: T[];
  /** CELEX id of the directive whose own number the query names (to be listed first) */
  own: Set<string>;
  /** CELEX ids of rows whose title cites the number the query names (e.g. an act amending that directive) */
  citing: Set<string>;
  /** the number the query names, if any */
  number: string | null;
}

export function matchDirectives<T extends DirectiveRow>(rows: T[], query: string, files?: Set<string> | null): DirectiveMatches<T> {
  const needle = normalize(query);
  const number = queryNumber(query);
  const own = new Set<string>();
  const citing = new Set<string>();
  if (!needle) return { rows, own, citing, number };
  // a query naming a regulation or a decision does not name a directive of the same number
  const ownNumber = number && !/\b(?:regulation|decision)s?\b/.test(needle) ? number : null;
  const cited = number ? citationRe(number) : null;
  const tight = /\d/.test(needle) ? compact(needle) : null; // "NIS2" finds "NIS 2 Directive"
  const out: T[] = [];
  for (const r of rows) {
    const hay = normalize([r.title, r.act, ...(r.names ?? []), r.celex].filter(Boolean).join(' '));
    const isOwn = ownNumber !== null && directiveNumber(r.celex) === ownNumber;
    const cites = !isOwn && !!cited?.test(normalize(r.title));
    const hit =
      isOwn || cites || hay.includes(needle) || (tight !== null && compact(hay).includes(tight)) || (!!r.dossier_id && !!files?.has(r.dossier_id));
    if (!hit) continue;
    out.push(r);
    if (isOwn) own.add(r.celex);
    if (cites) citing.add(r.celex);
  }
  return { rows: out, own, citing, number };
}
