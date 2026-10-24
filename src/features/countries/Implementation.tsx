import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { CountryDetail, InfringementInfo, TranspositionStatus } from '../../types/data';
import { formatDate, formatNumber } from '../../lib/format';
import { shownParam, useParamState, useParamText } from '../../lib/urlState';
import { dossierScores, loadSearch, type SearchEngine } from '../../lib/search';
import { EmptyState, ExtLink, Term } from '../../components/ui';
import { EURLEX_CELEX, TRANSPOSITION_LABEL, dossierPath } from '../legislation/labels';
import { SortTh, useSortable } from '../votes/sortable';
import { matchCases, matchDirectives, queryNumber } from './directiveSearch';
import './countries.css';

const T_ORDER: TranspositionStatus[] = [
  'measures_notified',
  'none_found',
  'deadline_not_reached',
  'no_deadline',
  'not_participating',
  'not_required',
  'unavailable',
];

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
// a new search starts from the first page
const TR_RESET = ['tr-show'];
const INF_RESET = ['inf-show'];

export function TranspositionTable({ rows, countryName }: { rows: TRow[]; countryName: string }) {
  // filters, order and rows shown are kept in the address (tr-…), so that Back from a file returns to the same list
  const [params, patch] = useParamState();
  const status = params.get('tr-status') ?? '';
  const qBox = useParamText('tr-q', TR_RESET);
  const q = qBox.value;
  const shown = shownParam(params, 'tr-show', PAGE);
  const counts = useMemo(() => {
    const m = new Map<TranspositionStatus, number>();
    for (const r of rows) m.set(r.status, (m.get(r.status) ?? 0) + 1);
    return m;
  }, [rows]);
  // files the site search finds for the query (common names, aliases); the index is loaded once there is a query
  const [engine, setEngine] = useState<SearchEngine | null>(null);
  const hasQuery = !!q.trim();
  useEffect(() => {
    if (hasQuery && !engine) loadSearch().then(setEngine, () => undefined);
  }, [hasQuery, engine]);
  const files = useMemo(
    () => (engine && hasQuery ? new Set(dossierScores(engine, q, queryNumber(q) ? { identifiers: true } : { wholeWords: true }).keys()) : null),
    [engine, hasQuery, q],
  );
  const match = useMemo(() => matchDirectives(status ? rows.filter((r) => r.status === status) : rows, q, files), [rows, status, q, files]);
  const filtered = match.rows;
  const { sorted: bySort, sort, toggle } = useSortable<TRow, 'title' | 'deadline' | 'measures' | 'status'>(
    filtered,
    {
      title: (r) => r.title,
      deadline: (r) => r.deadline ?? null,
      measures: (r) => r.measures,
      status: (r) => T_ORDER.indexOf(r.status),
    },
    { key: 'deadline', dir: 'desc' },
    { deadline: 'desc', measures: 'desc' },
    'tr-sort',
  );
  // the directive whose own number was searched for comes first, before acts whose titles only cite it
  const sorted = match.own.size ? [...bySort.filter((r) => match.own.has(r.celex)), ...bySort.filter((r) => !match.own.has(r.celex))] : bySort;

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
          <input id="tr-q" type="search" className="input" value={q} onChange={(e) => qBox.set(e.target.value)} onBlur={qBox.flush} />
        </div>
        <div className="field">
          <label htmlFor="tr-status">Status in the dataset</label>
          <select id="tr-status" className="select" value={status} onChange={(e) => patch({ 'tr-status': e.target.value, 'tr-show': null })}>
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
        {match.partial && filtered.length > 0 && <> · no whole-word matches for “{q.trim()}”, so these have words that start with it</>}
      </p>
      {filtered.length === 0 && hasQuery && (
        <p className="meta">
          No directive in this list matches “{q.trim()}”. The list covers the directives adopted in the legislative files on this site.{' '}
          <Link to={`/search?q=${encodeURIComponent(q.trim())}`}>Search the whole site</Link>
        </p>
      )}
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
                <SortTh k="deadline" sort={sort} onSort={toggle} className="hide-narrow">
                  Transposition deadline
                </SortTh>
                <SortTh k="measures" sort={sort} onSort={toggle} num>
                  Measures notified
                </SortTh>
                <SortTh k="status" sort={sort} onSort={toggle} className="hide-narrow">
                  Status in the dataset
                </SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, shown).map((r) => (
                <tr key={r.celex}>
                  <td className="impl-dir">
                    {r.dossier_id ? (
                      <Link className="row-link" to={dossierPath(r.dossier_id)}>
                        {r.title}
                      </Link>
                    ) : (
                      r.title
                    )}
                    <span className="meta as-block">
                      {/* the link first, where it was: a link centred under the title's would be too close a target */}
                      <ExtLink href={EURLEX_CELEX(r.celex)}>
                        <span className="mono">{r.celex}</span>
                      </ExtLink>
                      {r.act && (
                        <>
                          {' '}
                          · {r.act}
                          {r.names?.length ? ` (${r.names.join(', ')})` : ''}
                        </>
                      )}
                    </span>
                    {match.citing.has(r.celex) && match.number && (
                      <span className="meta impl-dir__cites">Listed because its title cites {match.number}; it is not that directive.</span>
                    )}
                    {match.viaSearch.has(r.celex) && (
                      <span className="meta impl-dir__cites">Listed because the site search finds its file for “{q.trim()}”.</span>
                    )}
                    {/* phones: the deadline and status columns are hidden and shown here */}
                    <span className="only-narrow impl-dir__more">
                      <TranspositionStatusLabel status={r.status} />
                      {r.status_note && <StatusNote r={r} />}
                      <span className="meta as-block">
                        Deadline: {r.deadline ? formatDate(r.deadline) : 'not recorded'}
                      </span>
                    </span>
                  </td>
                  <td className="nowrap hide-narrow">
                    {r.deadline ? formatDate(r.deadline) : <span className="muted">Not recorded</span>}
                  </td>
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
                  <td className="hide-narrow">
                    <TranspositionStatusLabel status={r.status} />
                    {/* the exemption's provision and condition (Directive (EU) 2016/798, Art. 33(4)), or Denmark's
                        position on a directive building upon the Schengen acquis (Protocol No 22, Art. 4) */}
                    {r.status_note && <StatusNote r={r} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sorted.length > shown && (
        <div className="more">
          <button type="button" className="btn" onClick={() => patch({ 'tr-show': String(shown + PAGE * 2) })}>
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

/** A row's status note, with the document it rests on when there is one (Denmark's notification to the Council). */
function StatusNote({ r }: { r: { status_note?: string | null; status_note_url?: string | null } }) {
  return (
    <span className="meta as-block">
      {r.status_note}
      {r.status_note_url && (
        <>
          {' '}
          <ExtLink href={r.status_note_url}>Notification</ExtLink>
        </>
      )}
    </span>
  );
}

const STATUS_LABEL: Record<InfringementInfo['status'], string> = { open: 'Open', closed: 'Closed', unknown: 'Status not recorded' };

const NO_DIRECTIVES: TRow[] = [];

export function InfringementTable({ rows, directives = NO_DIRECTIVES }: { rows: InfringementInfo[]; directives?: TRow[] }) {
  // kept in the address (inf-…) like the directives' filters; open cases are the default, "all" is inf-status=all
  const [params, patch] = useParamState();
  const rawStatus = params.get('inf-status') ?? 'open';
  const status = rawStatus === 'all' ? '' : rawStatus;
  const qBox = useParamText('inf-q', INF_RESET);
  const q = qBox.value;
  const nonComm = params.get('inf-nc') === '1';
  const shown = shownParam(params, 'inf-show', PAGE);
  const counts = useMemo(() => {
    const m = { open: 0, closed: 0, unknown: 0 } as Record<InfringementInfo['status'], number>;
    for (const r of rows) m[r.status] = (m[r.status] ?? 0) + 1;
    return m;
  }, [rows]);
  const hasNonComm = rows.some((r) => r.non_communication);
  // whole words, and the number and names of the directive a case concerns, as in the directive search above
  const match = useMemo(
    () => matchCases(rows.filter((r) => (!status || r.status === status) && (!nonComm || r.non_communication)), q, directives),
    [rows, status, nonComm, q, directives],
  );
  const filtered = match.rows;
  const { sorted, sort, toggle } = useSortable<InfringementInfo, 'id' | 'date' | 'stage'>(
    filtered,
    { id: (r) => r.id, date: (r) => r.latest_decision_date ?? null, stage: (r) => r.latest_stage ?? null },
    { key: 'date', dir: 'desc' },
    { date: 'desc' },
    'inf-sort',
  );

  if (rows.length === 0) return <EmptyState title="No infringement cases for this country in the available dataset" />;

  return (
    <div>
      <form className="filters" aria-label="Filter infringement cases" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="inf-q">Search cases</label>
          <input id="inf-q" type="search" className="input" value={q} onChange={(e) => qBox.set(e.target.value)} onBlur={qBox.flush} />
        </div>
        <div className="field">
          <label htmlFor="inf-status">Case status</label>
          <select
            id="inf-status"
            className="select"
            value={status}
            onChange={(e) => patch({ 'inf-status': e.target.value === 'open' ? null : e.target.value || 'all', 'inf-show': null })}
          >
            <option value="open">Open ({formatNumber(counts.open)})</option>
            <option value="closed">Closed ({formatNumber(counts.closed)})</option>
            {counts.unknown > 0 && <option value="unknown">Status not recorded ({formatNumber(counts.unknown)})</option>}
            <option value="">All ({formatNumber(rows.length)})</option>
          </select>
        </div>
        {hasNonComm && (
          <div className="field field--check">
            <input id="inf-nc" type="checkbox" checked={nonComm} onChange={(e) => patch({ 'inf-nc': e.target.checked ? '1' : null, 'inf-show': null })} />
            <label htmlFor="inf-nc">Only cases about not notifying transposition measures</label>
          </div>
        )}
      </form>
      <p className="results-bar__count" aria-live="polite" style={{ marginBottom: 'var(--sp-2)' }}>
        {formatNumber(filtered.length)} {filtered.length === 1 ? 'case' : 'cases'}
        {match.partial && filtered.length > 0 && <> · no whole-word matches for “{q.trim()}”, so these have words that start with it</>}
      </p>
      {filtered.length === 0 && q.trim() && (
        <p className="meta">
          No case {status ? 'with this status' : 'in this list'} matches “{q.trim()}”. Cases are found by their subject and number, and by
          the number or name of the directive they concern (for example <span className="mono">2022/2555</span> or NIS 2).
        </p>
      )}
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
                <SortTh k="stage" sort={sort} onSort={toggle} className="hide-narrow">
                  Latest stage (as published)
                </SortTh>
                <SortTh k="date" sort={sort} onSort={toggle} className="hide-narrow">
                  Decision date
                </SortTh>
                <th scope="col" className="hide-narrow">
                  Status
                </th>
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
                    {r.non_communication && <span className="meta as-block">Non-communication of transposition measures</span>}
                    {/* phones: the stage, date and status columns are hidden and shown here */}
                    <span className="only-narrow meta">
                      <span className={r.status === 'open' ? 'status-open' : undefined}>{STATUS_LABEL[r.status]}</span>
                      {r.latest_stage ? ` · ${r.latest_stage}` : ''}
                      {r.latest_decision_date ? ` · ${formatDate(r.latest_decision_date)}` : ''}
                    </span>
                  </td>
                  <td className="wrap-cell hide-narrow">{r.latest_stage ?? <span className="muted">Not recorded</span>}</td>
                  <td className="nowrap hide-narrow">{r.latest_decision_date ? formatDate(r.latest_decision_date) : '—'}</td>
                  <td className={`hide-narrow${r.status === 'open' ? ' status-open' : ''}`}>{STATUS_LABEL[r.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sorted.length > shown && (
        <div className="more">
          <button type="button" className="btn" onClick={() => patch({ 'inf-show': String(shown + PAGE * 2) })}>
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
      Court of Justice. Stages are shown exactly as the Commission publishes them. The list holds all open cases and all cases with
      a Commission decision since 1 January 2019; cases closed before then are not included.
    </p>
  );
}
