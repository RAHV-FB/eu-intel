import { Fragment, useId, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { Ballot, BallotPosition, CountryBreakdown, GroupBreakdown, PositionCounts } from '../../types/data';
import { countryName, formatNumber, pct } from '../../lib/format';
import { filterKey } from '../../lib/search';
import { shownParam, useParamState, useParamText } from '../../lib/urlState';
import { SortTh, useSortable } from './sortable';
import { POSITION_LABEL, cohesionPercent, cohesionText } from './labels';
import './votes.css';

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

/** A group's majority position on a vote, or that there is none because the most common positions are tied. */
export function GroupMajority({ c, majority }: { c: PositionCounts; majority: BallotPosition | null | undefined }) {
  if (majority) return <Pos pos={majority} />;
  return c.for + c.against + c.abstain > 0 ? <span>None (tie)</span> : <span className="muted">—</span>;
}

/** A heading shortened on the narrowest screens (below 22.5rem); screen readers always get the full word. */
function ShortOnNarrow({ full, short }: { full: string; short: string }) {
  return (
    <>
      <span className="label-full">{full}</span>
      <span className="label-short" aria-hidden="true">
        {short}
      </span>
    </>
  );
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
  const idBase = useId();
  // Phones (below 40rem): Group, For, Against and Abstained stay in columns; the other columns are hidden and their
  // content is shown on a second line under the row (tr.row-more), so no column is cut off.
  return (
    <div className="table-wrap table-card">
      <table className="table table--breakdown">
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
              <ShortOnNarrow full="Abstained" short="Abst." />
            </SortTh>
            <SortTh k="total" sort={sort} onSort={toggle} num className="hide-narrow">
              Recorded
            </SortTh>
            <th scope="col" className="hide-narrow">
              Split
            </th>
            <th scope="col" className="hide-narrow">
              Group majority
            </th>
            <SortTh k="cohesion" sort={sort} onSort={toggle} className="hide-narrow">
              Cohesion
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const th = `${idBase}-${r.group}`;
            const majority = <GroupMajority c={r} majority={r.majority} />;
            const pctWith = cohesionPercent(r, r.majority);
            const cohesion = pctWith != null ? cohesionText(pctWith) : <span className="muted">—</span>;
            return (
              <Fragment key={r.group}>
                <tr className="has-more">
                  <th scope="row" id={th}>
                    <Link to={`/people/groups/${encodeURIComponent(r.group)}`}>{r.group_code}</Link>
                    {groupNames?.get(r.group) && <span className="meta hide-sm">{groupNames.get(r.group)}</span>}
                  </th>
                  <td className="num">{formatNumber(r.for)}</td>
                  <td className="num">{formatNumber(r.against)}</td>
                  <td className="num">{formatNumber(r.abstain)}</td>
                  <td className="num hide-narrow">{formatNumber(r.for + r.against + r.abstain)}</td>
                  <td className="hide-narrow">
                    <MiniBar c={r} />
                  </td>
                  {r.group === 'ni' ? (
                    <td colSpan={2} className="muted hide-narrow">
                      Not a group: non-attached MEPs do not act together
                    </td>
                  ) : (
                    <>
                      <td className="hide-narrow">{majority}</td>
                      <td className="hide-narrow">{cohesion}</td>
                    </>
                  )}
                </tr>
                <tr className="row-more">
                  <td colSpan={4} headers={th}>
                    <div className="row-more__items">
                      <MiniBar c={r} />
                      <span>Recorded: {formatNumber(r.for + r.against + r.abstain)}</span>
                      {r.group === 'ni' ? (
                        <span className="muted">Not a group: non-attached MEPs do not act together</span>
                      ) : (
                        <>
                          <span>Group majority: {majority}</span>
                          {pctWith != null && <span>Cohesion: {pctWith}%</span>}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              </Fragment>
            );
          })}
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
  const idBase = useId();
  // Phones: as in the group table, Recorded, Share for and Split move to a second line under the row.
  return (
    <div className="table-wrap table-card">
      <table className="table table--breakdown">
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
              <ShortOnNarrow full="Abstained" short="Abst." />
            </SortTh>
            <SortTh k="total" sort={sort} onSort={toggle} num className="hide-narrow">
              Recorded
            </SortTh>
            <SortTh k="share" sort={sort} onSort={toggle} num className="hide-narrow">
              Share for
            </SortTh>
            <th scope="col" className="hide-narrow">
              Split
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const t = r.for + r.against + r.abstain;
            const th = `${idBase}-${r.country}`;
            return (
              <Fragment key={r.country}>
                <tr className="has-more">
                  <th scope="row" id={th}>
                    <Link to={`/countries/${r.country}`}>{countryName(r.country)}</Link>
                  </th>
                  <td className="num">{formatNumber(r.for)}</td>
                  <td className="num">{formatNumber(r.against)}</td>
                  <td className="num">{formatNumber(r.abstain)}</td>
                  <td className="num hide-narrow">{formatNumber(t)}</td>
                  <td className="num hide-narrow">{pct(r.for, t)}</td>
                  <td className="hide-narrow">
                    <MiniBar c={r} />
                  </td>
                </tr>
                <tr className="row-more">
                  <td colSpan={4} headers={th}>
                    <div className="row-more__items">
                      <MiniBar c={r} />
                      <span>Recorded: {formatNumber(t)}</span>
                      <span>Share for: {pct(r.for, t)}</span>
                    </div>
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const BALLOT_PAGE = 100;
const BALLOT_RESET = ['bl-show']; // a new search starts from the first page
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
  // filters, order and rows shown are kept in the address (bl-…), so that Back from an MEP returns to the same list
  const [params, patch] = useParamState();
  const qBox = useParamText('bl-q', BALLOT_RESET);
  const q = qBox.value;
  const group = params.get('bl-group') ?? '';
  const country = params.get('bl-country') ?? '';
  const pos = params.get('bl-pos') ?? '';
  const shown = shownParam(params, 'bl-show', BALLOT_PAGE);

  const groups = useMemo(() => [...new Set(ballots.map((b) => b.group).filter(Boolean) as string[])].sort((a, b) => (groupCodes.get(a) ?? a).localeCompare(groupCodes.get(b) ?? b)), [ballots, groupCodes]);
  const countries = useMemo(() => [...new Set(ballots.map((b) => b.country).filter(Boolean) as string[])].sort((a, b) => countryName(a).localeCompare(countryName(b))), [ballots]);

  // the MEPs' names as the filter compares them, accent-insensitively ("Garcia" finds García), once one is typed
  const typed = !!q.trim();
  const nameKeys = useMemo(() => (typed ? new Map(ballots.map((b) => [b, filterKey(names[b.mep] ?? b.mep)])) : null), [ballots, names, typed]);
  const filtered = useMemo(() => {
    const needle = filterKey(q);
    return ballots.filter(
      (b) =>
        (!group || b.group === group) &&
        (!country || b.country === country) &&
        (!pos || b.pos === pos) &&
        (!needle || !!nameKeys?.get(b)?.includes(needle)),
    );
  }, [ballots, nameKeys, q, group, country, pos]);

  const { sorted, sort, toggle } = useSortable<Ballot, BallotKey>(
    filtered,
    {
      name: (b) => names[b.mep] ?? b.mep,
      group: (b) => (b.group ? groupCodes.get(b.group) ?? b.group : null),
      country: (b) => (b.country ? countryName(b.country) : null),
      pos: (b) => POS_RANK[b.pos],
    },
    { key: 'name', dir: 'asc' },
    {},
    'bl-sort',
  );

  const set = (key: string) => (v: string) => patch({ [key]: v, 'bl-show': null });
  const setShown = (n: number) => patch({ 'bl-show': n > BALLOT_PAGE ? String(n) : null });

  return (
    <div>
      <form className="filters" aria-label="Filter individual votes" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="bl-q">MEP name</label>
          <input id="bl-q" className="input" type="search" value={q} onChange={(e) => qBox.set(e.target.value)} onBlur={qBox.flush} />
        </div>
        <div className="field">
          <label htmlFor="bl-pos">Position</label>
          <select id="bl-pos" className="select" value={pos} onChange={(e) => set('bl-pos')(e.target.value)}>
            <option value="">Any position</option>
            <option value="for">For</option>
            <option value="against">Against</option>
            <option value="abstain">Abstained</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="bl-group">Political group</label>
          <select id="bl-group" className="select" value={group} onChange={(e) => set('bl-group')(e.target.value)}>
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
          <select id="bl-country" className="select" value={country} onChange={(e) => set('bl-country')(e.target.value)}>
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
                <SortTh k="group" sort={sort} onSort={toggle} className="hide-narrow">
                  Group
                </SortTh>
                <SortTh k="country" sort={sort} onSort={toggle} className="hide-narrow">
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
                  <th scope="row">
                    <Link to={`/people/meps/${encodeURIComponent(b.mep)}`}>{names[b.mep] ?? `MEP ${b.mep}`}</Link>
                    {/* phones: the group and country columns are hidden and shown here, so the vote stays beside the name */}
                    {(b.group || b.country) && (
                      <span className="only-narrow meta">
                        {[b.group ? groupCodes.get(b.group) ?? b.group : null, b.country ? countryName(b.country) : null]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    )}
                  </th>
                  <td className="hide-narrow">{b.group ? groupCodes.get(b.group) ?? b.group : <span className="muted">—</span>}</td>
                  <td className="hide-narrow">{b.country ? countryName(b.country) : <span className="muted">—</span>}</td>
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
          <button type="button" className="btn" onClick={() => setShown(shown + BALLOT_PAGE * 3)}>
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
