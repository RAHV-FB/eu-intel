/**
 * The rows of the vote page's table by national party (partyRows.ts): recorded votes and MEPs with no recorded vote,
 * by party record and country, listed by country and party name.
 */
import { describe, expect, it } from 'vitest';
import type { Ballot, NoVoteCount } from '../../types/data';
import { orderPartyRows, partyRows } from './partyRows';

const ballots: Ballot[] = [
  { mep: '1', pos: 'against', group: 'epp', country: 'DE', party: 'cdu' },
  { mep: '2', pos: 'against', group: 'epp', country: 'DE', party: 'csu' },
  { mep: '3', pos: 'for', group: 's-d', country: 'DE', party: 'spd' },
  { mep: '4', pos: 'abstain', group: 'epp', country: 'DE', party: 'cdu' },
  { mep: '5', pos: 'for', group: 'ni', country: 'PL' }, // no party recorded that day
  { mep: '6', pos: 'for', group: 'greens-efa', country: 'DE', party: 'ind' },
  { mep: '7', pos: 'against', group: 'ni', country: 'DE', party: 'ind' },
];
const noVote: NoVoteCount[] = [
  ['cdu', 'epp', 'DE', 2],
  ['fw', 'renew', 'DE', 1], // a party none of whose MEPs voted
  [null, 'ecr', 'PL', 1],
];

describe('partyRows', () => {
  it('adds up the recorded votes and the MEPs with no recorded vote of each party record', () => {
    const rows = new Map(partyRows(ballots, noVote).map((r) => [`${r.party}|${r.country}`, r]));
    expect(rows.get('cdu|DE')).toEqual({ party: 'cdu', country: 'DE', groups: ['epp'], for: 0, against: 1, abstain: 1, didNotVote: 2 });
    expect(rows.get('csu|DE')).toMatchObject({ for: 0, against: 1, abstain: 0, didNotVote: 0 });
    expect(rows.get('fw|DE')).toMatchObject({ for: 0, against: 0, abstain: 0, didNotVote: 1, groups: ['renew'] });
    // MEPs with no party recorded: one row per country, never merged with a party
    expect(rows.get('null|PL')).toMatchObject({ party: null, for: 1, didNotVote: 1, groups: ['ni', 'ecr'] });
    // a record whose MEPs sit in more than one group lists each group
    expect(rows.get('ind|DE')!.groups).toEqual(['greens-efa', 'ni']);
    expect(rows.size).toBe(6);
  });

  it('gives no figure for MEPs who did not vote when the MEPs in office are not known', () => {
    const rows = partyRows(ballots, null);
    expect(rows.every((r) => r.didNotVote === null)).toBe(true);
    expect(rows.find((r) => r.party === 'fw')).toBeUndefined(); // known only from the MEPs in office
    expect(partyRows([], undefined)).toEqual([]);
  });

  it('lists rows by country, then by party name, and never by how many voted one way', () => {
    const names: Record<string, string> = { cdu: 'Christlich Demokratische Union', csu: 'Christlich-Soziale Union', spd: 'Sozialdemokratische Partei', ind: 'Independent', fw: 'Freie Wähler' };
    const ordered = orderPartyRows(partyRows(ballots, noVote), (id) => names[id] ?? null);
    expect(ordered.map((r) => r.party)).toEqual(['cdu', 'csu', 'fw', 'ind', 'spd', null]);
    // a record whose name is not known comes after the named ones of its country, before MEPs with no party
    const unnamed = orderPartyRows(partyRows(ballots, noVote), (id) => (id === 'csu' ? null : names[id] ?? null));
    expect(unnamed.map((r) => r.party)).toEqual(['cdu', 'fw', 'ind', 'spd', 'csu', null]);
  });
});
