import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import type { CouncilVote, DossierDetail, EpVoteSummary, Meta, VoteKind } from '../../../types/data';
import { ExtLink, SourceLink, Term, VoteBar } from '../../../components/ui';
import { formatDate } from '../../../lib/format';
import { CouncilVoteCard } from '../../council/CouncilVoteCard';
import { MarginText, OutcomeBadge } from '../../votes/components';
import { VoteTitle } from '../../votes/VoteTitle';
import { SplitLinks } from './Split';

const PRIMARY: VoteKind[] = ['final', 'mandate', 'resolution', 'motion', 'other'];

function EpVoteCard({ v }: { v: EpVoteSummary }) {
  return (
    <li className="dz-vote">
      <p className="dz-vote__meta">
        <time dateTime={v.date}>{formatDate(v.date, true)}</time>
        <span aria-hidden="true"> · </span>
        <span className="tag">{v.kind_label}</span>
      </p>
      <h3 className="dz-vote__title">
        <Link to={`/votes/${encodeURIComponent(v.id)}`}>
          <VoteTitle v={v} />
        </Link>
      </h3>
      <div className="dz-vote__outcome">
        <OutcomeBadge outcome={v.outcome} basis={v.outcome_basis} />
        {v.margin && <MarginText margin={v.margin} outcome={v.outcome} />}
      </div>
      {v.outcome_note && <p className="meta dz-vote__note">{v.outcome_note}</p>}
      <VoteBar forCount={v.for} against={v.against} abstain={v.abstain} label={v.display_title || v.title} />
      {v.margin && <p className="meta dz-vote__rule">Rule applied: {v.margin.rule_label}</p>}
      <p className="dz-vote__links">
        <Link to={`/votes/${encodeURIComponent(v.id)}`}>
          {v.has_ballots ? 'See how each political group, country’s MEPs and MEP voted' : 'Vote details'}
          <span aria-hidden="true"> →</span>
        </Link>
        <SourceLink source={v.source} />
      </p>
    </li>
  );
}

function CompactVote({ v }: { v: EpVoteSummary }) {
  return (
    <li className="dz-cvote">
      <span className="dz-cvote__date">
        <time dateTime={v.date}>{formatDate(v.date)}</time>
      </span>
      <span className="dz-cvote__main">
        <Link to={`/votes/${encodeURIComponent(v.id)}`}>
          <VoteTitle v={v} />
        </Link>
        <span className="meta"> · {v.kind_label}</span>
      </span>
      <span className="dz-cvote__res">
        <OutcomeBadge outcome={v.outcome} basis={v.outcome_basis} />
        {v.for != null && (
          <span className="meta num">
            {v.for}–{v.against ?? 0}–{v.abstain ?? 0}
            <span className="visually-hidden"> (for, against, abstained)</span>
          </span>
        )}
      </span>
    </li>
  );
}

export function ParliamentVotes({
  votes,
  oeilUrl,
  split = [],
}: {
  votes: EpVoteSummary[];
  oeilUrl?: string | null;
  split?: DossierDetail['related'];
}) {
  const [showAll, setShowAll] = useState(false);
  const listId = useId();
  const primary = votes.filter((v) => PRIMARY.includes(v.kind));
  const secondary = votes.filter((v) => !PRIMARY.includes(v.kind));
  // If there is no final/resolution vote, promote the most recent few so the section is never empty-looking.
  const main = primary.length ? primary : secondary.slice(0, 3);
  const rest = primary.length ? secondary : secondary.slice(3);

  return (
    <section className="dz-section" id="ep-votes" aria-labelledby="ep-votes-title">
      <h2 id="ep-votes-title">How the European Parliament voted</h2>
      <p className="dz-intro">
        Parliament’s plenary votes linked to this file by official identifiers: its final and negotiating-mandate votes, votes on
        the committee’s decision to negotiate, and <Term id="roll-call">roll-call votes</Term> on motions and resolutions. Votes on
        amendments and on parts of the text are not listed. Each vote’s page breaks a roll-call result down by{' '}
        <Term id="political-group">political group</Term>, by MEPs’ country and by MEP.
      </p>
      <p className="dz-callout">
        <strong>“Spanish MEPs voted…” is not the same as “Spain voted…”.</strong> MEPs are elected in each country but vote
        individually, usually with their political group. Member State governments vote separately, in the Council of the EU
        (see the next section).
      </p>
      {votes.length === 0 && split.length > 0 ? (
        <p className="dz-none">
          This proposal was split into separate files; Parliament’s votes are shown on them: <SplitLinks parts={split} />.
        </p>
      ) : votes.length === 0 ? (
        <p className="dz-none">
          No roll-call vote is matched to this file in our data (see <Link to="/about#coverage">coverage</Link>).
          {oeilUrl && (
            <>
              {' '}
              Parliament’s decisions on it are listed in its <ExtLink href={oeilUrl}>Legislative Observatory file</ExtLink>.
            </>
          )}
        </p>
      ) : (
        <>
          <ol className="dz-votes">
            {main.map((v) => (
              <EpVoteCard key={v.id} v={v} />
            ))}
          </ol>
          {rest.length > 0 && (
            <div className="dz-votes-more">
              <button type="button" className="btn" aria-expanded={showAll} aria-controls={listId} onClick={() => setShowAll((s) => !s)}>
                {showAll ? 'Hide' : 'Show'} {rest.length} {rest.every((v) => v.kind === 'procedural') ? 'procedural' : 'other'}{' '}
                vote{rest.length === 1 ? '' : 's'}
              </button>
              {showAll && (
                <ol className="dz-cvotes" id={listId}>
                  {rest.map((v) => (
                    <CompactVote key={v.id} v={v} />
                  ))}
                </ol>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export function CouncilVotes({
  votes,
  meta,
  split = [],
}: {
  votes: CouncilVote[];
  meta: Meta | undefined;
  split?: DossierDetail['related'];
}) {
  const src = meta?.sources.find((s) => s.id === 'council');
  const unavailable = src && (src.status === 'failed' || src.status === 'unavailable');
  return (
    <section className="dz-section" id="council-votes" aria-labelledby="council-title">
      <h2 id="council-title">How Member States voted in the Council</h2>
      <p className="dz-intro">
        In the <Term id="council">Council of the EU</Term>, government ministers vote on behalf of their country. Most laws
        need a <Term id="qmv">qualified majority</Term>; some areas require <Term id="unanimity">unanimity</Term>.
      </p>
      {votes.length > 0 ? (
        <div className="dz-council">
          {votes.map((v) => (
            <CouncilVoteCard key={v.id} vote={v} headingLevel={3} />
          ))}
        </div>
      ) : split.length > 0 ? (
        <p className="dz-none">
          This proposal was split into separate files; the Council’s votes are shown on them: <SplitLinks parts={split} />.
        </p>
      ) : unavailable ? (
        <p className="dz-none">
          Council voting results are not available in this release, so we cannot show how Member States voted on this file.
          See <Link to="/about#sources">data sources</Link>.
        </p>
      ) : (
        <p className="dz-none">
          No Council vote is linked to this file in the data we have. The Council publishes how each Member State voted when it
          formally adopts a legislative act; files still under discussion, or adopted outside the period covered, have no record
          here.
        </p>
      )}
    </section>
  );
}
