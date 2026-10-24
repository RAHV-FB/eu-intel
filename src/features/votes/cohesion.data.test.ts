/**
 * Group cohesion as the vote and group pages show it: one rounding, from the counts. The stored share is rounded to
 * three decimals, and rounding it again showed one point too many in about 1 in 30 cells (ECR on vote 199470: 64 of
 * 65 is 98%, stored 0.985, shown 99%). Data checks are skipped when the data has not been built.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { EpVoteDetail, GroupDetail } from '../../types/data';
import { cohesionPercent, cohesionText } from './labels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('people/groups/ecr.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

it('rounds the share of the group majority once, from the counts', () => {
  expect(cohesionPercent({ for: 64, against: 1, abstain: 0 }, 'for')).toBe(98);
  expect(cohesionPercent({ for: 136, against: 33, abstain: 0 }, 'for')).toBe(80); // EPP on vote 193822: 80.47%
  expect(cohesionPercent({ for: 29, against: 171, abstain: 0 }, 'for')).toBe(15); // 14.5%: half up, without float error
  expect(cohesionPercent({ for: 31, against: 31, abstain: 11 }, null)).toBeNull(); // a tie: no majority
  expect(cohesionPercent({ for: 0, against: 0, abstain: 0 }, 'for')).toBeNull();
  expect(cohesionText(98)).toBe('98% voted with the group majority');
  expect(cohesionText(null)).toBe('—');
});

describe.skipIf(!built)('cohesion on the built data', () => {
  it('shows ECR on vote 199470 at 98%, and every group row within half a point of its exact share', () => {
    const ecr = read<GroupDetail>('people/groups/ecr.json').votes.find((r) => r.vote_id === '199470')!;
    expect([ecr.counts, ecr.majority, ecr.cohesion]).toEqual([{ for: 64, against: 1, abstain: 0 }, 'for', 0.985]);
    expect(cohesionPercent(ecr.counts, ecr.majority)).toBe(98);
    let twice = 0;
    for (const f of readdirSync(new URL('people/groups/', DATA))) {
      for (const r of read<GroupDetail>(`people/groups/${f}`).votes) {
        const p = cohesionPercent(r.counts, r.majority);
        expect(p === null, `${f} ${r.vote_id}`).toBe(r.cohesion == null);
        if (p === null || !r.majority) continue;
        const exact = (100 * r.counts[r.majority]) / (r.counts.for + r.counts.against + r.counts.abstain);
        expect(Math.abs(p - exact), `${f} ${r.vote_id}`).toBeLessThanOrEqual(0.5);
        if (Math.round(r.cohesion! * 100) !== p) twice++;
      }
    }
    expect(twice).toBeGreaterThan(100); // the cells that rounding the stored share again got wrong
    const vote = read<EpVoteDetail>('votes/199470.json').groups.find((g) => g.group === 'ecr')!;
    expect(cohesionPercent(vote, vote.majority)).toBe(98);
  });
});
