/**
 * Why a vote with an established outcome shows no margin, as its page says: the reason must be the one that applies.
 * The data check is skipped when the data has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { EpVoteDetail, EpVoteSummary } from '../../types/data';
import { NO_MARGIN, noMarginText } from './labels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('votes/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe('the reason a decided vote has no margin', () => {
  it('names the missing counts, the unknown number of Members, or the rule not established', () => {
    // a procedural decision (votes cast) recorded without counts (195653, 9 Jul 2026)
    expect(noMarginText({ for: null, against: null, majority_rule: 'votes_cast' })).toBe(NO_MARGIN.counts);
    // an objection needing a majority of component Members while the Members in office are not established (109166,
    // 23 Oct 2019: 533 for)
    expect(noMarginText({ for: 533, against: 67, majority_rule: 'component_members' })).toBe(NO_MARGIN.members);
    expect(noMarginText({ for: 372, against: 120, majority_rule: 'two_thirds_cast' })).toBe(NO_MARGIN.members);
    expect(noMarginText({ for: 400, against: 200, majority_rule: 'unknown' })).toBe(NO_MARGIN.rule);
    expect(noMarginText({ for: 400, against: 200 })).toBe(NO_MARGIN.rule);
    expect(NO_MARGIN.rule).toBe('No margin shown: we have not established which majority this vote required.');
  });
});

describe.skipIf(!built)('votes without a margin on the built data', () => {
  it('gives each decided vote without a margin the reason that applies to it', () => {
    const seen = new Set<string>();
    for (const e of read<EpVoteSummary[]>('votes/index.json')) {
      if (e.margin || (e.outcome !== 'adopted' && e.outcome !== 'rejected')) continue;
      const v = read<EpVoteDetail>(`votes/${e.id}.json`);
      const reason = noMarginText(v);
      seen.add(reason);
      if (reason !== NO_MARGIN.rule) expect(v.majority_rule, e.id).not.toBe('unknown');
      if (reason === NO_MARGIN.rule) expect([v.majority_rule ?? 'unknown', v.for != null], e.id).toEqual(['unknown', true]);
    }
    expect(seen.has(NO_MARGIN.rule)).toBe(true);
  });
});
