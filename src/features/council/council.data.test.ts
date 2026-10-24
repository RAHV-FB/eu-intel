/**
 * Council votes on the real build (public/data from `python -m pipeline build`). Skipped when the data has not been
 * built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CountryDetail, CountrySummary, CouncilVote, DossierDetail, Meta } from '../../types/data';
import { formatNumber } from '../../lib/format';
import { councilRowTag, councilRowTitle } from './CouncilVoteCard';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('council/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe.skipIf(!built)('Council votes on the built data', () => {
  const votes = new Map((built ? read<CouncilVote[]>('council/index.json') : []).map((v) => [v.id, v]));

  it('includes the voting results whose Cellar title starts with a dash or bullet (wolf Directive, ST 9887/25)', () => {
    const wolf = votes.get('ST-9887-2025')!;
    expect(wolf.dossier_id).toBe('2025-0058');
    expect(Object.entries(wolf.positions).filter(([, p]) => p === 'abstain').map(([c]) => c).sort()).toEqual(['BE', 'ES', 'PL']);
  });

  it('shows unanimity where the legal basis requires it, saying what the sheet prints', () => {
    for (const v of votes.values()) {
      if (v.sheet_voting_rule) {
        expect(v.voting_rule, v.id).toBe('unanimity');
        expect(v.voting_rule_note ?? '', v.id).toContain('labels the voting rule “qualified majority”');
      }
      if (v.voting_rule !== 'unanimity' && v.assessment) expect(v.assessment.single_state_veto_possible, v.id).toBe(false);
    }
    expect([...votes.values()].filter((v) => v.sheet_voting_rule).map((v) => v.id).sort()).toEqual([
      'ST-15907-2022',
      'ST-5698-2024',
      'ST-7391-2020',
      'ST-9781-2024',
    ]);
  });

  it('dates the MFF amendment by its unanimous adoption on 15 December 2022, not the blocked vote of 6 December', () => {
    const blocked = votes.get('ST-15907-2022')!;
    expect([blocked.outcome, blocked.sheet_outcome]).toEqual(['not_adopted', 'adopted']);
    expect(votes.get('CM-5860-2022')!.positions.HU).toBe('abstain');
    const d = read<DossierDetail>('dossiers/2022-0369.json');
    expect(d.adopted).toBe('2022-12-15');
  });

  it('records the Pillar Two Directive’s adoption from the same communication, Hungary abstaining (CM 5860/22, point 2)', () => {
    // "all delegations voted in favour of, except for Hungary that abstained"; "completed on 15 December 2022 at 22:11"
    const cm = votes.get('CM-5860-2022-2')!;
    expect([cm.dossier_id, cm.date, cm.voting_rule, cm.outcome, cm.positions.HU]).toEqual(['2021-0433', '2022-12-15', 'unanimity', 'adopted', 'abstain']);
    expect(Object.values(cm.positions).filter((p) => p === 'for')).toHaveLength(26);
    expect(cm.source_note).toContain('Council Directive (EU) 2022/2523 of 14 December 2022');
    const hu = read<CountryDetail>('countries/HU.json');
    expect(hu.council_votes.find((r) => r.vote_id === 'CM-5860-2022-2')?.pos).toBe('abstain');
  });

  it('names the item voted on in country rows: Member States voted for the non-approval of Parliament’s amendments', () => {
    const de = read<CountryDetail>('countries/DE.json');
    const row = de.council_votes.find((r) => r.vote_id === 'ST-14700-2026')!;
    expect(row.pos).toBe('for');
    expect(row.display_title).toContain('Non-approval of the European Parliament');
    const hu = read<CountryDetail>('countries/HU.json');
    expect(hu.council_votes.find((r) => r.vote_id === 'ST-15907-2022')?.outcome).toBe('not_adopted');
  });

  it('names the derogation from the eight-week period as the item of ST 8160/20, on the card and in country rows', () => {
    const derog = votes.get('ST-8160-2020')!;
    expect(derog.vote_on).toBe('other');
    expect(derog.vote_on_label).toMatch(/^Derogation from the eight-week period for national parliaments/);
    const pt = read<CountryDetail>('countries/PT.json').council_votes.find((r) => r.vote_id === 'ST-8160-2020')!;
    expect([pt.pos, pt.vote_on_label]).toEqual(['abstain', derog.vote_on_label]);
    expect(pt.display_title).not.toContain('Adoption of the legislative act');
  });

  it('does not show the Council’s position on a draft amending budget as an act adopted (ST 10354/25)', () => {
    const dab = votes.get('ST-10354-2025')!;
    expect([dab.vote_on, dab.vote_on_label ?? null]).toEqual(['other', null]);
    expect(dab.vote_on_note ?? '').toContain('2025/0091(BUD)');
  });

  it('links the texts a rule or outcome correction was checked against, on the vote and its timeline step', () => {
    for (const v of votes.values()) if (v.sheet_voting_rule) expect(v.correction_sources?.length ?? 0, v.id).toBeGreaterThan(0);
    const step = read<DossierDetail>('dossiers/2022-0369.json').timeline.find((e) => e.id === 'council-ST-15907-2022')!;
    expect(step.title).toBe('Council did not adopt the act');
    expect(step.docs.map((d) => d.label)).toContain('Council of the EU – ST 15179/22');
  });

  it('links ST 9252/19 ("Interinstitutional File: 2016/0360 A (COD)") to the CRR II part, as an ordinary-procedure act', () => {
    const v = votes.get('ST-9252-2019')!;
    expect(v.dossier_id).toBe('2016-0360A');
    expect([v.assessment?.legal_basis, v.assessment?.states_required]).toEqual(['TEU Art. 16(4)', 16]);
    expect(read<DossierDetail>('dossiers/2016-0360A.json').council_votes.map((c) => c.id)).toEqual(['ST-9252-2019']);
    expect(read<CountryDetail>('countries/FR.json').council_votes.find((r) => r.vote_id === 'ST-9252-2019')?.dossier_id).toBe('2016-0360A');
  });

  it('marks every vote as taken at a meeting or by written procedure (ST 7236/20, 7237/20, 7360/20)', () => {
    expect([...votes.values()].filter((v) => v.written_procedure == null).map((v) => v.id)).toEqual([]);
    // Position (EU) No 8/2020 "Adopted by the Council on 15 April 2020"; the note is dated 16 April
    const taxonomy = votes.get('ST-7360-2020')!;
    expect([taxonomy.date, taxonomy.written_procedure, taxonomy.meeting ?? null]).toEqual(['2020-04-15', true, null]);
    const step = read<DossierDetail>('dossiers/2018-0178.json').timeline.find((e) => e.id === 'council-ST-7360-2020')!;
    expect([step.date, step.title]).toEqual(['2020-04-15', 'Council adopted its position at first reading (written procedure)']);
  });

  it('tags a country row with the item voted on, outside the title that phones clamp (ST 8160/20 beside ST 8159/20)', () => {
    const be = read<CountryDetail>('countries/BE.json').council_votes;
    const derog = be.find((r) => r.vote_id === 'ST-8160-2020')!;
    const act = be.find((r) => r.vote_id === 'ST-8159-2020')!;
    expect([derog.pos, act.pos]).toEqual(['for', 'against']);
    expect(councilRowTag(derog)).toBe(derog.vote_on_label);
    expect(councilRowTag(act)).toBeNull();
    expect(councilRowTitle(derog)).toBe(councilRowTitle(act)); // the same act; the tag tells the rows apart
    for (const r of be.filter((x) => x.vote_on === 'other')) {
      expect(councilRowTag(r), r.vote_id).toBe(r.vote_on_label || 'Other Council decision');
      if (r.vote_on_label) expect(councilRowTitle(r).endsWith(r.vote_on_label), r.vote_id).toBe(false);
    }
  });

  it('gives the About page and the country pages the same Council totals (747 votes, 745 with positions)', () => {
    const meta = read<Meta>('meta.json');
    const listed = [...votes.values()];
    const withPositions = listed.filter((v) => Object.keys(v.positions).length > 0).length;
    const summary = meta.sources.find((s) => s.id === 'council')!.summary ?? '';
    const coverage = meta.coverage_notes.find((n) => n.startsWith('Council votes:'))!;
    expect(meta.counts.council_votes).toBe(listed.length);
    expect(summary.startsWith(`${formatNumber(listed.length)} votes of the Council of the EU`)).toBe(true);
    // the breakdown divides the votes listed; those with positions are counted in a sentence of their own
    expect(summary).toContain(`${formatNumber(withPositions)} of them record each Member State's position.`);
    expect(summary).not.toMatch(/of them with each Member State's position:/);
    const parts = /: ([\d,]+) from the Council's voting-result documents and ([\d,]+) adoptions? by written procedure/.exec(summary);
    if (parts) expect(Number(parts[1].replace(/,/g, '')) + Number(parts[2].replace(/,/g, ''))).toBe(listed.length);
    expect(coverage.startsWith(`Council votes: ${formatNumber(listed.length)} votes`)).toBe(true);
    for (const c of read<CountrySummary[]>('countries/index.json')) {
      const p = c.council_positions;
      expect(p.for + p.against + p.abstain + p.not_participating, c.code).toBe(withPositions);
    }
  });

  it('lists every statement heading of ST 14020/20, numbering a repeated one', () => {
    expect(votes.get('ST-14020-2020')!.statements).toEqual([
      'Explanation by Hungary of its vote',
      'Statement by Hungary',
      'Statement by the Commission',
      'Draft Joint Statement by the Council, the European Parliament and the Commission',
      'Statement by the Commission (2)',
    ]);
  });
});
