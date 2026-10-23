/**
 * Dossier pages on the real build (public/data): split procedures' parents, Parliament's R/M reports and the
 * "Latest verified development". Skipped when the data has not been built.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, TimelineEvent } from '../../../types/data';
import { latestDone } from './Summary';

const DATA = new URL('../../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

const ev = (id: string, date: string, key: boolean): TimelineEvent =>
  ({ id, date, key, state: 'done', title: id, kind: 'other', institution: 'EP' }) as unknown as TimelineEvent;

describe('latest verified development', () => {
  it('takes the key step of the latest day, whatever the order of that day’s steps', () => {
    const tl = [ev('vote', '2026-09-15', false), ev('referral', '2026-09-15', true), ev('tabled', '2026-09-15', false)];
    expect(latestDone(tl, '2026-10-23')?.id).toBe('referral');
    expect(latestDone([ev('a', '2026-09-14', true), ev('b', '2026-09-15', false)], '2026-10-23')?.id).toBe('b');
    expect(latestDone([ev('a', '2026-11-01', true)], '2026-10-23')).toBeNull();
  });
});

describe.skipIf(!built)('dossiers on the built data', () => {
  const ids = built ? readdirSync(new URL('dossiers/', DATA)).filter((f) => f !== 'index.json').map((f) => f.replace(/\.json$/, '')) : [];
  const all = ids.map((id) => read<DossierDetail>(`dossiers/${id}.json`));

  it('agrees with "Where is it now?" on the latest milestone when both fall on the same day (2025-0418, 2026-0085)', () => {
    const today = '2026-10-23';
    for (const d of all) {
      const latest = latestDone(d.timeline, today);
      const milestone = [...d.timeline].reverse().find((e) => e.state === 'done' && e.key && e.date <= today);
      if (latest && milestone && latest.date === milestone.date && !latest.after_end_of_validity) expect(latest.id, d.id).toBe(milestone.id);
    }
    const d = all.find((x) => x.id === '2025-0418')!;
    expect(latestDone(d.timeline, today)!.title).toBe('Parliament sent the file back to committee to negotiate with the Council');
  });

  it('never shows a generated name as a split parent’s official title, and tells its parts apart', () => {
    const parents = all.filter((d) => d.related.some((r) => r.relation === 'Split into'));
    expect(parents.length).toBe(12);
    for (const d of parents) {
      expect(d.official_title ?? '', d.id).not.toMatch(/split into/);
      const parts = d.related.filter((r) => r.relation === 'Split into');
      expect(new Set(parts.map((r) => r.ref)).size, d.id).toBe(parts.length);
      for (const r of parts) expect(r.status_label, `${d.id} ${r.id}`).toBeTruthy();
      expect(d.status.named_acts?.map((a) => a.dossier), d.id).toEqual(parts.map((r) => r.id));
    }
    const p400 = parents.find((d) => d.id === '2016-0400')!;
    expect(p400.official_title).toBeNull();
    expect(p400.related.filter((r) => r.relation === 'Split into').map((r) => [r.ref, r.status_label])).toEqual([
      ['2016/0400A(COD)', 'In force'],
      ['2016/0400B(COD)', 'Withdrawn by the Commission'],
    ]);
    expect(parents.find((d) => d.id === '2016-0224')!.official_title?.trim()).toBe('Common procedure for international protection in the Union');
  });

  it('links the main file from a Parliament report’s status and next step, and the report from the main file', () => {
    const reports = all.filter((d) => /^\d{4}-\d{4}[RM]$/.test(d.id));
    expect(reports.map((d) => d.id).sort()).toEqual(['2017-0333R', '2018-0166R', '2020-0112R', '2021-0429R', '2023-0201M', '2023-0201R', '2025-0571R']);
    for (const d of reports) {
      const main = d.id.slice(0, 9);
      const link = d.status.named_acts?.find((a) => a.dossier === main);
      expect(link, d.id).toBeTruthy();
      expect(d.status.explanation).toContain(link!.label);
      expect(d.next_step.text).toContain(link!.label);
      const back = read<DossierDetail>(`dossiers/${main}.json`).related.find((r) => r.id === d.id);
      expect(back?.relation, d.id).toMatch(/^Parliament's (interim )?report$/);
      // the two have the same title (2020/0112(APP) and 2020/0112R(APP)): each link gives the other's reference
      expect(back?.ref, d.id).toBe(d.ref);
      expect(d.related.find((r) => r.relation === 'Report on')?.ref, d.id).toBe(read<DossierDetail>(`dossiers/${main}.json`).ref);
    }
  });

  it('names a rapporteur’s committee as OEIL does where the EP API gives none or a subcommittee', () => {
    const committee = (id: string, mep: string) => all.find((d) => d.id === id)!.rapporteurs.find((r) => r.mep_id === mep)?.committee;
    expect(committee('2021-0240', '96899')).toBe('CONT'); // EP API "org/null"; OEIL: CONT, FERNANDES José Manuel
    expect(committee('2025-0045', '204332')).toBe('AFET'); // EP API DROI; OEIL: AFET, ANDREWS Barry
    expect(all.find((d) => d.id === '2023-0187')!.rapporteurs.filter((r) => r.role === 'rapporteur').map((r) => r.committee)).toEqual(['ECON']);
    for (const d of all) for (const r of d.rapporteurs) expect(r.committee, `${d.id} ${r.mep_id}`).not.toBe('null');
  });
});
