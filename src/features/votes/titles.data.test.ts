/**
 * votes/titles.json on the real build (public/data from `python -m pipeline build`): the MEP, group and party pages read it
 * instead of votes/index.json, so each vote must give their tables what the index gives. Skipped when the data has not
 * been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { EpVoteSummary, EpVoteTitle } from '../../types/data';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('votes/titles.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

// what Mep.tsx, Group.tsx and Party.tsx read from a vote: its date and result, VoteTitle's and VoteRowMeta's fields,
// and the file it links to (Party.tsx)
const shown = (v: EpVoteTitle) => ({
  date: v.date,
  outcome: v.outcome,
  title: v.display_title || v.title,
  parts: v.display_title_parts ?? null,
  line: [v.kind_label, v.procedure_ref, v.distinction].filter(Boolean),
  file: v.dossier_id ?? null,
});

describe.skipIf(!built)('votes/titles.json on the built data', () => {
  const index = built ? read<EpVoteSummary[]>('votes/index.json') : [];
  const titles = built ? read<EpVoteTitle[]>('votes/titles.json') : [];

  it('lists the votes of the index, in its order', () => {
    expect(titles.length).toBeGreaterThan(0);
    expect(titles.map((t) => t.id)).toEqual(index.map((v) => v.id));
  });

  it('gives the tables the same date, result, title and line as the index does', () => {
    const asIndex = new Map(index.map((v) => [v.id, v]));
    for (const t of titles) expect(shown(t), t.id).toEqual(shown(asIndex.get(t.id)!));
  });

  it('holds nothing else of a vote: no margin, topics, counts, source or label', () => {
    // display_title_parts only for a label with French passages, title only for a vote with no display_title
    const allowed = new Set(['id', 'date', 'display_title', 'display_title_parts', 'distinction', 'kind_label', 'procedure_ref', 'outcome', 'dossier_id', 'title']);
    expect(titles.flatMap((t) => Object.keys(t).filter((k) => !allowed.has(k)))).toEqual([]);
    for (const t of titles) expect('title' in t && !!t.display_title, t.id).toBe(false);
  });
});
