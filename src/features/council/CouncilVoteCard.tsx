/**
 * One recorded vote of the Council of the EU (ministers of the Member States — NOT the European Council).
 * Used on the dossier page and wherever a full CouncilVote record is available.
 */
import { Link } from 'react-router-dom';
import type { CountryDetail, CouncilAssessment, CouncilPosition, CouncilVote, CouncilVoteOn } from '../../types/data';
import { ExtLink, SourceLink, Term, VoteBar } from '../../components/ui';
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

/** Short label for what a Council vote was on (country tables, timelines). */
export const COUNCIL_VOTE_ON_SHORT: Record<CouncilVoteOn, string> = {
  act: 'Adoption of the act',
  first_reading_position: 'Council position at first reading (not the final act)',
  other: 'Other Council decision',
};

type CouncilRow = CountryDetail['council_votes'][number];

/**
 * Tag on a country page's Council vote row: what was voted on when it is not the act itself, or that the act was not
 * adopted. An 'other' vote is tagged with the item voted on (vote_on_label: "Derogation from the eight-week period …",
 * ST 8160/20), or as another Council decision when the document names none. The tag sits outside the title, which
 * phones clamp to three lines, so that row does not read like the act's row beside it (ST 8159/20).
 */
export function councilRowTag(v: CouncilRow): string | null {
  if (v.vote_on === 'first_reading_position') return COUNCIL_VOTE_ON_SHORT.first_reading_position;
  if (v.vote_on === 'other') return v.vote_on_label || COUNCIL_VOTE_ON_SHORT.other;
  if (v.vote_on === 'act' && v.outcome === 'not_adopted') return 'Act not adopted by this vote';
  return null;
}

/** A country page's Council vote row title: the list title, without the item voted on that its tag shows. */
export function councilRowTitle(v: CouncilRow): string {
  const title = v.display_title ?? v.title;
  const tail = v.vote_on === 'other' && v.vote_on_label ? ` – ${v.vote_on_label}` : null;
  return tail && title.endsWith(tail) ? title.slice(0, -tail.length) : title;
}

/** Outcome wording that says what was adopted: the act, the Council's first-reading position, or another item. */
export function councilOutcomeLabel(vote: Pick<CouncilVote, 'outcome' | 'vote_on'>): string {
  if (vote.outcome === 'unknown') return 'Result not read from the source document';
  const adopted = vote.outcome === 'adopted';
  if (vote.vote_on === 'first_reading_position') return adopted ? 'Position adopted' : 'Position not adopted';
  if (vote.vote_on === 'act') return adopted ? 'Act adopted' : 'Act not adopted';
  return adopted ? 'Adopted' : 'Not adopted';
}

export function CouncilRule({ rule }: { rule: CouncilVote['voting_rule'] }) {
  if (rule === 'qmv') return <Term id="qmv">Qualified majority</Term>;
  if (rule === 'unanimity') return <Term id="unanimity">Unanimity</Term>;
  if (rule === 'simple_majority') return <>Simple majority</>;
  return <>Voting rule not read from the source document</>;
}

/** "Denmark", "Denmark and Ireland", "Denmark, Ireland and the United Kingdom". */
function listNames(codes: string[]): string {
  const names = codes.map((c) => (c === 'GB' ? 'the United Kingdom' : countryName(c)));
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

function VoteOn({ vote }: { vote: CouncilVote }) {
  if (vote.vote_on === 'first_reading_position') {
    return (
      <>
        <strong>The Council’s position at first reading</strong> — this vote did not adopt the act. Under the{' '}
        <Term id="olp">ordinary legislative procedure</Term>, Parliament then decides on the Council’s position at second reading.
      </>
    );
  }
  if (vote.vote_on === 'act') {
    return <strong>{/legislative act/i.test(vote.stage ?? '') ? 'Adoption of the legislative act' : 'Adoption of the act'}</strong>;
  }
  // an 'other' vote: the item(s) as the build names them (the derogation, not "Adoption of the legislative act")
  if (vote.vote_on === 'other') {
    if (vote.vote_on_label) return <strong>{vote.vote_on_label}</strong>;
    return vote.stage ? <>{COUNCIL_VOTE_ON_SHORT.other}</> : <>Not named in the voting-result document</>;
  }
  if (vote.stage) return <strong>{vote.stage}</strong>;
  return <>Not named in the voting-result document</>;
}

/** Size of a blocking minority under the established legal basis, or null when it is not established. */
function blockingRule(a: CouncilAssessment, notParticipating: number): string | null {
  if (notParticipating === 0 && a.legal_basis === 'TEU Art. 16(4)') {
    return 'at least four Member States representing more than 35% of the EU population';
  }
  if (notParticipating > 0 && a.legal_basis === 'TFEU Art. 238(3)(a)' && a.blocking_minority_min_states != null) {
    return `at least ${formatNumber(a.blocking_minority_min_states)} of the participating Member States, representing more than 35% of their combined population (TFEU Art. 238(3)(a))`;
  }
  return null;
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
  const notParticipating = a?.states_not_participating ?? groups.not_participating.length;
  const participating = a?.states_participating ?? recorded.length - groups.not_participating.length;
  const bmRule = a ? blockingRule(a, notParticipating) : null;
  const checked = vote.correction_sources ?? []; // the texts a correction of the rule or outcome rests on

  return (
    <article className="cvote" aria-labelledby={`cvote-${vote.id}`}>
      <header className="cvote__head">
        <p className="cvote__eyebrow">
          <Term id="council">Council of the EU</Term>
          {vote.configuration ? <> · {vote.configuration}</> : null} · <time dateTime={vote.date}>{formatDate(vote.date, true)}</time>
          {vote.written_procedure ? <> · written procedure</> : null}
        </p>
        <H id={`cvote-${vote.id}`} className="cvote__title">
          {vote.title}
        </H>
        <p className="cvote__voteon">
          <span className="cvote__voteon-label">Vote on: </span>
          <VoteOn vote={vote} />
        </p>
        {vote.vote_on_note && <p className="meta cvote__voteon-note">{vote.vote_on_note}</p>}
        {vote.date_note && <p className="meta cvote__voteon-note">{vote.date_note}</p>}
        <dl className="cvote__facts">
          <div>
            <dt>Outcome</dt>
            <dd>
              <span className={`cvote__outcome cvote__outcome--${vote.outcome}`}>
                <span aria-hidden="true">{vote.outcome === 'adopted' ? '●' : vote.outcome === 'not_adopted' ? '✕' : '○'}</span>{' '}
                {councilOutcomeLabel(vote)}
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
        {vote.voting_rule_note && <p className="meta cvote__voteon-note">{vote.voting_rule_note}</p>}
        {vote.outcome_note && <p className="meta cvote__voteon-note">{vote.outcome_note}</p>}
        {checked.length > 0 && (
          <p className="meta cvote__voteon-note">
            Texts checked:{' '}
            {checked.map((x, i) => (
              <span key={x.url}>
                {i > 0 && '; '}
                <ExtLink href={x.url}>{x.label}</ExtLink>
              </span>
            ))}
            .
          </p>
        )}
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
              <section className="cvote__pos cvote__pos--missing" aria-label={`Position not read: ${missing.length}`}>
                <p className="cvote__pos-title">
                  <i className="cvote__swatch cvote__swatch--missing" aria-hidden="true" />
                  Position not read from the voting sheet <span className="num">({missing.length})</span>
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
        <p className="meta">
          {vote.positions_note ||
            'We could not read the Member State positions from the published voting sheet, so no individual positions are shown for this vote.'}{' '}
          See the Council’s voting-result document linked below.
        </p>
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
                  {a.states_required_alt != null && a.states_required_alt !== a.states_required ? (
                    <>
                      <b className="num">{formatNumber(a.states_required)}</b> were needed if the Council acted on a Commission proposal (55%),
                      or <b className="num">{formatNumber(a.states_required_alt)}</b> if it did not (72%).
                    </>
                  ) : (
                    <>
                      <b className="num">{formatNumber(a.states_required)}</b> were needed.
                    </>
                  )}
                </li>
                {popFor && (
                  <li>
                    They represent <b className="num">{popFor}</b> of{' '}
                    {notParticipating > 0 ? 'the population of the participating Member States' : 'the EU population'}
                    {popReq ? (
                      <>
                        ; at least <b className="num">{popReq}</b> was needed
                      </>
                    ) : null}
                    .
                  </li>
                )}
                {notParticipating > 0 && (
                  <li>
                    {groups.not_participating.length > 0 ? listNames(groups.not_participating) : `${formatNumber(notParticipating)} Member States`}{' '}
                    did not take part in this vote, so both thresholds are calculated over the {formatNumber(participating)} participating
                    Member States (TFEU Art. 238(3)).
                  </li>
                )}
                {a.adopted_by_rule === true && <li>On these figures, both qualified-majority thresholds were met.</li>}
                {a.adopted_by_rule === false && <li>On these figures, the qualified-majority thresholds were not met.</li>}
                {a.blocking_minority_existed === true && (
                  <li>The Member States not voting in favour formed a blocking minority{bmRule ? ` (${bmRule})` : ''}.</li>
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
            {a.rule === 'unanimity' && a.adopted_by_rule === false && (a.states_against ?? groups.against.length) > 0 && (
              <li>
                {groups.against.length > 0 ? listNames(groups.against) : `${formatNumber(a.states_against ?? 0)} Member States`}{' '}
                voted against, so unanimity was not reached.
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
                  {a.rule === 'qmv' && bmRule ? `; here a blocking minority needed ${bmRule}` : ''}.
                </>
              )}
            </li>
            {a.note && <li className="cvote__note">{a.note}</li>}
          </ul>
        ) : (
          <p className="meta">
            {recorded.length === 0
              ? 'No assessment: applying the voting rule needs the individual Member State positions, which we could not read.'
              : 'No assessment: the applicable voting rule or the data needed to check it could not be established from the records.'}
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
        {vote.source_note && <p className="meta">{vote.source_note}</p>}
        <SourceLink source={vote.source} />
      </footer>
    </article>
  );
}

export default CouncilVoteCard;
