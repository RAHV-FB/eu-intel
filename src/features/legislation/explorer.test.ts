import { describe, expect, it } from 'vitest';
import type { DossierSummary } from '../../types/data';
import { buildHaystacks, buildHaystacksOnce, keywordScores, sortRows } from './explorer';

// TEST-ONLY rows shaped like dossiers/index.json (only the fields the keyword box reads)
const row = (id: string, title: string, celex: string[] = []): DossierSummary =>
  ({ id, title, official_title: null, short: null, ref: id.replace('-', '/') + '(COD)', type: 'COD', celex }) as unknown as DossierSummary;
const ROWS = [row('2021-0106', 'Artificial Intelligence Act', ['32024R1689']), row('2020-0353', 'Batteries and waste batteries')];

describe('legislation explorer keyword box', () => {
  it('builds the word lists of a loaded file list once, the same as buildHaystacks', () => {
    const once = buildHaystacksOnce(ROWS);
    expect(buildHaystacksOnce(ROWS)).toBe(once); // a page opened again, or a search typed again, reuses them
    expect(once).toEqual(buildHaystacks(ROWS));
    expect(buildHaystacksOnce([...ROWS])).not.toBe(once);
    // until the search index loads, the words stand in for it
    expect([...keywordScores(ROWS, once, null, 'battery').keys()]).toEqual(['2020-0353']);
    expect([...keywordScores(ROWS, once, null, '2024/1689').keys()]).toEqual(['2021-0106']);
  });
});

describe('legislation explorer: next scheduled step', () => {
  // TEST-ONLY rows with the fields the order reads
  const f = (id: string, next_scheduled?: string, last_event = '2026-01-01') =>
    ({ id, stage: 'negotiations', last_event, ...(next_scheduled ? { next_scheduled } : {}) }) as unknown as DossierSummary;
  it('puts planned steps on or after the reader’s date first, soonest first; a passed one counts as none', () => {
    const rows = [f('a'), f('b', '2026-11-19'), f('c', '2026-11-04', '2026-06-01'), f('d', '2026-11-06'), f('e', undefined, '2026-09-01')];
    expect(sortRows(rows, 'scheduled', new Map(), '2026-11-05').map((r) => r.id)).toEqual(['d', 'b', 'e', 'c', 'a']);
  });
});
