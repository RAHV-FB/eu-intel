/**
 * Keyword search over a country page's directives: by title, by the directive's own number however it is written
 * ("2022/2555", "Directive (EU) 2022/2555", "Directive 2014/35/EU", the CELEX id 32022L2555), and by the names
 * its file is known by ("NIS 2 Directive", also typed "NIS2"). Words are matched whole (singular or plural), as
 * in the rest of the site: "ban" does not find "Urban", "NIS" does not find "mechanisms"; only when no directive
 * has them, words of 4+ letters that are not abbreviations may be the start of a longer word in a title or name.
 * The files the site search finds for the query (by their common names and aliases) match as well, as in the
 * legislation explorer, and are marked when nothing else in the row matches.
 * The same page's infringement cases are searched the same way (matchCases), each with the number and names of the
 * directive it concerns.
 */
import { hasWord, keywordTokens, normalize, typedAbbreviations, wordSet } from '../../lib/search';

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
  /** CELEX ids of rows listed only because the site search finds their file for the query */
  viaSearch: Set<string>;
  /** the number the query names, if any */
  number: string | null;
  /** no row has the query's words whole, so these have words in their titles or names that start with them */
  partial: boolean;
}

export function matchDirectives<T extends DirectiveRow>(rows: T[], query: string, files?: Set<string> | null): DirectiveMatches<T> {
  const needle = normalize(query);
  const number = queryNumber(query);
  const own = new Set<string>();
  const citing = new Set<string>();
  const viaSearch = new Set<string>();
  if (!needle) return { rows, own, citing, viaSearch, number, partial: false };
  // a query naming a regulation or a decision does not name a directive of the same number
  const ownNumber = number && !/\b(?:regulation|decision)s?\b/.test(needle) ? number : null;
  const cited = number ? citationRe(number) : null;
  const tight = /\d/.test(needle) ? compact(needle) : null; // "NIS2" finds "NIS 2 Directive"
  // a query naming a number is matched by that number; other queries by their words
  const tokens = number ? [] : keywordTokens(query);
  const abbreviations = typedAbbreviations(query);
  const pass = (prefix: boolean) => {
    const out: T[] = [];
    for (const r of rows) {
      const hay = normalize([r.title, r.act, ...(r.names ?? []), r.celex].filter(Boolean).join(' '));
      const isOwn = ownNumber !== null && directiveNumber(r.celex) === ownNumber;
      const cites = !isOwn && !!cited?.test(normalize(r.title));
      const words = wordSet(r.title, r.act, ...(r.names ?? []), r.celex);
      const named = prefix ? wordSet(r.title, ...(r.names ?? [])) : null;
      const has = (t: string) => hasWord(words, t) || (named !== null && t.length >= 4 && !abbreviations.has(t) && hasWord(named, t, true));
      const inRow = isOwn || cites || (tokens.length > 0 && tokens.every(has)) || (tight !== null && compact(hay).includes(tight));
      const found = !prefix && !!r.dossier_id && !!files?.has(r.dossier_id);
      if (!inRow && !found) continue;
      out.push(r);
      if (isOwn) own.add(r.celex);
      if (cites) citing.add(r.celex);
      if (!inRow) viaSearch.add(r.celex);
    }
    return out;
  };
  const exact = pass(false);
  if (exact.length || !tokens.length) return { rows: exact, own, citing, viaSearch, number, partial: false };
  const loose = pass(true);
  return { rows: loose, own, citing, viaSearch, number, partial: loose.length > 0 };
}

export interface CaseRow {
  id: string;
  title: string;
  celex?: string | null;
}

/** "2016/679" for an act's CELEX id, whatever its type (32022L2555, 32016R0679, 32019D1234). */
function actNumber(celex: string | null | undefined): string | null {
  const m = /^3(\d{4})[LRD]0*(\d{1,4})$/.exec(celex ?? '');
  return m ? `${m[1]}/${m[2]}` : null;
}

/** The type of act a query names, as the letter of its CELEX id: "Regulation (EU) 2016/679" -> "r". */
function queryType(needle: string): string | null {
  const celex = /(?:^|\s)3\d{4}([lrd])\d/.exec(needle);
  if (celex) return celex[1];
  if (/\bregulations?\b/.test(needle)) return 'r';
  if (/\bdirectives?\b/.test(needle)) return 'l';
  if (/\bdecisions?\b/.test(needle)) return 'd';
  return null;
}

/** A CELEX id a title cites the act by ("Lack of transposition of Directive 32024L1069 by Ireland"). */
const CITED_CELEX = /(?:^|[^\p{L}\p{N}])3(\d{4})[lrd]0*(\d{1,4})(?![\p{L}\p{N}])/gu;

/**
 * Infringement cases matching a query, in the given order: by the words of the case's subject and number, and of
 * the directive it concerns (its number and the names its file is known by, from the page's `directives`: "NIS2"
 * finds a case titled "Lack of transposition of Directive (EU) 2022/2555 …"), matched whole as in matchDirectives.
 * A query naming an act's number finds the cases about that act (by the case's CELEX id) and those whose subject
 * cites it, as year/number or as a CELEX id.
 */
export function matchCases<T extends CaseRow>(rows: T[], query: string, directives: readonly DirectiveRow[] = []): { rows: T[]; partial: boolean } {
  const needle = normalize(query);
  if (!needle) return { rows, partial: false };
  // queryNumber reads a directive's CELEX id; a case may concern a regulation or a decision (32016R0679)
  const otherCelex = /(?:^|\s)3(\d{4})[rd]0*(\d{1,4})(?:\s|$)/.exec(needle);
  const number = queryNumber(query) ?? (otherCelex ? `${otherCelex[1]}/${otherCelex[2]}` : null);
  const type = number ? queryType(needle) : null;
  const cited = number ? citationRe(number) : null;
  const tight = !number && /\d/.test(needle) ? compact(needle) : null; // "NIS2" finds "NIS 2 Directive"
  const tokens = number ? [] : keywordTokens(query);
  const abbreviations = typedAbbreviations(query);
  const byCelex = new Map(directives.map((d) => [d.celex, d]));
  const pass = (prefix: boolean) =>
    rows.filter((r) => {
      const d = r.celex ? byCelex.get(r.celex) : undefined;
      const title = normalize(r.title);
      if (number) {
        // the case's own act has the number: it is that act unless the query names another type of act
        if (actNumber(r.celex) === number) return !type || type === r.celex?.[5]?.toLowerCase();
        if (cited?.test(title)) return true;
        for (const m of title.matchAll(CITED_CELEX)) if (`${m[1]}/${m[2]}` === number) return true;
      }
      const texts = [r.title, r.id, r.celex, d?.act, ...(d?.names ?? []), d?.title];
      if (tight !== null && compact(normalize(texts.filter(Boolean).join(' '))).includes(tight)) return true;
      if (!tokens.length) return false;
      const words = wordSet(...texts);
      const named = prefix ? wordSet(r.title, ...(d?.names ?? []), d?.title) : null;
      return tokens.every((t) => hasWord(words, t) || (named !== null && t.length >= 4 && !abbreviations.has(t) && hasWord(named, t, true)));
    });
  const exact = pass(false);
  if (exact.length || !tokens.length) return { rows: exact, partial: false };
  const loose = pass(true);
  return { rows: loose, partial: loose.length > 0 };
}
