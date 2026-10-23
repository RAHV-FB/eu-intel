import { Link } from 'react-router-dom';
import type { HomeData, HomeListItem } from '../../types/data';
import { formatDate } from '../../lib/format';
import { dossierPath } from '../legislation/labels';

type HomeList = HomeData['lists'][number];

/** Where each list leads for "see more" (filters on the explorer / votes pages). */
const MORE: Partial<Record<HomeList['id'], { to: string; label: string }>> = {
  recently_adopted: { to: '/legislation?stage=law&sort=adopted', label: 'Adopted legislation in our dataset' },
  under_debate: { to: '/legislation?stage=active&sort=updated', label: 'All files still being decided' },
  stalled: { to: '/legislation?blocked=1', label: 'Officially reported as blocked' },
  upcoming: { to: '/legislation?sort=deadline', label: 'All upcoming dates' },
  close_votes: { to: '/votes?kind=final&close=1', label: 'All close final votes' },
  rejected: { to: '/votes?kind=final&outcome=rejected', label: 'All final votes Parliament rejected' },
};

function itemHref(it: HomeListItem): string | null {
  if (it.dossier_id) return dossierPath(it.dossier_id);
  if (it.vote_id) return `/votes/${encodeURIComponent(it.vote_id)}`;
  return null;
}

function Row({ it }: { it: HomeListItem }) {
  const href = itemHref(it);
  return (
    <li className="hl__row">
      <div className="hl__date">{it.date ? <time dateTime={it.date}>{formatDate(it.date)}</time> : <span aria-hidden="true">—</span>}</div>
      <div className="hl__body">
        {href ? (
          <Link to={href} className="hl__title">
            {it.title}
          </Link>
        ) : (
          <span className="hl__title">{it.title}</span>
        )}
        {(it.subtitle || it.badge) && (
          <div className="hl__sub">
            {it.badge && <span className="hl__badge">{it.badge}</span>}
            {it.subtitle && <span>{it.subtitle}</span>}
          </div>
        )}
      </div>
    </li>
  );
}

export function HomeLists({ lists }: { lists: HomeList[] }) {
  if (!lists.length) return null;
  const filled = lists.filter((l) => l.items.length > 0);
  const empty = lists.filter((l) => l.items.length === 0);
  return (
    <>
      {filled.length > 0 && (
        <div className="hl-grid">
          {filled.map((l) => {
            const more = MORE[l.id];
            const headingId = `hl-${l.id}`;
            return (
              <section key={l.id} className="hl" aria-labelledby={headingId}>
                <h3 id={headingId} className="hl__heading">
                  {l.title}
                </h3>
                {l.description && <p className="hl__desc">{l.description}</p>}
                <ol className="hl__list">
                  {l.items.slice(0, 6).map((it, i) => (
                    <Row key={`${it.dossier_id ?? it.vote_id ?? ''}-${i}`} it={it} />
                  ))}
                </ol>
                {more && (
                  <Link to={more.to} className="hl__more">
                    {more.label} →
                  </Link>
                )}
              </section>
            );
          })}
        </div>
      )}
      {empty.length > 0 && (
        <p className="hl-empty">
          <strong>Nothing recorded in the current data for:</strong>{' '}
          {empty.map((l, i) => (
            <span key={l.id} title={l.description}>
              {i > 0 && ' · '}
              {l.title}
            </span>
          ))}
          . These lists fill in as the official sources report activity — see <Link to="/about#coverage">what’s covered</Link>.
        </p>
      )}
    </>
  );
}
