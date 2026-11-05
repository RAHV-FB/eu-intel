/**
 * What a Council vote card says about the voting rule, on constructed votes (no built data needed). The assessments
 * are those pipeline/analysis/council_qmv.py gives for these positions (tests/test_council_qmv.py, 2026 figures).
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type { CouncilAssessment, CouncilPosition, CouncilVote } from '../../types/data';
import { COUNTRY_NAMES } from '../../lib/format';
import { CouncilVoteCard } from './CouncilVoteCard';

const EU27 = Object.keys(COUNTRY_NAMES).filter((c) => c !== 'GB');

function vote(against: string[], a: Partial<CouncilAssessment>): CouncilVote {
  const positions = Object.fromEntries(EU27.map((c) => [c, (against.includes(c) ? 'against' : 'for') as CouncilPosition]));
  return {
    id: 'ST-1-2026', date: '2026-03-02', title: 'Regulation on widgets', dossier_id: null, dossier_ref: null,
    configuration: null, stage: 'Adoption of the legislative act', vote_on: 'act', vote_on_label: null, vote_on_note: null,
    meeting: null, written_procedure: false, council_doc: null, voting_rule: 'qmv', outcome: 'adopted', positions,
    positions_note: null, statements: [],
    source: { institution: 'Council', url: 'https://example.invalid/st', label: 'Voting result', retrieved_at: null },
    assessment: {
      rule: 'qmv', states_for: 27 - against.length, states_required: 15, population_required_pct: 65, single_state_veto_possible: false,
      note: '', legal_basis: 'TEU Art. 16(4)', states_against: against.length, states_abstain: 0, states_not_participating: 0,
      states_participating: 27, blocking_minority_min_states: 4, ...a,
    },
  } as CouncilVote;
}

const text = (v: CouncilVote) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(CouncilVoteCard, { vote: v })))
    .replace(/<\/li>/g, '\n')
    .replace(/<[^>]+>/g, '');

describe('Council vote card: what the qualified-majority rule meant', () => {
  it('says the qualified majority was deemed attained, not that both thresholds were met, when three large states voted against', () => {
    // Germany, France and Italy: 46.84% of the 2026 population against, 53.16% for, but only three Member States
    const t = text(vote(['DE', 'FR', 'IT'], { population_for_pct: 53.16, adopted_by_rule: true, deemed_attained: true, blocking_minority_existed: false }));
    expect(t).toContain('They represent 53.2% of the EU population; at least 65% was needed.');
    expect(t).toContain(
      'The population threshold was not met, but the Member States not voting in favour were too few to form a blocking minority, so ' +
        'the qualified majority is deemed attained (TEU Art. 16(4)).',
    );
    expect(t).not.toContain('both qualified-majority thresholds were met');
  });

  it('says both thresholds were met otherwise', () => {
    const t = text(vote(['DE', 'ES', 'NL', 'BG'], { population_for_pct: 65.23, adopted_by_rule: true, deemed_attained: false, blocking_minority_existed: false }));
    expect(t).toContain('On these figures, both qualified-majority thresholds were met.');
    expect(t).not.toContain('deemed attained');
    const blocked = text(vote(['DE', 'ES', 'NL', 'AT'], { population_for_pct: 64.62, adopted_by_rule: false, deemed_attained: false, blocking_minority_existed: true }));
    expect(blocked).toContain('On these figures, the qualified-majority thresholds were not met.');
    expect(blocked).toContain('The Member States not voting in favour formed a blocking minority');
  });
});
