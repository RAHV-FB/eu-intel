/**
 * Client-side search over public/data/search.json.
 * OWNER: search workstream (Agent E). This file defines the interface used by the UI;
 * the implementation (normalization, aliases, fuzzy matching, ranking) lives here too.
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

/** Lowercase, strip accents and punctuation. */
export function normalize(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}/()-]+/gu, ' ')
    .trim();
}

let engine: Promise<SearchEngine> | null = null;

/** Placeholder engine: substring scoring. Replaced by the search workstream. */
export function loadSearch(): Promise<SearchEngine> {
  engine ??= loadData<SearchDoc[]>('search.json').then((docs) => {
    const norm = docs.map((d) => normalize([d.t, d.a, d.x].filter(Boolean).join(' ')));
    return {
      size: docs.length,
      search(query: string, opts: SearchOptions = {}) {
        const q = normalize(query);
        if (!q) return [];
        const hits: SearchHit[] = [];
        docs.forEach((doc, i) => {
          if (opts.kinds && !opts.kinds.includes(doc.k)) return;
          const at = norm[i].indexOf(q);
          if (at >= 0) hits.push({ doc, score: (doc.w ?? 1) * (at === 0 ? 2 : 1) });
        });
        return hits.sort((a, b) => b.score - a.score).slice(0, opts.limit ?? 50);
      },
    };
  });
  return engine;
}
