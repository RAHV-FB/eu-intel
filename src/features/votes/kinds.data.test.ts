/**
 * Kinds of votes, links and notes on the real build (public/data from `python -m pipeline build`). Skipped when the
 * data has not been built. Each case is a record Parliament's own texts were checked against.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, EpVoteDetail, EpVoteSummary, SearchDoc } from '../../types/data';
import { createSearchEngine } from '../../lib/search';
import { matchVotes, voteHaystacks } from './keyword';
import { DETAIL_EXPLAINER } from './labels';

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
    // the explanation fits every recommendation voted: A9-0200/2022 (146609, Interpol agreement negotiations) cites
    // "Rules 114(4) and 54", A9-0251/2022 (150162) "Rule 118", B9-0057/2022 (139042) "Rule 208(12)"
    for (const id of ['146609', '150162', '139042']) expect(byId.get(id)?.kind_detail, id).toBe('recommendation');
    const text = DETAIL_EXPLAINER.recommendation;
    expect(text).toContain('on an international agreement under negotiation');
    for (const rule of ['Rule 118', 'Rule 114(4)', 'Rule 208(12)']) expect(text).toContain(rule);
    expect(text).toContain('Each report cites the rule');
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
    // 17 split votes on parts of the text, adopted: not proposals to amend
    expect(dossier('2018-0190').ep_approval_without_vote).toMatchObject({ amendments_voted: false, parts_voted: true });
    expect(dossier('2023-0288').ep_approval_without_vote?.record?.identifier).toBe('MTG-PL-2025-05-06-DEC-176084');
    // where the step links the rejected motion to reject that decided it, the step says so (2017/0121(COD), 8 Jul 2020:
    // 116204, "Proposal for rejection (Rule 67(1))", rejected 218-469-7; Art. 294(7)(a) TFEU); 13 such steps
    const step = dossier('2017-0121').timeline.find((e) => e.id === '2017-0121-DEC-DCPL-2020-07-08')!;
    expect(step.vote_id).toBe('116204');
    expect(step.detail).toMatch(/rejected a motion to reject the Council's position.*\(Article 294\(7\)\(a\) TFEU\)\. The vote link opens that motion\.$/);
    for (const id of ['2017-0122', '2017-0123', '2018-0152A', '2018-0152B', '2018-0210', '2018-0228', '2018-0247', '2018-0249', '2018-0250', '2018-0254', '2023-0226', '2023-0232']) {
      const s = dossier(id).timeline.filter((e) => e.title === "Parliament approved the Council's position at second reading" && e.vote_id);
      expect(s.length, id).toBe(1);
      expect(s[0].detail ?? '', id).toContain('Article 294(7)(a) TFEU');
    }
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
