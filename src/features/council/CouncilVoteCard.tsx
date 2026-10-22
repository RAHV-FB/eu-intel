/**
 * One recorded vote of the Council of the EU (ministers of the Member States — NOT the European Council).
 * Used on the dossier page (Agent F1) and wherever a full CouncilVote record is available.
 */
import { Link } from 'react-router-dom';
import type { CouncilPosition, CouncilVote } from '../../types/data';
import { SourceLink, Term, VoteBar } from '../../components/ui';
import { COUNTRY_NAMES, countryName, formatDate, formatNumber } from '../../lib/format';
import './council.css';

const EU27 = Object.keys(COUNTRY_NAMES).filter((c) => c !== 'GB');
/** The UK left the EU on 31 January 2020; from then on the Council has 27 members. */
const EU27_FROM = '2020-02-01';

export const COUNCIL_POSITION_LABEL: Record<CouncilPosition, string> = {
  for: 'In favour',
  against: 'Against',
  abstain: 'Abstained',
  not_participating: 'Not participating',
};

const POSITION_ORDER: CouncilPosition[] = ['for', 'against', 'abstain', 'not_participating'];

const OUTCOME_LABEL: Record<CouncilVote['outcome'], string> = {
  adopted: 'Adopted',
  not_adopted: 'Not adopted',
  unknown: 'Outcome not recorded',
};

export function CouncilRule({ rule }: { rule: CouncilVote['voting_rule'] }) {
  if (rule === 'qmv') return <Term id="qmv">Qualified majority</Term>;
  if (rule === 'unanimity') return <Term id="unanimity">Unanimity</Term>;
  if (rule === 'simple_majority') return <>Simple majority</>;
  return <>Voting rule not recorded</>;
}

/** Percentages may arrive as 0–100 or as 0–1 fractions; normalise for display. */
function pctValue(v: number | null | undefined, scale: number): string | null {
  if (v == null) return null;
  return `${(v * scale).toLocaleString('en-GB', { maximumFractionDigits: 1 })}%`;
}

export function CouncilVoteCard({
  vote,
  headingLevel = 3,
  showDossier = false,
}: {
  vote: CouncilVote;
  headingLevel?: 2 | 3 | 4;
  showDossier?: boolean;
}) {
  const H = `h${headingLevel}` as 'h2' | 'h3' | 'h4';
  const Sub = `h${headingLevel + 1}` as 'h3' | 'h4' | 'h5';
  const groups: Record<CouncilPosition, string[]> = { for: [], against: [], abstain: [], not_participating: [] };
  for (const [code, pos] of Object.entries(vote.positions ?? {})) {
    if (groups[pos]) groups[pos].push(code);
  }
  for (const k of POSITION_ORDER) groups[k].sort((a, b) => countryName(a).localeCompare(countryName(b)));
  const recorded = Object.keys(vote.positions ?? {});
  const missing =
    recorded.length > 0 && vote.date >= EU27_FROM ? EU27.filter((c) => !(c in vote.positions)).sort((a, b) => countryName(a).localeCompare(countryName(b))) : [];

  const a = vote.assessment;
  const scale = a?.population_required_pct != null && a.population_required_pct <= 1 ? 100 : 1;
  const popFor = pctValue(a?.population_for_pct, scale);
  const popReq = pctValue(a?.population_required_pct, scale);
  const participating = recorded.length - groups.not_participating.length;

  return (
    <article className="cvote" aria-labelledby={`cvote-${vote.id}`}>
      <header className="cvote__head">
        <p className="cvote__eyebrow">
          <Term id="council">Council of the EU</Term>
          {vote.configuration ? <> · {vote.configuration}</> : null} · <time dateTime={vote.date}>{formatDate(vote.date, true)}</time>
        </p>
        <H id={`cvote-${vote.id}`} className="cvote__title">
          {vote.title}
        </H>
        <dl className="cvote__facts">
          <div>
            <dt>Outcome</dt>
            <dd>
              <span className={`cvote__outcome cvote__outcome--${vote.outcome}`}>
                <span aria-hidden="true">{vote.outcome === 'adopted' ? '●' : vote.outcome === 'not_adopted' ? '✕' : '○'}</span>{' '}
                {OUTCOME_LABEL[vote.outcome]}
              </span>
            </dd>
          </div>
          <div>
            <dt>Voting rule</dt>
            <dd>
              <CouncilRule rule={vote.voting_rule} />
            </dd>
          </div>
          {showDossier && vote.dossier_id && (
            <div>
              <dt>Legislative file</dt>
              <dd>
                <Link to={`/legislation/${vote.dossier_id}`}>{vote.dossier_ref || vote.dossier_id}</Link>
              </dd>
            </div>
          )}
        </dl>
      </header>

      {recorded.length > 0 ? (
        <>
          <VoteBar
            forCount={groups.for.length}
            against={groups.against.length}
            abstain={groups.abstain.length}
            label="Member States"
          />
          <p className="meta cvote__unit">Counts are Member States, not ministers or population.</p>
          <div className="cvote__positions">
            {POSITION_ORDER.filter((p) => groups[p].length > 0).map((p) => (
              <section key={p} className={`cvote__pos cvote__pos--${p}`} aria-label={`${COUNCIL_POSITION_LABEL[p]}: ${groups[p].length}`}>
                <p className="cvote__pos-title">
                  <i className={`cvote__swatch cvote__swatch--${p}`} aria-hidden="true" />
                  {COUNCIL_POSITION_LABEL[p]} <span className="num">({groups[p].length})</span>
                </p>
                <ul className="cvote__states">
                  {groups[p].map((c) => (
                    <li key={c}>
                      <Link to={`/countries/${c}`}>{countryName(c)}</Link>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
            {missing.length > 0 && (
              <section className="cvote__pos cvote__pos--missing" aria-label={`No position recorded: ${missing.length}`}>
                <p className="cvote__pos-title">
                  <i className="cvote__swatch cvote__swatch--missing" aria-hidden="true" />
                  No position recorded in the source <span className="num">({missing.length})</span>
                </p>
                <ul className="cvote__states">
                  {missing.map((c) => (
                    <li key={c}>{countryName(c)}</li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </>
      ) : (
        <p className="meta">The source does not record individual Member State positions for this vote.</p>
      )}

      <div className="cvote__assessment">
        <Sub className="cvote__sub">What the voting rule meant here</Sub>
        {a ? (
          <ul>
            {a.rule === 'qmv' && (
              <>
                <li>
                  <b className="num">{formatNumber(a.states_for)}</b> Member States voted in favour
                  {participating > 0 && recorded.length > 0 ? <> out of {formatNumber(participating)} taking part</> : null}; at least{' '}
                  <b className="num">{formatNumber(a.states_required)}</b> were needed.
                </li>
                {popFor && (
                  <li>
                    They represent <b className="num">{popFor}</b> of the EU population
                    {popReq ? (
                      <>
                        ; at least <b className="num">{popReq}</b> was needed
                      </>
                    ) : null}
                    .
                  </li>
                )}
                {a.adopted_by_rule === true && <li>On these figures, both qualified-majority thresholds were met.</li>}
                {a.adopted_by_rule === false && <li>On these figures, the qualified-majority thresholds were not met.</li>}
                {a.blocking_minority_existed === true && (
                  <li>
                    The Member States not voting in favour met the conditions for a blocking minority (at least four Member States
                    representing more than 35% of the EU population).
                  </li>
                )}
                {a.blocking_minority_existed === false && (
                  <li>The Member States not voting in favour did not form a blocking minority.</li>
                )}
              </>
            )}
            {a.rule === 'unanimity' && (
              <li>
                Unanimity required every participating Member State not to vote against;{' '}
                <b className="num">{formatNumber(a.states_for)}</b> voted in favour. Abstaining does not prevent adoption.
              </li>
            )}
            {a.rule === 'simple_majority' && (
              <li>
                <b className="num">{formatNumber(a.states_for)}</b> Member States voted in favour; at least{' '}
                <b className="num">{formatNumber(a.states_required)}</b> were needed.
              </li>
            )}
            <li>
              {a.single_state_veto_possible ? (
                <>
                  <strong>Could a single country block it?</strong> Yes — under unanimity, one Member State voting against is enough to
                  block a decision.
                </>
              ) : (
                <>
                  <strong>Could a single country block it?</strong> No. Only under unanimity can one Member State block a decision on
                  its own
                  {a.rule === 'qmv'
                    ? '; under qualified majority a blocking minority needs at least four Member States representing more than 35% of the EU population'
                    : ''}
                  .
                </>
              )}
            </li>
            {a.note && <li className="cvote__note">{a.note}</li>}
          </ul>
        ) : (
          <p className="meta">
            No assessment: the applicable voting rule or the data needed to check it could not be established from the records.
          </p>
        )}
      </div>

      {vote.statements.length > 0 && (
        <div className="cvote__statements">
          <Sub className="cvote__sub">Statements recorded with the vote</Sub>
          <ul>
            {vote.statements.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      <footer className="cvote__foot">
        <SourceLink source={vote.source} />
      </footer>
    </article>
  );
}

export default CouncilVoteCard;
