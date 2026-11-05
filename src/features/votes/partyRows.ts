/**
 * The rows of the vote page's table by national party (PartyBreakdown): one per national party record that Parliament's
 * membership data lists MEPs under on the day of the vote. Recorded votes come from the ballots, which give each voter's
 * party record, group and country that day; the MEPs in office with no recorded vote from `no_vote`, which the build
 * counts from the same records (pipeline/build.py party_breakdown, which also gives the party pages their counts).
 */
import type { Ballot, NoVoteCount } from '../../types/data';
import { countryName } from '../../lib/format';
import { compareValues } from './sortable';

export interface PartyRow {
  /** the party record (EP org id); null for MEPs with no party recorded that day */
  party: string | null;
  /** the MEPs' country of representation */
  country: string | null;
  /** their political groups that day (slugs) */
  groups: string[];
  for: number;
  against: number;
  abstain: number;
  /** in office that day with no recorded vote; null when that is not known (`no_vote` null) */
  didNotVote: number | null;
}

/** One row per party record and country, so that a country filter keeps exactly the MEPs it keeps in the list of MEPs. */
export function partyRows(ballots: Ballot[], noVote: NoVoteCount[] | null | undefined): PartyRow[] {
  const known = Array.isArray(noVote);
  const rows = new Map<string, PartyRow>();
  const row = (party: string | null, country: string | null, group: string | null) => {
    const key = `${party ?? ''}|${country ?? ''}`;
    let r = rows.get(key);
    if (!r) {
      r = { party, country, groups: [], for: 0, against: 0, abstain: 0, didNotVote: known ? 0 : null };
      rows.set(key, r);
    }
    if (group && !r.groups.includes(group)) r.groups.push(group);
    return r;
  };
  for (const b of ballots) row(b.party ?? null, b.country ?? null, b.group ?? null)[b.pos] += 1;
  for (const [party, group, country, n] of noVote ?? []) {
    const r = row(party, country, group);
    r.didNotVote = (r.didNotVote ?? 0) + n;
  }
  return [...rows.values()];
}

/** By country, then by party name (MEPs with no party recorded after the parties of their country); never by how many
 * MEPs voted one way. `label` names a party record, or gives null when its name is not known. */
export function orderPartyRows(rows: PartyRow[], label: (party: string) => string | null): PartyRow[] {
  const name = (r: PartyRow) => (r.party ? label(r.party) : null);
  return [...rows].sort(
    (a, b) =>
      compareValues(a.country ? countryName(a.country) : null, b.country ? countryName(b.country) : null, 'asc') ||
      Number(a.party === null) - Number(b.party === null) ||
      compareValues(name(a), name(b), 'asc') ||
      compareValues(a.party, b.party, 'asc'),
  );
}
