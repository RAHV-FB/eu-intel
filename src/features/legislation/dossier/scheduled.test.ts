/**
 * Steps the build scheduled, on the visitor's date: "Latest recorded step" and the next date fixed in law
 * (Summary.tsx) read them the way the timeline shows them (format.ts eventOn).
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail } from '../../../types/data';
import { latestDone, nextScheduled } from './Summary';

const DATA = new URL('../../../../public/data/', import.meta.url);
const file = new URL('dossiers/2022-0167.json', DATA);

// 2022/0167(COD), Directive (EU) 2024/1260 (asset recovery and confiscation): in the build of 23 October 2026 its
// transposition deadline, 23 November 2026, is the last step, scheduled
describe.skipIf(!existsSync(file))('a scheduled step once its date has come', () => {
  const d = existsSync(file) ? (JSON.parse(readFileSync(file, 'utf8')) as DossierDetail) : null;

  it('is the next date fixed in law until its day is over, then the latest development, in the past tense', () => {
    const tl = d!.timeline;
    expect(tl.at(-1)).toMatchObject({ kind: 'transposition_deadline', state: 'scheduled', date: '2026-11-23' });
    expect(nextScheduled(tl, '2026-11-23')?.title).toBe('Deadline for Member States to transpose the directive');
    expect(latestDone(tl, '2026-11-23')?.title).toBe('Entered into force');
    // the timeline showed it done from 24 November, but "Latest recorded step" kept the entry into force
    expect(latestDone(tl, '2026-11-24')).toMatchObject({
      kind: 'transposition_deadline',
      state: 'done',
      title: 'Deadline for Member States to transpose the directive (passed)',
    });
    expect(nextScheduled(tl, '2026-11-24')).toBeNull();
  });
});
