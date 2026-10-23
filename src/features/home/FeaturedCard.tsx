import { Link } from 'react-router-dom';
import type { FeaturedItem } from '../../types/data';
import { BasisNote, ExtLink, StatusBadge } from '../../components/ui';
import { formatDate } from '../../lib/format';
import { EURLEX_CELEX, dossierPath } from '../legislation/labels';

/** One editorially selected file on the homepage: what it is, where it stands, what's next. */
export function FeaturedCard({ item, topicLabel }: { item: FeaturedItem; topicLabel: (slug: string) => string }) {
  const d = item.dossier;
  const topic = d.topics[0];
  return (
    <article className="fcard">
      <div className="fcard__top">
        <StatusBadge stage={item.status.stage} label={item.status.label} blocked={d.officially_blocked} />
        {topic && <span className="fcard__topic">{topicLabel(topic)}</span>}
      </div>
      <h3 className="fcard__title">
        <Link to={dossierPath(d.id)}>{d.title}</Link>
      </h3>
      <p className="fcard__what">{item.what}</p>
      <dl className="fcard__facts">
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
              </>
            ) : (
              <span className="meta">No dated step recorded</span>
            )}
            {item.latest_note && <span className="meta fcard__note">{item.latest_note}</span>}
          </dd>
        </div>
        <div>
          <dt>What happens next</dt>
          <dd>
            <NextStepText item={item} />
          </dd>
        </div>
      </dl>
      <div className="fcard__foot">
        <OfficialLinks item={item} />
        <Link to={dossierPath(d.id)} className="fcard__more">
          Full details<span className="visually-hidden"> on {d.title}</span> →
        </Link>
      </div>
    </article>
  );
}

/**
 * Human-readable official pages first (the procedure file and, once adopted, the law on EUR-Lex); the
 * Parliament API record the data comes from is offered separately and labelled as machine-readable.
 */
function OfficialLinks({ item }: { item: FeaturedItem }) {
  const celex = item.dossier.celex[0];
  const api = item.source?.url;
  return (
    <span className="source">
      Official records: {item.oeil_url && <ExtLink href={item.oeil_url}>Procedure file (Legislative Observatory)</ExtLink>}
      {celex && (
        <>
          {item.oeil_url && ' · '}
          <ExtLink href={EURLEX_CELEX(celex)}>Law on EUR-Lex</ExtLink>
        </>
      )}
      {api && (
        <>
          {(item.oeil_url || celex) && ' · '}
          <ExtLink href={api}>Machine-readable data (EP Open Data API)</ExtLink>
        </>
      )}
    </span>
  );
}

/**
 * The next procedural step when one is recorded or derivable; for adopted acts without one,
 * the next date fixed in law (application / transposition) when there is one.
 */
function NextStepText({ item }: { item: FeaturedItem }) {
  const ns = item.next_step;
  const today = new Date().toISOString().slice(0, 10);
  const next = item.dossier.next_date && item.dossier.next_date >= today ? item.dossier.next_date : null;
  if (ns.basis === 'unknown' && next) {
    return (
      <>
        Next date fixed in law: <time dateTime={next}>{formatDate(next)}</time>
      </>
    );
  }
  if (ns.basis === 'unknown') return <span className="meta">No next step recorded</span>;
  return (
    <>
      {ns.text} <BasisNote basis={ns.basis} />
    </>
  );
}
