import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { EpVoteTitle, MembershipPeriod, MepDetail, Meta } from '../types/data';
import { useData } from '../lib/data';
import { isMissing } from '../features/guide/missing';
import { countryName, formatDate, formatNumber } from '../lib/format';
import { shownParam, useParamState } from '../lib/urlState';
import { ballotScope } from '../lib/scope';
import { EmptyState, ErrorState, ExtLink, LoadFailed, Loading, NotFound, PageHeader, SourceLink, Term } from '../components/ui';
import { RowTitle, StackLabel } from '../components/StackedTable';
import { useFocusRevealed } from '../components/useFocusRevealed';
import { dossierPath, useDocumentTitle } from '../features/legislation/labels';
import { EP_MEP_URL, periodText, rapporteurRoleLabel, roleLabel, termShort, useGroups } from '../features/people/labels';
import { Pos } from '../features/votes/Breakdowns';
import { VoteRowMeta, VoteTitle } from '../features/votes/VoteTitle';
import '../features/people/people.css';
import '../features/votes/common.css';

const VOTES_PAGE = 50;

function History({ items, link }: { items: MembershipPeriod[]; link?: (p: MembershipPeriod) => string | null }) {
  const sorted = [...items].sort((a, b) => (b.from ?? '').localeCompare(a.from ?? ''));
  return (
    <ol className="history">
      {sorted.map((p, i) => {
        const href = link?.(p);
        const role = roleLabel(p.role);
        return (
          <li key={`${p.id}-${p.from ?? i}`} className={p.to ? undefined : 'is-current'}>
            <span className="history__label">{href ? <Link to={href}>{p.label}</Link> : p.label}</span>
            {p.code && p.code !== p.label && <span className="meta"> ({p.code})</span>}
            <span className="history__meta">
              {periodText(p.from, p.to)}
              {!p.to && ' (current)'}
              {role && role !== 'Member' ? ` · ${role}` : ''}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default function Mep() {
  const { id = '' } = useParams();
  const { data: m, error, loading } = useData<MepDetail>(`people/meps/${encodeURIComponent(id)}.json`);
  const groups = useGroups();
  const votesIndex = useData<EpVoteTitle[]>(m && m.votes.length > 0 ? 'votes/titles.json' : null);
  const meta = useData<Meta>('meta.json');
  const noVoteData = meta.data ? meta.data.counts.ep_votes_with_ballots === 0 : false;
  // votes shown: kept in the address, so that Back from a vote returns to the same list
  const [params, patch] = useParamState();
  const shown = shownParam(params, 'show', VOTES_PAGE);
  useDocumentTitle(m ? m.name : isMissing(error) ? 'MEP not found' : error ? 'MEP could not be loaded' : 'MEP');

  const voteById = useMemo(() => new Map((votesIndex.data ?? []).map((v) => [v.id, v])), [votesIndex.data]);
  // a vote's date and result while the vote list loads, or when it failed to: not "—", which means not recorded
  const unknown = votesIndex.error ? <span className="muted">Not loaded</span> : <span className="muted">…</span>;
  // "Show more votes" moves keyboard focus to the first vote it shows
  const more = useFocusRevealed<HTMLTableSectionElement>(Math.min(shown, m?.votes.length ?? 0));

  if (loading) return <div className="container page"><Loading label="Loading MEP…" /></div>;
  if (isMissing(error)) return <NotFound what="MEP" />;
  if (error || !m) return <LoadFailed title="This MEP could not be loaded" />;

  const currentGroup = m.groups.find((g) => !g.to) ?? null;
  const currentParty = m.parties.find((p) => !p.to) ?? null;
  const committeesNow = m.committees.filter((c) => !c.to);
  const committeesPast = m.committees.filter((c) => c.to);
  const groupHref = (p: MembershipPeriod) => {
    const slug = groups.byId.has(p.id) ? p.id : [...groups.byId.values()].find((g) => g.code === p.code)?.id;
    return slug ? `/people/groups/${encodeURIComponent(slug)}` : null;
  };

  return (
    <div className="container page">
      <p className="meta mb-3">
        <Link to="/people">← People & Parties</Link>
      </p>
      <PageHeader
        eyebrow={m.active ? 'Member of the European Parliament' : 'Former Member of the European Parliament'}
        title={m.name}
        lead={
          <>
            Elected in <Link to={`/countries/${m.country}`}>{countryName(m.country)}</Link>
            {m.group_code && (
              <>
                {' '}
                · {m.active ? '' : 'last recorded group: '}
                {m.group ? <Link to={`/people/groups/${encodeURIComponent(m.group)}`}>{m.group_code}</Link> : m.group_code}
              </>
            )}
          </>
        }
      />

      <dl className="facts card">
        <div>
          <dt>Status</dt>
          <dd>
            <span className={`status-dot${m.active ? '' : ' status-dot--former'}`}>{m.active ? 'Current MEP' : 'Former MEP'}</span>
          </dd>
        </div>
        <div>
          <dt>Country represented</dt>
          <dd>{countryName(m.country)}</dd>
        </div>
        <div>
          <dt>
            <Term id="political-group">Political group</Term>
          </dt>
          <dd>
            {currentGroup ? (
              <>
                {currentGroup.code ?? currentGroup.label}
                <span className="meta as-block">{currentGroup.label}</span>
              </>
            ) : m.group_code ? (
              <>{m.group_code} (last recorded)</>
            ) : (
              'Not recorded'
            )}
          </dd>
        </div>
        <div>
          <dt>National party</dt>
          <dd>
            {currentParty ? (
              <Link to={`/people/parties/${encodeURIComponent(currentParty.id)}`}>{currentParty.label}</Link>
            ) : m.party_label ? (
              <>{m.party_label} (last recorded)</>
            ) : (
              'Not recorded'
            )}
          </dd>
        </div>
        <div>
          <dt>Parliamentary terms served</dt>
          <dd>{m.terms.length ? [...m.terms].sort((a, b) => a - b).map(termShort).join(', ') : '—'}</dd>
        </div>
      </dl>

      <div className="grid grid--2 section">
        <section aria-labelledby="g-h">
          <h2 id="g-h" className="section-title">
            Political group membership
          </h2>
          {m.groups.length ? <History items={m.groups} link={groupHref} /> : <p className="meta">No group membership recorded.</p>}
        </section>
        <section aria-labelledby="p-h">
          <h2 id="p-h" className="section-title">
            National party
          </h2>
          {m.parties.length ? (
            <History items={m.parties} link={(p) => `/people/parties/${encodeURIComponent(p.id)}`} />
          ) : (
            <p className="meta">No national party recorded.</p>
          )}
        </section>
      </div>

      <section className="section" aria-labelledby="c-h">
        <h2 id="c-h">Committees</h2>
        <p className="section-intro">Parliament’s committees prepare its work on legislation before plenary votes.</p>
        {m.committees.length === 0 ? (
          <p className="meta">No committee memberships recorded.</p>
        ) : (
          <div className="grid grid--2">
            <div>
              <h3>Current</h3>
              {committeesNow.length ? <History items={committeesNow} /> : <p className="meta">None recorded.</p>}
            </div>
            <div>
              <h3>Earlier</h3>
              {committeesPast.length ? <History items={committeesPast} /> : <p className="meta">None recorded.</p>}
            </div>
          </div>
        )}
      </section>

      <section className="section" aria-labelledby="r-h">
        <h2 id="r-h">Rapporteur and shadow rapporteur roles on files we track</h2>
        {m.rapporteur_for.length === 0 ? (
          <p className="meta">No rapporteur or shadow rapporteur role recorded on a legislative file in our dataset.</p>
        ) : (
          <ul className="roles">
            {m.rapporteur_for.map((r) => (
              <li key={`${r.dossier_id}-${r.role}-${r.committee ?? ''}`}>
                <Link className="row-link" to={dossierPath(r.dossier_id)}>
                  {r.title}
                </Link>{' '}
                <span className="meta roles__role">{rapporteurRoleLabel(r.role, r.committee, r.former)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="section" aria-labelledby="v-h">
        <h2 id="v-h">Recorded votes</h2>
        <p className="section-intro">
          How {m.name} voted in the <Term id="roll-call">roll-call votes</Term> listed on this site.{' '}
          {ballotScope(meta.data?.scope, meta.data?.counts.ep_votes_with_ballots)} Votes where no position is recorded (for example
          when the MEP was absent) are not shown; that is not the same as abstaining.
        </p>
        {m.votes.length === 0 ? (
          noVoteData ? (
            <EmptyState title="Parliament vote data is not available in this release">
              See <Link to="/about#coverage">coverage</Link> for the status of each source.
            </EmptyState>
          ) : (
            <EmptyState title="No recorded votes on the votes we index">Individual votes are only published for roll-call votes.</EmptyState>
          )
        ) : (
          <>
            {votesIndex.error && (
              <div className="mb-3">
                <ErrorState
                  error={votesIndex.error}
                  title="The titles, dates and results of these votes could not be loaded. Each vote’s own page has them."
                />
              </div>
            )}
            <div className="table-wrap table-card">
              {/* Explicit roles: on phones the rows are laid out as cards (table--stack), not as table cells. */}
              <table className="table table--stack" role="table">
                <caption className="visually-hidden">Recorded votes, newest first</caption>
                <thead role="rowgroup">
                  <tr role="row">
                    <th scope="col" role="columnheader">Date</th>
                    <th scope="col" role="columnheader">Vote</th>
                    <th scope="col" role="columnheader">Recorded vote</th>
                    <th scope="col" role="columnheader">Result</th>
                  </tr>
                </thead>
                <tbody role="rowgroup" ref={more.ref}>
                  {m.votes.slice(0, shown).map((b) => {
                    const v = voteById.get(b.vote_id);
                    return (
                      <tr key={b.vote_id} role="row">
                        <td className="nowrap" role="cell">
                          <StackLabel>Date</StackLabel>
                          {v ? formatDate(v.date) : votesIndex.data ? '—' : unknown}
                        </td>
                        <td className="stack-title" role="cell">
                          <RowTitle to={`/votes/${encodeURIComponent(b.vote_id)}`}>{v ? <VoteTitle v={v} /> : `Vote ${b.vote_id}`}</RowTitle>
                          {v && <VoteRowMeta v={v} />}
                        </td>
                        <td role="cell">
                          <StackLabel>Recorded vote</StackLabel>
                          <Pos pos={b.pos} />
                        </td>
                        <td className="nowrap" role="cell">
                          <StackLabel>Result</StackLabel>
                          {v ? (v.outcome === 'adopted' ? 'Adopted' : v.outcome === 'rejected' ? 'Rejected' : v.outcome === 'lapsed' ? 'Lapsed' : '—') : votesIndex.data ? '—' : unknown}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {m.votes.length > shown && (
              <div className="more">
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    more.reveal();
                    patch({ show: String(shown + VOTES_PAGE) });
                  }}
                >
                  Show more votes
                </button>
                <span className="meta">
                  Showing {formatNumber(shown)} of {formatNumber(m.votes.length)}
                </span>
              </div>
            )}
          </>
        )}
      </section>

      <section className="section" aria-labelledby="o-h">
        <h2 id="o-h">Official sources</h2>
        <ul className="stack" style={{ paddingLeft: '1.1rem' }}>
          <li>
            <ExtLink href={m.official_url || EP_MEP_URL(m.id)}>Official profile on the European Parliament website</ExtLink>
          </li>
          <li>
            <SourceLink source={m.source} prefix="Membership data:" />
            {m.source?.retrieved_at && <span className="meta"> · retrieved {formatDate(m.source.retrieved_at.slice(0, 10))}</span>}
          </li>
        </ul>
      </section>
    </div>
  );
}
