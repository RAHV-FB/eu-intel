/**
 * Dossier pages on the real build (public/data): split procedures' parents, Parliament's R/M reports and the
 * "Latest verified development". Skipped when the data has not been built.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, TimelineEvent } from '../../../types/data';
import { institutionSuffix } from '../labels';
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

describe('steps dated in the act', () => {
  it('names no institution after them: EUR-Lex records them, the act sets them', () => {
    expect(institutionSuffix('Entered into force', 'EUR-Lex', 'entry_into_force')).toBe('');
    expect(institutionSuffix('Started to apply: The Regulation in general (Art. 93(2))', 'EUR-Lex', 'application')).toBe('');
    expect(institutionSuffix('Published in the Official Journal of the EU', 'EUR-Lex', 'publication')).toBe('EUR-Lex');
  });
});

describe.skipIf(!built)('application dates, act names and sources on the built data', () => {
  const ids = built ? readdirSync(new URL('dossiers/', DATA)).filter((f) => f !== 'index.json').map((f) => f.replace(/\.json$/, '')) : [];
  const all = ids.map((id) => read<DossierDetail>(`dossiers/${id}.json`));
  const byId = (id: string) => all.find((d) => d.id === id)!;

  it('never presents an application date EUR-Lex gives as not recorded as applying from the entry into force (ETIAS, VIS)', () => {
    // Regulation (EU) 2018/1240, Art. 96: "This Regulation shall apply from the date determined by the Commission"
    const etias = byId('2016-0357A');
    expect(etias.application?.application_unrecorded).toEqual([{ partial: false, articles: ['Art. 96'] }]);
    expect(etias.status.explanation).toContain('EUR-Lex records no date from which the act in general applies (it refers to Art. 96).');
    expect(etias.next_step.text).not.toMatch(/^The regulation applies directly/);
    const vis = byId('2018-0152A');
    expect(vis.next_step.text).toContain('EUR-Lex records no date from which this regulation in general applies.');
    for (const d of all)
      if (d.application?.application_unrecorded?.some((x) => !x.partial) && d.instrument === 'regulation' && d.stage === 'in_force')
        expect(d.next_step.text, d.id).not.toMatch(/^The regulation applies directly/);
  });

  it('gives the dates set since by the decision the act refers to (Clinical Trials Regulation, EPPO, PRIMA)', () => {
    const ctr = byId('2012-0192');
    expect(ctr.application?.application_detail).toEqual([{ date: '2022-01-31', partial: false, provisions: 'The Regulation (Art. 99, second paragraph)' }]);
    expect(byId('2013-0255').application?.application_dates).toEqual(['2021-06-01']);
    expect(byId('2016-0325').status.since).toBe('2017-08-07'); // Decision (EU) 2017/1324, Art. 15: twentieth day after 18.7.2017
  });

  it('cites a checked date’s text as its source, never EUR-Lex’s record that lacks it (DSA, Return Regulation)', () => {
    const dated = new Set(['entry_into_force', 'application', 'transposition_deadline', 'transposition_application']);
    let n = 0;
    for (const d of all)
      for (const e of d.timeline)
        if (dated.has(e.kind) && e.source?.label?.includes('(checked ')) {
          n++;
          expect(e.source.url, `${d.id} ${e.id}`).toBe(e.docs?.[0]?.url);
          expect(e.source.label, `${d.id} ${e.id}`).not.toContain('Cellar');
        }
    expect(n).toBeGreaterThan(20);
    const dsa = byId('2020-0361').timeline.find((e) => e.kind === 'application' && e.date === '2024-02-17')!;
    expect(dsa.source?.label).toBe('Regulation (EU) 2022/2065, Article 93 (checked 23 October 2026)');
  });

  it('names an act by its number in its steps, never by a type word and its CELEX id', () => {
    for (const d of all) for (const e of d.timeline) expect(e.detail ?? '', `${d.id} ${e.id}`).not.toMatch(/^(?:Regulation|Directive|Decision|Act) 3\d{4}[A-Z]\d{4}/);
    expect(byId('2016-0002').timeline.find((e) => e.kind === 'entry_into_force')?.detail).toBe('Directive (EU) 2019/884');
  });

  it('calls the first date from which any of an act applies "Rules", not "Further provisions" (PPWR)', () => {
    // Regulation (EU) 2025/40, Art. 71: "It shall apply from 12 August 2026. However, Article 67(5) shall apply from 12 February 2029."
    expect(byId('2022-0396').timeline.find((e) => e.kind === 'application' && e.date === '2026-08-12')?.title).toBe(
      'Rules started to apply (date recorded by EUR-Lex)',
    );
    // Regulation (EU) 2026/1388, Art. 38: some provisions apply from its entry into force, so 17 July 2028 is further
    expect(byId('2023-0226').timeline.find((e) => e.kind === 'application' && e.date === '2028-07-17')?.title).toBe(
      'Further provisions start to apply (date recorded by EUR-Lex)',
    );
  });

  it('titles a file after its adopted act where the procedure’s title is a placeholder or names other acts', () => {
    const placeholder = /\[(?:X+|…|\.\.\.)\]|\bX{3,}\b|\.\.\.\/\.\.\./;
    for (const d of all) if (d.acts.length) expect(`${d.title} ${d.official_title ?? ''}`, d.id).not.toMatch(placeholder);
    expect(byId('2023-0393').title).toBe('Extending Directive (EU) 2024/2841 to third-country nationals legally residing in a Member State');
    expect(byId('2021-0395').official_title).not.toContain('2002/465');
    const dk = read<{ transposition: { celex: string; title: string; status: string; status_note?: string | null }[] }>('countries/DK.json');
    const row = (c: string) => dk.transposition.find((t) => t.celex === c)!;
    expect(row('32024L2842').title).not.toMatch(placeholder);
    expect(row('32023L2843').title).toContain('2011/99/EU');
    // Directive (EU) 2023/977 builds upon the Schengen acquis: Denmark decided to implement it (ST 15298/23)
    expect(row('32023L0977').status_note).toContain('Denmark decided to implement it in its national law under Article 4 of Protocol No 22');
  });

  it('links the AI Act to Directive 2014/90/EU, which its Art. 105 amends, not to Implementing Regulation No 90/2014', () => {
    const ai = byId('2021-0106');
    expect(ai.acts[0].amends).toContain('32014L0090');
    expect(ai.acts[0].amends).not.toContain('32014R0090');
    expect(byId('2012-0358').related.filter((r) => r.relation === 'Amended by').map((r) => r.id)).toContain('2021-0106');
  });

  it('cites a split proposal’s parts on its page, not the EUR-Lex record of one part’s act', () => {
    const parents = all.filter((d) => d.related.some((r) => r.relation === 'Split into'));
    for (const d of parents) {
      expect(d.sources.filter((s) => s.institution === 'EUR-Lex'), d.id).toEqual([]);
      for (const s of d.sources) expect(s.label ?? '', d.id).not.toMatch(/\d{4}\/\d{4}[A-Z]\(COD\)$/);
    }
    expect(byId('2016-0400').sources.map((s) => s.label)).toEqual([
      'Legislative Observatory (OEIL) – procedure file 2016/0400A(COD) (separate file)',
      'Legislative Observatory (OEIL) – procedure file 2016/0400B(COD) (separate file)',
    ]);
  });
});
