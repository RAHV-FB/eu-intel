/**
 * The Insights legislative charts on the built index (public/data from `python -m pipeline build`): each legislative
 * procedure counted once. Skipped when the data has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierSummary } from '../../types/data';
import { legislativePatterns } from './analysis';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe.skipIf(!built)('Insights on the built index', () => {
  const files = built ? read<DossierSummary[]>('dossiers/index.json') : [];
  const x = legislativePatterns(files);

  it('counts no split file or Parliament report as "Not determinable", and no proposal twice', () => {
    const split = files.filter((f) => f.status_label === 'Split into separate procedures');
    const reports = files.filter((f) => f.status_label === 'Parliament report (not a legislative act)');
    expect(split.length).toBeGreaterThan(0);
    expect([x.splitParents, x.reports]).toEqual([split.length, reports.length]);
    expect(x.counted).toBe(files.length - split.length - reports.length);
    expect(x.stages.reduce((n, s) => n + s.count, 0)).toBe(x.counted);
    const left = new Set([...split, ...reports].map((f) => f.id));
    const unknown = files.filter((f) => f.stage === 'unknown' && !left.has(f.id)).length;
    expect(x.stages.find((s) => s.id === 'unknown')?.count ?? 0).toBe(unknown);
    // each split file's proposal date is its parts': the parts are counted, the file itself is not counted again
    for (const p of split) {
      const parts = files.filter((f) => f.id.length === p.id.length + 1 && f.id.startsWith(p.id) && !/[RM]$/.test(f.id));
      expect(parts.length, p.id).toBeGreaterThan(1);
      expect(
        parts.every((f) => f.started === p.started),
        p.id,
      ).toBe(true);
    }
    const byYear = new Map<number, number>();
    for (const f of files)
      if (f.started && !left.has(f.id)) byYear.set(Number(f.started.slice(0, 4)), (byYear.get(Number(f.started.slice(0, 4))) ?? 0) + 1);
    for (const t of x.timeline) expect(t.introduced, String(t.year)).toBe(byYear.get(t.year) ?? 0);
  });
});
