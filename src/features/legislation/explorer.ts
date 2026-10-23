/**
 * Filtering, ranking and sorting for the legislation explorer. All state lives in the URL query string.
 */
import type { DossierSummary, LegalInstrument } from '../../types/data';
import { dossierScores, hasWord, keywordTokens, wordSet, type SearchEngine } from '../../lib/search';
import { ADOPTED_STAGES, dossierYear, stagesFor } from './labels';

export type SortKey = 'relevance' | 'updated' | 'newest' | 'adopted' | 'blocked' | 'deadline';

export const SORT_LABEL: Record<SortKey, string> = {
  relevance: 'Best match',
  updated: 'Recently updated',
  newest: 'Newest proposals',
  adopted: 'Most recently adopted',
  blocked: 'Officially blocked first',
  deadline: 'Upcoming application dates & deadlines',
};

export const PAGE_SIZE = 25;

export interface ExplorerState {
  q: string;
  topic: string | null;
  stage: string | null;
  type: string | null;
  instrument: LegalInstrument | null;
  year: number | null;
  blocked: boolean;
  sort: SortKey;
  show: number;
}

const SORTS = Object.keys(SORT_LABEL) as SortKey[];

export function readState(p: URLSearchParams): ExplorerState {
  const q = (p.get('q') ?? '').slice(0, 200);
  const sortParam = p.get('sort') as SortKey | null;
  const sort: SortKey = sortParam && SORTS.includes(sortParam) ? sortParam : q.trim() ? 'relevance' : 'updated';
  const year = Number(p.get('year'));
  const show = Number(p.get('show'));
  return {
    q,
    topic: p.get('topic') || null,
    stage: p.get('stage') || null,
    type: p.get('type') || null,
    instrument: (p.get('instrument') as LegalInstrument | null) || null,
    year: Number.isInteger(year) && year > 1950 ? year : null,
    blocked: p.get('blocked') === '1',
    sort,
    show: Number.isInteger(show) && show > PAGE_SIZE ? Math.min(show, 5000) : PAGE_SIZE,
  };
}

export type Facet = 'topic' | 'stage' | 'type' | 'instrument' | 'year' | 'blocked';

// ------------------------------------------------------------------ text matching

export interface Haystack {
  title: Set<string>;
  all: Set<string>;
}

/** Act number from a CELEX number for acts from 2015 on ("32024R1689" -> "2024/1689"), as cited in the press. */
function actNumber(celex: string): string | null {
  const m = /^3(\d{4})[RLD]0*(\d+)$/.exec(celex);
  return m && Number(m[1]) >= 2015 ? `${m[1]}/${m[2]}` : null;
}

export function buildHaystacks(rows: DossierSummary[]): Map<string, Haystack> {
  const m = new Map<string, Haystack>();
  for (const d of rows) {
    const celex = d.celex ?? [];
    m.set(d.id, {
      title: wordSet(d.title),
      all: wordSet(d.title, d.official_title, d.short, d.ref, d.id, d.type, ...celex, ...celex.map(actNumber)),
    });
  }
  return m;
}

/** Fallback scoring while the search index loads: every query word must be a whole word of the file (or its
 * singular/plural); title matches weigh more. "ai" does not match "Spain", "act" does not match "contracts". */
export function simpleScore(h: Haystack | undefined, tokens: string[]): number {
  if (!h || !tokens.length) return 0;
  let score = 0;
  for (const t of tokens) {
    if (hasWord(h.title, t)) score += 3;
    else if (hasWord(h.all, t)) score += 1;
    else return 0;
  }
  return score;
}

export function queryTokens(q: string): string[] {
  return keywordTokens(q);
}

/** Map search-engine dossier hits to dossier ids → normalised score (0..1]. */
export function engineScores(engine: SearchEngine | null, q: string): Map<string, number> {
  return engine ? dossierScores(engine, q) : new Map();
}

/**
 * Files matching the keyword query, with their relevance. Once the search index is loaded only its matches
 * count, so "N files match" agrees with the Legislation results on /search for the same query; until then a
 * whole-word match on titles and references stands in.
 */
export function keywordScores(
  rows: DossierSummary[],
  haystacks: Map<string, Haystack>,
  engine: SearchEngine | null,
  q: string,
): Map<string, number> {
  if (engine) return engineScores(engine, q);
  const tokens = queryTokens(q);
  const out = new Map<string, number>();
  for (const d of rows) {
    const s = simpleScore(haystacks.get(d.id), tokens);
    if (s > 0) out.set(d.id, s);
  }
  return out;
}

// ------------------------------------------------------------------ filters

export function makePredicates(s: ExplorerState): Record<Facet, ((d: DossierSummary) => boolean) | null> {
  const stages = stagesFor(s.stage);
  return {
    topic: s.topic ? (d) => d.topics.includes(s.topic!) : null,
    stage: stages ? (d) => stages.has(d.stage) : null,
    type: s.type ? (d) => d.type === s.type : null,
    instrument: s.instrument ? (d) => d.instrument === s.instrument : null,
    year: s.year ? (d) => dossierYear(d) === s.year : null,
    blocked: s.blocked ? (d) => d.officially_blocked : null,
  };
}

export function applyFilters(
  rows: DossierSummary[],
  preds: Record<Facet, ((d: DossierSummary) => boolean) | null>,
  except?: Facet,
): DossierSummary[] {
  const active = (Object.entries(preds) as [Facet, ((d: DossierSummary) => boolean) | null][]).filter(
    ([k, p]) => p && k !== except,
  ) as [Facet, (d: DossierSummary) => boolean][];
  if (!active.length) return rows;
  return rows.filter((d) => active.every(([, p]) => p(d)));
}

export function countBy<K extends string | number>(rows: DossierSummary[], key: (d: DossierSummary) => K | K[] | null | undefined) {
  const m = new Map<K, number>();
  for (const d of rows) {
    const k = key(d);
    if (k == null) continue;
    for (const v of Array.isArray(k) ? k : [k]) m.set(v, (m.get(v) ?? 0) + 1);
  }
  return m;
}

// ------------------------------------------------------------------ sorting

const desc = (a?: string | null, b?: string | null) => (b ?? '').localeCompare(a ?? '');

/** The date shown on each row and used by the adoption sort. */
export function adoptionDate(d: DossierSummary): string | null {
  if (!ADOPTED_STAGES.has(d.stage)) return null;
  return d.adopted ?? null;
}

export function upcomingDate(d: DossierSummary, today: string): string | null {
  return d.next_date && d.next_date >= today ? d.next_date : null;
}

export function sortRows(rows: DossierSummary[], sort: SortKey, scores: Map<string, number>, today: string): DossierSummary[] {
  const out = rows.slice();
  switch (sort) {
    case 'relevance':
      out.sort((a, b) => (scores.get(b.id) ?? 0) - (scores.get(a.id) ?? 0) || desc(a.last_event, b.last_event));
      break;
    case 'newest':
      out.sort((a, b) => desc(a.started, b.started) || desc(a.last_event, b.last_event));
      break;
    case 'adopted':
      // Adopted files first, by adoption date when recorded (else by latest recorded step); others after.
      out.sort((a, b) => {
        const aa = ADOPTED_STAGES.has(a.stage) ? 1 : 0;
        const bb = ADOPTED_STAGES.has(b.stage) ? 1 : 0;
        return bb - aa || desc(a.adopted ?? a.last_event, b.adopted ?? b.last_event);
      });
      break;
    case 'blocked':
      out.sort((a, b) => Number(b.officially_blocked) - Number(a.officially_blocked) || desc(a.last_event, b.last_event));
      break;
    case 'deadline':
      out.sort((a, b) => {
        const da = upcomingDate(a, today);
        const db = upcomingDate(b, today);
        if (da && db) return da.localeCompare(db);
        if (da) return -1;
        if (db) return 1;
        return desc(a.last_event, b.last_event);
      });
      break;
    case 'updated':
    default:
      out.sort((a, b) => desc(a.last_event, b.last_event) || desc(a.started, b.started));
  }
  return out;
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}
