import { Link } from 'react-router-dom';
import type { FeaturedItem } from '../../types/data';
import { BasisNote, SourceLink, StatusBadge, institutionLabel } from '../../components/ui';
import { formatDate } from '../../lib/format';
import { dossierPath } from '../legislation/labels';

/** One editorially selected file on the homepage: what it is, where it stands, what's next. */
export function FeaturedCard({ item, topicLabel }: { item: FeaturedItem; topicLabel: (slug: string) => string }) {
  const d = item.dossier;
  const topic = d.topics[0];
  return (
    <article className="feature">
      <div className="feature__top">
        <StatusBadge stage={item.status.stage} label={item.status.label} blocked={d.officially_blocked} />
        {topic && <span className="feature__topic">{topicLabel(topic)}</span>}
      </div>
      <h3 className="feature__title">
        <Link to={dossierPath(d.id)}>{d.title}</Link>
      </h3>
      <p className="feature__what">{item.what}</p>
      <dl className="feature__facts">
        {item.why && (
          <div>
            <dt>Why it matters</dt>
            <dd>{item.why}</dd>
          </div>
        )}
        <div>
          <dt>Latest verified step</dt>
          <dd>
            {item.latest ? (
              <>
                <time dateTime={item.latest.date}>{formatDate(item.latest.date)}</time>
                {' · '}
                {item.latest.title}
                <span className="meta"> ({institutionLabel(item.latest.institution)})</span>
              </>
            ) : (
              <span className="meta">No dated step recorded</span>
            )}
          </dd>
        </div>
        <div>
          <dt>What happens next</dt>
          <dd>
            {item.next_step.text} <BasisNote basis={item.next_step.basis} />
          </dd>
        </div>
      </dl>
      <div className="feature__foot">
        <SourceLink source={item.source} />
        <Link to={dossierPath(d.id)} className="feature__more">
          Full details<span className="visually-hidden"> on {d.title}</span> →
        </Link>
      </div>
    </article>
  );
}
