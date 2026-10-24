import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { PartyDetail, PartyRef } from '../types/data';
import { useData } from '../lib/data';
import { isMissing } from '../features/guide/missing';
import { countryName, formatDate, formatNumber } from '../lib/format';
import { LoadFailed, Loading, LookupNotice, NotFound, PageHeader, SourceLink, Term } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { partyRecordTitle, partySeating, periodText, recordPeriod, termYears, useGroups } from '../features/people/labels';
import { SortTh, compareValues, useSortable } from '../features/votes/sortable';
import '../features/people/people.css';

type MepRow = PartyDetail['meps'][number];

/** A link to another party record, with the term it covers when it shares this record's name (and its period when
 * it also shares the term with this record or with another record listed, as Azione's two 2019–2024 records do). */
function PartyRefLink({ r, withTerm, terms, others = [] }: { r: PartyRef; withTerm: boolean; terms?: number[]; others?: PartyRef[] }) {
  const term = termYears(r.terms);
  const sameTerm = !!term && (term === termYears(terms) || others.some((o) => o.id !== r.id && termYears(o.terms) === term));
  return (
    <>
      <Link to={`/people/parties/${encodeURIComponent(r.id)}`}>{r.label}</Link>
      {withTerm && term && (
        <>
          {' '}
          ({term}
          {sameTerm && `, ${recordPeriod(r.start, r.end)}`})
        </>
      )}
    </>
  );
}

/** "Dan Nica from 16 Jul 2024": a membership Parliament records in the record outside the record's own period. */
function outsideText(x: NonNullable<PartyDetail['outside_period']>[number]): string {
  return `${x.name} ${x.to ? `${x.from ? `from ${formatDate(x.from)} ` : ''}to ${formatDate(x.to)}` : x.from ? `from ${formatDate(x.from)}` : ''}`.trim();
}

/** The MEP's own status: sitting today (in this party record or under another one) or a former MEP. */
function statusText(r: MepRow): string {
  return r.active || r.mep_active ? 'Current MEP' : 'Former MEP';
}

export default function Party() {
  const { id = '' } = useParams();
  const { data: p, error, loading } = useData<PartyDetail>(`people/parties/${encodeURIComponent(id)}.json`);
  const groups = useGroups();
  useDocumentTitle(p ? partyRecordTitle(p) : isMissing(error) ? 'National party not found' : error ? 'National party could not be loaded' : 'National party');

  // by name within each status, as the Name column sorts ("Ľuboš" before "Monika", not after it as in the data's order)
  const byName = useMemo(() => [...(p?.meps ?? [])].sort((a, b) => compareValues(a.name, b.name, 'asc')), [p]);
  const m = useSortable<MepRow, 'name' | 'from' | 'to' | 'status'>(
    byName,
    {
      name: (r) => r.name,
      from: (r) => r.from ?? null,
      to: (r) => r.to ?? (r.active ? '9999' : null),
      status: (r) => (r.active ? 0 : r.mep_active ? 1 : 2),
    },
    { key: 'status', dir: 'asc' },
    { from: 'desc', to: 'desc' },
    'sort',
  );
  const history = useMemo(() => [...(p?.group_history ?? [])].sort((a, b) => (b.from ?? '').localeCompare(a.from ?? '')), [p]);
  const now = useMemo(() => new Map((p?.now_parties ?? []).map((r) => [r.id, r])), [p]);

  if (loading) return <div className="container page"><Loading label="Loading party…" /></div>;
  if (isMissing(error)) return <NotFound what="national party" />;
  if (error || !p) return <LoadFailed title="This party could not be loaded" />;

  const term = termYears(p.terms);
  const sameName = p.same_name ?? [];
  const nowParties = p.now_parties ?? [];
  // a record of an earlier term: Parliament closed it, and its MEPs are no longer recorded in it
  const closed = !!p.end && p.members_active === 0;
  // the records the build lists as having this record's name (names compared without spacing or punctuation)
  const sameIds = new Set(sameName.map((r) => r.id));
  const sameLabel = (r: PartyRef) => sameIds.has(r.id) || r.label === p.label;
  const outside = p.outside_period ?? [];
  const afterEnd = !!p.end && outside.every((x) => !!x.from && x.from > p.end!);
  const sittingElsewhere = nowParties.reduce((n, r) => n + (r.meps ?? 0), 0);
  // the non-attached members (NI) are not a political group; MEPs no longer in this record "sat"
  const seating = partySeating(p.groups);
  const sit = p.members_active > 0 ? 'sit' : 'sat';

  return (
    <div className="container page">
      <p className="meta mb-3">
        <Link to="/people?view=parties">← National parties</Link>
      </p>
      <PageHeader
        eyebrow={
          <>
            National party · {countryName(p.country)}
            {term && <> · {term}</>}
          </>
        }
        title={p.label}
        lead={
          <>
            {p.code && p.code !== p.label ? <>{p.code} · </> : null}A national party (or electoral list) from{' '}
            <Link to={`/countries/${p.country}`}>{countryName(p.country)}</Link>, as recorded in Parliament’s membership data.
            {seating === 'groups' && (
              <>
                {' '}
                Its MEPs {sit} in Parliament in a European <Term id="political-group">political group</Term>.
              </>
            )}
            {seating === 'non-attached' && (
              <>
                {' '}
                Its MEPs {sit} in Parliament as non-attached members, outside any <Term id="political-group">political group</Term>.
              </>
            )}
            {seating === 'both' && (
              <>
                {' '}
                Its MEPs {p.members_active > 0 ? 'have sat' : 'sat'} in Parliament in a European{' '}
                <Term id="political-group">political group</Term> or as non-attached members.
              </>
            )}
          </>
        }
      />

      {(sameName.length > 0 || closed || outside.length > 0) && (
        <div className="callout party-record">
          <p>
            Parliament’s membership data records national parties term by term, so the same party can have several records. This
            record covers {p.start ? <>the period {recordPeriod(p.start, p.end)}</> : 'a period that is not recorded'}
            {term && <> ({term})</>}
            {closed ? ', and none of its MEPs is recorded in it today.' : '.'}
            {outside.length > 0 && (
              <>
                {' '}
                Parliament’s membership data also lists {outside.map(outsideText).join(', ')} in this record,{' '}
                {afterEnd ? 'after that period ended' : 'outside that period'}.
              </>
            )}
          </p>
          {sameName.length > 0 && (
            <p>
              {sameName.length === 1 ? 'Other record' : 'Other records'} of {p.label} ({countryName(p.country)}):{' '}
              {sameName.map((r, i) => (
                <span key={r.id}>
                  {i > 0 && ', '}
                  <PartyRefLink r={r} withTerm terms={p.terms} others={sameName} />
                  {r.start && !r.end && r.members_active > 0 && <> – {formatNumber(r.members_active)} current {r.members_active === 1 ? 'MEP' : 'MEPs'}</>}
                </span>
              ))}
              .
            </p>
          )}
        </div>
      )}

      <LookupNotice failed={groups.failed} what="Political group names" />

      <dl className="facts facts--inline">
        {closed ? (
          <>
            <div>
              <dt>MEPs in this record</dt>
              <dd className="big">{formatNumber(p.members_total)}</dd>
            </div>
            <div>
              <dt>Period of this record</dt>
              <dd>{p.start ? recordPeriod(p.start, p.end) : 'Not recorded'}</dd>
            </div>
          </>
        ) : (
          <>
            <div>
              {/* MEPs sitting today who are still in this record; those listed here who sit under another record are
                  counted in the note below the figures, so that the figure agrees with the "Current MEP" rows below */}
              <dt>Current MEPs in this record</dt>
              <dd className="big">{formatNumber(p.members_active)}</dd>
            </div>
            <div>
              <dt>MEPs in our dataset</dt>
              <dd className="big">{formatNumber(p.members_total)}</dd>
            </div>
          </>
        )}
        <div>
          <dt>
            {/* the non-attached (NI) are not a political group */}
            {!p.groups.includes('ni')
              ? 'European political groups'
              : p.groups.length > 1
                ? 'European political groups and non-attached members'
                : 'Non-attached members'}
          </dt>
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

      {nowParties.length > 0 && (
        <p className="note mt-3">
          {formatNumber(sittingElsewhere)} of the MEPs listed here {sittingElsewhere === 1 ? 'sits' : 'sit'} in Parliament today under
          another party record:{' '}
          {nowParties.map((r, i) => (
            <span key={r.id}>
              {i > 0 && ', '}
              <PartyRefLink r={r} withTerm={sameLabel(r)} terms={p.terms} /> ({formatNumber(r.meps ?? 0)})
            </span>
          ))}
          .
        </p>
      )}

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
                  {/* phones: the status is shown under the name and the period in one column, so nothing is off-screen */}
                  <SortTh k="status" sort={m.sort} onSort={m.toggle} className="hide-narrow">
                    Status
                  </SortTh>
                  <SortTh k="from" sort={m.sort} onSort={m.toggle}>
                    <span className="hide-narrow">With this party from</span>
                    <span className="only-narrow">With this party</span>
                  </SortTh>
                  <SortTh k="to" sort={m.sort} onSort={m.toggle} className="hide-narrow">
                    Until
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {m.sorted.map((r) => {
                  const moved = r.now_party ? now.get(r.now_party) : undefined;
                  const nowLine = moved && (
                    <span className="meta party-now">
                      Now: <PartyRefLink r={moved} withTerm={sameLabel(moved)} terms={p.terms} />
                    </span>
                  );
                  return (
                    <tr key={`${r.id}-${r.from ?? ''}`}>
                      <th scope="row">
                        <Link to={`/people/meps/${encodeURIComponent(r.id)}`}>{r.name}</Link>
                        <span className="only-narrow meta">
                          {statusText(r)}
                          {nowLine}
                        </span>
                      </th>
                      <td className="hide-narrow">
                        <span className={`status-dot${r.active || r.mep_active ? '' : ' status-dot--former'}`}>{statusText(r)}</span>
                        {nowLine}
                      </td>
                      <td>
                        <span className="hide-narrow nowrap">{r.from ? formatDate(r.from) : '—'}</span>
                        <span className="only-narrow">{r.from || r.to ? periodText(r.from, r.to) : '—'}</span>
                      </td>
                      <td className="nowrap hide-narrow">{r.to ? formatDate(r.to) : r.from ? 'Ongoing' : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="note mt-3">
          Dates are the party membership periods recorded by Parliament, within the parliamentary terms covered by our dataset (see{' '}
          <Link to="/about#coverage">coverage</Link>). “Current MEP” means the person sits in Parliament today; “Now” names the party
          record a sitting MEP is listed under when it is another one.
        </p>
      </section>

      <p className="note section">
        <SourceLink source={p.source} />
        {p.source?.retrieved_at && <> · retrieved {formatDate(p.source.retrieved_at.slice(0, 10))}</>}
      </p>
    </div>
  );
}
