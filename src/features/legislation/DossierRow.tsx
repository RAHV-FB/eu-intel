import { Link } from 'react-router-dom';
import type { DossierSummary } from '../../types/data';
import { StatusBadge } from '../../components/ui';
import { formatDate, noUpdateText } from '../../lib/format';
import { ACTIVE_STAGES, INSTRUMENT_LABEL, dossierPath } from './labels';
import type { SortKey } from './explorer';
import { latestStepOn } from './latestStep';

/** The date the order is by, when it is not the latest recorded step's (shown on every row). */
function sortDate(d: DossierSummary, sort: SortKey, today: string): { label: string; date: string } | null {
  if (sort === 'deadline' && d.next_date && d.next_date >= today) return { label: 'Next legal date', date: d.next_date };
  if (sort === 'adopted' && d.adopted) return { label: 'Adopted', date: d.adopted };
  if (sort === 'newest' && d.started) return { label: 'Proposed', date: d.started };
  return null;
}

/** One legislative file in a list: human title, short description, type, status, its latest recorded step (named, and
 * dated), the date the list is ordered by, topics. */
export function DossierRow({
  d,
  sort = 'updated',
  today,
  topicLabel,
  following,
  headingLevel = 3,
}: {
  d: DossierSummary;
  sort?: SortKey;
  today: string;
  topicLabel?: (slug: string) => string;
  following?: boolean;
  headingLevel?: 2 | 3;
}) {
  const H = `h${headingLevel}` as 'h2' | 'h3';
  const sd = sortDate(d, sort, today);
  const step = latestStepOn(d, today);
  const last = step?.date ?? d.last_event;
  // the stuck view: how long a file still being decided has gone without a recorded step, on the reader's date
  const stuck = sort === 'stuck' && ACTIVE_STAGES.has(d.stage) && last ? noUpdateText(0, last, today) : null;
  return (
    <li className="drow">
      <div className="drow__main">
        <H className="drow__title">
          <Link to={dossierPath(d.id)} title={d.title.length > 160 ? d.title : undefined}>
            {d.title}
          </Link>
        </H>
        {/* the names the file's page gives under its heading (an act's own short title, verified common names) */}
        {d.names && d.names.length > 0 && <p className="drow__names">Also known as {d.names.join(', ')}</p>}
        {d.short && <p className="drow__short">{d.short}</p>}
        <p className="drow__meta dot-list">
          <span>{d.type_label || d.type}</span>
          {d.instrument && d.instrument !== 'other' && (
            <span>
              {INSTRUMENT_LABEL[d.instrument]}
              {d.celex.length === 0 && ' (as proposed)'}
            </span>
          )}
          <span className="ref">{d.ref}</span>
        </p>
        {topicLabel && d.topics.length > 0 && (
          <ul className="drow__topics" aria-label="Topics">
            {d.topics.slice(0, 4).map((t) => (
              <li key={t}>
                <Link to={`/legislation?topic=${encodeURIComponent(t)}`} className="tag drow__topic">
                  {topicLabel(t)}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="drow__side">
        <StatusBadge stage={d.stage} label={d.status_label} blocked={d.officially_blocked} />
        {d.officially_blocked && <span className="drow__blocked">Officially reported as blocked</span>}
        {stuck && <span className="drow__stuck">{stuck}</span>}
        {step ? (
          <span className="drow__step">
            <span className="drow__step-label">Latest step:</span> {step.title} ·{' '}
            <time dateTime={step.date}>{formatDate(step.date)}</time>
          </span>
        ) : (
          last && (
            <span className="drow__date">
              Latest recorded step <time dateTime={last}>{formatDate(last)}</time>
            </span>
          )
        )}
        {sd ? (
          <span className="drow__date">
            {sd.label} <time dateTime={sd.date}>{formatDate(sd.date)}</time>
          </span>
        ) : (
          !last &&
          d.started && (
            <span className="drow__date">
              Proposed <time dateTime={d.started}>{formatDate(d.started)}</time>
            </span>
          )
        )}
        {following && (
          <span className="drow__following">
            <span aria-hidden="true">★ </span>Following
          </span>
        )}
      </div>
    </li>
  );
}
