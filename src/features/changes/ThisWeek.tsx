import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { ActivityItem } from '../../types/data';
import { formatDate, formatNumber } from '../../lib/format';
import { ChangeItem } from './ChangeItem';
import { changesOf, countByKind, countLabel, formatDays, latestChanges, type Latest } from './changes';
import './changes.css';

/** The rows the strip shows (phones show the first four). */
const SHOWN = 6;

/** What the strip covers, on the reader's date. */
function coverage(l: Latest): string {
  if (l.recordedAt) return `Recorded by our data refresh${l.days.length > 1 ? 'es' : ''} of ${formatDays(l.days)}, newest step first.`;
  return `Steps dated from ${formatDate(l.from)}; when they appeared in the official records was not tracked.`;
}

/**
 * "This week in EU law" on the home page: the changes of the latest week of recording (`items`: activity.json, which the
 * home page reads), newest step first, with how many there are of each kind, each kind leading to the What changed page.
 * Called "this week" only while the latest refresh is at most a week old on the reader's date; then "Latest changes".
 */
export function ThisWeek({ items }: { items: ActivityItem[] | undefined }) {
  const latest = useMemo(() => (items ? latestChanges(changesOf(items), Date.now()) : null), [items]);
  if (!latest?.changes.length) return null;
  const counts = countByKind(latest.changes);
  return (
    <section className="section tw" aria-labelledby="tw-title">
      <div className="lx-head">
        <div>
          <p className="lx-kicker">From the official records</p>
          <h2 id="tw-title">{latest.current ? 'This week in EU law' : 'Latest changes in EU law'}</h2>
        </div>
        <p className="lx-head__note">{coverage(latest)}</p>
      </div>
      <p className="tw__counts dot-list">
        {counts.map((k) => (
          <span key={k.key}>
            <Link to={`/legislation/changes?kind=${k.key}`}>{countLabel(k.key, k.n)}</Link>
          </span>
        ))}
      </p>
      <ol className="ch-list tw__list">
        {latest.changes.slice(0, SHOWN).map((c) => (
          <ChangeItem key={c.id} c={c} compact />
        ))}
      </ol>
      <Link to="/legislation/changes" className="hl__more">
        All {formatNumber(latest.changes.length)} changes, and earlier weeks, by topic →
      </Link>
    </section>
  );
}
