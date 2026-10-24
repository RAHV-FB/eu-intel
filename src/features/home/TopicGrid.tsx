import { Link } from 'react-router-dom';
import type { Topic } from '../../types/data';
import { formatNumber } from '../../lib/format';

export function TopicGrid({ topics }: { topics: Topic[] }) {
  const shown = topics.filter((t) => t.count > 0);
  if (!shown.length) return null;
  return (
    <ul className="topic-grid">
      {shown.map((t) => (
        <li key={t.slug}>
          <Link to={`/legislation?topic=${encodeURIComponent(t.slug)}`} className="topic-grid__link">
            <span className="topic-grid__label">{t.label}</span>
            <span className="topic-grid__count">
              {formatNumber(t.count)} <span className="visually-hidden">legislative</span> files
            </span>
            {t.description && <span className="topic-grid__desc">{t.description}</span>}
          </Link>
        </li>
      ))}
    </ul>
  );
}
