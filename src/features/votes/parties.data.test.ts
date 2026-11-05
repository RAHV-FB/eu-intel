/**
 * The national-party breakdown on the real build (public/data): the vote page adds up its rows in the browser from the
 * ballots and `no_vote` (partyRows.ts), the party pages list counts the build made (PartyDetail.votes); both must say the
 * same, for every party record and every vote on a whole text. Skipped when the data has not been built.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { EpVoteDetail, EpVoteSummary, PartyDetail, PartySummary } from '../../types/data';
import { orderPartyRows, partyRows } from './partyRows';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('votes/index.json', DATA)) && existsSync(new URL('people/parties/5195.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe.skipIf(!built)('national parties on the built data', () => {
  it('answers how CDU and CSU voted on the Nature Restoration Law (vote 164499)', () => {
    const v = read<EpVoteDetail>('votes/164499.json');
    const names = new Map(read<PartySummary[]>('people/parties.json').map((p) => [p.id, p]));
    const de = orderPartyRows(
      partyRows(v.ballots, v.no_vote).filter((r) => r.country === 'DE'),
      (id) => names.get(id)?.label ?? null,
    );
    const counts = (code: string) => {
      const r = de.find((x) => x.party && names.get(x.party)?.code === code)!;
      return [r.for, r.against, r.abstain, r.didNotVote];
    };
    expect(counts('CDU')).toEqual([0, 19, 0, 4]);
    expect(counts('CSU')).toEqual([0, 6, 0, 0]);
    // by party name, as the page lists them
    const labels = de.map((r) => names.get(r.party!)!.label);
    expect(labels).toEqual([...labels].sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' })));
    // Germany's party rows add up to its row in the table by country (46 for, 42 against)
    const sum = de.reduce((s, r) => [s[0] + r.for, s[1] + r.against, s[2] + r.abstain], [0, 0, 0]);
    expect(sum).toEqual([46, 42, 0]);
    expect(v.countries.find((c) => c.country === 'DE')).toEqual({ country: 'DE', for: 46, against: 42, abstain: 0 });
  });

  it('gives each vote page rows that add up to its country table, and each party page the same counts', () => {
    const index = read<EpVoteSummary[]>('votes/index.json');
    const kinds = new Map(index.map((v) => [v.id, v.kind]));
    const dates = new Map(index.map((v) => [v.id, v.date]));
    const parties = new Map(read<PartySummary[]>('people/parties.json').map((p) => [p.id, p]));
    // party record|vote -> [vote, for, against, abstained, did not vote], as the vote page adds them up
    const fromVotes = new Map<string, (string | number | null)[]>();
    const problems: string[] = []; // collected, so that the hundreds of thousands of rows cost one assertion each check
    let checked = 0;
    for (const s of index) {
      if (!s.has_ballots) continue;
      const v = read<EpVoteDetail>(`votes/${s.id}.json`);
      if (!(v.no_vote === null || Array.isArray(v.no_vote))) problems.push(`${s.id}: no_vote missing`);
      const rows = partyRows(v.ballots, v.no_vote);
      const byCountry = new Map<string, number[]>();
      for (const r of rows) {
        const c = byCountry.get(r.country ?? '') ?? [0, 0, 0];
        byCountry.set(r.country ?? '', [c[0] + r.for, c[1] + r.against, c[2] + r.abstain]);
        // a party record's MEPs represent the party's own country
        if (r.party && parties.has(r.party) && r.country !== parties.get(r.party)!.country) problems.push(`${s.id} ${r.party}: ${r.country}`);
        if (s.kind !== 'final' && s.kind !== 'mandate') continue;
        if (!r.party) continue;
        const key = `${r.party}|${s.id}`;
        const prev = fromVotes.get(key);
        // one row per party record and country: a party is never split, but add up in case it were
        fromVotes.set(
          key,
          prev
            ? [s.id, (prev[1] as number) + r.for, (prev[2] as number) + r.against, (prev[3] as number) + r.abstain, prev[4] === null ? null : (prev[4] as number) + (r.didNotVote ?? 0)]
            : [s.id, r.for, r.against, r.abstain, r.didNotVote],
        );
      }
      // the table by country lists the countries with a recorded vote (not those whose MEPs all did not vote)
      const recorded = Object.fromEntries([...byCountry].filter(([, c]) => c[0] + c[1] + c[2] > 0).sort());
      const table = Object.fromEntries(v.countries.map((c) => [c.country, [c.for, c.against, c.abstain]]).sort());
      if (JSON.stringify(recorded) !== JSON.stringify(table)) problems.push(`${s.id}: party rows do not add up to the countries`);
      checked++;
    }
    expect(checked).toBeGreaterThan(2500);
    const fromParties = new Map<string, (string | number | null)[]>();
    for (const f of readdirSync(new URL('people/parties/', DATA))) {
      const p = read<PartyDetail>(`people/parties/${f}`);
      let last = '9999-12-31';
      for (const r of p.votes) {
        if (!/^(final|mandate)$/.test(kinds.get(r[0]) ?? '')) problems.push(`${p.id} ${r[0]}: ${kinds.get(r[0])}`);
        // newest first
        const d = dates.get(r[0])!;
        if (!(d <= last)) problems.push(`${p.id} ${r[0]}: not newest first`);
        last = d;
        fromParties.set(`${p.id}|${r[0]}`, r);
      }
    }
    expect(problems).toEqual([]);
    expect(fromParties.size).toBeGreaterThan(100000);
    expect(fromParties).toEqual(fromVotes);
  });
});
