/**
 * Kinds of votes, links and notes on the real build (public/data from `python -m pipeline build`). Skipped when the
 * data has not been built. Each case is a record Parliament's own texts were checked against.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, EpVoteDetail, EpVoteSummary, SearchDoc } from '../../types/data';
import { createSearchEngine } from '../../lib/search';
import { matchVotes, voteHaystacks } from './keyword';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('votes/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe.skipIf(!built)('votes on the built data', () => {
  const votes = built ? read<EpVoteSummary[]>('votes/index.json') : [];
  const byId = new Map(votes.map((v) => [v.id, v]));
  const dossier = (id: string) => read<DossierDetail>(`dossiers/${id}.json`);

  it('a budget decision is a final vote on the budget, whatever its label calls it', () => {
    // 170632 "Motion for a resolution" (TA-10-2024-0049: "Approves the Council position on Draft amending budget No
    // 5/2024"), 198409 EGF/2026/004, 126342 the 2021 budget (TA-9-2020-0385: "Approves the Council position on the
    // second draft general budget"); the reading of the 2027 draft budget, "all sections", stays a resolution
    for (const id of ['170632', '198409', '126342']) {
      expect([byId.get(id)?.kind, byId.get(id)?.final_role], id).toEqual(['final', 'budget']);
    }
    expect(byId.get('198774')?.kind).toBe('resolution');
    const bud = votes.filter((v) => /^(Draft amending budget|Mobilisation of the)/i.test(v.display_title) && v.procedure_ref?.endsWith('(BUD)'));
    expect(bud.length).toBeGreaterThan(90);
    expect(bud.filter((v) => v.kind !== 'final').map((v) => v.id)).toEqual([]);
  });

  it('a resolution accompanying a consent is not a final vote, and the consent votes are', () => {
    expect(votes.filter((v) => /\d[RM]\(/.test(v.procedure_ref ?? '') && v.kind === 'final').map((v) => v.id)).toEqual([]);
    expect([byId.get('115243')?.kind, byId.get('115243')?.procedure_ref]).toEqual(['resolution', '2019/0090M(NLE)']);
    expect([byId.get('115242')?.kind, byId.get('115242')?.final_role]).toEqual(['final', 'consent']);
    expect(byId.get('124727')?.kind).toBe('resolution');
  });

  it('the airport slots file lists its final vote of 26 March 2020 (686-0-2) on its decision', () => {
    const d = dossier('2020-0042');
    expect(d.ep_votes.map((v) => v.id)).toEqual(['112991']);
    expect(d.timeline.find((x) => x.date === '2020-03-26' && x.kind === 'ep_position')?.vote_id).toBe('112991');
  });

  it('a motion of censure states both conditions of Article 234 TFEU', () => {
    const v = read<EpVoteDetail>('votes/179569.json');
    expect(v.margin).toMatchObject({ threshold: 372, votes_cast: 557, two_thirds_of_cast: 372, majority_of_members: 360 });
  });

  it('a recommendation of Parliament is labelled as one, and the GMO objection of 13 May 2020 as an objection', () => {
    expect(byId.get('139042')?.kind_label).toBe('Vote on a recommendation of Parliament');
    expect(byId.get('139042')?.display_title).toMatch(/— vote on the recommendation$/);
    expect([byId.get('113694')?.kind, byId.get('113694')?.kind_detail]).toEqual(['motion', 'objection']);
  });

  it('timeline steps: consent given on the linked vote of another day, a split part’s negotiation vote', () => {
    const consent = dossier('2018-0132').timeline.find((x) => x.date === '2021-03-25');
    expect([consent?.title, consent?.vote_id]).toEqual(['Parliament gave its consent', '129442']);
    const derived = dossier('2020-0055').timeline.find((x) => x.vote_id === '113149');
    expect(derived?.title).toBe('Parliament voted on consent'); // its outcome is only derived from the counts
    const part = dossier('2023-0077A');
    expect(part.timeline.find((x) => x.id === '2023-0077A-DEC-PLEIN1-2023-09-14')?.vote_id).toBe('158371');
    expect(part.ep_votes.map((v) => v.id)).toContain('158371');
  });

  it('a second-reading approval says no vote on the text was held, with Parliament’s record where it has one', () => {
    expect(dossier('2018-0198').ep_approval_without_vote).toMatchObject({
      date: '2025-05-06',
      record: { identifier: 'MTG-PL-2025-05-06-DEC-176082' },
      amendments_voted: false,
      first_reading: '2019-02-14',
    });
    expect(dossier('2017-0237').ep_approval_without_vote?.amendments_voted).toBe(true); // ten amendments, 29 Apr 2021
    expect(dossier('2023-0288').ep_approval_without_vote?.record?.identifier).toBe('MTG-PL-2025-05-06-DEC-176084');
  });

  it('the votes search does not match a year against procedure or document numbers: "discharge 2022"', () => {
    const engine = createSearchEngine(read<SearchDoc[]>('search.json'));
    const found = matchVotes(votes, voteHaystacks(votes), 'discharge 2022', engine) ?? new Set<string>();
    expect(found.has('175675')).toBe(false); // Discharge 2023 on 2024/2022(DEC)
    expect(found.has('159015')).toBe(false); // Discharge 2021, 2022/2083(DEC)
    expect([...found].filter((id) => !/\b2022\b/.test(`${byId.get(id)?.display_title} ${byId.get(id)?.subject ?? ''}`))).toEqual([]);
    expect(matchVotes(votes, voteHaystacks(votes), '2024/2022(DEC)', engine)?.has('175675')).toBe(true);
  });
});
