/**
 * Steps the Council and Parliament have scheduled (pipeline/analysis/scheduled.py), on the reader's date: the data is
 * rebuilt weekly, so a planned date can pass while the page is read. A step stays ahead on its day (the meeting may
 * not have taken place yet), is then said to have been scheduled on the file's page and left out of the home page's
 * list; it is never shown as done.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, DossierSummary, HomeData, Meta, ScheduledStep } from '../../../types/data';
import { PLANNED_BADGE, plannedAhead, stillAhead } from '../../../lib/format';
import { passedNote, plannedState, stepLabel } from './ScheduledNext';

// 2023/0167(COD), retail investment: the Council's adoption planned for 19 November 2026 (Cellar, 5 November 2026)
const ADOPTION: ScheduledStep = {
  date: '2026-11-19',
  institution: 'Council',
  label: "Approval of the EP's first reading position by the Council (adoption of the legislative act)",
  meeting: 'Council of the European Union (General Affairs)',
  documents: [{ id: 'CM 4825/26', kind: 'agenda', url: 'https://data.consilium.europa.eu/doc/document/CM-4825-2026-INIT/EN/pdf' }],
  sources: [{ institution: 'EUR-Lex', url: 'https://publications.europa.eu/resource/procedure-event/2023_167.2026-11-19_APR_R1_byCONSIL' }],
};

describe('a scheduled step on the reader’s date', () => {
  it('is ahead until its day is over, then passed', () => {
    expect(plannedState(ADOPTION, '2026-11-05')).toBe('ahead');
    expect(plannedState(ADOPTION, '2026-11-19')).toBe('ahead');
    expect(plannedState(ADOPTION, '2026-11-20')).toBe('passed');
    expect(plannedAhead('2026-11-19', '2026-11-19')).toBe(true);
  });

  it('is said to have been scheduled once passed, never shown as done', () => {
    expect(passedNote(ADOPTION)).toBe('Was scheduled for 19 November 2026; not yet recorded as done.');
  });

  it('gives the reading with the step', () => {
    expect(stepLabel({ label: 'Vote in EP plenary', phase: 'Second reading' })).toBe('Vote in EP plenary (second reading)');
    expect(stepLabel(ADOPTION)).toBe(ADOPTION.label);
  });

  it('is left out of the home page’s list once its day is over', () => {
    const items = [
      { date: '2026-11-12', badge: PLANNED_BADGE },
      { date: '2026-11-19', badge: PLANNED_BADGE },
    ];
    expect(stillAhead(items, '2026-11-12')).toEqual(items);
    expect(stillAhead(items, '2026-11-13')).toEqual([items[1]]);
    expect(stillAhead(items, '2026-11-20')).toEqual([]);
  });
});

// ------------------------------------------------------------------ the built data (skipped without planned steps)
const DATA = new URL('../../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;
const files = built ? read<DossierSummary[]>('dossiers/index.json').map((d) => read<DossierDetail>(`dossiers/${d.id}.json`)) : [];
const planned = files.filter((d) => d.scheduled?.length);

describe.skipIf(!planned.length)('scheduled steps in the built data', () => {
  const buildDay = read<Meta>('meta.json').built_at.slice(0, 10);
  const home = read<HomeData>('home.json').lists.find((l) => l.id === 'scheduled')!;

  it('are all ahead of the build, by date, each with its source', () => {
    for (const d of planned) {
      const steps = d.scheduled!;
      expect(steps.map((s) => s.date), d.id).toEqual([...steps.map((s) => s.date)].sort());
      for (const s of steps) {
        expect(s.date > buildDay, `${d.id} ${s.date}`).toBe(true);
        expect(plannedState(s, buildDay)).toBe('ahead');
        expect(s.sources.length, d.id).toBeGreaterThan(0);
        expect(s.label.trim(), d.id).not.toBe('');
      }
    }
  });

  it('list the next three weeks on the home page, and leave out each once its day is over', () => {
    expect(home.items.length).toBeGreaterThan(0);
    const end = new Date(Date.parse(buildDay) + 21 * 86_400_000).toISOString().slice(0, 10);
    for (const it of home.items) {
      expect(it.badge).toBe(PLANNED_BADGE);
      expect(it.date! > buildDay && it.date! <= end, `${it.dossier_id} ${it.date}`).toBe(true);
      const step = files.find((d) => d.id === it.dossier_id)?.scheduled?.find((s) => s.date === it.date);
      expect(step, `${it.dossier_id} ${it.date}`).toBeDefined();
    }
    expect(stillAhead(home.items, buildDay)).toEqual(home.items);
    const last = home.items.at(-1)!.date!;
    const after = new Date(Date.parse(last) + 86_400_000).toISOString().slice(0, 10);
    expect(stillAhead(home.items, after)).toEqual([]);
  });
});
