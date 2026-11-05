import { describe, expect, it } from 'vitest';
import { isClose } from '../votes/labels';
import { CLOSE_FINAL_VOTES, councilPatterns, legislativePatterns, notCountedText, parliamentPatterns } from './analysis';

describe('Insights: counts from source fields, no inferred outcomes', () => {
  it('keeps withdrawn, repealed and unknown legislation separate', () => {
    const x = legislativePatterns([
      { id: '2020-0001', stage: 'in_force', started: '2020-01-01', adopted: '2022-02-01' },
      { id: '2020-0002', stage: 'no_longer_in_force', started: '2020-01-01', adopted: '2021-03-01' },
      { id: '2021-0001', stage: 'withdrawn', started: '2021-01-01', adopted: null },
      { id: '2021-0002', stage: 'unknown', started: null, adopted: null },
    ]);
    expect(x.total).toBe(4);
    expect(x.counted).toBe(4);
    expect(x.stages.find((s) => s.id === 'withdrawn')?.count).toBe(1);
    expect(x.stages.find((s) => s.id === 'no_longer_in_force')?.count).toBe(1);
    expect(x.stages.find((s) => s.id === 'unknown')?.count).toBe(1);
    expect(x.timeline.find((t) => t.year === 2020)?.introduced).toBe(2);
    expect(x.timeline.find((t) => t.year === 2021)?.adopted).toBe(1);
  });

  it('counts a split proposal through its parts, once each, and leaves out Parliament’s reports on a procedure', () => {
    // 2019/0001(COD) was split into 2019/0001A and 2019/0001B: the parent is listed as a file whose status is "Split
    // into separate procedures" (stage 'unknown') and carries its parts' proposal date; 2023/0201M and R are reports
    // Parliament adopted on 2023/0201(COD), not legislative files.
    const x = legislativePatterns([
      { id: '2019-0001', stage: 'unknown', started: '2019-01-07', adopted: null },
      { id: '2019-0001A', stage: 'in_force', started: '2019-01-07', adopted: '2021-06-28' },
      { id: '2019-0001B', stage: 'in_force', started: '2019-01-07', adopted: '2021-06-28' },
      { id: '2019-0002', stage: 'proposed', started: '2019-03-01', adopted: null },
      { id: '2023-0201', stage: 'in_force', started: '2023-06-20', adopted: '2024-02-29' },
      { id: '2023-0201M', stage: 'unknown', started: null, adopted: null },
      { id: '2023-0201R', stage: 'unknown', started: null, adopted: null },
      { id: '2021-0415', stage: 'unknown', started: '2021-12-09', adopted: null }, // a status that is not determinable
    ]);
    expect(x.total).toBe(8); // the files listed, as on /legislation
    expect([x.counted, x.splitParents, x.reports]).toEqual([5, 1, 2]);
    // 2 parts in force + 2023/0201 = 3; the parent is not "not determinable": its parts are counted
    expect(x.stages).toEqual([
      { id: 'in_force', label: 'In force', count: 3 },
      { id: 'proposed', label: 'Proposal under examination', count: 1 },
      { id: 'unknown', label: 'Not determinable', count: 1 },
    ]);
    expect(x.stages.reduce((n, s) => n + s.count, 0)).toBe(x.counted);
    // 2019: the two parts and 2019/0002, not the parent a third time
    expect(x.timeline).toEqual([
      { year: 2019, introduced: 3, adopted: 0 },
      { year: 2021, introduced: 1, adopted: 2 },
      { year: 2023, introduced: 1, adopted: 0 },
      { year: 2024, introduced: 0, adopted: 1 },
    ]);
    expect(notCountedText(x)).toBe(
      'The bars count 5 of the 8 files listed: 1 proposal was split into separate procedures, which are counted instead; ' +
        '2 are reports Parliament adopted on a procedure, not legislative files.',
    );
    expect(notCountedText({ total: 4, counted: 4, splitParents: 0, reports: 0 })).toBe('');
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

  it('links its count of close final votes to the list of exactly those votes', () => {
    const margin = (relative: number) => ({ rule: 'votes_cast', rule_label: '', threshold: 301, distance: 1, relative, label: '' }) as const;
    const votes = [
      { kind: 'final', outcome: 'adopted', margin: margin(0.01), date: '2025-01-01', has_ballots: true, id: '1', display_title: 'Text' },
      { kind: 'final', outcome: 'adopted', margin: margin(0.2), date: '2025-01-02', has_ballots: true, id: '2', display_title: 'Text' },
      { kind: 'motion', outcome: 'rejected', margin: margin(-0.01), date: '2025-01-03', has_ballots: true, id: '3', display_title: 'Motion' },
    ] as const;
    const x = parliamentPatterns([...votes]);
    expect([x.withMargin, x.close]).toEqual([2, 1]);
    // the /votes page's kind and close filters (src/pages/Votes.tsx), applied to the link's address
    const q = new URL(CLOSE_FINAL_VOTES, 'https://example.org').searchParams;
    const listed = votes.filter((v) => (!q.get('kind') || v.kind === q.get('kind')) && (q.get('close') !== '1' || isClose(v)));
    expect(listed.map((v) => v.id)).toEqual(['1']);
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
