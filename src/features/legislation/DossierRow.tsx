import { Link } from 'react-router-dom';
import type { DossierSummary } from '../../types/data';
import { StatusBadge } from '../../components/ui';
import { formatDate } from '../../lib/format';
import { INSTRUMENT_LABEL, dossierPath, isSameTitle } from './labels';
import type { SortKey } from './explorer';

function relevantDate(d: DossierSummary, sort: SortKey, today: string): { label: string; date: string } | null {
  if (sort === 'deadline' && d.next_date && d.next_date >= today) return { label: 'Next legal date', date: d.next_date };
  if (sort === 'adopted' && d.adopted) return { label: 'Adopted', date: d.adopted };
  if (sort === 'newest' && d.started) return { label: 'Proposed', date: d.started };
  if (d.last_event) return { label: 'Latest recorded step', date: d.last_event };
  if (d.started) return { label: 'Proposed', date: d.started };
  return null;
}

/** One legislative file in a list: human title, short description, type, status, a relevant date, topics. */
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
  const rd = relevantDate(d, sort, today);
  const showOfficial = !d.short && !isSameTitle(d.title, d.official_title);
  return (
    <li className="drow">
      <div className="drow__main">
        <H className="drow__title">
          <Link to={dossierPath(d.id)}>{d.title}</Link>
        </H>
        {d.short ? (
          <p className="drow__short">{d.short}</p>
        ) : (
          showOfficial && <p className="drow__official">{d.official_title}</p>
        )}
        <p className="drow__meta">
          <span>{d.type_label || d.type}</span>
          {d.instrument && d.instrument !== 'other' && <span>{INSTRUMENT_LABEL[d.instrument]}</span>}
          <span className="mono drow__ref">{d.ref}</span>
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
        {rd && (
          <span className="drow__date">
            {rd.label} <time dateTime={rd.date}>{formatDate(rd.date)}</time>
          </span>
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
