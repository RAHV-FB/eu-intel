import { describe, expect, it } from 'vitest';
import { councilPatterns, legislativePatterns, parliamentPatterns } from './analysis';

describe('Insights: counts from source fields, no inferred outcomes', () => {
  it('keeps withdrawn, repealed and unknown legislation separate', () => {
    const x = legislativePatterns([
      { stage: 'in_force', started: '2020-01-01', adopted: '2022-02-01' },
      { stage: 'no_longer_in_force', started: '2020-01-01', adopted: '2021-03-01' },
      { stage: 'withdrawn', started: '2021-01-01', adopted: null },
      { stage: 'unknown', started: null, adopted: null },
    ]);
    expect(x.total).toBe(4);
    expect(x.stages.find((s) => s.id === 'withdrawn')?.count).toBe(1);
    expect(x.stages.find((s) => s.id === 'no_longer_in_force')?.count).toBe(1);
    expect(x.timeline.find((t) => t.year === 2020)?.introduced).toBe(2);
    expect(x.timeline.find((t) => t.year === 2021)?.adopted).toBe(1);
  });

  it('excludes non-final votes and unknown outcomes from final decision denominator', () => {
    const x = parliamentPatterns([
      { kind: 'final', outcome: 'adopted', margin: null, date: '2025-01-01', has_ballots: true, id: '1', display_title: 'Text' },
      { kind: 'final', outcome: 'unknown', margin: null, date: '2025-02-01', has_ballots: false, id: '2', display_title: 'Text' },
      { kind: 'motion', outcome: 'rejected', margin: null, date: '2025-03-01', has_ballots: true, id: '3', display_title: 'Motion' },
    ]);
    expect(x.total).toBe(3);
    expect(x.final).toBe(2);
    expect(x.withOutcome).toBe(1);
    expect(x.withMargin).toBe(0);
    expect(x.close).toBe(0);
    expect(x.years[0]).toEqual({ year: '2025', count: 2 });
  });

  it('uses recorded positions as denominator, excluding non-participation', () => {
    const [row] = councilPatterns([{
      code: 'ES', name: 'Spain', council_positions: { for: 7, against: 2, abstain: 1, not_participating: 4 },
      open_infringements: null,
    }]);
    expect(row.recorded).toBe(10);
    expect(row.dissent).toBe(3);
    expect(row.share).toBe(0.3);
    expect(row.notParticipating).toBe(4);
  });

  it('lists countries alphabetically, not by their count, and leaves out those with no recorded position', () => {
    const pos = (against: number) => ({ for: 5, against, abstain: 0, not_participating: 0 });
    const rows = councilPatterns([
      { code: 'SE', name: 'Sweden', council_positions: pos(9), open_infringements: null },
      { code: 'AT', name: 'Austria', council_positions: pos(1), open_infringements: null },
      { code: 'CZ', name: 'Czechia', council_positions: pos(4), open_infringements: null },
      { code: 'MT', name: 'Malta', council_positions: { for: 0, against: 0, abstain: 0, not_participating: 3 }, open_infringements: null },
    ]);
    expect(rows.map((r) => r.code)).toEqual(['AT', 'CZ', 'SE']);
  });
});
