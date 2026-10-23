import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { BallotPosition, EpVoteSummary, GroupDetail, MepSummary, Meta, PositionCounts } from '../types/data';
import { useData } from '../lib/data';
import { isMissing } from '../features/guide/missing';
import { countryName, formatDate, formatNumber, pct } from '../lib/format';
import { shownParam, useParamState } from '../lib/urlState';
import { ballotScope } from '../lib/scope';
import { EmptyState, ErrorState, Loading, NotFound, PageHeader, SourceLink, Term } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { termLabel } from '../features/people/labels';
import { MiniBar, Pos } from '../features/votes/Breakdowns';
import { SortTh, useSortable } from '../features/votes/sortable';
import { VoteTitle } from '../features/votes/VoteTitle';
import { RowTitle } from '../components/StackedTable';
import { cohesionText } from '../features/votes/labels';
import '../features/people/people.css';

type CountryRow = { country: string; members: number };
type PartyRow = GroupDetail['parties'][number];
type VoteRow = { vote_id: string; majority?: BallotPosition | null; cohesion?: number | null; counts: PositionCounts; v?: EpVoteSummary };

const VOTES_PAGE = 40;

export default function Group() {
  const { id = '' } = useParams();
  const { data: g, error, loading } = useData<GroupDetail>(`people/groups/${encodeURIComponent(id)}.json`);
  const meps = useData<MepSummary[]>(g && g.member_ids.length > 0 ? 'people/meps.json' : null);
  const votesIndex = useData<EpVoteSummary[]>(g && g.votes.length > 0 ? 'votes/index.json' : null);
  const meta = useData<Meta>('meta.json');
  const noVoteData = meta.data ? meta.data.counts.ep_votes_with_ballots === 0 : false;
  // votes shown: kept in the address, so that Back from a vote returns to the same list
  const [params, patch] = useParamState();
  const shown = shownParam(params, 'show', VOTES_PAGE);
  useDocumentTitle(g ? `${g.code} – ${g.name}` : isMissing(error) ? 'Political group not found' : 'Political group');

  const countryRows = useMemo<CountryRow[]>(
    () => Object.entries(g?.countries ?? {}).map(([country, members]) => ({ country, members })),
    [g],
  );
  const c = useSortable<CountryRow, 'country' | 'members'>(
    countryRows,
    { country: (r) => countryName(r.country), members: (r) => r.members },
    { key: 'members', dir: 'desc' },
    { members: 'desc' },
  );
  const p = useSortable<PartyRow, 'label' | 'country' | 'members'>(
    g?.parties ?? [],
    { label: (r) => r.label, country: (r) => countryName(r.country), members: (r) => r.members },
    { key: 'members', dir: 'desc' },
    { members: 'desc' },
  );
  const voteRows = useMemo<VoteRow[]>(() => {
    const byId = new Map((votesIndex.data ?? []).map((v) => [v.id, v]));
    return (g?.votes ?? []).map((r) => ({ ...r, v: byId.get(r.vote_id) }));
  }, [g, votesIndex.data]);
  const vs = useSortable<VoteRow, 'date' | 'cohesion' | 'recorded'>(
    voteRows,
    {
      date: (r) => r.v?.date ?? null,
      cohesion: (r) => r.cohesion ?? null,
      recorded: (r) => r.counts.for + r.counts.against + r.counts.abstain,
    },
    { key: 'date', dir: 'desc' },
    { date: 'desc', recorded: 'desc' },
    'sort',
  );
  const members = useMemo(() => {
    const byId = new Map((meps.data ?? []).map((m) => [m.id, m]));
    return (g?.member_ids ?? [])
      .map((id) => byId.get(id) ?? ({ id, name: `MEP ${id}`, sort: id, country: '', active: true, terms: [] } as MepSummary))
      .sort((a, b) => (a.sort || a.name).localeCompare(b.sort || b.name));
  }, [g, meps.data]);

  if (loading) return <div className="container page"><Loading label="Loading group…" /></div>;
  if (isMissing(error)) return <NotFound what="political group" />;
  if (error || !g) return <div className="container page"><ErrorState error={error} title="This group could not be loaded" /></div>;

  const isNi = g.id === 'ni';
  const totalMembers = countryRows.reduce((n, r) => n + r.members, 0) || g.members;
  const maxCountry = Math.max(1, ...countryRows.map((r) => r.members));

  return (
    <div className="container page">
      <p className="meta" style={{ marginBottom: 'var(--sp-3)' }}>
        <Link to="/people?view=groups">← Political groups</Link>
      </p>
      <PageHeader
        eyebrow={
          isNi ? (
            <>MEPs who belong to no political group</>
          ) : (
            <>
              <Term id="political-group">Political group</Term> in the European Parliament
            </>
          )
        }
        title={g.name}
        lead={
          <>
            {g.code}
            {g.terms.length > 0 && <> · {g.terms.map(termLabel).join(', ')}</>}
            {!g.active && <> · not a group in the current term</>}
          </>
        }
      />

      <dl className="facts card">
        <div>
          <dt>Current members</dt>
          <dd className="big">{formatNumber(g.members)}</dd>
        </div>
        <div>
          <dt>Countries represented</dt>
          <dd className="big">{formatNumber(countryRows.length)}</dd>
        </div>
        <div>
          <dt>National parties</dt>
          <dd className="big">{formatNumber(g.parties.length)}</dd>
        </div>
      </dl>
      <p className="note" style={{ marginTop: 'var(--sp-3)' }}>
        {isNi
          ? 'Non-attached members are MEPs who have not joined any political group. They are listed together here for convenience; they do not form a group and do not act together.'
          : 'A political group brings together MEPs from national parties in several countries.'}{' '}
        Figures on this page come from Parliament’s membership records.
      </p>

      <div className="grid grid--2 section">
        <section aria-labelledby="bc-h">
          <h2 id="bc-h">Current members by country</h2>
          {countryRows.length === 0 ? (
            <p className="meta">No current members recorded.</p>
          ) : (
            <div className="table-wrap table-card">
              <table className="table">
                <caption className="visually-hidden">Current members by country. Select a column heading to sort.</caption>
                <thead>
                  <tr>
                    <SortTh k="country" sort={c.sort} onSort={c.toggle}>
                      Country
                    </SortTh>
                    <SortTh k="members" sort={c.sort} onSort={c.toggle} num>
                      Members
                    </SortTh>
                    <th scope="col" className="num">
                      Share
                    </th>
                    <th scope="col">
                      <span className="visually-hidden">Bar</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {c.sorted.map((r) => (
                    <tr key={r.country}>
                      <th scope="row" style={{ fontWeight: 500 }}>
                        <Link to={`/countries/${r.country}`}>{countryName(r.country)}</Link>
                      </th>
                      <td className="num">{formatNumber(r.members)}</td>
                      <td className="num">{pct(r.members, totalMembers)}</td>
                      <td style={{ width: '35%' }}>
                        <span
                          aria-hidden="true"
                          style={{ display: 'block', height: 8, borderRadius: 2, background: 'var(--blue-muted)', width: `${(r.members / maxCountry) * 100}%`, minWidth: 2, marginTop: '0.45em' }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section aria-labelledby="np-h">
          <h2 id="np-h">National parties</h2>
          {g.parties.length === 0 ? (
            <p className="meta">No national parties recorded.</p>
          ) : (
            <div className="table-wrap table-card">
              <table className="table">
                <caption className="visually-hidden">National parties with current members in this group. Select a column heading to sort.</caption>
                <thead>
                  <tr>
                    <SortTh k="label" sort={p.sort} onSort={p.toggle}>
                      Party
                    </SortTh>
                    <SortTh k="country" sort={p.sort} onSort={p.toggle} className="hide-narrow">
                      Country
                    </SortTh>
                    <SortTh k="members" sort={p.sort} onSort={p.toggle} num>
                      MEPs
                    </SortTh>
                  </tr>
                </thead>
                <tbody>
                  {p.sorted.map((r) => (
                    <tr key={r.id}>
                      <th scope="row" className="wrap-anywhere" style={{ fontWeight: 500 }}>
                        <Link to={`/people/parties/${encodeURIComponent(r.id)}`}>{r.label}</Link>
                        {/* phones: the country column is hidden and shown here, so the MEP count stays on screen */}
                        <span className="only-narrow meta" style={{ fontWeight: 400 }}>
                          {countryName(r.country)}
                        </span>
                      </th>
                      <td className="hide-narrow">{countryName(r.country)}</td>
                      <td className="num">{formatNumber(r.members)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <section className="section" aria-labelledby="m-h">
        <h2 id="m-h">Current members ({formatNumber(g.member_ids.length)})</h2>
        {members.length === 0 ? (
          <p className="meta">No current members recorded.</p>
        ) : meps.loading ? (
          <Loading label="Loading member names…" />
        ) : (
          <ul className="member-grid">
            {members.map((m) => (
              <li key={m.id}>
                <Link to={`/people/meps/${encodeURIComponent(m.id)}`}>{m.name}</Link>
                {m.country && <span className="meta">{countryName(m.country)}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="section" aria-labelledby="gv-h">
        <h2 id="gv-h">How members voted</h2>
        <p className="section-intro">
          A group has no vote of its own. For each <Term id="roll-call">roll-call vote</Term> we list, these figures add up how the group’s
          members voted individually, using membership on the day of the vote. “Group majority” is the most common position among them;
          check the number of recorded votes before drawing conclusions. {ballotScope(meta.data?.scope, meta.data?.counts.ep_votes_with_ballots)}
        </p>
        {g.votes.length === 0 ? (
          <EmptyState
            title={noVoteData ? 'Parliament vote data is not available in this release' : 'No recorded votes for this group on the votes we index'}
          >
            {noVoteData && (
              <>
                See <Link to="/about#coverage">coverage</Link> for the status of each source.
              </>
            )}
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap table-card">
              <table className="table table--clamp">
                <caption className="visually-hidden">Group members’ recorded votes. Select a column heading to sort.</caption>
                <thead>
                  <tr>
                    {/* phones: the vote and the group majority stay; date, counts and cohesion are shown inside them */}
                    <SortTh k="date" sort={vs.sort} onSort={vs.toggle} className="hide-narrow">
                      Date
                    </SortTh>
                    <th scope="col">Vote</th>
                    <th scope="col" className="num hide-narrow">
                      For
                    </th>
                    <th scope="col" className="num hide-narrow">
                      Against
                    </th>
                    <th scope="col" className="num hide-narrow">
                      Abst.
                    </th>
                    <SortTh k="recorded" sort={vs.sort} onSort={vs.toggle} num className="hide-narrow">
                      Recorded
                    </SortTh>
                    {!isNi && (
                      <>
                        <th scope="col">Group majority</th>
                        <SortTh k="cohesion" sort={vs.sort} onSort={vs.toggle} className="hide-narrow">
                          Cohesion
                        </SortTh>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {vs.sorted.slice(0, shown).map((r) => (
                    <tr key={r.vote_id}>
                      <td className="nowrap hide-narrow">{r.v ? formatDate(r.v.date) : '—'}</td>
                      <td className="gv-vote">
                        <span className="only-narrow meta">{r.v ? formatDate(r.v.date) : '—'}</span>
                        <RowTitle to={`/votes/${encodeURIComponent(r.vote_id)}`}>{r.v ? <VoteTitle v={r.v} /> : `Vote ${r.vote_id}`}</RowTitle>
                        <MiniBar c={r.counts} />
                        <span className="only-narrow meta">
                          For {formatNumber(r.counts.for)} · Against {formatNumber(r.counts.against)} · Abstained{' '}
                          {formatNumber(r.counts.abstain)} · Recorded {formatNumber(r.counts.for + r.counts.against + r.counts.abstain)}
                        </span>
                      </td>
                      <td className="num hide-narrow">{formatNumber(r.counts.for)}</td>
                      <td className="num hide-narrow">{formatNumber(r.counts.against)}</td>
                      <td className="num hide-narrow">{formatNumber(r.counts.abstain)}</td>
                      <td className="num hide-narrow">{formatNumber(r.counts.for + r.counts.against + r.counts.abstain)}</td>
                      {!isNi && (
                        <>
                          <td>
                            {r.majority ? <Pos pos={r.majority} /> : <span className="muted">—</span>}
                            {r.cohesion != null && <span className="only-narrow meta">Cohesion {Math.round(r.cohesion * 100)}%</span>}
                          </td>
                          <td className="hide-narrow">{r.cohesion != null ? cohesionText(r.cohesion) : <span className="muted">—</span>}</td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {vs.sorted.length > shown && (
              <div className="more">
                <button type="button" className="btn" onClick={() => patch({ show: String(shown + VOTES_PAGE) })}>
                  Show more votes
                </button>
                <span className="meta">
                  Showing {formatNumber(shown)} of {formatNumber(vs.sorted.length)}
                </span>
              </div>
            )}
          </>
        )}
      </section>

      <p className="note section">
        <SourceLink source={g.source} />
        {g.source?.retrieved_at && <> · retrieved {formatDate(g.source.retrieved_at.slice(0, 10))}</>}
      </p>
    </div>
  );
}
