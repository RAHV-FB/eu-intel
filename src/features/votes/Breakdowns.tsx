import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Ballot, BallotPosition, CountryBreakdown, GroupBreakdown, PositionCounts } from '../../types/data';
import { countryName, formatNumber, pct } from '../../lib/format';
import { SortTh, useSortable } from './sortable';
import { POSITION_LABEL, cohesionText } from './labels';

/** Small proportional bar for table rows (numbers are always in adjacent cells). */
export function MiniBar({ c }: { c: PositionCounts }) {
  const total = c.for + c.against + c.abstain;
  if (!total) return null;
  const w = (n: number) => `${(n / total) * 100}%`;
  return (
    <span className="minibar" aria-hidden="true">
      {c.for > 0 && <span className="f" style={{ width: w(c.for) }} />}
      {c.abstain > 0 && <span className="x" style={{ width: w(c.abstain) }} />}
      {c.against > 0 && <span className="a" style={{ width: w(c.against) }} />}
    </span>
  );
}

export function Pos({ pos }: { pos: BallotPosition | 'not_participating' | null | undefined }) {
  if (!pos) return <span className="pos pos--none">Not recorded</span>;
  if (pos === 'not_participating') return <span className="pos pos--not_participating">Not participating</span>;
  return <span className={`pos pos--${pos}`}>{POSITION_LABEL[pos]}</span>;
}

type GroupKey = 'group' | 'for' | 'against' | 'abstain' | 'total' | 'cohesion';

export function GroupBreakdownTable({ rows, groupNames }: { rows: GroupBreakdown[]; groupNames?: Map<string, string> }) {
  const { sorted, sort, toggle } = useSortable<GroupBreakdown, GroupKey>(
    rows,
    {
      group: (r) => r.group_code,
      for: (r) => r.for,
      against: (r) => r.against,
      abstain: (r) => r.abstain,
      total: (r) => r.for + r.against + r.abstain,
      cohesion: (r) => r.cohesion ?? null,
    },
    { key: 'total', dir: 'desc' },
    { for: 'desc', against: 'desc', abstain: 'desc', total: 'desc', cohesion: 'desc' },
  );
  return (
    <div className="table-wrap table-card">
      <table className="table">
        <caption className="visually-hidden">Recorded votes of MEPs by political group (membership on the day of the vote). Select a column heading to sort.</caption>
        <thead>
          <tr>
            <SortTh k="group" sort={sort} onSort={toggle}>
              Group
            </SortTh>
            <SortTh k="for" sort={sort} onSort={toggle} num>
              For
            </SortTh>
            <SortTh k="against" sort={sort} onSort={toggle} num>
              Against
            </SortTh>
            <SortTh k="abstain" sort={sort} onSort={toggle} num>
              Abstained
            </SortTh>
            <SortTh k="total" sort={sort} onSort={toggle} num>
              Recorded
            </SortTh>
            <th scope="col">Split</th>
            <th scope="col">Group majority</th>
            <SortTh k="cohesion" sort={sort} onSort={toggle}>
              Cohesion
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.group}>
              <th scope="row">
                <Link to={`/people/groups/${encodeURIComponent(r.group)}`}>{r.group_code}</Link>
                {groupNames?.get(r.group) && <span className="meta hide-sm" style={{ fontWeight: 400 }}>{groupNames.get(r.group)}</span>}
              </th>
              <td className="num">{formatNumber(r.for)}</td>
              <td className="num">{formatNumber(r.against)}</td>
              <td className="num">{formatNumber(r.abstain)}</td>
              <td className="num">{formatNumber(r.for + r.against + r.abstain)}</td>
              <td>
                <MiniBar c={r} />
              </td>
              {r.group === 'ni' ? (
                <td colSpan={2} className="muted">
                  Not a group: non-attached MEPs do not act together
                </td>
              ) : (
                <>
                  <td>{r.majority ? <Pos pos={r.majority} /> : <span className="muted">—</span>}</td>
                  <td>{r.cohesion != null ? cohesionText(r.cohesion) : <span className="muted">—</span>}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type CountryKey = 'country' | 'for' | 'against' | 'abstain' | 'total' | 'share';

export function CountryBreakdownTable({ rows }: { rows: CountryBreakdown[] }) {
  const { sorted, sort, toggle } = useSortable<CountryBreakdown, CountryKey>(
    rows,
    {
      country: (r) => countryName(r.country),
      for: (r) => r.for,
      against: (r) => r.against,
      abstain: (r) => r.abstain,
      total: (r) => r.for + r.against + r.abstain,
      share: (r) => {
        const t = r.for + r.against + r.abstain;
        return t ? r.for / t : null;
      },
    },
    { key: 'country', dir: 'asc' },
    { for: 'desc', against: 'desc', abstain: 'desc', total: 'desc', share: 'desc' },
  );
  return (
    <div className="table-wrap table-card">
      <table className="table">
        <caption className="visually-hidden">Recorded votes of MEPs by the country they represent. Select a column heading to sort.</caption>
        <thead>
          <tr>
            <SortTh k="country" sort={sort} onSort={toggle}>
              MEPs from
            </SortTh>
            <SortTh k="for" sort={sort} onSort={toggle} num>
              For
            </SortTh>
            <SortTh k="against" sort={sort} onSort={toggle} num>
              Against
            </SortTh>
            <SortTh k="abstain" sort={sort} onSort={toggle} num>
              Abstained
            </SortTh>
            <SortTh k="total" sort={sort} onSort={toggle} num>
              Recorded
            </SortTh>
            <SortTh k="share" sort={sort} onSort={toggle} num>
              Share for
            </SortTh>
            <th scope="col">Split</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const t = r.for + r.against + r.abstain;
            return (
              <tr key={r.country}>
                <th scope="row">
                  <Link to={`/countries/${r.country}`}>{countryName(r.country)}</Link>
                </th>
                <td className="num">{formatNumber(r.for)}</td>
                <td className="num">{formatNumber(r.against)}</td>
                <td className="num">{formatNumber(r.abstain)}</td>
                <td className="num">{formatNumber(t)}</td>
                <td className="num">{pct(r.for, t)}</td>
                <td>
                  <MiniBar c={r} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const BALLOT_PAGE = 100;
type BallotKey = 'name' | 'group' | 'country' | 'pos';
const POS_RANK: Record<BallotPosition, number> = { for: 0, against: 1, abstain: 2 };

export function BallotList({
  ballots,
  names,
  groupCodes,
}: {
  ballots: Ballot[];
  names: Record<string, string>;
  groupCodes: Map<string, string>;
}) {
  const [q, setQ] = useState('');
  const [group, setGroup] = useState('');
  const [country, setCountry] = useState('');
  const [pos, setPos] = useState('');
  const [shown, setShown] = useState(BALLOT_PAGE);

  const groups = useMemo(() => [...new Set(ballots.map((b) => b.group).filter(Boolean) as string[])].sort((a, b) => (groupCodes.get(a) ?? a).localeCompare(groupCodes.get(b) ?? b)), [ballots, groupCodes]);
  const countries = useMemo(() => [...new Set(ballots.map((b) => b.country).filter(Boolean) as string[])].sort((a, b) => countryName(a).localeCompare(countryName(b))), [ballots]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return ballots.filter(
      (b) =>
        (!group || b.group === group) &&
        (!country || b.country === country) &&
        (!pos || b.pos === pos) &&
        (!needle || (names[b.mep] ?? b.mep).toLowerCase().includes(needle)),
    );
  }, [ballots, names, q, group, country, pos]);

  const { sorted, sort, toggle } = useSortable<Ballot, BallotKey>(
    filtered,
    {
      name: (b) => names[b.mep] ?? b.mep,
      group: (b) => (b.group ? groupCodes.get(b.group) ?? b.group : null),
      country: (b) => (b.country ? countryName(b.country) : null),
      pos: (b) => POS_RANK[b.pos],
    },
    { key: 'name', dir: 'asc' },
  );

  const reset = (fn: (v: string) => void) => (v: string) => {
    fn(v);
    setShown(BALLOT_PAGE);
  };

  return (
    <div>
      <form className="filters" aria-label="Filter individual votes" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="bl-q">MEP name</label>
          <input id="bl-q" className="input" type="search" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="bl-pos">Position</label>
          <select id="bl-pos" className="select" value={pos} onChange={(e) => reset(setPos)(e.target.value)}>
            <option value="">Any position</option>
            <option value="for">For</option>
            <option value="against">Against</option>
            <option value="abstain">Abstained</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="bl-group">Political group</label>
          <select id="bl-group" className="select" value={group} onChange={(e) => reset(setGroup)(e.target.value)}>
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g} value={g}>
                {groupCodes.get(g) ?? g}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="bl-country">Country represented</label>
          <select id="bl-country" className="select" value={country} onChange={(e) => reset(setCountry)(e.target.value)}>
            <option value="">All countries</option>
            {countries.map((c) => (
              <option key={c} value={c}>
                {countryName(c)}
              </option>
            ))}
          </select>
        </div>
      </form>
      <p className="results-bar__count" aria-live="polite" style={{ marginBottom: 'var(--sp-2)' }}>
        {filtered.length === ballots.length
          ? `${formatNumber(ballots.length)} MEPs with a recorded vote`
          : `${formatNumber(filtered.length)} of ${formatNumber(ballots.length)} MEPs with a recorded vote`}
      </p>
      {filtered.length > 0 && (
        <div className="table-wrap table-card">
          <table className="table">
            <caption className="visually-hidden">Individual MEP votes. Select a column heading to sort.</caption>
            <thead>
              <tr>
                <SortTh k="name" sort={sort} onSort={toggle}>
                  MEP
                </SortTh>
                <SortTh k="group" sort={sort} onSort={toggle}>
                  Group
                </SortTh>
                <SortTh k="country" sort={sort} onSort={toggle}>
                  Country
                </SortTh>
                <SortTh k="pos" sort={sort} onSort={toggle}>
                  Recorded vote
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, shown).map((b) => (
                <tr key={b.mep}>
                  <th scope="row" style={{ fontWeight: 500 }}>
                    <Link to={`/people/meps/${encodeURIComponent(b.mep)}`}>{names[b.mep] ?? `MEP ${b.mep}`}</Link>
                  </th>
                  <td>{b.group ? groupCodes.get(b.group) ?? b.group : <span className="muted">—</span>}</td>
                  <td>{b.country ? countryName(b.country) : <span className="muted">—</span>}</td>
                  <td>
                    <Pos pos={b.pos} />
                    {b.intended && b.intended !== b.pos && (
                      <span className="ballot-correction">Later stated intention: {POSITION_LABEL[b.intended].toLowerCase()}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sorted.length > shown && (
        <div className="more">
          <button type="button" className="btn" onClick={() => setShown((n) => n + BALLOT_PAGE * 3)}>
            Show more MEPs
          </button>
          <button type="button" className="btn" onClick={() => setShown(sorted.length)}>
            Show all {formatNumber(sorted.length)}
          </button>
        </div>
      )}
    </div>
  );
}
