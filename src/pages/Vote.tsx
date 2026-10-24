import { useMemo } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import type { DossierDetail, EpVoteDetail } from '../types/data';
import { useData } from '../lib/data';
import { isMissing } from '../features/guide/missing';
import { useHashScroll } from '../features/guide/useHashScroll';
import { countryName, formatDate, formatNumber } from '../lib/format';
import { Disclosure, ErrorState, ExtLink, Loading, LookupNotice, NotFound, PageHeader, SourceLink, Term, VoteBar } from '../components/ui';
import { dossierPath, useDocumentTitle } from '../features/legislation/labels';
import { useGroups } from '../features/people/labels';
import { CloseVoteMethod, MarginText, OutcomeBadge } from '../features/votes/components';
import { BallotList, CountryBreakdownTable, GroupBreakdownTable } from '../features/votes/Breakdowns';
import { LangText, VoteTitle } from '../features/votes/VoteTitle';
import { DETAIL_EXPLAINER, FINAL_ROLE_EXPLAINER, KIND_EXPLAINER, KIND_LABEL, POSITION_LABEL } from '../features/votes/labels';

const OUTCOME_BASIS_TEXT: Record<string, string> = {
  published: 'Outcome as published in Parliament’s open data',
  minutes: 'Outcome as recorded in the official minutes of the sitting',
  derived: 'Outcome calculated from the recorded counts under the applicable majority rule',
  none: 'We could not establish the outcome from the official sources we use; see the official record',
};
// a derived outcome without an established majority rule: the counts give the same result under every rule
const DERIVED_ANY_RULE =
  'Outcome calculated from the recorded counts: it is the same under every majority rule Parliament applies (votes cast, component Members, two thirds)';

export default function Vote() {
  const { id = '' } = useParams();
  // vote ids are EP voting ids (digits); anything else, e.g. /votes/index, is not a vote page
  const validId = /^\d+$/.test(id);
  const { data: v, error, loading } = useData<EpVoteDetail>(validId ? `votes/${encodeURIComponent(id)}.json` : null);
  const groups = useGroups();
  // the file's Council votes, if any: the page links on to how the Member States voted on the same file
  const { data: dossier } = useData<DossierDetail>(v?.dossier_id ? `dossiers/${v.dossier_id}.json` : null);
  const notFound = !validId || (!!v && !Array.isArray(v.ballots)) || isMissing(error);
  useDocumentTitle(notFound ? 'Vote not found' : v ? v.display_title || v.title : 'Parliament vote', v && !notFound ? formatDate(v.date) : null);
  // a link to a section (/votes/166051#meps) lands on it once the vote has loaded
  useHashScroll(!loading && !!v);

  // "All votes" returns to the list as it was filtered, when the vote was opened from it (VoteListItem)
  const fromList = (useLocation().state as { votesList?: unknown } | null)?.votesList;
  const listUrl = typeof fromList === 'string' && /^\/votes(\?|$)/.test(fromList) ? fromList : '/votes';

  const groupNames = useMemo(() => new Map([...groups.byId].map(([id, g]) => [id, g.name])), [groups.byId]);
  const groupCodes = useMemo(() => {
    const m = new Map([...groups.byId].map(([id, g]) => [id, g.code]));
    for (const g of v?.groups ?? []) m.set(g.group, g.group_code);
    return m;
  }, [groups.byId, v]);

  if (!validId || (v && !Array.isArray(v.ballots))) return <NotFound what="vote" />;
  if (loading) return <div className="container page"><Loading label="Loading vote…" /></div>;
  if (isMissing(error)) return <NotFound what="vote" />;
  if (error || !v) return <div className="container page"><ErrorState error={error} title="This vote could not be loaded" /></div>;

  const corrections = v.ballots.filter((b) => b.intended && b.intended !== b.pos);
  const intentions = v.intentions ?? [];
  const decided = v.outcome === 'adopted' || v.outcome === 'rejected';
  const explainer = v.kind_detail
    ? DETAIL_EXPLAINER[v.kind_detail]
    : v.final_role
      ? FINAL_ROLE_EXPLAINER[v.final_role]
      : KIND_EXPLAINER[v.kind];
  const procedureRef = v.procedure_ref || v.dossier_ref;
  const groupAndCountry = (group?: string | null, country?: string | null) =>
    group || country ? (
      <span className="meta">
        {' '}
        ({[group ? groupCodes.get(group) ?? group : null, country ? countryName(country) : null].filter(Boolean).join(', ')})
      </span>
    ) : null;
  const amendmentRejected = (v.kind === 'amendment' || v.kind === 'split_or_separate') && v.outcome === 'rejected';
  const ballotTotal = v.ballots.length;
  const councilVotes = dossier && dossier.id === v.dossier_id ? dossier.council_votes : [];
  const latestCouncil = councilVotes.reduce<string | null>((m, c) => (!m || c.date > m ? c.date : m), null);
  const councilPath = v.dossier_id ? `${dossierPath(v.dossier_id)}#council-votes` : null;

  return (
    <div className="container page vote-page">
      <p className="meta" style={{ marginBottom: 'var(--sp-3)' }}>
        <Link to={listUrl}>← All votes</Link>
      </p>
      <PageHeader
        eyebrow={
          <>
            European Parliament plenary · {v.kind_label || KIND_LABEL[v.kind]}
          </>
        }
        title={<VoteTitle v={v} />}
        lead={
          <>
            Voted on <time dateTime={v.date}>{formatDate(v.date, true)}</time>
            {v.dossier_id ? (
              <>
                {' '}
                · Part of <Link to={dossierPath(v.dossier_id)}>{v.dossier_ref || 'this legislative file'}</Link>
              </>
            ) : (
              procedureRef && (
                <>
                  {' '}
                  · Procedure <span className="mono">{procedureRef}</span>
                </>
              )
            )}
          </>
        }
      />

      {v.has_ballots && (
        <nav className="vote-jump" aria-label="On this page">
          <ul>
            <li>
              <a href="#groups">By political group</a>
            </li>
            <li>
              <a href="#countries">By MEPs’ country</a>
            </li>
            <li>
              <a href="#meps">Individual MEPs</a>
            </li>
          </ul>
        </nav>
      )}

      <section className="vote-summary" aria-labelledby="result-h">
        <div className="vote-summary__top">
          <h2 id="result-h" className="visually-hidden">
            Result
          </h2>
          <OutcomeBadge outcome={v.outcome} />
          <span className="meta">
            {v.outcome_basis === 'derived' && v.majority_rule === 'unknown' ? DERIVED_ANY_RULE : OUTCOME_BASIS_TEXT[v.outcome_basis ?? 'none']}
          </span>
        </div>
        {v.outcome_note && <p className="vote-summary__note">{v.outcome_note}</p>}
        <VoteBar forCount={v.for} against={v.against} abstain={v.abstain} label="Official result" />
        <div className="margin-box">
          {v.margin && decided ? (
            <>
              <span className="margin-box__label">
                <MarginText margin={v.margin} short outcome={v.outcome} />
              </span>
              <span className="meta">
                Rule applied: {v.margin.rule_label}. Votes in favour needed: {formatNumber(v.margin.threshold)}
                {v.margin.rule === 'two_thirds_cast' && v.margin.two_thirds_of_cast != null && v.margin.component_members != null ? (
                  <>
                    . Both conditions must be met: two thirds of the {formatNumber(v.margin.votes_cast)} votes cast for or against (
                    {formatNumber(v.margin.two_thirds_of_cast)}; abstentions do not count) and a majority of the{' '}
                    {formatNumber(v.margin.component_members)} Members in office on the day of the vote (
                    {formatNumber(v.margin.majority_of_members)}), as recorded in Parliament’s membership data
                  </>
                ) : (
                  v.margin.component_members != null && (
                    <>
                      {' '}
                      (a majority of the {formatNumber(v.margin.component_members)} Members in office on the day of the vote, as
                      recorded in Parliament’s membership data)
                    </>
                  )
                )}
                .
              </span>
            </>
          ) : decided ? (
            <MarginText margin={null} />
          ) : (
            <span className="meta">No margin is shown because the outcome is not established.</span>
          )}
          {v.attendees != null && <span className="meta">MEPs recorded as present: {formatNumber(v.attendees)}</span>}
        </div>
        <div>
          <SourceLink source={v.source} prefix="Official record:" />
        </div>
      </section>

      {amendmentRejected && (
        <p className="callout callout--gold" style={{ marginTop: 'var(--sp-5)' }}>
          <strong>This was a vote on an amendment, not on the law as a whole.</strong> Rejecting an amendment only means that change was
          not made to the text. {v.dossier_id && <Link to={dossierPath(v.dossier_id)}>See the file’s status and final votes.</Link>}
        </p>
      )}

      <section className="section" aria-labelledby="what-h">
        <h2 id="what-h">What was voted</h2>
        <dl className="facts">
          <div>
            <dt>Kind of vote</dt>
            <dd>{v.kind_label || KIND_LABEL[v.kind]}</dd>
          </div>
          <div>
            <dt>Date</dt>
            <dd>{formatDate(v.date, true)}</dd>
          </div>
          {v.subject && v.subject !== v.display_title && (
            <div>
              <dt>Subject</dt>
              <dd>
                {v.subject}
                {v.subject_procedure && <span className="meta"> ({v.subject_procedure})</span>}
              </dd>
            </div>
          )}
          {procedureRef && (
            <div>
              <dt>
                <Term id="procedure-reference">Procedure</Term>
              </dt>
              <dd className="mono">
                {v.dossier_id ? (
                  <Link to={dossierPath(v.dossier_id)}>{procedureRef}</Link>
                ) : v.procedure_url ? (
                  <ExtLink href={v.procedure_url}>{procedureRef}</ExtLink>
                ) : (
                  procedureRef
                )}
              </dd>
            </div>
          )}
          {v.reference_text && (
            <div>
              <dt>Text voted on</dt>
              <dd className="mono" lang={v.reference_text_lang}>
                {v.reference_text}
              </dd>
            </div>
          )}
          {v.doc_ids.length > 0 && (
            <div>
              <dt>Documents</dt>
              <dd className="mono">{v.doc_ids.join(', ')}</dd>
            </div>
          )}
          {latestCouncil && councilPath && (
            <div>
              <dt>Council of the EU</dt>
              <dd>
                <Link to={councilPath}>How Member States voted on this file</Link>
                <span className="meta">
                  {' '}
                  ({councilVotes.length > 1 ? `${councilVotes.length} Council votes, the latest on ` : ''}
                  {formatDate(latestCouncil, true)})
                </span>
              </dd>
            </div>
          )}
        </dl>
        <p className="note" style={{ marginTop: 'var(--sp-4)' }}>{explainer}</p>
        {v.title && v.title !== v.display_title && (
          <p className="note">
            Label in the official record:{' '}
            <q>
              <LangText text={v.title} parts={v.title_parts} />
            </q>
          </p>
        )}
      </section>

      {!v.has_ballots ? (
        <section className="section" aria-labelledby="ind-h">
          <h2 id="ind-h">How MEPs voted</h2>
          <p className="callout">
            Individual votes were not recorded for this vote, so we cannot show how political groups, countries’ MEPs or individual MEPs
            voted. Parliament records each MEP’s choice only in a <Term id="roll-call">roll-call vote</Term>.
          </p>
        </section>
      ) : (
        <>
          <section className="section" id="groups" aria-labelledby="groups-h">
            <div className="section-head">
              <h2 id="groups-h">By political group</h2>
            </div>
            <p className="section-intro">
              A <Term id="political-group">political group</Term> does not cast a vote of its own: these figures add up how its members
              voted individually. “Group majority” is the most common position among members with a recorded vote; cohesion is the share
              of them who voted that way.
            </p>
            <LookupNotice failed={groups.failed} what="Political group names" />
            {v.groups.length > 0 ? (
              <GroupBreakdownTable rows={v.groups} groupNames={groupNames} />
            ) : (
              <p className="meta">Group breakdown not available for this vote.</p>
            )}
          </section>

          <section className="section" id="countries" aria-labelledby="countries-h">
            <h2 id="countries-h">By MEPs’ country</h2>
            <p className="section-intro">
              This groups MEPs by the country they were elected in. It is <strong>not</strong> the position of that country’s government:
              Member States vote separately, in the <Term id="council">Council of the EU</Term>.
              {latestCouncil && councilPath && (
                <>
                  {' '}
                  <Link to={councilPath}>See how Member States voted on this file in the Council</Link>.
                </>
              )}
            </p>
            {v.countries.length > 0 ? (
              <CountryBreakdownTable rows={v.countries} />
            ) : (
              <p className="meta">Country breakdown not available for this vote.</p>
            )}
          </section>

          <section className="section" id="meps" aria-labelledby="meps-h">
            <h2 id="meps-h">Individual MEPs</h2>
            <p className="section-intro">
              Each MEP’s recorded vote, with their group and country on the day of the vote. MEPs who are not listed have no vote
              recorded — for example because they were absent or did not take part. <strong>Not recorded is not the same as abstained.</strong>
            </p>
            <BallotList ballots={v.ballots} names={v.mep_names} groupCodes={groupCodes} />
          </section>

          <section className="section" aria-labelledby="notes-h">
            <h2 id="notes-h">Notes on the record</h2>
            <div className="stack">
              <p className={v.reconciliation.matches ? 'note' : 'callout callout--gold'}>
                {v.reconciliation.matches ? (
                  <>
                    The {formatNumber(ballotTotal)} individual votes add up to the official totals.
                  </>
                ) : (
                  <>
                    <strong>The individual votes do not add up exactly to the official totals.</strong>{' '}
                  </>
                )}
                {v.reconciliation.note ? <> {v.reconciliation.note}</> : null}
              </p>
              {corrections.length > 0 ? (
                <Disclosure summary={`Vote corrections recorded after the vote (${formatNumber(corrections.length)})`}>
                  <p className="note">
                    MEPs can state after the vote that they intended to vote differently. Parliament publishes these corrections, but they do
                    not change the official result.
                  </p>
                  <ul>
                    {corrections.map((b) => (
                      <li key={b.mep}>
                        <Link to={`/people/meps/${encodeURIComponent(b.mep)}`}>{v.mep_names[b.mep] ?? `MEP ${b.mep}`}</Link>
                        {groupAndCountry(b.group, b.country)}: recorded {POSITION_LABEL[b.pos].toLowerCase()}; stated intention{' '}
                        {POSITION_LABEL[b.intended!].toLowerCase()}.
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              ) : null}
              {intentions.length > 0 && (
                <Disclosure summary={`Stated intentions of MEPs with no recorded vote (${formatNumber(intentions.length)})`}>
                  <p className="note">
                    These MEPs have no vote recorded for this roll call. After the vote they stated how they had intended to vote. The
                    statements do not change the official result and are not counted in the figures above.
                  </p>
                  <ul>
                    {intentions.map((x) => (
                      <li key={x.mep}>
                        <Link to={`/people/meps/${encodeURIComponent(x.mep)}`}>{v.mep_names[x.mep] ?? `MEP ${x.mep}`}</Link>
                        {groupAndCountry(x.group, x.country)}: no recorded vote; stated intention {POSITION_LABEL[x.intended].toLowerCase()}.
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              )}
              {corrections.length === 0 && intentions.length === 0 && (
                <p className="note">No vote corrections or stated voting intentions were recorded for this vote.</p>
              )}
            </div>
          </section>
        </>
      )}

      <section className="section" aria-labelledby="method-h">
        <h2 id="method-h">About these figures</h2>
        <Disclosure summary="How the margin is calculated">
          <CloseVoteMethod />
        </Disclosure>
      </section>
    </div>
  );
}
