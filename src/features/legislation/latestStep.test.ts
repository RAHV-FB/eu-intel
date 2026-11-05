/**
 * A file's latest recorded step in lists, on the reader's date: the step the build names, or a step dated in the law that
 * has passed since (steps_ahead), as the file's page counts it (latestDone).
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, DossierSummary, SearchDoc } from '../../types/data';
import { latestDone } from './dossier/Summary';
import { latestDateOn, latestStepOn, withLatestStepOn } from './latestStep';
import { sortRows } from './explorer';

// 2022/0167(COD), Directive (EU) 2024/1260 as built on 23 October 2026: entered into force on 22 May 2024; its
// transposition deadline, 23 November 2026, ahead
const ROW = {
  last_event: '2024-05-22',
  last_step: { title: 'Entered into force', kind: 'entry_into_force' as const },
  steps_ahead: [{ date: '2026-11-23', kind: 'transposition_deadline' as const, title: 'Deadline for Member States to transpose the directive', key: true }],
};

describe('the latest recorded step in lists', () => {
  it('is the build’s until a step dated in the law has passed, then that step, in the past tense', () => {
    expect(latestStepOn(ROW, '2026-11-05')).toEqual({ date: '2024-05-22', title: 'Entered into force', kind: 'entry_into_force' });
    // a deadline passes once its day is over
    expect(latestStepOn(ROW, '2026-11-23')?.date).toBe('2024-05-22');
    expect(latestStepOn(ROW, '2026-11-24')).toEqual({
      date: '2026-11-23',
      title: 'Deadline for Member States to transpose the directive (passed)',
      kind: 'transposition_deadline',
    });
    expect(latestDateOn(ROW, '2026-11-24')).toBe('2026-11-23');
    // an entry into force has come on its day
    const eif = { ...ROW, steps_ahead: [{ date: '2026-11-24', kind: 'entry_into_force' as const, title: 'Enters into force', key: true }] };
    expect(latestStepOn(eif, '2026-11-24')?.title).toBe('Entered into force');
    expect(latestStepOn({ last_event: '2026-01-01' }, '2026-11-05')).toBeNull(); // a date without a named step
  });

  it('rolls rows forward for sorting, leaving the others as they are', () => {
    const plain = { id: 'b', last_event: '2026-10-01', last_step: { title: 'Council adopted the act', kind: 'council_adoption' as const } };
    const rows = [{ id: 'a', ...ROW }, plain] as unknown as DossierSummary[];
    expect(withLatestStepOn(rows, '2026-11-05')).toBe(rows);
    const on = withLatestStepOn(rows, '2026-11-24');
    expect(on[0]).toMatchObject({ last_event: '2026-11-23', last_step: { kind: 'transposition_deadline' } });
    expect(on[1]).toBe(rows[1]);
    // "Recently updated" then puts the file whose deadline passed first
    expect(sortRows(on, 'updated', new Map(), '2026-11-24').map((d) => d.id)).toEqual(['a', 'b']);
    expect(sortRows(rows, 'updated', new Map(), '2026-11-05').map((d) => d.id)).toEqual(['b', 'a']);
  });
});

describe('the stuck view', () => {
  const r = (id: string, stage: string, last?: string) => ({ id, stage, last_event: last }) as unknown as DossierSummary;
  it('lists files still being decided first, the longest without a recorded step first; the others after', () => {
    const rows = [
      r('adopted-old', 'in_force', '2015-01-01'),
      r('recent', 'negotiations', '2026-10-01'),
      r('no-step', 'proposed'),
      r('oldest', 'parliament_position', '2015-06-10'),
      r('adopted-new', 'in_force', '2026-10-30'),
      r('old', 'proposed', '2023-12-14'),
    ];
    expect(sortRows(rows, 'stuck', new Map(), '2026-11-05').map((d) => d.id)).toEqual([
      'oldest',
      'old',
      'recent',
      'no-step',
      'adopted-new',
      'adopted-old',
    ]);
  });
});

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;
const plusDays = (d: string, n: number) => new Date(Date.parse(`${d}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);

describe.skipIf(!built)('the latest step on the built data', () => {
  const index = built ? read<DossierSummary[]>('dossiers/index.json') : [];
  const search = built ? new Map(read<SearchDoc[]>('search.json').filter((d) => d.k === 'dossier').map((d) => [d.id, d])) : new Map();
  const builtOn = built ? read<{ built_at: string }>('meta.json').built_at.slice(0, 10) : '';

  it('names in lists the step the file’s page names, on the build’s date and the weeks after it', () => {
    // every file with a step dated in the law ahead, and a sample of the others
    const sample = [...index.filter((d) => d.steps_ahead?.length), ...index.filter((_, i) => i % 40 === 0)];
    expect(sample.some((d) => d.steps_ahead?.length)).toBe(true);
    for (const d of sample) {
      const detail = read<DossierDetail>(`dossiers/${d.id}.json`);
      const doc = search.get(d.id);
      for (const today of [builtOn, plusDays(builtOn, 20), plusDays(builtOn, 50)]) {
        const page = latestDone(detail.timeline, today);
        const listed = latestStepOn(d, today);
        expect(listed?.date ?? null, `${d.id} ${today}`).toBe(page?.date ?? null);
        expect(listed?.title ?? null, `${d.id} ${today}`).toBe(page?.title ?? null);
        // search results name the same step
        const found = doc?.e ? latestStepOn({ last_event: doc.d, last_step: { title: doc.e, kind: 'other' }, steps_ahead: doc.n }, today) : null;
        expect(found?.title ?? null, `${d.id} ${today} (search)`).toBe(page?.title ?? null);
      }
    }
  });
});
