/**
 * Council votes on the real build (public/data from `python -m pipeline build`). Skipped when the data has not been
 * built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CountryDetail, CouncilVote, DossierDetail } from '../../types/data';

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
