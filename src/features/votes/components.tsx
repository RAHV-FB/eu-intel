import { Link } from 'react-router-dom';
import type { EpVoteSummary, VoteKind, VoteMargin, VoteOutcome } from '../../types/data';
import { Term, VoteBar } from '../../components/ui';
import { formatDate, formatNumber } from '../../lib/format';
import { CLOSE_RELATIVE, DERIVED_OUTCOME, KIND_EXPLAINER, KIND_LABEL, OUTCOME_ICON, OUTCOME_LABEL, isClose, outcomeTone } from './labels';
import { VoteTitle } from './VoteTitle';
import './common.css';
import './votes.css';

/** The outcome; given its basis, an outcome we calculated from the counts says so next to the badge. */
export function OutcomeBadge({ outcome, basis }: { outcome: VoteOutcome; basis?: EpVoteSummary['outcome_basis'] }) {
  const badge = (
    <span className={`badge badge--${outcomeTone(outcome)}`}>
      <span aria-hidden="true" className="badge__icon">
        {OUTCOME_ICON[outcome]}
      </span>
      {OUTCOME_LABEL[outcome]}
    </span>
  );
  if (basis !== 'derived' || (outcome !== 'adopted' && outcome !== 'rejected')) return badge;
  return (
    <>
      {badge}
      <span className="meta">
        {DERIVED_OUTCOME}
        <span className="visually-hidden">.</span>
      </span>
    </>
  );
}

/**
 * "Majority reached: N votes more than needed" / "Majority not reached: N votes short". Nothing is shown unless the outcome
 * is given and is adopted or rejected: a margin is our calculation and must never stand next to an outcome that is not
 * established.
 */
export function MarginText({
  margin,
  short,
  outcome,
}: {
  margin: VoteMargin | null | undefined;
  short?: boolean;
  outcome?: VoteOutcome;
}) {
  if (outcome && outcome !== 'adopted' && outcome !== 'rejected') return null;
  if (!margin) {
    return short ? null : (
      <span className="meta">No margin shown: we have not established which majority this vote required.</span>
    );
  }
  if (!outcome) return null; // a margin is shown only next to the outcome it measures
  return (
    <span className="margin">
      {isClose({ margin, outcome }) && (
        <span className="margin__close">
          <span aria-hidden="true">◆ </span>Close vote
          <span className="visually-hidden">.</span>
        </span>
      )}{' '}
      {margin.label}
    </span>
  );
}

/** One row in a list of plenary votes. */
export function VoteListItem({ v, showDossier = true }: { v: EpVoteSummary; showDossier?: boolean }) {
  return (
    <li className="vote-item">
      <div className="vote-item__main">
        <p className="vote-item__meta">
          <time dateTime={v.date}>{formatDate(v.date)}</time>
          <span aria-hidden="true"> · </span>
          <span>{v.kind_label || KIND_LABEL[v.kind]}</span>
          {showDossier && v.dossier_ref && v.dossier_id ? (
            <>
              <span aria-hidden="true"> · </span>
              <Link to={`/legislation/${v.dossier_id}`} className="mono vote-item__ref">
                {v.dossier_ref}
              </Link>
            </>
          ) : (
            showDossier &&
            v.procedure_ref && (
              <>
                <span aria-hidden="true"> · </span>
                <span className="mono vote-item__ref">{v.procedure_ref}</span>
              </>
            )
          )}
        </p>
        <h3 className="vote-item__title">
          <Link to={`/votes/${encodeURIComponent(v.id)}`}>
            <VoteTitle v={v} />
          </Link>
        </h3>
        <div className="vote-item__outcome">
          <OutcomeBadge outcome={v.outcome} basis={v.outcome_basis} />
          <MarginText margin={v.margin} short outcome={v.outcome} />
        </div>
        {v.outcome_note && <p className="meta vote-item__note">{v.outcome_note}</p>}
      </div>
      <div className="vote-item__bar">
        <VoteBar forCount={v.for} against={v.against} abstain={v.abstain} compact label={v.display_title || v.title} />
      </div>
    </li>
  );
}

const GUIDE_ORDER: VoteKind[] = ['final', 'mandate', 'resolution', 'motion', 'procedural'];
// kinds of vote the explorer never lists (votes/index.json holds none), explained so the results can be read
const NOT_LISTED: VoteKind[] = ['amendment', 'split_or_separate'];

export function VoteKindGuide() {
  return (
    <div className="vote-guide">
      <dl className="vote-guide__list">
        {GUIDE_ORDER.map((k) => (
          <div key={k}>
            <dt>{KIND_LABEL[k]}</dt>
            <dd>{KIND_EXPLAINER[k]}</dd>
          </div>
        ))}
      </dl>
      <p>Not listed on this site: votes on amendments and on parts of a text.</p>
      <dl className="vote-guide__list">
        {NOT_LISTED.map((k) => (
          <div key={k}>
            <dt>{KIND_LABEL[k]}</dt>
            <dd>{KIND_EXPLAINER[k]}</dd>
          </div>
        ))}
      </dl>
      <p className="callout">
        <strong>A rejected amendment does not mean the law was rejected.</strong> Parliament usually votes on many amendments before
        voting on the text as a whole. Only the final vote tells you Parliament’s position on the law — and Parliament’s vote alone
        does not make a law: under the <Term id="olp">ordinary legislative procedure</Term> the <Term id="council">Council</Term> must
        agree on the same text.
      </p>
    </div>
  );
}

export function CloseVoteMethod() {
  return (
    <div className="stack">
      <p>
        Most plenary votes need a majority of the votes cast (abstentions do not count). Some need a majority of all Parliament’s
        members, or two thirds of the votes cast. We calculate a margin only when the applicable threshold is established from the
        records: how many votes in favour were needed, and how far the result was from that number.
      </p>
      <p>
        We call a vote <strong>close</strong> when the votes in favour were within {formatNumber(CLOSE_RELATIVE * 100)}% of the votes
        counted towards the threshold. Votes without an established threshold or outcome are never labelled close and are left out
        of the “close votes” filter (and the homepage’s Close votes list) and placed last when sorting by margin.
      </p>
    </div>
  );
}
