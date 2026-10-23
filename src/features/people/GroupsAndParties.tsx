import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { GroupSummary, PartySummary } from '../../types/data';
import { countryName, formatNumber } from '../../lib/format';
import { Disclosure, EmptyState } from '../../components/ui';
import { CollapsibleFilters, PHONE_WIDTH } from '../../components/CollapsibleFilters';
import { useMediaQuery } from '../../components/useMediaQuery';
import { SortTh, useSortable } from '../votes/sortable';
import { termLabel } from './labels';
import './people.css';

type GKey = 'code' | 'name' | 'members' | 'countries';

export function GroupsOverview({ groups }: { groups: GroupSummary[] }) {
  const current = useMemo(() => groups.filter((g) => g.active), [groups]);
  const earlier = useMemo(() => groups.filter((g) => !g.active).sort((a, b) => a.code.localeCompare(b.code)), [groups]);
  const total = current.reduce((n, g) => n + g.members, 0);
  const { sorted, sort, toggle } = useSortable<GroupSummary, GKey>(
    current,
    {
      code: (g) => g.code,
      name: (g) => g.name,
      members: (g) => g.members,
      countries: (g) => Object.keys(g.countries).length,
    },
    { key: 'members', dir: 'desc' },
    { members: 'desc', countries: 'desc' },
  );

  return (
    <section aria-labelledby="groups-h">
      <h2 id="groups-h">Political groups in the current Parliament</h2>
      <p className="section-intro">
        {formatNumber(current.filter((g) => g.id !== 'ni').length)} political groups
        {current.some((g) => g.id === 'ni') ? ' and the non-attached members (NI), who belong to no group' : ''} — {formatNumber(total)}{' '}
        current MEPs in total in our dataset.
      </p>
      {current.length === 0 ? (
        <EmptyState title="No current group data available" />
      ) : (
        <div className="table-wrap table-card">
          <table className="table">
            <caption className="visually-hidden">Political groups. Select a column heading to sort.</caption>
            <thead>
              <tr>
                <SortTh k="code" sort={sort} onSort={toggle}>
                  Group
                </SortTh>
                <SortTh k="name" sort={sort} onSort={toggle}>
                  Full name
                </SortTh>
                <SortTh k="members" sort={sort} onSort={toggle} num>
                  Current members
                </SortTh>
                <SortTh k="countries" sort={sort} onSort={toggle} num>
                  Countries represented
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.map((g) => (
                <tr key={g.id}>
                  <th scope="row">
                    <Link to={`/people/groups/${encodeURIComponent(g.id)}`}>{g.code}</Link>
                  </th>
                  <td>{g.name}</td>
                  <td className="num">{formatNumber(g.members)}</td>
                  <td className="num">{formatNumber(Object.keys(g.countries).length)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {earlier.length > 0 && (
        <div style={{ marginTop: 'var(--sp-6)' }}>
          <h3>Groups from earlier terms in our dataset</h3>
          <ul className="member-grid">
            {earlier.map((g) => (
              <li key={g.id}>
                <Link to={`/people/groups/${encodeURIComponent(g.id)}`}>{g.code}</Link>
                <span className="meta">
                  {g.name}
                  {g.terms.length > 0 && <> · {g.terms.map(termLabel).join(', ')}</>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

const PAGE = 60;
type PKey = 'label' | 'country' | 'active' | 'total';

export function PartiesBrowse({ parties, groups }: { parties: PartySummary[]; groups: Map<string, GroupSummary> }) {
  const [params, setParams] = useSearchParams();
  const [shown, setShown] = useState(PAGE);
  const q = params.get('pq') ?? '';
  const country = params.get('pcountry') ?? '';
  const scope = params.get('pscope') ?? 'current';
  const set = (key: string, value: string, dflt = '') => {
    const next = new URLSearchParams(params);
    if (value && value !== dflt) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const filterKey = params.toString();
  useEffect(() => setShown(PAGE), [filterKey]);

  const countries = useMemo(
    () => [...new Set(parties.map((p) => p.country))].sort((a, b) => countryName(a).localeCompare(countryName(b))),
    [parties],
  );
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return parties.filter(
      (p) =>
        (scope === 'all' || p.members_active > 0) &&
        (!country || p.country === country) &&
        (!needle || p.label.toLowerCase().includes(needle) || (p.code ?? '').toLowerCase().includes(needle)),
    );
  }, [parties, q, country, scope]);
  const { sorted, sort, toggle } = useSortable<PartySummary, PKey>(
    filtered,
    {
      label: (p) => p.label,
      country: (p) => countryName(p.country),
      active: (p) => p.members_active,
      total: (p) => p.members_total,
    },
    { key: 'country', dir: 'asc' },
    { active: 'desc', total: 'desc' },
  );

  return (
    <section aria-labelledby="parties-h">
      <h2 id="parties-h">National parties</h2>
      <p className="section-intro">
        MEPs are elected on national lists. These are the national parties (and independent lists) recorded for MEPs in our dataset, with
        the European political groups their MEPs joined.
      </p>
      <form className="filters" role="search" aria-label="Find a national party" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="pf-q">Party name</label>
          <input id="pf-q" className="input" type="search" value={q} onChange={(e) => set('pq', e.target.value)} />
        </div>
        <CollapsibleFilters label="Filters" active={(country ? 1 : 0) + (scope !== 'current' ? 1 : 0)}>
          <div className="field">
            <label htmlFor="pf-country">Country</label>
            <select id="pf-country" className="select" value={country} onChange={(e) => set('pcountry', e.target.value)}>
              <option value="">All countries</option>
              {countries.map((c) => (
                <option key={c} value={c}>
                  {countryName(c)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pf-scope">Show</label>
            <select id="pf-scope" className="select" value={scope} onChange={(e) => set('pscope', e.target.value, 'current')}>
              <option value="current">Parties with current MEPs</option>
              <option value="all">All parties in dataset</option>
            </select>
          </div>
        </CollapsibleFilters>
      </form>
      <p className="results-bar__count" aria-live="polite" style={{ marginBottom: 'var(--sp-3)' }}>
        {formatNumber(filtered.length)} {filtered.length === 1 ? 'party' : 'parties'}
      </p>
      {filtered.length === 0 ? (
        <EmptyState title="No parties match these filters" />
      ) : (
        <>
          <div className="table-wrap table-card">
            <table className="table">
              <caption className="visually-hidden">National parties. Select a column heading to sort.</caption>
              <thead>
                <tr>
                  <SortTh k="label" sort={sort} onSort={toggle}>
                    Party
                  </SortTh>
                  <SortTh k="country" sort={sort} onSort={toggle}>
                    Country
                  </SortTh>
                  <SortTh k="active" sort={sort} onSort={toggle} num>
                    Current MEPs
                  </SortTh>
                  <SortTh k="total" sort={sort} onSort={toggle} num>
                    MEPs in dataset
                  </SortTh>
                  <th scope="col">European political groups</th>
                </tr>
              </thead>
              <tbody>
                {sorted.slice(0, shown).map((p) => (
                  <tr key={p.id}>
                    <th scope="row" style={{ fontWeight: 500 }}>
                      <Link to={`/people/parties/${encodeURIComponent(p.id)}`}>{p.label}</Link>
                      {p.code && p.code !== p.label && <span className="meta"> ({p.code})</span>}
                    </th>
                    <td>{countryName(p.country)}</td>
                    <td className="num">{formatNumber(p.members_active)}</td>
                    <td className="num">{formatNumber(p.members_total)}</td>
                    <td>
                      <ul className="inline-list">
                        {p.groups.map((g) => (
                          <li key={g}>
                            <Link className="group-chip" to={`/people/groups/${encodeURIComponent(g)}`} title={groups.get(g)?.name}>
                              {groups.get(g)?.code ?? g}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sorted.length > shown && (
            <div className="more">
              <button type="button" className="btn" onClick={() => setShown((n) => n + PAGE)}>
                Show {formatNumber(Math.min(PAGE, sorted.length - shown))} more
              </button>
              <span className="meta">
                Showing {formatNumber(shown)} of {formatNumber(sorted.length)}
              </span>
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** What a national party is and what a political group is. On phones it is folded into a disclosure, so the lists start higher up. */
export function PartyVsGroup() {
  const narrow = useMediaQuery(PHONE_WIDTH);
  const body = (
    <div className={narrow ? 'party-vs-group party-vs-group--plain' : 'party-vs-group'}>
      <div>
        <h2>National party</h2>
        <p>
          The party an MEP was elected for in their own country, such as a party that also runs in national elections. National parties
          are organised country by country.
        </p>
      </div>
      <div>
        <h2>European political group</h2>
        <p>
          The group an MEP sits with inside Parliament. Groups bring together national parties from several countries with a similar
          outlook; a group needs at least 23 MEPs from at least seven Member States. Groups organise Parliament’s work, but each MEP casts
          their own vote.
        </p>
      </div>
    </div>
  );
  if (!narrow) return body;
  return (
    <div className="party-vs-group-disclosure">
      <Disclosure summary="National party or political group?">{body}</Disclosure>
    </div>
  );
}
