import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { MepSummary } from '../../types/data';
import { countryName, formatNumber } from '../../lib/format';
import { clearAllParams, shownParam, useParamState, useParamText } from '../../lib/urlState';
import { EmptyState } from '../../components/ui';
import { CollapsibleFilters } from '../../components/CollapsibleFilters';
import { SortTh, useSortable } from '../votes/sortable';
import { FULL_TERM_MIN_MEPS, termLabel, type GroupLabel } from './labels';
import './people.css';

const PAGE = 60;
const SHOW_RESET = ['show']; // a new search starts from the first page
type Key = 'name' | 'country' | 'group' | 'party';

export function MepSearch({ meps, groups }: { meps: MepSummary[]; groups: Map<string, GroupLabel> }) {
  const [params, patch] = useParamState();
  // rows shown: kept in the address like the filters, so that Back from an MEP returns to the same list
  const shown = shownParam(params, 'show', PAGE);
  const qBox = useParamText('q', SHOW_RESET);
  const q = qBox.value;
  const country = params.get('country') ?? '';
  const group = params.get('group') ?? '';
  const partyBox = useParamText('party', SHOW_RESET);
  const party = partyBox.value;
  const status = params.get('status') ?? 'current';
  const term = params.get('term') ?? '';

  // a new filter starts from the first page
  const set = (key: string, value: string, dflt = '') => patch({ [key]: value !== dflt ? value : null, show: null });
  const setShown = (n: number) => patch({ show: String(n) });

  const opts = useMemo(() => {
    const countries = [...new Set(meps.map((m) => m.country))].sort((a, b) => countryName(a).localeCompare(countryName(b)));
    const groupIds = [...new Set(meps.map((m) => m.group).filter(Boolean) as string[])].sort((a, b) =>
      (groups.get(a)?.code ?? a).localeCompare(groups.get(b)?.code ?? b),
    );
    // Only offer terms our dataset covers in full; `terms` also lists earlier terms served by long-serving MEPs.
    const perTerm = new Map<number, number>();
    for (const m of meps) for (const t of m.terms) perTerm.set(t, (perTerm.get(t) ?? 0) + 1);
    const terms = [...perTerm].filter(([, n]) => n >= FULL_TERM_MIN_MEPS).map(([t]) => t).sort((a, b) => b - a);
    return { countries, groupIds, terms };
  }, [meps, groups]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const pNeedle = party.trim().toLowerCase();
    return meps.filter(
      (m) =>
        (status === 'all' || (status === 'current' ? m.active : !m.active)) &&
        (!country || m.country === country) &&
        (!group || m.group === group) &&
        (!term || m.terms.includes(Number(term))) &&
        (!pNeedle || (m.party_label ?? '').toLowerCase().includes(pNeedle)) &&
        (!needle || m.name.toLowerCase().includes(needle) || m.sort.toLowerCase().includes(needle)),
    );
  }, [meps, q, country, group, party, status, term]);

  const { sorted, sort, toggle } = useSortable<MepSummary, Key>(
    filtered,
    {
      name: (m) => m.sort || m.name,
      country: (m) => countryName(m.country),
      group: (m) => m.group_code ?? null,
      party: (m) => m.party_label ?? null,
    },
    { key: 'name', dir: 'asc' },
    {},
    'sort',
  );

  const anyFilter = [q, country, group, party, term].some(Boolean) || status !== 'current';
  const activeFilters = [country, group, party.trim(), term].filter(Boolean).length + (status !== 'current' ? 1 : 0);

  return (
    <section aria-labelledby="mep-h">
      <h2 id="mep-h" className="visually-hidden">
        Find an MEP
      </h2>
      <form className="filters filters--wide-first" role="search" aria-label="Find an MEP" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="mf-q">Name</label>
          <input id="mf-q" className="input" type="search" value={q} placeholder="Search by name" onChange={(e) => qBox.set(e.target.value)} onBlur={qBox.flush} />
        </div>
        <CollapsibleFilters label="Filters" active={activeFilters}>
          <div className="field">
            <label htmlFor="mf-country">Country represented</label>
            <select id="mf-country" className="select" value={country} onChange={(e) => set('country', e.target.value)}>
              <option value="">All countries</option>
              {opts.countries.map((c) => (
                <option key={c} value={c}>
                  {countryName(c)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="mf-group">Political group</label>
            <select id="mf-group" className="select" value={group} onChange={(e) => set('group', e.target.value)}>
              <option value="">All groups</option>
              {opts.groupIds.map((g) => (
                <option key={g} value={g}>
                  {groups.get(g)?.code ?? g}
                  {groups.get(g)?.active === false ? ' (earlier term)' : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="mf-party">National party</label>
            <input id="mf-party" className="input" type="search" value={party} placeholder="Party name" onChange={(e) => partyBox.set(e.target.value)} onBlur={partyBox.flush} />
          </div>
          <div className="field">
            <label htmlFor="mf-status">Status</label>
            <select id="mf-status" className="select" value={status} onChange={(e) => set('status', e.target.value, 'current')}>
              <option value="current">Current MEPs</option>
              <option value="former">Former MEPs</option>
              <option value="all">Current and former</option>
            </select>
          </div>
          {opts.terms.length > 1 && (
            <div className="field">
              <label htmlFor="mf-term">Parliamentary term</label>
              <select id="mf-term" className="select" value={term} onChange={(e) => set('term', e.target.value)}>
                <option value="">All terms covered</option>
                {opts.terms.map((t) => (
                  <option key={t} value={t}>
                    {termLabel(t)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </CollapsibleFilters>
      </form>

      <div className="results-bar">
        <p className="results-bar__count" aria-live="polite">
          {formatNumber(filtered.length)} {filtered.length === 1 ? 'MEP' : 'MEPs'}
          {status === 'current' ? ' currently in office' : status === 'former' ? ' no longer in office' : ''}
        </p>
        {anyFilter && (
          <button type="button" className="linkish" onClick={() => patch(clearAllParams({ view: 'meps' }))}>
            Clear all filters
          </button>
        )}
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="No MEPs match these filters">Try another spelling, or include former MEPs.</EmptyState>
      ) : (
        <>
          <div className="table-wrap table-card">
            <table className="table">
              <caption className="visually-hidden">MEPs matching the filters. Select a column heading to sort.</caption>
              <thead>
                <tr>
                  <SortTh k="name" sort={sort} onSort={toggle}>
                    Name
                  </SortTh>
                  {/* phones: country, national party and status are shown under the name, so the group stays on screen */}
                  <SortTh k="country" sort={sort} onSort={toggle} className="hide-narrow">
                    Country
                  </SortTh>
                  <SortTh k="group" sort={sort} onSort={toggle}>
                    Group
                  </SortTh>
                  <SortTh k="party" sort={sort} onSort={toggle} className="hide-narrow">
                    National party
                  </SortTh>
                  <th scope="col" className="hide-narrow">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.slice(0, shown).map((m) => (
                  <tr key={m.id}>
                    <th scope="row" style={{ fontWeight: 500 }}>
                      <Link to={`/people/meps/${encodeURIComponent(m.id)}`}>{m.name}</Link>
                      <span className="only-narrow meta" style={{ fontWeight: 400 }}>
                        {countryName(m.country)} · {m.active ? 'Current' : 'Former'}
                        {m.party_label && (
                          <span style={{ display: 'block' }}>
                            {m.party ? <Link to={`/people/parties/${encodeURIComponent(m.party)}`}>{m.party_label}</Link> : m.party_label}
                          </span>
                        )}
                      </span>
                    </th>
                    <td className="hide-narrow">{countryName(m.country)}</td>
                    <td>
                      {m.group ? (
                        <span title={groups.get(m.group)?.name}>{m.group_code ?? groups.get(m.group)?.code ?? m.group}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="hide-narrow">
                      {m.party && m.party_label ? (
                        <Link to={`/people/parties/${encodeURIComponent(m.party)}`}>{m.party_label}</Link>
                      ) : (
                        <span className="muted">{m.party_label ?? '—'}</span>
                      )}
                    </td>
                    <td className="hide-narrow">
                      <span className={`status-dot${m.active ? '' : ' status-dot--former'}`}>{m.active ? 'Current' : 'Former'}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sorted.length > shown && (
            <div className="more">
              <button type="button" className="btn" onClick={() => setShown(shown + PAGE)}>
                Show {formatNumber(Math.min(PAGE, sorted.length - shown))} more
              </button>
              <span className="meta">
                Showing {formatNumber(shown)} of {formatNumber(sorted.length)}
              </span>
            </div>
          )}
          <p className="note" style={{ marginTop: 'var(--sp-3)' }}>
            For former MEPs, the group and party shown are the last ones recorded.
          </p>
        </>
      )}
    </section>
  );
}
