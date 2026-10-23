import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import type { ActivityItem, ISODate, TimelineEvent } from '../../../types/data';
import { EmptyState, ExtLink, SourceLink, institutionLabel } from '../../../components/ui';
import { eventOn, formatDate, formatDateTime, safeUrl } from '../../../lib/format';

const INSTITUTION_SHORT: Record<string, string> = {
  EP: 'Parliament',
  'EP and Council': 'Parliament and Council',
  Council: 'Council',
  'European Council': 'European Council',
  Commission: 'Commission',
  'EUR-Lex': 'Official Journal / EUR-Lex',
  OEIL: 'Legislative Observatory',
  LegislativeTrain: 'Legislative Train',
  CJEU: 'Court of Justice',
};

function EventItem({ e: recorded, today }: { e: TimelineEvent; today: ISODate }) {
  // the visitor's date: a date the build had ahead may have passed since (state and title as the build would give)
  const e = eventOn(recorded, today);
  const scheduled = e.state === 'scheduled';
  const docs = e.docs ?? [];
  // Avoid repeating the same official link twice (document link and source often coincide).
  const sourceIsDoc = !!e.source && docs.some((doc) => doc.url && doc.url === e.source?.url);
  return (
    <li className={`tl__item${scheduled ? ' is-scheduled' : ''}${e.key ? ' is-key' : ''}`}>
      <span className="tl__mark" aria-hidden="true" />
      <div className="tl__date">
        <time dateTime={e.date}>{formatDate(e.date)}</time>
        {scheduled && <span className="tl__sched">Scheduled</span>}
      </div>
      <div className="tl__body">
        <p className="tl__title">{e.title}</p>
        <p className="tl__inst" title={institutionLabel(e.institution)}>
          {INSTITUTION_SHORT[e.institution] ?? institutionLabel(e.institution)}
        </p>
        {e.detail && <p className="tl__detail">{e.detail}</p>}
        {e.after_end_of_validity && (
          <p className="tl__detail">
            A date after the act’s validity ended ({formatDate(e.after_end_of_validity)}); EUR-Lex still records it for
            the act.
          </p>
        )}
        {(docs.length > 0 || e.vote_id || e.source) && (
          <div className="tl__links">
            {e.vote_id && (
              <Link to={`/votes/${encodeURIComponent(e.vote_id)}`} className="tl__vote">
                How MEPs voted →
              </Link>
            )}
            {docs.length > 0 && (
              <ul className="tl__docs" aria-label="Documents">
                {docs.map((doc) => (
                  <li key={doc.id}>
                    {safeUrl(doc.url) ? (
                      <ExtLink href={doc.url}>{doc.label || doc.id}</ExtLink>
                    ) : (
                      <span className="mono">{doc.label || doc.id}</span>
                    )}
                    {doc.label && doc.label !== doc.id && <span className="meta mono"> {doc.id}</span>}
                  </li>
                ))}
              </ul>
            )}
            {e.source && !sourceIsDoc && <SourceLink source={e.source} />}
          </div>
        )}
      </div>
    </li>
  );
}

export function Timeline({
  events,
  changes,
  today,
  eurlexOnly,
  oeilUrl,
}: {
  events: TimelineEvent[];
  changes: ActivityItem[];
  today: ISODate;
  eurlexOnly?: boolean;
  oeilUrl?: string | null;
}) {
  const [all, setAll] = useState(false);
  const listId = useId();
  const keyEvents = events.filter((e) => e.key || e.state === 'scheduled');
  const hasToggle = keyEvents.length > 0 && keyEvents.length < events.length;
  const shown = all || !hasToggle ? events : keyEvents;

  return (
    <section className="dz-section" id="timeline" aria-labelledby="timeline-title">
      <h2 id="timeline-title">Timeline</h2>
      <p className="dz-intro">
        Steps recorded in the official procedure file and in EUR-Lex.{' '}
        {oeilUrl && !eurlexOnly && (
          <>
            Parliament’s <ExtLink href={oeilUrl}>procedure file in the Legislative Observatory</ExtLink> lists them in
            readable form; “Machine-readable record” links open the underlying data in Parliament’s open data API.{' '}
          </>
        )}
        {hasToggle && !all ? 'Showing key milestones. ' : ''}
        Not every law goes through every step: many are agreed at Parliament’s first reading, some never reach a vote.
      </p>
      {eurlexOnly && (
        <p className="dz-caveat" role="note">
          <strong>The procedure’s earlier steps are not in our dataset.</strong> This page is built from the act’s EUR-Lex
          record only, so the proposal, Parliament’s votes and the Council’s steps are not shown here.
          {oeilUrl && (
            <>
              {' '}
              See the <ExtLink href={oeilUrl}>procedure file in Parliament’s Legislative Observatory</ExtLink>.
            </>
          )}
        </p>
      )}
      {events.length === 0 ? (
        <EmptyState title="No dated steps are recorded for this file." />
      ) : (
        <>
          <ol className="tl" id={listId}>
            {shown.map((e) => (
              <EventItem key={e.id} e={e} today={today} />
            ))}
          </ol>
          {hasToggle && (
            <button type="button" className="btn tl__toggle" aria-controls={listId} aria-expanded={all} onClick={() => setAll((a) => !a)}>
              {all ? 'Show key milestones only' : `Show all ${events.length} recorded events`}
            </button>
          )}
        </>
      )}

      {changes.length > 0 && (
        <div className="dz-changes">
          <h3>Changes detected since earlier data refreshes</h3>
          <ul>
            {changes.slice(0, 10).map((c) => (
              <li key={c.id}>
                <time dateTime={c.date}>{formatDate(c.date)}</time> — {c.title}
                {c.detected_at && <span className="meta"> (first recorded by us {formatDateTime(c.detected_at)})</span>}
                {c.source && (
                  <>
                    {' '}
                    <SourceLink source={c.source} />
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
