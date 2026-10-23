import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { CountryDetail, InfringementInfo, TranspositionStatus } from '../../types/data';
import { formatDate, formatNumber } from '../../lib/format';
import { EmptyState, ExtLink, Term } from '../../components/ui';
import { EURLEX_CELEX, TRANSPOSITION_LABEL, dossierPath } from '../legislation/labels';
import { SortTh, useSortable } from '../votes/sortable';
import './countries.css';

const T_ORDER: TranspositionStatus[] = ['measures_notified', 'none_found', 'deadline_not_reached', 'not_participating', 'unavailable'];

export const NIM_URL = (celex: string) => `https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:${encodeURIComponent(celex)}`;

export function TranspositionStatusLabel({ status }: { status: TranspositionStatus }) {
  return (
    <span className={`tstatus tstatus--${status}`}>
      <span className="tstatus__icon" aria-hidden="true" />
      {TRANSPOSITION_LABEL[status]}
    </span>
  );
}

type TRow = CountryDetail['transposition'][number];
const PAGE = 25;

export function TranspositionTable({ rows, countryName }: { rows: TRow[]; countryName: string }) {
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [shown, setShown] = useState(PAGE);
  const counts = useMemo(() => {
    const m = new Map<TranspositionStatus, number>();
    for (const r of rows) m.set(r.status, (m.get(r.status) ?? 0) + 1);
    return m;
  }, [rows]);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => (!status || r.status === status) && (!needle || `${r.title} ${r.celex}`.toLowerCase().includes(needle)));
  }, [rows, status, q]);
  const { sorted, sort, toggle } = useSortable<TRow, 'title' | 'deadline' | 'measures' | 'status'>(
    filtered,
    {
      title: (r) => r.title,
      deadline: (r) => r.deadline ?? null,
      measures: (r) => r.measures,
      status: (r) => T_ORDER.indexOf(r.status),
    },
    { key: 'deadline', dir: 'desc' },
    { deadline: 'desc', measures: 'desc' },
  );

  if (rows.length === 0)
    return <EmptyState title="No directives with transposition data for this country in this release" />;

  return (
    <div>
      <dl className="facts" style={{ marginBottom: 'var(--sp-4)' }}>
        {T_ORDER.filter((s) => counts.get(s)).map((s) => (
          <div key={s}>
            <dt>{TRANSPOSITION_LABEL[s]}</dt>
            <dd className="big">{formatNumber(counts.get(s))}</dd>
          </div>
        ))}
      </dl>
      <form className="filters" aria-label="Filter directives" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="tr-q">Search directives</label>
          <input id="tr-q" type="search" className="input" value={q} onChange={(e) => (setQ(e.target.value), setShown(PAGE))} />
        </div>
        <div className="field">
          <label htmlFor="tr-status">Status in the dataset</label>
          <select id="tr-status" className="select" value={status} onChange={(e) => (setStatus(e.target.value), setShown(PAGE))}>
            <option value="">All ({formatNumber(rows.length)})</option>
            {T_ORDER.filter((s) => counts.get(s)).map((s) => (
              <option key={s} value={s}>
                {TRANSPOSITION_LABEL[s]} ({formatNumber(counts.get(s))})
              </option>
            ))}
          </select>
        </div>
      </form>
      <p className="results-bar__count" aria-live="polite" style={{ marginBottom: 'var(--sp-2)' }}>
        {formatNumber(filtered.length)} {filtered.length === 1 ? 'directive' : 'directives'}
      </p>
      {filtered.length > 0 && (
        <div className="table-wrap table-card">
          <table className="table">
            <caption className="visually-hidden">
              Directives and national measures notified by {countryName}. Select a column heading to sort.
            </caption>
            <thead>
              <tr>
                <SortTh k="title" sort={sort} onSort={toggle}>
                  Directive
                </SortTh>
                <SortTh k="deadline" sort={sort} onSort={toggle}>
                  Transposition deadline
                </SortTh>
                <SortTh k="measures" sort={sort} onSort={toggle} num>
                  Measures notified
                </SortTh>
                <SortTh k="status" sort={sort} onSort={toggle}>
                  Status in the dataset
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, shown).map((r) => (
                <tr key={r.celex}>
                  <td style={{ minWidth: '15rem' }}>
                    {r.dossier_id ? <Link to={dossierPath(r.dossier_id)}>{r.title}</Link> : r.title}
                    <span className="meta" style={{ display: 'block' }}>
                      <ExtLink href={EURLEX_CELEX(r.celex)}>
                        <span className="mono">{r.celex}</span>
                      </ExtLink>
                    </span>
                  </td>
                  <td className="nowrap">{r.deadline ? formatDate(r.deadline) : <span className="muted">Not recorded</span>}</td>
                  <td className="num">
                    {r.status === 'unavailable' ? (
                      <span className="muted">—</span>
                    ) : (
                      <ExtLink href={NIM_URL(r.celex)}>
                        {formatNumber(r.measures)}
                        <span className="visually-hidden"> national measures on EUR-Lex</span>
                      </ExtLink>
                    )}
                  </td>
                  <td>
                    <TranspositionStatusLabel status={r.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sorted.length > shown && (
        <div className="more">
          <button type="button" className="btn" onClick={() => setShown((n) => n + PAGE * 2)}>
            Show more directives
          </button>
          <span className="meta">
            Showing {formatNumber(shown)} of {formatNumber(sorted.length)}
          </span>
        </div>
      )}
    </div>
  );
}

const STATUS_LABEL: Record<InfringementInfo['status'], string> = { open: 'Open', closed: 'Closed', unknown: 'Status not recorded' };

export function InfringementTable({ rows }: { rows: InfringementInfo[] }) {
  const [status, setStatus] = useState('open');
  const [q, setQ] = useState('');
  const [nonComm, setNonComm] = useState(false);
  const [shown, setShown] = useState(PAGE);
  const counts = useMemo(() => {
    const m = { open: 0, closed: 0, unknown: 0 } as Record<InfringementInfo['status'], number>;
    for (const r of rows) m[r.status] = (m[r.status] ?? 0) + 1;
    return m;
  }, [rows]);
  const hasNonComm = rows.some((r) => r.non_communication);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (!status || r.status === status) &&
        (!nonComm || r.non_communication) &&
        (!needle || `${r.title} ${r.id} ${r.celex ?? ''}`.toLowerCase().includes(needle)),
    );
  }, [rows, status, nonComm, q]);
  const { sorted, sort, toggle } = useSortable<InfringementInfo, 'id' | 'date' | 'stage'>(
    filtered,
    { id: (r) => r.id, date: (r) => r.latest_decision_date ?? null, stage: (r) => r.latest_stage ?? null },
    { key: 'date', dir: 'desc' },
    { date: 'desc' },
  );

  if (rows.length === 0) return <EmptyState title="No infringement cases for this country in the available dataset" />;

  return (
    <div>
      <form className="filters" aria-label="Filter infringement cases" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="inf-q">Search cases</label>
          <input id="inf-q" type="search" className="input" value={q} onChange={(e) => (setQ(e.target.value), setShown(PAGE))} />
        </div>
        <div className="field">
          <label htmlFor="inf-status">Case status</label>
          <select id="inf-status" className="select" value={status} onChange={(e) => (setStatus(e.target.value), setShown(PAGE))}>
            <option value="open">Open ({formatNumber(counts.open)})</option>
            <option value="closed">Closed ({formatNumber(counts.closed)})</option>
            {counts.unknown > 0 && <option value="unknown">Status not recorded ({formatNumber(counts.unknown)})</option>}
            <option value="">All ({formatNumber(rows.length)})</option>
          </select>
        </div>
        {hasNonComm && (
          <div className="field field--check">
            <input id="inf-nc" type="checkbox" checked={nonComm} onChange={(e) => (setNonComm(e.target.checked), setShown(PAGE))} />
            <label htmlFor="inf-nc">Only cases about not notifying transposition measures</label>
          </div>
        )}
      </form>
      <p className="results-bar__count" aria-live="polite" style={{ marginBottom: 'var(--sp-2)' }}>
        {formatNumber(filtered.length)} {filtered.length === 1 ? 'case' : 'cases'}
      </p>
      {filtered.length > 0 && (
        <div className="table-wrap table-card">
          <table className="table">
            <caption className="visually-hidden">Infringement cases. Select a column heading to sort.</caption>
            <thead>
              <tr>
                <SortTh k="id" sort={sort} onSort={toggle}>
                  Case
                </SortTh>
                <th scope="col">Subject</th>
                <SortTh k="stage" sort={sort} onSort={toggle}>
                  Latest stage (as published)
                </SortTh>
                <SortTh k="date" sort={sort} onSort={toggle}>
                  Decision date
                </SortTh>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, shown).map((r) => (
                <tr key={r.id}>
                  <td className="nowrap mono">
                    <ExtLink href={r.source?.url}>{r.id}</ExtLink>
                  </td>
                  <td className="wrap-cell">
                    {r.title}
                    {r.non_communication && <span className="meta" style={{ display: 'block' }}>Non-communication of transposition measures</span>}
                  </td>
                  <td className="wrap-cell">{r.latest_stage ?? <span className="muted">Not recorded</span>}</td>
                  <td className="nowrap">{r.latest_decision_date ? formatDate(r.latest_decision_date) : '—'}</td>
                  <td className={r.status === 'open' ? 'status-open' : undefined}>{STATUS_LABEL[r.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sorted.length > shown && (
        <div className="more">
          <button type="button" className="btn" onClick={() => setShown((n) => n + PAGE * 2)}>
            Show more cases
          </button>
          <span className="meta">
            Showing {formatNumber(shown)} of {formatNumber(sorted.length)}
          </span>
        </div>
      )}
    </div>
  );
}

export function InfringementNote() {
  return (
    <p className="callout">
      An <Term id="infringement">infringement case</Term> is opened by the European Commission when it considers that a Member State may
      not be applying EU law correctly. <strong>An open case is not a court ruling</strong>: most cases are closed before reaching the
      Court of Justice. Stages are shown exactly as the Commission publishes them.
    </p>
  );
}
