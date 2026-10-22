import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { PartyDetail } from '../types/data';
import { useData } from '../lib/data';
import { isMissing } from '../features/guide/missing';
import { countryName, formatDate, formatNumber } from '../lib/format';
import { ErrorState, Loading, NotFound, PageHeader, SourceLink, Term } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { periodText, useGroups } from '../features/people/labels';
import { SortTh, useSortable } from '../features/votes/sortable';
import '../features/people/people.css';

type MepRow = PartyDetail['meps'][number];

export default function Party() {
  const { id = '' } = useParams();
  const { data: p, error, loading } = useData<PartyDetail>(`people/parties/${encodeURIComponent(id)}.json`);
  const groups = useGroups();
  useDocumentTitle(p ? `${p.label} (${countryName(p.country)})` : 'National party');

  const m = useSortable<MepRow, 'name' | 'from' | 'to' | 'status'>(
    p?.meps ?? [],
    { name: (r) => r.name, from: (r) => r.from ?? null, to: (r) => r.to ?? (r.active ? '9999' : null), status: (r) => (r.active ? 0 : 1) },
    { key: 'status', dir: 'asc' },
    { from: 'desc', to: 'desc' },
  );
  const history = useMemo(() => [...(p?.group_history ?? [])].sort((a, b) => (b.from ?? '').localeCompare(a.from ?? '')), [p]);

  if (loading) return <div className="container page"><Loading label="Loading party…" /></div>;
  if (isMissing(error)) return <NotFound what="national party" />;
  if (error || !p) return <div className="container page"><ErrorState error={error} title="This party could not be loaded" /></div>;

  return (
    <div className="container page">
      <p className="meta" style={{ marginBottom: 'var(--sp-3)' }}>
        <Link to="/people?view=parties">← National parties</Link>
      </p>
      <PageHeader
        eyebrow={<>National party · {countryName(p.country)}</>}
        title={p.label}
        lead={
          <>
            {p.code && p.code !== p.label ? <>{p.code} · </> : null}A national party (or electoral list) from{' '}
            <Link to={`/countries/${p.country}`}>{countryName(p.country)}</Link>, as recorded in Parliament’s membership data. Its MEPs sit in
            Parliament in a European <Term id="political-group">political group</Term>.
          </>
        }
      />

      <dl className="facts card">
        <div>
          <dt>Current MEPs</dt>
          <dd className="big">{formatNumber(p.members_active)}</dd>
        </div>
        <div>
          <dt>MEPs in our dataset</dt>
          <dd className="big">{formatNumber(p.members_total)}</dd>
        </div>
        <div>
          <dt>European political groups</dt>
          <dd>
            {p.groups.length ? (
              <ul className="inline-list">
                {p.groups.map((g) => (
                  <li key={g}>
                    <Link className="group-chip" to={`/people/groups/${encodeURIComponent(g)}`} title={groups.byId.get(g)?.name}>
                      {groups.byId.get(g)?.code ?? g}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              'None recorded'
            )}
          </dd>
        </div>
      </dl>

      <section className="section" aria-labelledby="gh-h">
        <h2 id="gh-h">Political groups its MEPs sat in</h2>
        <p className="section-intro">
          Periods during which this party’s MEPs were members of each group. MEPs of the same party usually, but not always, sit in the
          same group.
        </p>
        {history.length === 0 ? (
          <p className="meta">No group membership recorded.</p>
        ) : (
          <ol className="history">
            {history.map((h, i) => {
              const g = groups.byId.get(h.group);
              return (
                <li key={`${h.group}-${h.from ?? i}`} className={h.to ? undefined : 'is-current'}>
                  <span className="history__label">
                    <Link to={`/people/groups/${encodeURIComponent(h.group)}`}>{g?.code ?? h.group}</Link>
                  </span>
                  {g && <span className="meta"> {g.name}</span>}
                  <span className="history__meta">
                    {periodText(h.from, h.to)}
                    {!h.to && ' (current)'} · {formatNumber(h.meps)} {h.meps === 1 ? 'MEP' : 'MEPs'}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <section className="section" aria-labelledby="pm-h">
        <h2 id="pm-h">MEPs</h2>
        {p.meps.length === 0 ? (
          <p className="meta">No MEPs recorded.</p>
        ) : (
          <div className="table-wrap table-card">
            <table className="table">
              <caption className="visually-hidden">MEPs recorded for this party. Select a column heading to sort.</caption>
              <thead>
                <tr>
                  <SortTh k="name" sort={m.sort} onSort={m.toggle}>
                    Name
                  </SortTh>
                  <SortTh k="status" sort={m.sort} onSort={m.toggle}>
                    Status
                  </SortTh>
                  <SortTh k="from" sort={m.sort} onSort={m.toggle}>
                    With this party from
                  </SortTh>
                  <SortTh k="to" sort={m.sort} onSort={m.toggle}>
                    Until
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {m.sorted.map((r) => (
                  <tr key={`${r.id}-${r.from ?? ''}`}>
                    <th scope="row" style={{ fontWeight: 500 }}>
                      <Link to={`/people/meps/${encodeURIComponent(r.id)}`}>{r.name}</Link>
                    </th>
                    <td>
                      <span className={`status-dot${r.active ? '' : ' status-dot--former'}`}>{r.active ? 'Current MEP' : 'Former MEP'}</span>
                    </td>
                    <td className="nowrap">{r.from ? formatDate(r.from) : '—'}</td>
                    <td className="nowrap">{r.to ? formatDate(r.to) : r.from ? 'Ongoing' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="note" style={{ marginTop: 'var(--sp-3)' }}>
          Dates are the party membership periods recorded by Parliament, within the parliamentary terms covered by our dataset (see{' '}
          <Link to="/about#coverage">coverage</Link>).
        </p>
      </section>

      <p className="note section">
        <SourceLink source={p.source} />
        {p.source?.retrieved_at && <> · retrieved {formatDate(p.source.retrieved_at.slice(0, 10))}</>}
      </p>
    </div>
  );
}
