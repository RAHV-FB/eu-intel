/**
 * Dossier pages on the real build (public/data): split procedures' parents, Parliament's R/M reports and the
 * "Latest verified development". Skipped when the data has not been built.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CoverageScope, DossierDetail, Meta, TimelineEvent } from '../../../types/data';
import { latestDone } from './Summary';
import { noCouncilVoteNote } from './Votes';
import { currentStepKey } from './WhereIsIt';

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

describe('why a file shows no Council vote', () => {
  const scope = { council_votes_from: '2019-01-28', council_votes_to: '2026-10-19' } as CoverageScope;
  const step = { ...ev('council', '2022-12-14', true), kind: 'council_adoption', title: 'Council adopted the act after consulting Parliament' } as TimelineEvent;

  it('does not call a file adopted within the period of our Council data under discussion or outside it (2021-0433)', () => {
    const note = noCouncilVoteNote([step], '2022-12-14', scope);
    expect(note).toContain('Its timeline records “Council adopted the act after consulting Parliament” on 14 December 2022, within the period');
    expect(note).toContain('28 January 2019 to 19 October 2026');
    expect(note).not.toContain('under discussion');
  });

  it('says when the Council’s step falls before or after the Council votes in our data, and keeps the general reason otherwise', () => {
    expect(noCouncilVoteNote([{ ...step, date: '2018-03-12' }], '2018-03-12', scope)).toContain('before the first Council vote in our data (28 January 2019)');
    expect(noCouncilVoteNote([{ ...step, date: '2026-10-21' }], null, scope)).toContain('after the latest Council vote in our data (19 October 2026)');
    expect(noCouncilVoteNote([], '2020-08-06', scope)).toContain('The file was adopted on 6 August 2020, within the period');
    expect(noCouncilVoteNote([], null, scope)).toContain('files still under discussion, or adopted outside the period covered (28 January 2019 to 19 October 2026)');
    expect(noCouncilVoteNote([step], '2022-12-14', undefined)).toContain('files still under discussion');
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

  it('says why a file adopted while our Council data runs has no Council vote, and links CRR II’s (2016-0360A)', () => {
    const scope = read<Meta>('meta.json').scope;
    expect([scope?.council_votes_from, scope?.council_votes_to]).toEqual(['2019-01-28', '2026-10-19']);
    const none = all.filter((d) => d.council_votes.length === 0 && !d.related.some((r) => r.relation === 'Split into'));
    const within = none.filter((d) => noCouncilVoteNote(d.timeline, d.adopted, scope).includes('within the period'));
    expect(within.map((d) => d.id)).toContain('2021-0433');
    expect(within.map((d) => d.id)).not.toContain('2016-0360A');
    for (const d of none) {
      const step = [...d.timeline].reverse().find((e) => e.state === 'done' && (e.kind === 'council_adoption' || e.kind === 'council_position'));
      if (step || d.adopted) expect(noCouncilVoteNote(d.timeline, d.adopted, scope), d.id).not.toContain('under discussion');
    }
  });

  it('never shows a recorded provisional agreement as not yet reached on the path (2023-0210, 2023-0134)', () => {
    const at = (id: string) => currentStepKey(all.find((d) => d.id === id)!);
    expect(at('2023-0210')).toBe('adopted'); // early second-reading agreement approved in committee on 5 May 2026
    expect(at('2023-0134')).toBe('adopted'); // "Approved by Parliament" on the text agreed with the Council
    expect(at('2018-0332')).toBe('deciding'); // negotiations after the first reading, no agreement recorded
    const order = ['proposed', 'deciding', 'agreement', 'adopted', 'in_force'];
    for (const d of all.filter((x) => x.type === 'COD')) {
      const agreed = d.timeline.some((e) => e.state === 'done' && e.kind === 'provisional_agreement');
      const key = currentStepKey(d);
      if (agreed && key) expect(order.indexOf(key), d.id).toBeGreaterThanOrEqual(order.indexOf('agreement'));
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
