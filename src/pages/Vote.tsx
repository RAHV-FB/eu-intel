import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { EpVoteDetail, GroupSummary } from '../types/data';
import { useData } from '../lib/data';
import { isMissing } from '../features/guide/missing';
import { countryName, formatDate, formatNumber } from '../lib/format';
import { Disclosure, ErrorState, Loading, NotFound, PageHeader, SourceLink, Term, VoteBar } from '../components/ui';
import { dossierPath, useDocumentTitle } from '../features/legislation/labels';
import { CloseVoteMethod, MarginText, OutcomeBadge } from '../features/votes/components';
import { BallotList, CountryBreakdownTable, GroupBreakdownTable } from '../features/votes/Breakdowns';
import { KIND_EXPLAINER, KIND_LABEL, POSITION_LABEL } from '../features/votes/labels';

export default function Vote() {
  const { id = '' } = useParams();
  const { data: v, error, loading } = useData<EpVoteDetail>(`votes/${encodeURIComponent(id)}.json`);
  const groupsState = useData<GroupSummary[]>('people/groups.json');
  useDocumentTitle(v ? v.display_title || v.title : 'Parliament vote');

  const groupNames = useMemo(() => new Map((groupsState.data ?? []).map((g) => [g.id, g.name])), [groupsState.data]);
  const groupCodes = useMemo(() => {
    const m = new Map((groupsState.data ?? []).map((g) => [g.id, g.code]));
    for (const g of v?.groups ?? []) m.set(g.group, g.group_code);
    return m;
  }, [groupsState.data, v]);

  if (loading) return <div className="container page"><Loading label="Loading vote…" /></div>;
  if (isMissing(error)) return <NotFound what="vote" />;
  if (error || !v) return <div className="container page"><ErrorState error={error} title="This vote could not be loaded" /></div>;

  const corrections = v.ballots.filter((b) => b.intended && b.intended !== b.pos);
  const amendmentRejected = (v.kind === 'amendment' || v.kind === 'split_or_separate') && v.outcome === 'rejected';
  const ballotTotal = v.ballots.length;

  return (
    <div className="container page">
      <p className="meta" style={{ marginBottom: 'var(--sp-3)' }}>
        <Link to="/votes">← All votes</Link>
      </p>
      <PageHeader
        eyebrow={
          <>
            European Parliament plenary · {v.kind_label || KIND_LABEL[v.kind]}
          </>
        }
        title={v.display_title || v.title}
        lead={
          <>
            Voted on <time dateTime={v.date}>{formatDate(v.date, true)}</time>
            {v.dossier_id && (
              <>
                {' '}
                · Part of <Link to={dossierPath(v.dossier_id)}>{v.dossier_ref || 'this legislative file'}</Link>
              </>
            )}
          </>
        }
      />

      <section className="vote-summary" aria-labelledby="result-h">
        <div className="vote-summary__top">
          <h2 id="result-h" className="visually-hidden">
            Result
          </h2>
          <OutcomeBadge outcome={v.outcome} />
          <span className="meta">Official result recorded by Parliament</span>
        </div>
        <VoteBar forCount={v.for} against={v.against} abstain={v.abstain} label="Official result" />
        <div className="margin-box">
          {v.margin ? (
            <>
              <span className="margin-box__label">
                <MarginText margin={v.margin} short />
              </span>
              <span className="meta">
                Rule applied: {v.margin.rule_label}. Votes in favour needed: {formatNumber(v.margin.threshold)}.
              </span>
            </>
          ) : (
            <MarginText margin={null} />
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
          {v.dossier_ref && (
            <div>
              <dt>
                <Term id="procedure-reference">Procedure</Term>
              </dt>
              <dd className="mono">{v.dossier_id ? <Link to={dossierPath(v.dossier_id)}>{v.dossier_ref}</Link> : v.dossier_ref}</dd>
            </div>
          )}
          {v.reference_text && (
            <div>
              <dt>Text voted on</dt>
              <dd className="mono">{v.reference_text}</dd>
            </div>
          )}
          {v.doc_ids.length > 0 && (
            <div>
              <dt>Documents</dt>
              <dd className="mono">{v.doc_ids.join(', ')}</dd>
            </div>
          )}
        </dl>
        <p className="note" style={{ marginTop: 'var(--sp-4)' }}>{KIND_EXPLAINER[v.kind]}</p>
        {v.title && v.title !== v.display_title && (
          <p className="note">
            Parliament’s own label for this vote: <q>{v.title}</q>
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
          <section className="section" aria-labelledby="groups-h">
            <div className="section-head">
              <h2 id="groups-h">By political group</h2>
            </div>
            <p className="section-intro">
              A <Term id="political-group">political group</Term> does not cast a vote of its own: these figures add up how its members
              voted individually. “Group majority” is the most common position among members with a recorded vote; cohesion is the share
              of them who voted that way.
            </p>
            {v.groups.length > 0 ? (
              <GroupBreakdownTable rows={v.groups} groupNames={groupNames} />
            ) : (
              <p className="meta">Group breakdown not available for this vote.</p>
            )}
          </section>

          <section className="section" aria-labelledby="countries-h">
            <h2 id="countries-h">By MEPs’ country</h2>
            <p className="section-intro">
              This groups MEPs by the country they were elected in. It is <strong>not</strong> the position of that country’s government:
              Member States vote separately, in the <Term id="council">Council of the EU</Term>.
            </p>
            {v.countries.length > 0 ? (
              <CountryBreakdownTable rows={v.countries} />
            ) : (
              <p className="meta">Country breakdown not available for this vote.</p>
            )}
          </section>

          <section className="section" aria-labelledby="meps-h">
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
                        {b.group || b.country ? (
                          <span className="meta">
                            {' '}
                            ({[b.group ? groupCodes.get(b.group) ?? b.group : null, b.country ? countryName(b.country) : null].filter(Boolean).join(', ')})
                          </span>
                        ) : null}
                        : recorded {POSITION_LABEL[b.pos].toLowerCase()}; stated intention {POSITION_LABEL[b.intended!].toLowerCase()}.
                      </li>
                    ))}
                  </ul>
                </Disclosure>
              ) : (
                <p className="note">No vote corrections were recorded for this vote.</p>
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
