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
