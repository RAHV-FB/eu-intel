/**
 * Client-side search over public/data/search.json (SearchDoc[]).
 *
 * Ranking, strongest first (a weaker tier never outranks a stronger one):
 *   1. exact identifier      procedure "2021/0106(COD)" or "2021/0106", CELEX "32024R1689" or "CELEX:32024R1689",
 *                            "COM(2021)206", act number "2024/1689", "Regulation (EU) 2024/1689", "Directive 2014/24/EU"
 *   2. exact name            title or alias equals the query ("AI Act", "EPP", "Spain", "Spanish")
 *   3. name starts with the query as whole words, or contains it as a phrase
 *   4. every meaningful word matches a whole word, exactly or as its singular/plural ("battery" ~ "batteries");
 *      only when no document matches that way, one word may match an everyday synonym ("ai law" -> "act").
 *      A generic word ("rules", "law") also matches through its synonyms one step below ("asylum rules" ->
 *      "asylum ... regulation"), unless the query is itself a name ("rule of law", "climate law")
 *   5. the last word matched only as the start of a longer word ("artific" -> "artificial", "Spa" -> "Spain"):
 *      in as-you-type suggestions (`typing`, 3+ letters), or on the results page when nothing matched whole words.
 *      On the results page, legislation, topics and guides also match related forms of query words of 4+
 *      letters that are not abbreviations ("fish" -> "fisheries", "farming" -> "farm"), below every whole-word
 *      match and flagged `partial`
 *   6. at least one word matched only approximately (typo tolerance)
 *   7. all but one word matched exactly (queries of three or more meaningful words, name particles such as
 *      "von" or "der" not counted)
 * An identifier among other words ("GDPR 2016/679") ranks the file that owns it with tier 1 when that file
 * matches the other words too; an act citation naming the act type ("Council Decision No 376/2014/EU") ranks
 * the act of that type first.
 * Inside a tier: field weight (title > alias > keyword), match quality, then the static boost `w`
 * (featured dossiers, active MEPs, countries, groups), then shorter titles and newer dates.
 * People's names are not singularised ("Carlos" is not "Carlo").
 *
 * Input conventions (pipeline/build.py): `a` = alternative names separated by " | ";
 * `x` = space-separated keywords and identifiers (multi-word keywords joined by "-").
 */
import type { SearchDoc, SearchKind } from '../types/data';
import { loadData } from './data';

export interface SearchOptions {
  kinds?: SearchKind[];
  limit?: number;
  /** As-you-type suggestions: the last word (3+ letters) may also match the start of a longer word. */
  typing?: boolean;
}

export interface SearchHit {
  doc: SearchDoc;
  score: number;
  /** Matched only through the start of a longer word or a related word form (tier 5), not through whole words. */
  partial?: boolean;
}

export interface SearchEngine {
  search(query: string, opts?: SearchOptions): SearchHit[];
  size: number;
}

const SPECIAL: Record<string, string> = {
  ß: 'ss', æ: 'ae', œ: 'oe', ø: 'o', ł: 'l', đ: 'd', ð: 'd', þ: 'th', ı: 'i', ħ: 'h',
};

/** Lowercase, strip accents and punctuation (keeps "/", "(", ")" and "-" for identifiers). */
export function normalize(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[ßæœøłđðþıħ]/g, (c) => SPECIAL[c] ?? c)
    .replace(/[^\p{L}\p{N}/()-]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Words of a normalized string. */
function words(s: string): string[] {
  return normalize(s)
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);
}

/** Canonical form for identifier comparison: normalized, no spaces. */
function idKey(s: string): string {
  return normalize(s).replace(/\s+/g, '');
}

const ID_RE = /^(?:\d{4}\/\d{4}[a-z]?(?:\([a-z]{3}\))?|\d{1,4}\/\d{1,4}|\d{5}[a-z]{1,2}\d{1,4}(?:\(\d+\))?|com[/(]?\d{4}[)/]?\d+)$/;

// How official texts cite an act: "CELEX:32024R1689", "Regulation (EU) 2024/1689", "Regulation (EU) No 1316/2013",
// "Commission Implementing Decision (EU) 2024/123", "Directive 2014/24/EU", "Decision (EU, Euratom) 2020/2053".
const ACT_CITATION_HEAD =
  /^(?:celex\s*)?(?:(?:commission|council)\s+)?(?:(?:implementing|delegated)\s+)?(?:(?:regulation|directive|decision)s?\s*)?(?:\((?:eu|ec|eec|euratom)(?:\s+euratom)?\)\s*)?(?:(?:no|nr|n)\s+)?/;
const ACT_CITATION_TAIL = /(\d)\/(?:eu|ec|eec|euratom|jha|cfsp)(?:\s+euratom)?$/;

/** Identifier forms of a query: as typed, and with an act citation reduced to its number ("2024/1689"). */
function idCandidates(query: string): string[] {
  const n = normalize(query);
  const bare = n.replace(ACT_CITATION_HEAD, '').replace(ACT_CITATION_TAIL, '$1');
  return [...new Set([idKey(n), idKey(bare)])].filter(Boolean);
}

const CELEX_TYPE: Record<string, string> = { regulation: 'r', directive: 'l', decision: 'd' };
const ACT_CITATION_TYPE =
  /^(?:celex\s*)?(?:(?:commission|council)\s+)?(?:(?:implementing|delegated)\s+)?(regulation|directive|decision)\b/;

/** The act an act citation names, as CELEX type letter, year and number: "Council Decision No 376/2014/EU" ->
 * "d2014/376", "Directive 2014/24/EU" -> "l2014/24", "Regulation (EU) 2024/1689" -> "r2024/1689". Before 2015
 * regulations and decisions were numbered "number/year", directives "year/number". */
function citedActKeys(query: string): string[] {
  const n = normalize(query);
  const type = ACT_CITATION_TYPE.exec(n);
  const num = /(\d{1,4})\/(\d{1,4})(?:\/[a-z]+)?(?:\s+euratom)?$/.exec(n);
  if (!type || !num) return [];
  const t = CELEX_TYPE[type[1]];
  const year = (s: string) => s.length === 4 && Number(s) >= 1950;
  const out: string[] = [];
  if (year(num[1])) out.push(`${t}${num[1]}/${Number(num[2])}`);
  if (year(num[2])) out.push(`${t}${num[2]}/${Number(num[1])}`);
  return out;
}

/** The act keys ("r2014/376") of a sector-3 CELEX number ("32014R0376"). */
function celexActKey(k: string): string | null {
  const m = /^3(\d{4})([rld])0*(\d+)$/.exec(k);
  return m ? `${m[2]}${m[1]}/${m[3]}` : null;
}

/** Words typed with a capital letter after the first ("AMLA", "SAFE", "MiCA", "eIDAS"): abbreviations, which
 * are matched as whole words only. */
export function typedAbbreviations(query: string): Set<string> {
  const out = new Set<string>();
  for (const raw of query.split(/[^\p{L}\p{N}]+/u)) if (/\p{Lu}/u.test(raw.slice(1))) out.add(normalize(raw));
  return out;
}

// Name particles: not counted as matched words in tier 7, so "von der Leyen" does not find "von der Schulenburg".
const PARTICLES = new Set([
  'von', 'van', 'der', 'den', 'de', 'del', 'della', 'des', 'di', 'da', 'du', 'la', 'le', 'les', 'los', 'las', 'ten',
  'ter', 'zu', 'af',
]); // prettier-ignore

// Word families (tier 5 on the results page): a word of 4+ letters also matches longer words built on it, and
// the word without a common ending matches its other forms. The rest of the longer word must be a common ending
// or a word of its own of 6+ letters: "fish" -> "fisheries", "fishing"; "cyber" -> "cybersecurity"; "farming" ->
// "farm", "farmers"; "children" -> "child"; but "euro" not -> "european" or "eurojust", "bank" not -> "bankruptcy".
const FAMILY_IRREGULAR: Record<string, string> = { children: 'child' };
const FAMILY_STRIP = /(?:eries|ery|ings|ing|ers|er|ations|ation|ed)$/;
const FAMILY_ENDINGS = new Set([
  '', 's', 'es', 'd', 'ed', 'r', 'rs', 'er', 'ers', 'ing', 'ings', 'ery', 'eries', 'ermen', 'ren', 'ation', 'ations',
  'ion', 'ions', 'ment', 'ments', 'ness', 'ship', 'ships', 'hood', 'y', 'ies',
]); // prettier-ignore
// Names (people, parties, groups, countries) have no word families: "olive" must not find Oliver Schenk.
const FAMILY_KINDS = new Set<SearchKind>(['dossier', 'act', 'topic', 'page']);

/** The stems whose word family a query word matches: the word itself and the word without a common ending. */
export function familyStems(w: string): string[] {
  const out = [w];
  const irregular = FAMILY_IRREGULAR[w];
  if (irregular) out.push(irregular);
  const s = w.replace(FAMILY_STRIP, '');
  if (s !== w && s.length >= 4) out.push(s);
  return out;
}

/** Words that need not match (they carry little meaning on their own). Name particles such as "de", "la",
 * "le" or "von" are not here: "Le Pen" must not match any "pen…" word on its own. */
const STOP = new Set([
  'the', 'of', 'and', 'for', 'on', 'in', 'to', 'a', 'an', 'by', 'with', 'or', 'at', 'from', 'as', 'vs', 'versus',
]);

/** Generic everyday synonyms (curated, dossier-specific aliases come from the data). Used for at most one
 * query word, and only when no document matches all the words as typed. */
const SYNONYMS: Record<string, string[]> = {
  law: ['act', 'regulation', 'directive', 'legislation'],
  laws: ['act', 'regulation', 'directive', 'legislation'],
  legislation: ['act', 'regulation', 'directive'],
  rules: ['regulation', 'directive'],
  rule: ['regulation', 'directive'],
  ban: ['prohibition', 'prohibiting', 'prohibited'],
  mep: ['member'],
  meps: ['member', 'members'],
  eu: ['european', 'union'],
  europe: ['european'],
};

/** Generic words for a law: with another meaningful word they also match through their synonyms, one step
 * below the literal matches ("asylum rules" finds the asylum regulations, not only a file saying "rules"). */
const GENERIC = new Set(['law', 'laws', 'legislation', 'rules', 'rule']);

// Words ending in "s" that are not plurals of a shorter word.
const NOT_PLURAL = new Set(['news', 'means', 'series', 'species', 'lens', 'goods', 'arms', 'politics', 'economics']);

/** Light English singular form, applied to index and query words alike: batteries -> battery, cars -> car,
 * taxes -> tax, processes -> process. Not a full stemmer: other inflections are left alone. */
export function singular(w: string): string {
  if (w.length <= 3 || /\d/.test(w) || NOT_PLURAL.has(w)) return w;
  if (w.endsWith('ies') && w.length > 4) return `${w.slice(0, -3)}y`;
  if (/(?:ss|sh|ch|x)es$/.test(w)) return w.slice(0, -2);
  if (w.endsWith('s') && !/(?:ss|us|is)$/.test(w)) return w.slice(0, -1);
  return w;
}

/** Meaningful words of a query for whole-word list filters (stop words dropped unless nothing else is left). */
export function keywordTokens(query: string): string[] {
  const all = words(query);
  const req = all.filter((w) => !STOP.has(w));
  return req.length ? req : all;
}

/** The words of some texts, with their singular forms, for `hasWord`. */
export function wordSet(...texts: (string | null | undefined)[]): Set<string> {
  const out = new Set<string>();
  for (const t of texts) {
    if (!t) continue;
    for (const w of words(t)) {
      out.add(w);
      out.add(singular(w));
    }
  }
  return out;
}

/** Whole-word test against a `wordSet` (singular/plural-insensitive); with `prefix` (3+ letters), the
 * token may also be the start of a longer word. */
export function hasWord(set: Set<string>, token: string, prefix = false): boolean {
  if (set.has(token) || set.has(singular(token))) return true;
  if (!prefix || token.length < 3) return false;
  for (const w of set) if (w.startsWith(token)) return true;
  return false;
}

const W_TITLE = 3;
const W_ALIAS = 2.5;
const W_KEY = 1.5;

const M_EXACT = 1;
const M_PLURAL = 0.97;
const M_SYN = 0.8;
const M_PREFIX = 0.6;
const M_FUZZY = 0.3;

const TITLE_BONUS = 500;
const ACT_TYPE_BONUS = 3000; // above any static boost: the cited act type decides between acts sharing a number

const TIER = {
  id: 1e8,
  exact: 1e7,
  starts: 5e6,
  phrase: 3e6,
  all: 1e6,
  syn: 8e5, // all words, a generic one through a synonym, while other files match literally
  prefix: 5e5,
  fuzzy: 1e5,
  partial: 1e4,
};

interface Prepared {
  doc: SearchDoc;
  title: string; // normalized words joined by spaces
  names: string[]; // title + aliases (normalized phrases)
  namesSing: string[]; // the same with every word in its singular form
  titleLen: number;
}

const singularPhrase = (phrase: string) => phrase.split(' ').map(singular).join(' ');

interface WordMatch {
  base: Map<number, number>; // doc -> best weighted quality (exact, singular/plural, or prefix)
  syn: Map<number, number>; // doc -> best weighted quality through a synonym
  fuzzy: boolean; // base holds approximate matches only
  prefixOnly: Set<number>; // docs in `base` matched only as the start of a longer word
}

/** Optimal string alignment distance, bounded by `max` (returns max + 1 when exceeded). */
function editDistance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const n = b.length;
  let prev2: number[] = [];
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    let rowMin = i;
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, prev2[j - 2] + 1);
      cur.push(v);
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > max) return max + 1;
    prev2 = prev;
    prev = cur;
  }
  return prev[n];
}

function lowerBound(arr: string[], x: string): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The phrase with one word replaced by a synonym, e.g. ["ai", "law"] -> "ai act", "ai regulation". */
function phraseVariants(qWords: string[]): string[] {
  const out: string[] = [];
  qWords.forEach((w, k) => {
    for (const s of SYNONYMS[w] ?? []) {
      if (s !== w) out.push([...qWords.slice(0, k), s, ...qWords.slice(k + 1)].join(' '));
    }
  });
  return out.slice(0, 16);
}

/** Build a search engine over SearchDoc[] (exported for tests). */
export function createSearchEngine(docs: SearchDoc[]): SearchEngine {
  const prepared: Prepared[] = [];
  const postings = new Map<string, Map<number, number>>(); // word -> doc -> best field weight
  const byId = new Map<string, number[]>();
  const byName = new Map<string, number[]>();
  const byNameSing = new Map<string, number[]>(); // singular-form names: "battery regulation" ~ "batteries regulation"

  const post = (w: string, i: number, weight: number) => {
    let m = postings.get(w);
    if (!m) postings.set(w, (m = new Map()));
    if ((m.get(i) ?? 0) < weight) m.set(i, weight);
  };
  const add = <K>(map: Map<K, number[]>, k: K, i: number) => {
    const l = map.get(k);
    if (!l) map.set(k, [i]);
    else if (l[l.length - 1] !== i) l.push(i);
  };

  const actKeys = new Map<number, Set<string>>(); // doc -> its acts' CELEX type, year and number ("r2014/376")

  docs.forEach((doc, i) => {
    const titleWords = words(doc.t);
    const title = titleWords.join(' ');
    const aliases = (doc.a ?? '')
      .split('|')
      .map((s) => words(s).join(' '))
      .filter(Boolean);
    const names = [title, ...aliases];
    // a person's name has no plural: "Carlos" is not "Carlo"
    const namesSing = doc.k === 'mep' ? names : names.map(singularPhrase);
    prepared.push({ doc, title, names, namesSing, titleLen: titleWords.length });
    for (const n of names) add(byName, n, i);
    if (doc.k !== 'mep') for (const n of namesSing) add(byNameSing, n, i);
    for (const w of titleWords) post(w, i, W_TITLE);
    for (const a of aliases) for (const w of a.split(' ')) post(w, i, W_ALIAS);
    for (const raw of (doc.x ?? '').split(/\s+/)) {
      if (!raw) continue;
      const k = idKey(raw);
      if (ID_RE.test(k)) {
        add(byId, k, i);
        const num = k.match(/^(\d{4}\/\d{4})[a-z]?\(/);
        if (num) add(byId, num[1], i);
        const act = celexActKey(k);
        if (act) {
          if (!actKeys.has(i)) actKeys.set(i, new Set());
          actKeys.get(i)!.add(act);
        }
      }
      for (const w of words(raw)) post(w, i, W_KEY);
      if (raw.includes('-')) add(byName, words(raw).join(' '), i); // multi-word keyword phrase
    }
  });
  const vocab = [...postings.keys()].sort();
  const bySingular = new Map<string, string[]>(); // singular form -> index words with that form
  for (const w of vocab) {
    const s = singular(w);
    const l = bySingular.get(s);
    if (l) l.push(w);
    else bySingular.set(s, [w]);
  }

  function wordMatches(qw: string, allowPrefix: boolean, family = false): WordMatch {
    const base = new Map<number, number>();
    const syn = new Map<number, number>();
    const whole = new Set<number>();
    const put = (into: Map<number, number>, w: string, quality: number, only?: (i: number) => boolean) => {
      const p = postings.get(w);
      if (!p) return;
      for (const [i, fw] of p) {
        if (only && !only(i)) continue;
        const s = fw * quality;
        if ((into.get(i) ?? 0) < s) into.set(i, s);
        if (into === base && quality > M_PREFIX) whole.add(i);
      }
    };
    put(base, qw, M_EXACT);
    const notPerson = (i: number) => prepared[i].doc.k !== 'mep';
    for (const w of bySingular.get(singular(qw)) ?? []) if (w !== qw) put(base, w, M_PLURAL, notPerson);
    for (const s of SYNONYMS[qw] ?? []) put(syn, s, M_SYN);
    if (allowPrefix) {
      let n = 0;
      for (let j = lowerBound(vocab, qw); j < vocab.length && vocab[j].startsWith(qw) && n < 400; j++, n++) {
        if (vocab[j] !== qw) put(base, vocab[j], M_PREFIX);
      }
    }
    if (family) {
      const familyDoc = (i: number) => FAMILY_KINDS.has(prepared[i].doc.k);
      for (const stem of familyStems(qw)) {
        let n = 0;
        for (let j = lowerBound(vocab, stem); j < vocab.length && vocab[j].startsWith(stem) && n < 400; j++, n++) {
          const rest = vocab[j].slice(stem.length);
          // a common ending, or a word of its own of 6+ letters: "cyber" + "security", not "safe" + "guard"
          const compound = singular(rest).length >= 6 && bySingular.has(singular(rest));
          if (FAMILY_ENDINGS.has(rest) || compound) {
            put(base, vocab[j], M_PREFIX, familyDoc);
          }
        }
      }
    }
    const prefixOnly = new Set([...base.keys()].filter((i) => !whole.has(i)));
    // a word of the index (if only in a person's name: "Costa", from "Costas") is not a typo
    const known = bySingular.has(singular(qw));
    if (base.size > 0 || syn.size > 0 || known || qw.length < 4 || /\d/.test(qw)) {
      return { base, syn, fuzzy: false, prefixOnly };
    }
    const max = qw.length >= 7 ? 2 : 1;
    for (const w of vocab) {
      if (Math.abs(w.length - qw.length) > max || w[0] !== qw[0]) continue;
      if (editDistance(qw, w, max) <= max) put(base, w, M_FUZZY);
    }
    return { base, syn, fuzzy: base.size > 0, prefixOnly };
  }

  /** prefix: "last" = the word being typed may be the start of a longer word (suggestions); "all" = any word
   * may (results page, only once nothing matched whole words). Never for words under 3 letters. "family" (and
   * "all") = words of 4+ letters that are not abbreviations also match their word family (tier 5). */
  function run(query: string, prefix: 'none' | 'last' | 'all' | 'family'): Map<number, number> {
    const qWords = words(query);
    const scores = new Map<number, number>();
    if (!qWords.length) return scores;
    const phrase = qWords.join(' ');
    const phraseSing = singularPhrase(phrase);
    const lastTyped = qWords[qWords.length - 1];
    // "chat control" must not match "chatbots", "ai" must not match "air" or "aid"
    const prefixLast = (prefix === 'last' || prefix === 'all') && lastTyped.length >= 3;
    const prefixWord = (w: string) => w.length >= 3 && (prefix === 'all' || (prefix === 'last' && w === lastTyped));
    const abbreviations = typedAbbreviations(query);
    const familyWord = (w: string) =>
      (prefix === 'family' || prefix === 'all') && w.length >= 4 && !/\d/.test(w) && !abbreviations.has(w);
    const bump = (i: number, s: number) => {
      if ((scores.get(i) ?? -Infinity) < s) scores.set(i, s);
    };
    const boost = (i: number) => (prepared[i].doc.w ?? 1) * 400 - Math.min(prepared[i].titleLen, 40) * 2;

    // 1. identifiers; an act citation that names the act type puts the act of that type first
    const cited = citedActKeys(query);
    for (const k of idCandidates(query)) {
      for (const i of byId.get(k) ?? []) {
        const typed = cited.some((a) => actKeys.get(i)?.has(a)) ? ACT_TYPE_BONUS : 0;
        bump(i, TIER.id + boost(i) + typed);
      }
    }
    let named = false; // the query is (part of) a name: "rule of law", "climate law"

    // 2-3. names (title / aliases / multi-word keywords), singular/plural-insensitive
    for (const i of new Set([...(byName.get(phrase) ?? []), ...(byNameSing.get(phraseSing) ?? [])])) {
      const isTitle = prepared[i].namesSing[0] === (prepared[i].doc.k === 'mep' ? phrase : phraseSing);
      // a topic's alias is an everyday word ("AI", "data"): it ranks with names starting with the query,
      // with the bonus of a title match
      const topicAlias = prepared[i].doc.k === 'topic' && !isTitle;
      const asTyped = prepared[i].names.includes(phrase) ? 10 : 0;
      bump(i, (topicAlias ? TIER.starts : TIER.exact) + boost(i) + (isTitle || topicAlias ? 300 : 0) + asTyped);
      named = true;
    }
    // synonym variants of the whole phrase ("ai law" -> "ai act"), just below exact names
    if (qWords.length <= 4) {
      for (const v of phraseVariants(qWords)) {
        for (const i of byName.get(v) ?? []) bump(i, TIER.starts + 100 + boost(i));
      }
    }
    if (phrase.length >= 2) {
      prepared.forEach((p, i) => {
        let best = 0;
        for (const [k, n] of p.names.entries()) {
          const fw = k === 0 ? 300 : 200;
          const ns = p.namesSing[k];
          const ps = p.doc.k === 'mep' ? phrase : phraseSing; // a person's name has no plural
          if (n.startsWith(phrase + ' ') || ns.startsWith(ps + ' ')) {
            best = Math.max(best, TIER.starts + fw);
          } else if (phrase.length >= 3 && (` ${n} `.includes(` ${phrase} `) || ` ${ns} `.includes(` ${ps} `))) {
            best = Math.max(best, TIER.phrase + fw);
          } else if (prefixLast && n.length > phrase.length && n.startsWith(phrase)) {
            best = Math.max(best, TIER.prefix + fw); // "spa" -> "spain"
          }
        }
        if (best) bump(i, best + boost(i));
        if (best >= TIER.phrase) named = true;
      });
    }

    // 4-7. words
    const required = qWords.filter((w) => !STOP.has(w));
    const req = required.length ? required : qWords;
    const per = req.map((w) => wordMatches(w, prefixWord(w), familyWord(w)));
    const optional = qWords.filter((w) => STOP.has(w) && required.length).map((w) => wordMatches(w, false).base);
    const extra = (i: number) => optional.reduce((acc, m) => acc + (m.get(i) ?? 0) * 0.2, 0);

    // every word matched as typed (whole word, singular/plural, prefix of the last word, or typo)
    const full = (expand: number, tier = TIER.all): number => {
      let n = 0;
      const [first, ...rest] = per.map((m, k) => (k === expand ? new Map([...m.syn, ...m.base]) : m.base));
      for (const [i, s0] of first) {
        let sum = s0;
        let ok = true;
        for (const m of rest) {
          const s = m.get(i);
          if (s === undefined) {
            ok = false;
            break;
          }
          sum += s;
        }
        if (!ok) continue;
        n++;
        const fuzzy = per.some((m) => m.fuzzy);
        const partial = per.some((m, k) => m.prefixOnly.has(i) && !(k === expand && m.syn.has(i)));
        // every word is a whole word of the title ("battery" in "Batteries and waste batteries")
        const inTitle = per.every((m) => (m.base.get(i) ?? 0) >= W_TITLE * M_PLURAL) ? TITLE_BONUS : 0;
        bump(i, (fuzzy ? TIER.fuzzy : partial ? TIER.prefix : tier) + (sum + extra(i)) * 100 + inTitle + boost(i));
      }
      return n;
    };
    let anyFull = full(-1) > 0;
    // no document has all the words: let one word match a synonym ("ai law" -> "act"), never two at once
    if (!anyFull) {
      per.forEach((m, k) => {
        if (m.syn.size && full(k) > 0) anyFull = true;
      });
    } else if (!named && req.some((w) => !GENERIC.has(w))) {
      // a generic word next to a subject word also matches through its synonyms, below the literal matches:
      // "asylum rules" finds the asylum regulations, not only the one file that says "rules"
      per.forEach((m, k) => {
        if (m.syn.size && GENERIC.has(req[k])) full(k, TIER.syn);
      });
    }

    // an identifier among other words ("GDPR 2016/679"): the file it identifies, when it matches the other
    // words too, ranks with the identifier matches, above files that only mention the number
    const tokens = normalize(query).split(' ');
    if (tokens.length > 1) {
      for (const t of tokens) {
        const k = idKey(t);
        if (!ID_RE.test(k)) continue;
        for (const i of byId.get(k) ?? []) {
          const s = scores.get(i) ?? 0;
          if (s >= TIER.all && s < TIER.id) bump(i, TIER.id + boost(i));
        }
      }
    }

    // all but one word: name particles do not count ("von der Leyen" is not "von der Schulenburg")
    const content = req.filter((w) => !PARTICLES.has(w));
    if (!anyFull && scores.size === 0 && content.length >= 3) {
      const counts = new Map<number, { exactN: number; sum: number }>();
      per.forEach(({ base, fuzzy, prefixOnly }, k) => {
        if (fuzzy || PARTICLES.has(req[k])) return;
        for (const [i, s] of base) {
          if (s < W_KEY * M_PLURAL || prefixOnly.has(i)) continue;
          const c = counts.get(i) ?? { exactN: 0, sum: 0 };
          c.exactN += 1;
          c.sum += s;
          counts.set(i, c);
        }
      });
      for (const [i, c] of counts) {
        if (c.exactN >= content.length - 1) bump(i, TIER.partial + c.sum * 100 + boost(i));
      }
    }
    return scores;
  }

  function search(query: string, opts: SearchOptions = {}): SearchHit[] {
    const limit = opts.limit ?? 50;
    const kinds = opts.kinds?.length ? new Set(opts.kinds) : null;
    let scores = run(query, opts.typing ? 'last' : 'none');
    if (!opts.typing) {
      // nothing matched whole words: fall back to words starting with those typed ("pharma package")
      if (scores.size === 0) scores = run(query, 'all');
      else {
        // related word forms, below every whole-word match: "fish" -> "fisheries", "farming" -> "farm"
        for (const [i, s] of run(query, 'family')) {
          if (!scores.has(i) && s >= TIER.prefix && s < TIER.syn) scores.set(i, s);
        }
      }
    }

    const hits: SearchHit[] = [];
    for (const [i, score] of scores) {
      const doc = prepared[i].doc;
      if (kinds && !kinds.has(doc.k)) continue;
      const hit: SearchHit = { doc, score };
      if (score >= TIER.prefix && score < TIER.syn) hit.partial = true;
      hits.push(hit);
    }
    hits.sort(
      (a, b) =>
        b.score - a.score ||
        (b.doc.d ?? '').localeCompare(a.doc.d ?? '') ||
        a.doc.t.localeCompare(b.doc.t) ||
        a.doc.id.localeCompare(b.doc.id),
    );
    return hits.slice(0, limit);
  }

  return { search, size: docs.length };
}

/** Dossier ids matched by the engine, with scores normalised to (0..1], in the engine's order. The legislation
 * explorer and the votes list use this so that their keyword matches agree with the search page. `partial`
 * collects the ids matched only through related word forms; `identifiers` keeps only the matches on an identifier
 * or on a name holding the query as a phrase (a number: a title citing "Directive (EU) 2022/2464"). */
export function dossierScores(
  engine: SearchEngine,
  query: string,
  opts: { wholeWords?: boolean; identifiers?: boolean; partial?: Set<string> } = {},
): Map<string, number> {
  const m = new Map<string, number>();
  if (!query.trim()) return m;
  let hits: SearchHit[];
  try {
    hits = engine.search(query, { kinds: ['dossier'], limit: 5000 });
  } catch {
    return m;
  }
  const max = hits[0]?.score || 1;
  for (const h of hits) {
    if (opts.wholeWords && h.partial) continue;
    if (opts.identifiers && h.score < TIER.phrase) continue;
    const fromUrl = /^\/legislation\/([^/?#]+)/.exec(h.doc.u)?.[1];
    const id = fromUrl ? decodeURIComponent(fromUrl) : h.doc.id;
    if (!m.has(id)) {
      m.set(id, h.score / max);
      if (h.partial) opts.partial?.add(id);
    }
  }
  return m;
}

let engine: Promise<SearchEngine> | null = null;

/** Load search.json once and build the engine (cached; retried after a failure). */
export function loadSearch(): Promise<SearchEngine> {
  engine ??= loadData<SearchDoc[]>('search.json').then(createSearchEngine);
  engine.catch(() => {
    engine = null;
  });
  return engine;
}
