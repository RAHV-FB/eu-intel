import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { CountryDetail, Meta } from '../types/data';
import { useData } from '../lib/data';
import { isMissing } from '../features/guide/missing';
import { COUNTRY_NAMES, formatDate, formatNumber, pct } from '../lib/format';
import { useParamState } from '../lib/urlState';
import { ErrorState, ExtLink, Loading, NotFound, PageHeader, SourceLink, Tag, Term } from '../components/ui';
import { RowTitle, StackLabel } from '../components/StackedTable';
import { dossierPath, useDocumentTitle } from '../features/legislation/labels';
import { useGroups } from '../features/people/labels';
import { formatIndicator } from '../features/countries/CountryTable';
import { InfringementNote, InfringementTable, TranspositionTable } from '../features/countries/Implementation';
import { COUNCIL_POSITION_LABEL, COUNCIL_VOTE_ON_SHORT } from '../features/council/CouncilVoteCard';
import { Pos } from '../features/votes/Breakdowns';
import { SortTh, useSortable } from '../features/votes/sortable';
import '../features/countries/countries.css';

type GroupRow = { group: string; code: string; name: string; meps: number };
type MepRow = CountryDetail['meps'][number];

export default function Country() {
  const { code = '' } = useParams();
  const upper = code.toUpperCase();
  const valid = upper in COUNTRY_NAMES && upper !== 'GB';
  const { data: c, error, loading } = useData<CountryDetail>(valid ? `countries/${upper}.json` : null);
  const meta = useData<Meta>('meta.json');
  const groups = useGroups();
  // the open MEP list and the full Council vote list are kept in the address, so that Back returns to them
  const [params, patch] = useParamState();
  const allVotes = params.get('cvotes') === 'all';
  const showMeps = params.get('meps') === 'all';
  useDocumentTitle(!valid || isMissing(error) ? 'Country not found' : c ? c.name : COUNTRY_NAMES[upper]);

  const groupRows = useMemo<GroupRow[]>(
    () =>
      Object.entries(c?.groups ?? {})
        .filter(([, n]) => n > 0)
        .map(([g, n]) => ({ group: g, code: groups.byId.get(g)?.code ?? g, name: groups.byId.get(g)?.name ?? '', meps: n })),
    [c, groups.byId],
  );
  const gs = useSortable<GroupRow, 'code' | 'meps'>(groupRows, { code: (r) => r.code, meps: (r) => r.meps }, { key: 'meps', dir: 'desc' }, { meps: 'desc' });
  const ms = useSortable<MepRow, 'name' | 'group' | 'party'>(
    c?.meps ?? [],
    { name: (r) => r.name, group: (r) => (r.group ? groups.byId.get(r.group)?.code ?? r.group : null), party: (r) => r.party_label ?? null },
    { key: 'name', dir: 'asc' },
  );

  if (!valid) return <NotFound what="country" />;
  if (loading) return <div className="container page"><Loading label="Loading country…" /></div>;
  if (isMissing(error)) return <NotFound what="country" />;
  if (error || !c) return <div className="container page"><ErrorState error={error} title="This country could not be loaded" /></div>;

  const cp = c.council_positions;
  const councilTotal = cp.for + cp.against + cp.abstain + cp.not_participating;
  const councilSource = meta.data?.sources.find((s) => s.id === 'council');
  const councilDataExists = (meta.data?.counts.council_votes ?? 0) > 0;
  const implSource = meta.data?.sources.find((s) => s.id === 'implementation');
  const votesShown = allVotes ? c.council_votes : c.council_votes.slice(0, 20);

  return (
    <div className="container page">
      <p className="meta" style={{ marginBottom: 'var(--sp-3)' }}>
        <Link to="/countries">← All countries</Link>
      </p>
      <PageHeader
        eyebrow="Member State"
        title={c.name}
        lead={`Three different kinds of information about ${c.name} and the EU, kept separate: who represents it in the European Parliament, how its government took part in Council decisions, and what official records show about applying EU law.`}
      />
      <nav aria-label="Sections on this page">
        <ol className="country-nav">
          <li>
            <a href="#representation">
              <span className="n" aria-hidden="true">1</span> Representation
            </a>
          </li>
          <li>
            <a href="#participation">
              <span className="n" aria-hidden="true">2</span> Participation in EU decisions
            </a>
          </li>
          <li>
            <a href="#implementation">
              <span className="n" aria-hidden="true">3</span> Implementation
            </a>
          </li>
        </ol>
      </nav>

      {/* ------------------------------------------------------------ 1 */}
      <section id="representation" className="csection" aria-labelledby="rep-h">
        <p className="csection__kicker">1 · European Parliament</p>
        <h2 id="rep-h">Representation</h2>
        <p className="section-intro">
          MEPs elected in {c.name}. In Parliament they sit in European <Term id="political-group">political groups</Term> and vote
          individually — not as a national delegation, and not on behalf of the government.
        </p>
        <dl className="facts card">
          <div>
            <dt>Current MEPs</dt>
            <dd className="big">{formatNumber(c.meps_active)}</dd>
          </div>
          <div>
            <dt>Political groups</dt>
            <dd className="big">{formatNumber(groupRows.length)}</dd>
          </div>
          <div>
            <dt>National parties</dt>
            <dd className="big">{formatNumber(c.parties.filter((p) => p.members_active > 0).length)}</dd>
          </div>
        </dl>

        <div className="grid grid--2" style={{ marginTop: 'var(--sp-5)' }}>
          <div>
            <h3>MEPs by political group</h3>
            {groupRows.length === 0 ? (
              <p className="meta">No group memberships recorded.</p>
            ) : (
              <div className="table-wrap table-card">
                <table className="table">
                  <caption className="visually-hidden">Current MEPs from {c.name} by political group. Select a column heading to sort.</caption>
                  <thead>
                    <tr>
                      <SortTh k="code" sort={gs.sort} onSort={gs.toggle}>
                        Group
                      </SortTh>
                      <SortTh k="meps" sort={gs.sort} onSort={gs.toggle} num>
                        MEPs
                      </SortTh>
                      <th scope="col" className="num">
                        Share
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {gs.sorted.map((r) => (
                      <tr key={r.group}>
                        <th scope="row" style={{ fontWeight: 500 }}>
                          <Link to={`/people/groups/${encodeURIComponent(r.group)}`}>{r.code}</Link>
                          {r.name && <span className="meta" style={{ display: 'block', fontWeight: 400 }}>{r.name}</span>}
                        </th>
                        <td className="num">{formatNumber(r.meps)}</td>
                        <td className="num">{pct(r.meps, c.meps_active)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div>
            <h3>National parties with current MEPs</h3>
            {c.parties.length === 0 ? (
              <p className="meta">No national parties recorded.</p>
            ) : (
              <ul className="stack" style={{ listStyle: 'none', padding: 0 }}>
                {[...c.parties]
                  .filter((p) => p.members_active > 0)
                  .sort((a, b) => b.members_active - a.members_active || a.label.localeCompare(b.label))
                  .map((p) => (
                    <li key={p.id} style={{ marginTop: 'var(--sp-2)' }}>
                      <Link to={`/people/parties/${encodeURIComponent(p.id)}`}>{p.label}</Link>{' '}
                      <span className="meta">
                        · {formatNumber(p.members_active)} {p.members_active === 1 ? 'MEP' : 'MEPs'}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </div>

        {c.meps.length > 0 && (
          <div style={{ marginTop: 'var(--sp-5)' }}>
            <button type="button" className="btn" aria-expanded={showMeps} aria-controls="country-meps" onClick={() => patch({ meps: showMeps ? null : 'all' })}>
              {showMeps ? 'Hide the list of MEPs' : `Show all ${formatNumber(c.meps.length)} current MEPs from ${c.name}`}
            </button>
            <div id="country-meps" hidden={!showMeps} style={{ marginTop: 'var(--sp-3)' }}>
              {showMeps && (
              <div className="table-wrap table-card">
                <table className="table">
                  <caption className="visually-hidden">Current MEPs from {c.name}. Select a column heading to sort.</caption>
                  <thead>
                    <tr>
                      <SortTh k="name" sort={ms.sort} onSort={ms.toggle}>
                        Name
                      </SortTh>
                      <SortTh k="group" sort={ms.sort} onSort={ms.toggle}>
                        Group
                      </SortTh>
                      <SortTh k="party" sort={ms.sort} onSort={ms.toggle}>
                        National party
                      </SortTh>
                    </tr>
                  </thead>
                  <tbody>
                    {ms.sorted.map((m) => (
                      <tr key={m.id}>
                        <th scope="row" style={{ fontWeight: 500 }}>
                          <Link to={`/people/meps/${encodeURIComponent(m.id)}`}>{m.name}</Link>
                        </th>
                        <td>{m.group ? groups.byId.get(m.group)?.code ?? m.group : '—'}</td>
                        <td>{m.party_label ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* ------------------------------------------------------------ 2 */}
      <section id="participation" className="csection csection--council" aria-labelledby="par-h">
        <p className="csection__kicker">2 · Council of the EU</p>
        <h2 id="par-h">Participation in EU decisions</h2>
        <p className="section-intro">
          In the <Term id="council">Council of the EU</Term>, a minister from {c.name}’s government votes on EU laws together with the
          other Member States. This is the country’s official position — separate from how its MEPs voted in Parliament.
        </p>
        <p className="callout">
          Most Council decisions use <Term id="qmv">qualified majority voting</Term>: a decision passes with at least 55% of Member States
          representing at least 65% of the EU population. <strong>One country voting against cannot normally block a decision on its own</strong>{' '}
          — a blocking minority needs at least four Member States representing more than 35% of the EU population. Only where <Term id="unanimity">unanimity</Term> is required can a single country
          block.
        </p>

        {councilTotal === 0 ? (
          <div className="state state--empty" style={{ marginTop: 'var(--sp-4)' }}>
            <strong>{councilDataExists ? `No Council votes recorded for ${c.name} in our dataset` : 'Council vote data unavailable'}</strong>
            <div className="meta">
              {councilDataExists
                ? 'None of the Council votes in our dataset records a position for this country.'
                : councilSource?.note ?? 'Member State voting results were not available from an accessible official source in this release.'}{' '}
              {councilSource?.url && <ExtLink href={councilSource.url}>Council of the EU voting results</ExtLink>}
            </div>
          </div>
        ) : (
          <>
            <dl className="facts card" style={{ marginTop: 'var(--sp-4)' }}>
              {(['for', 'against', 'abstain', 'not_participating'] as const).map((k) => (
                <div key={k}>
                  <dt>{COUNCIL_POSITION_LABEL[k]}</dt>
                  <dd className="big">{formatNumber(cp[k])}</dd>
                </div>
              ))}
            </dl>
            <p className="note" style={{ marginTop: 'var(--sp-2)' }}>
              Counts of Council votes in our dataset ({formatNumber(councilTotal)} in total), by {c.name}’s recorded position.
            </p>
            {c.council_votes.length > 0 && (
              <div className="table-wrap table-card" style={{ marginTop: 'var(--sp-4)' }}>
                {/* Explicit roles: on phones the rows are laid out as cards (table--stack), not as table cells. */}
                <table className="table table--stack" role="table">
                  <caption className="visually-hidden">Council votes and {c.name}’s position, newest first</caption>
                  <thead role="rowgroup">
                    <tr role="row">
                      <th scope="col" role="columnheader">Date</th>
                      <th scope="col" role="columnheader">Voted on</th>
                      <th scope="col" role="columnheader">{c.name}’s position</th>
                    </tr>
                  </thead>
                  <tbody role="rowgroup">
                    {votesShown.map((v) => (
                      <tr key={v.vote_id} role="row">
                        <td className="nowrap" role="cell">
                          <StackLabel>Date</StackLabel>
                          {formatDate(v.date)}
                        </td>
                        <td className="stack-title" role="cell">
                          <RowTitle to={v.dossier_id ? dossierPath(v.dossier_id) : null}>{v.display_title ?? v.title}</RowTitle>
                          {v.vote_on && v.vote_on !== 'act' && (
                            <>
                              {' '}
                              <Tag>{COUNCIL_VOTE_ON_SHORT[v.vote_on]}</Tag>
                            </>
                          )}
                        </td>
                        <td role="cell">
                          <StackLabel>{c.name}’s position</StackLabel>
                          <Pos pos={v.pos} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {c.council_votes.length > 20 && !allVotes && (
              <div className="more">
                <button type="button" className="btn" onClick={() => patch({ cvotes: 'all' })}>
                  Show all {formatNumber(c.council_votes.length)} Council votes
                </button>
              </div>
            )}
            {councilSource && (
              <p className="note" style={{ marginTop: 'var(--sp-3)' }}>
                Source: <ExtLink href={councilSource.url}>{councilSource.name}</ExtLink>
              </p>
            )}
          </>
        )}
      </section>

      {/* ------------------------------------------------------------ 3 */}
      <section id="implementation" className="csection csection--impl" aria-labelledby="imp-h">
        <p className="csection__kicker">3 · National application of EU law</p>
        <h2 id="imp-h">Implementation</h2>
        <p className="section-intro">
          What official records show about how {c.name} applies EU law: {c.indicators.length > 0 && 'published indicators, '}national
          measures notified for <Term id="directive">directives</Term>, and <Term id="infringement">infringement cases</Term> opened by
          the European Commission.
        </p>

        {/* Country indicators (Single Market Scoreboard) could not be retrieved for any Member State in this release (see About) */}
        {c.indicators.length > 0 && (
          <>
            <h3>Published indicators</h3>
            <div className="indicators">
              {c.indicators.map((i) => (
                <div className="indicator" key={i.indicator}>
                  <p className="indicator__label">{i.label}</p>
                  <p className="indicator__value">{formatIndicator(i.value, i.unit)}</p>
                  <p>
                    <strong>Period:</strong> {i.period}
                  </p>
                  <p>{i.definition}</p>
                  <SourceLink source={i.source} />
                </div>
              ))}
            </div>
          </>
        )}

        <h3>National measures for directives</h3>
        <p className="note">
          A directive must be <Term id="transposition">transposed</Term> into national law by a deadline. “Measures notified” means{' '}
          {c.name} has notified at least one national measure to the Commission, as listed by EUR-Lex; it does not show whether
          transposition is complete or correct. <strong>“No measures found in the available dataset” is not proof of non-compliance</strong>{' '}
          — for example, some directives do not require national measures from every Member State, and the dataset may be incomplete.
        </p>
        <TranspositionTable rows={c.transposition} countryName={c.name} />

        <h3>Infringement cases</h3>
        <InfringementNote />
        <div style={{ marginTop: 'var(--sp-4)' }}>
          <InfringementTable rows={c.infringements} />
        </div>
        {implSource && (
          <p className="note" style={{ marginTop: 'var(--sp-3)' }}>
            Sources: <ExtLink href={implSource.url}>{implSource.name}</ExtLink>
            {implSource.fetched_at && <> · retrieved {formatDate(implSource.fetched_at.slice(0, 10))}</>}
          </p>
        )}
      </section>
    </div>
  );
}
