/**
 * Client-side search over public/data/search.json (SearchDoc[]).
 *
 * Ranking, strongest first (a weaker tier never outranks a stronger one):
 *   1. exact identifier      procedure "2021/0106(COD)" or "2021/0106", CELEX "32024R1689", "COM(2021)206"
 *   2. exact name            title or alias equals the query ("AI Act", "EPP", "Spain", "Spanish")
 *   3. name starts with / contains the query as a phrase
 *   4. every meaningful word matches (exact word, synonym, plural, or prefix)
 *   5. same, but at least one word only matched approximately (typo tolerance)
 *   6. all but one word matched exactly (queries of three or more meaningful words only)
 * Inside a tier: field weight (title > alias > keyword), match quality, then the static boost `w`
 * (featured dossiers, active MEPs, countries, groups), then shorter titles and newer dates.
 *
 * Input conventions (pipeline/build.py): `a` = alternative names separated by " | ";
 * `x` = space-separated keywords and identifiers (multi-word keywords joined by "-").
 */
import type { SearchDoc, SearchKind } from '../types/data';
import { loadData } from './data';

export interface SearchOptions {
  kinds?: SearchKind[];
  limit?: number;
}

export interface SearchHit {
  doc: SearchDoc;
  score: number;
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

const ID_RE = /^(?:\d{4}\/\d{4}(?:\([a-z]{3}\))?|\d{5}[a-z]{1,2}\d{1,4}(?:\(\d+\))?|com[/(]?\d{4}[)/]?\d+)$/;

/** Words that need not match (they carry little meaning on their own). */
const STOP = new Set([
  'the', 'of', 'and', 'for', 'on', 'in', 'to', 'a', 'an', 'by', 'with', 'or', 'at', 'from', 'as',
  'de', 'der', 'den', 'die', 'von', 'van', 'la', 'le', 'les', 'du', 'des', 'del', 'di', 'da', 'el',
]);

/** Generic everyday synonyms (curated, dossier-specific aliases come from the data). */
const SYNONYMS: Record<string, string[]> = {
  law: ['act', 'regulation', 'directive', 'legislation'],
  laws: ['act', 'regulation', 'directive', 'legislation'],
  legislation: ['act', 'regulation', 'directive'],
  rules: ['regulation', 'directive', 'rules'],
  rule: ['regulation', 'directive'],
  ban: ['prohibition', 'prohibiting', 'prohibited'],
  mep: ['member'],
  meps: ['member', 'members'],
  eu: ['european', 'union'],
  europe: ['european'],
};

const W_TITLE = 3;
const W_ALIAS = 2.5;
const W_KEY = 1.5;

const M_EXACT = 1;
const M_SYN = 0.8;
const M_PREFIX = 0.6;
const M_FUZZY = 0.3;

const TIER = {
  id: 1e8,
  exact: 1e7,
  starts: 5e6,
  phrase: 3e6,
  all: 1e6,
  fuzzy: 1e5,
  partial: 1e4,
};

interface Prepared {
  doc: SearchDoc;
  title: string; // normalized words joined by spaces
  names: string[]; // title + aliases (normalized phrases)
  titleLen: number;
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

  docs.forEach((doc, i) => {
    const titleWords = words(doc.t);
    const title = titleWords.join(' ');
    const aliases = (doc.a ?? '')
      .split('|')
      .map((s) => words(s).join(' '))
      .filter(Boolean);
    const names = [title, ...aliases];
    prepared.push({ doc, title, names, titleLen: titleWords.length });
    for (const n of names) add(byName, n, i);
    for (const w of titleWords) post(w, i, W_TITLE);
    for (const a of aliases) for (const w of a.split(' ')) post(w, i, W_ALIAS);
    for (const raw of (doc.x ?? '').split(/\s+/)) {
      if (!raw) continue;
      const k = idKey(raw);
      if (ID_RE.test(k)) {
        add(byId, k, i);
        const num = k.match(/^(\d{4}\/\d{4})\(/);
        if (num) add(byId, num[1], i);
      }
      for (const w of words(raw)) post(w, i, W_KEY);
      if (raw.includes('-')) add(byName, words(raw).join(' '), i); // multi-word keyword phrase
    }
  });
  const vocab = [...postings.keys()].sort();

  function wordMatches(qw: string, allowPrefix: boolean): { m: Map<number, number>; fuzzyOnly: boolean } {
    const m = new Map<number, number>();
    const put = (w: string, quality: number) => {
      const p = postings.get(w);
      if (!p) return;
      for (const [i, fw] of p) {
        const s = fw * quality;
        if ((m.get(i) ?? 0) < s) m.set(i, s);
      }
    };
    put(qw, M_EXACT);
    for (const s of SYNONYMS[qw] ?? []) put(s, M_SYN);
    if (qw.length > 3 && qw.endsWith('s')) put(qw.slice(0, -1), M_SYN + 0.1);
    if (allowPrefix) {
      let n = 0;
      for (let j = lowerBound(vocab, qw); j < vocab.length && vocab[j].startsWith(qw) && n < 400; j++, n++) {
        if (vocab[j] !== qw) put(vocab[j], M_PREFIX);
      }
    }
    if (m.size > 0 || qw.length < 4 || /\d/.test(qw)) return { m, fuzzyOnly: false };
    const max = qw.length >= 7 ? 2 : 1;
    for (const w of vocab) {
      if (Math.abs(w.length - qw.length) > max || w[0] !== qw[0]) continue;
      if (editDistance(qw, w, max) <= max) put(w, M_FUZZY);
    }
    return { m, fuzzyOnly: m.size > 0 };
  }

  function search(query: string, opts: SearchOptions = {}): SearchHit[] {
    const limit = opts.limit ?? 50;
    const kinds = opts.kinds?.length ? new Set(opts.kinds) : null;
    const qWords = words(query);
    if (!qWords.length) return [];
    const phrase = qWords.join(' ');
    const scores = new Map<number, number>();
    const bump = (i: number, s: number) => {
      if ((scores.get(i) ?? -Infinity) < s) scores.set(i, s);
    };
    const boost = (i: number) => (prepared[i].doc.w ?? 1) * 400 - Math.min(prepared[i].titleLen, 40) * 2;

    // 1. identifiers
    const qid = idKey(query);
    for (const i of byId.get(qid) ?? []) bump(i, TIER.id + boost(i));

    // 2-3. names (title / aliases / multi-word keywords)
    for (const i of byName.get(phrase) ?? []) {
      const exactTier = prepared[i].doc.k === 'topic' && prepared[i].title !== phrase ? TIER.starts : TIER.exact;
      bump(i, exactTier + boost(i) + (prepared[i].title === phrase ? 300 : 0));
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
          if (n.startsWith(phrase + ' ') || (n.startsWith(phrase) && n.length > phrase.length)) {
            best = Math.max(best, TIER.starts + fw);
          } else if (phrase.length >= 3 && ` ${n} `.includes(` ${phrase} `)) {
            best = Math.max(best, TIER.phrase + fw);
          }
        }
        if (best) bump(i, best + boost(i));
      });
    }

    // 4-6. words
    const required = qWords.filter((w) => !STOP.has(w));
    const req = required.length ? required : qWords;
    // prefix matching only for the word being typed (the last one): "chat control" must not match "chatbots"
    const lastTyped = qWords[qWords.length - 1];
    const per = req.map((w) => wordMatches(w, w === lastTyped && w.length >= 2));
    const optional = qWords.filter((w) => STOP.has(w) && required.length).map((w) => wordMatches(w, false).m);
    const counts = new Map<number, { n: number; sum: number; fuzzy: boolean; exactN: number }>();
    per.forEach(({ m, fuzzyOnly }) => {
      for (const [i, s] of m) {
        const c = counts.get(i) ?? { n: 0, sum: 0, fuzzy: false, exactN: 0 };
        c.n += 1;
        c.sum += s;
        c.fuzzy ||= fuzzyOnly;
        if (!fuzzyOnly && s >= W_KEY * M_EXACT) c.exactN += 1;
        counts.set(i, c);
      }
    });
    let anyFull = false;
    for (const [i, c] of counts) {
      if (c.n < req.length) continue;
      anyFull = true;
      const extra = optional.reduce((acc, m) => acc + (m.get(i) ?? 0) * 0.2, 0);
      bump(i, (c.fuzzy ? TIER.fuzzy : TIER.all) + (c.sum + extra) * 100 + boost(i));
    }
    if (!anyFull && scores.size === 0 && req.length >= 3) {
      for (const [i, c] of counts) {
        if (c.exactN >= req.length - 1 && !c.fuzzy) bump(i, TIER.partial + c.sum * 100 + boost(i));
      }
    }

    const hits: SearchHit[] = [];
    for (const [i, score] of scores) {
      const doc = prepared[i].doc;
      if (kinds && !kinds.has(doc.k)) continue;
      hits.push({ doc, score });
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

let engine: Promise<SearchEngine> | null = null;

/** Load search.json once and build the engine (cached; retried after a failure). */
export function loadSearch(): Promise<SearchEngine> {
  engine ??= loadData<SearchDoc[]>('search.json').then(createSearchEngine);
  engine.catch(() => {
    engine = null;
  });
  return engine;
}
