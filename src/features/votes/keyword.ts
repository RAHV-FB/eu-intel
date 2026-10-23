/**
 * Keyword matching for the votes list. Words are matched whole (accent- and case-insensitive, singular or
 * plural), so "gaza" no longer matches a rapporteur called Pagazaurtundúa. A vote linked to a legislative
 * file also matches when the site search finds that file, so its common names work: "AI Act" finds the
 * votes on the Artificial Intelligence Act. References are matched whole: "2023/0134(COD)" or "2023/2116"
 * against the vote's procedure and file references (and acts identified by the number), "A9-0050/2024"
 * against the session document in its label.
 */
import type { EpVoteSummary } from '../../types/data';
import {
  dossierScores,
  hasWord,
  keywordTokens,
  normalize,
  typedAbbreviations,
  wordSet,
  type SearchEngine,
} from '../../lib/search';

// procedure references and act numbers ("2023/0134(COD)", "2016/0224A", "2023/2116", "376/2014"), session
// documents ("A9-0050/2024"), as they read once normalised
const REF_RE = /(?<![\w/-])(?:[abc]\d{1,2}-\d{4}\/\d{4}|\d{4}\/\d{1,4}[a-z]?(?:\s*\([a-z]{3}\))?|\d{1,4}\/\d{4})(?![\w/-])/g;
const DOC_RE = /\b[ABC]\d{1,2}-\d{4}\/\d{4}\b/gi;
// act numbers cited in a title: "Regulation (EU) 2016/679", "Regulation (EU) No 1316/2013"
const TITLE_NUMBER_RE = /(?<![\w/-])\d{1,4}\/\d{1,4}(?![\w/-])/g;
// the words of an act citation around a number ("Directive (EU) 2022/2464", "Reg 2016/679")
const CITATION_WORDS = new Set([
  'regulation', 'reg', 'directive', 'decision', 'implementing', 'delegated', 'commission', 'council', 'eu', 'ec', 'eec',
  'euratom', 'no', 'nr', 'celex',
]); // prettier-ignore

/** The reference keys of a vote: its procedure and file references, with and without the procedure type and
 * the letter of a split procedure, the session documents in its label and the act numbers its titles cite. */
function refKeys(v: EpVoteSummary): string[] {
  const out: string[] = [];
  for (const r of [v.procedure_ref, v.dossier_ref]) {
    const m = r ? /^(\d{4}\/\d{4})([a-z]?)(\([a-z]{3}\))?$/.exec(normalize(r).replace(/\s+/g, '')) : null;
    if (m) out.push(`${m[1]}${m[2]}${m[3] ?? ''}`, `${m[1]}${m[2]}`, m[1]);
  }
  for (const d of v.title.match(DOC_RE) ?? []) out.push(normalize(d));
  for (const t of [v.display_title, v.title, v.subject]) {
    if (t) out.push(...(normalize(t).match(TITLE_NUMBER_RE) ?? []));
  }
  return out;
}

export function voteHaystacks(votes: EpVoteSummary[]): Map<string, Set<string>> {
  const m = new Map<string, Set<string>>();
  for (const v of votes) {
    const words = wordSet(v.display_title, v.title, v.subject, v.dossier_ref, v.procedure_ref, v.id);
    for (const k of refKeys(v)) words.add(k);
    m.set(v.id, words);
  }
  return m;
}

export interface VoteMatches {
  ids: Set<string>;
  /** Nothing matched whole words, so these votes have words in their titles that start with those typed. */
  partial: boolean;
}

/**
 * The votes matching `q`, or null when the query has no words. If nothing matches whole words, words of 4+
 * letters that are not abbreviations may be the start of a longer word in the vote's title or subject
 * ("artific" -> "artificial"), as on the search page; never in Parliament's raw label, whose rapporteur names
 * would match ("PiS" is not "Pisapia").
 */
export function matchVoteDetails(
  votes: EpVoteSummary[],
  haystacks: Map<string, Set<string>>,
  q: string,
  engine: SearchEngine | null,
): VoteMatches | null {
  const n = normalize(q).replace(/(\d)\/(?:eu|ec|eec|euratom)\b/g, '$1 '); // "No 376/2014/EU" cites 376/2014
  const refs = [...n.matchAll(REF_RE)].map((m) => m[0].replace(/\s+/g, ''));
  const rest = refs.length ? n.replace(REF_RE, ' ') : q;
  const tokens = keywordTokens(rest).filter((t) => !refs.length || !CITATION_WORDS.has(t));
  if (!tokens.length && !refs.length) return null;
  const none = new Map<string, number>();
  // a reference matches the vote's own references, or a file that the number identifies (an act number)
  const refFiles = refs.map((r) => (engine ? dossierScores(engine, r, { identifiers: true }) : none));
  const refsMatch = (v: EpVoteSummary, words: Set<string> | undefined) =>
    refs.every((r, k) => words?.has(r) || (v.dossier_id != null && refFiles[k].has(v.dossier_id)));
  const abbreviations = typedAbbreviations(q);
  const pass = (prefix: boolean, viaFiles: Map<string, number>) => {
    const out = new Set<string>();
    for (const v of votes) {
      const words = haystacks.get(v.id);
      if (!refsMatch(v, words)) continue;
      if (!tokens.length) {
        out.add(v.id);
        continue;
      }
      const titled = prefix ? wordSet(v.display_title, v.subject) : null;
      const startsWord = (t: string) => titled !== null && t.length >= 4 && !abbreviations.has(t) && hasWord(titled, t, true);
      const has = (t: string) => (words && hasWord(words, t)) || startsWord(t);
      if (tokens.every(has) || (v.dossier_id && viaFiles.has(v.dossier_id))) out.add(v.id);
    }
    return out;
  };
  const words = !tokens.length ? '' : refs.length ? tokens.join(' ') : q;
  const exact = pass(false, engine && words ? dossierScores(engine, words, { wholeWords: true }) : none);
  if (exact.size || !tokens.length) return { ids: exact, partial: false };
  // through the linked file only when every word may match the start of a longer word ("PiS" may not)
  const loosely = tokens.every((t) => t.length >= 4 && !abbreviations.has(t));
  const loose = pass(true, engine && loosely ? dossierScores(engine, words) : none);
  return { ids: loose, partial: loose.size > 0 };
}

/** Ids of the votes matching `q`, or null when the query has no words (see `matchVoteDetails`). */
export function matchVotes(
  votes: EpVoteSummary[],
  haystacks: Map<string, Set<string>>,
  q: string,
  engine: SearchEngine | null,
): Set<string> | null {
  return matchVoteDetails(votes, haystacks, q, engine)?.ids ?? null;
}
