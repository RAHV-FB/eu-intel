/**
 * Keyword matching for the votes list. Words are matched whole (accent- and case-insensitive, singular or
 * plural), so "gaza" no longer matches a rapporteur called Pagazaurtundúa. A vote linked to a legislative
 * file also matches when the site search finds that file, so its common names work: "AI Act" finds the
 * votes on the Artificial Intelligence Act ("AI Act vote" too: "vote" is not looked for in the file's names); a
 * file the search matches only approximately counts last, and flagged. References are matched whole:
 * "2023/0134(COD)" or "2023/2116" against the vote's procedure and file references (and acts identified by the
 * number), "A9-0050/2024" against the session document in its label; their years and serial numbers are not words
 * of the vote ("discharge 2022" is not a vote on 2024/2022(DEC)). The rapporteurs named in Parliament's label
 * match only as written ("Carlos" is not Carlo Fidanza).
 */
import type { EpVoteSummary } from '../../types/data';
import {
  dossierScores,
  hasWord,
  keywordTokens,
  normalize,
  similarWords,
  typedAbbreviations,
  wordSet,
  words as wordsOf,
  type SearchEngine,
} from '../../lib/search';

// procedure references and act numbers ("2023/0134(COD)", "2016/0224A", also "2016/0224 A" as on the search page,
// "2023/2116", "376/2014"), session documents ("A9-0050/2024"), as they read once normalised
const REF_RE =
  /(?<![\w/-])(?:[abc]\d{1,2}-\d{4}\/\d{4}|\d{4}\/\d{4}\s[a-z](?![\w/-])(?:\s*\([a-z]{3}\))?|\d{4}\/\d{1,4}[a-z]?(?:\s*\([a-z]{3}\))?|\d{1,4}\/\d{4})(?![\w/-])/g;
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

// the rapporteurs after a committee report in Parliament's label: "A9-0197/2020 - Carlo Calenda - Resolution"
const RAPPORTEURS_RE = /\bA\d{1,2}-\d{4}\/\d{4}\s+[-–]\s+(.+?)\s+[-–]\s+/;
// procedure references and session documents in Parliament's label are matched whole (refKeys), never by their year or
// serial number: "discharge 2022" is not 175675, Discharge 2023 on 2024/2022(DEC) labelled "A10-0050/2025 – …"
const LABEL_REF_RE = /\b\d{4}\/\d{4}[A-Z]?(?:\s*\([A-Z]{3}\))?|\b(?:RC-)?[ABC]\d{1,2}[-‐-–−]\d{4}\/\d{4}\b/gi;
// the words of those names are kept with this mark: a name has no singular form ("Carlos" is not "Carlo")
const NAME = '=';
const VOTE_WORDS = new Set(['vote', 'votes', 'voted', 'voting']);

export function voteHaystacks(votes: EpVoteSummary[]): Map<string, Set<string>> {
  const m = new Map<string, Set<string>>();
  for (const v of votes) {
    const names = RAPPORTEURS_RE.exec(v.title)?.[1];
    const label = names ? v.title.replace(RAPPORTEURS_RE, (all, n: string) => all.replace(n, ' ')) : v.title;
    // the vote's references are its reference keys only (refKeys); the vote id stays a word ("166051")
    const words = wordSet(v.display_title, label.replace(LABEL_REF_RE, ' '), v.subject, v.id);
    for (const w of names ? wordsOf(names) : []) words.add(NAME + w);
    for (const k of refKeys(v)) words.add(k);
    m.set(v.id, words);
  }
  return m;
}

const HAYSTACKS = new WeakMap<EpVoteSummary[], Map<string, Set<string>>>();

/** `voteHaystacks` of a loaded vote list, built when first needed and kept for that list (a page opened again, or a
 * search typed again, does not build them again). */
export function voteHaystacksOnce(votes: EpVoteSummary[]): Map<string, Set<string>> {
  let m = HAYSTACKS.get(votes);
  if (!m) HAYSTACKS.set(votes, (m = voteHaystacks(votes)));
  return m;
}

// the words of each vote's title and subject, for the word starts: built once for a vote, when first needed
const TITLED = new WeakMap<EpVoteSummary, Set<string>>();
function titledWords(v: EpVoteSummary): Set<string> {
  let s = TITLED.get(v);
  if (!s) TITLED.set(v, (s = wordSet(v.display_title, v.subject)));
  return s;
}

export interface VoteMatches {
  ids: Set<string>;
  /** Nothing matched whole words, so these votes have words in their titles that start with those typed. */
  partial: boolean;
  /** Nothing matched otherwise, so these are votes on files that the search matches only approximately: with
   * the `similar` words in place of a typed word (typo tolerance: "macro" for "Macron"), or on all but one word. */
  approximate?: boolean;
  similar?: string[];
}

/**
 * The votes matching `q`, or null when the query has no words. If nothing matches whole words, words of 4+
 * letters that are not abbreviations may be the start of a longer word in the vote's title or subject
 * ("artific" -> "artificial"), as on the search page; never in Parliament's raw label, whose rapporteur names
 * would match ("PiS" is not "Pisapia"). A file that the search matches only approximately (a similar word,
 * or all but one word) links its votes only when nothing else matches, and `similar` says so.
 */
export function matchVoteDetails(
  votes: EpVoteSummary[],
  haystacks: Map<string, Set<string>>,
  q: string,
  engine: SearchEngine | null,
): VoteMatches | null {
  let fileIds: Set<string | null | undefined> | null = null;
  const n = normalize(q)
    .replace(/(\d)\/(?:eu|ec|eec|euratom)\b/g, '$1 ') // "No 376/2014/EU" cites 376/2014
    // a file's id as in the site's addresses ("2021-0106", "2016-0282A", "2021 0106") is its procedure number; other
    // pairs of numbers are not ("2021-2027", "2019-2024")
    .replace(/(?<![\w/-])(\d{4})[-\s](\d{4}[a-z]?)(?![\w/-])/g, (all, y: string, num: string) =>
      (fileIds ??= new Set(votes.map((v) => v.dossier_id))).has(`${y}-${num.toUpperCase()}`) ? `${y}/${num}` : all,
    );
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
      const titled = prefix ? titledWords(v) : null;
      const startsWord = (t: string) => titled !== null && t.length >= 4 && !abbreviations.has(t) && hasWord(titled, t, true);
      const has = (t: string) => (words && (hasWord(words, t) || words.has(NAME + t))) || startsWord(t);
      if (tokens.every(has) || (v.dossier_id && viaFiles.has(v.dossier_id))) out.add(v.id);
    }
    return out;
  };
  // the linked file: words naming what this page lists say nothing about it ("AI Act vote" is a vote on the AI Act)
  const fileTokens = tokens.some((t) => !VOTE_WORDS.has(t)) ? tokens.filter((t) => !VOTE_WORDS.has(t)) : tokens;
  const words = !tokens.length ? '' : refs.length || fileTokens.length < tokens.length ? fileTokens.join(' ') : q;
  const partial = new Set<string>();
  const similar = new Map<string, string[]>();
  const files = engine && words ? dossierScores(engine, words, { partial, approximate: similar }) : none;
  const only = (keep: (id: string) => boolean) => new Map([...files].filter(([id]) => keep(id)));
  const exact = pass(false, only((id) => !partial.has(id) && !similar.has(id)));
  if (exact.size || !tokens.length) return { ids: exact, partial: false };
  // through the linked file only when every word may match the start of a longer word ("PiS" may not)
  const loosely = tokens.every((t) => t.length >= 4 && !abbreviations.has(t));
  const loose = pass(true, loosely ? only((id) => !similar.has(id)) : none);
  if (loose.size) return { ids: loose, partial: true };
  // last, the votes on files the search matches only approximately ("Macron": "macro-financial"; "AI Act vote":
  // the AI Act, on all but one word)
  const close = pass(false, only((id) => similar.has(id)));
  if (!close.size) return { ids: close, partial: false };
  // the files' similar words, best match first (`files` is in the search's order)
  const linked = new Set(votes.filter((v) => close.has(v.id) && v.dossier_id).map((v) => v.dossier_id!));
  const alike = similarWords([...files.keys()].filter((id) => linked.has(id)).map((id) => similar.get(id)));
  return { ids: close, partial: false, approximate: true, ...(alike.length ? { similar: alike } : {}) };
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
