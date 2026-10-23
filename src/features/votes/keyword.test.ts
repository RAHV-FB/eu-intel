import { describe, expect, it } from 'vitest';
import type { EpVoteSummary, SearchDoc } from '../../types/data';
import { createSearchEngine } from '../../lib/search';
import { matchVoteDetails, voteHaystacks } from './keyword';

// TEST-ONLY votes and files shaped like votes/index.json and search.json rows (labels as Parliament writes them)
const vote = (id: string, title: string, display_title: string, dossier_id: string | null = null): EpVoteSummary =>
  ({ id, date: '2024-01-01', title, display_title, dossier_id, topics: [] }) as unknown as EpVoteSummary;
const VOTES = [
  vote('190668', 'A10-0088/2026 – Carlo Fidanza – Motion for a resolution (as a whole)', 'Livestock sector — vote on the resolution'),
  vote('160141', 'A9-0001/2023 - Carlos Zorrinho - Provisional agreement - Am 2', 'Digital decade — final vote on the text'),
  vote('174881', "A10-0010/2025 - Décision d'engager des négociations interinstitutionnelles", "EU talent pool — vote on the committee's decision"),
  vote('130845', 'RC-B9-0123/2021 - Motion for a resolution', 'Russia, the case of Alexei Navalny and Ukraine’s borders — vote on the resolution'),
  vote('157259', 'Nature restoration – A9-0220/2023 – César Luena – Rejection', 'Nature Restoration Regulation — motion to reject the Commission proposal', '2022-0195'),
  vote('182479', 'A10-0050/2025 – Name Surname – Provisional agreement', 'Assistance to Egypt — final vote on the text', '2024-0071'),
];
const DOCS: SearchDoc[] = [
  { id: '2022-0195', k: 'dossier', t: 'Nature restoration', s: '2022/0195(COD) · In force', u: '/legislation/2022-0195', w: 1.2 },
  { id: '2024-0071', k: 'dossier', t: 'Macro-financial assistance to the Arab Republic of Egypt', s: '2024/0071(COD) · In force', u: '/legislation/2024-0071', w: 1.2 },
  { id: 's-d', k: 'group', t: 'Group of the Progressive Alliance of Socialists and Democrats', s: 'Political group', a: 'S&D', u: '/people/groups/s-d', w: 4 },
]; // prettier-ignore
const engine = createSearchEngine(DOCS);
const hay = voteHaystacks(VOTES);
const match = (q: string) => matchVoteDetails(VOTES, hay, q, engine);
const ids = (q: string) => [...(match(q)?.ids ?? [])].sort();

describe('vote keyword matching', () => {
  it('matches rapporteurs only as written: "Carlos" is not Carlo Fidanza', () => {
    expect(ids('Carlos')).toEqual(['160141']);
    expect(ids('Carlo')).toEqual(['190668']);
    expect(ids('agreements')).toEqual(['160141', '182479']); // other label words keep their plurals
  });

  it('does not match single letters left by apostrophes: "S&D"', () => {
    expect(ids('S&D')).toEqual([]);
  });

  it('does not match the word "vote" against the linked file: "nature restoration vote"', () => {
    expect(ids('nature restoration vote')).toEqual(['157259']);
    expect(match('nature restoration vote')?.approximate).toBeUndefined(); // a whole-word match of the file
  });

  it('lists votes on files matched only through a similar word last, and says so', () => {
    const m = match('Macron');
    expect([...(m?.ids ?? [])]).toEqual(['182479']);
    expect(m?.approximate).toBe(true);
    expect(m?.similar).toEqual(['macro']);
    expect(m?.partial).toBe(false);
  });
});
