import { Link } from 'react-router-dom';
import type { FeaturedItem } from '../../types/data';
import { BasisNote, ExtLink, StatusBadge } from '../../components/ui';
import { asOfToday, formatDate } from '../../lib/format';
import { EURLEX_CELEX, dossierPath } from '../legislation/labels';

/**
 * One editorially selected file on the homepage, as an overview: where it stands, what it is and what's next. Why it
 * matters, the latest step and the other official records are on the file's own page.
 */
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
        <div>
          <dt>What happens next</dt>
          <dd>
            <NextStepText item={item} />
          </dd>
        </div>
      </dl>
      <div className="fcard__foot">
        <Link to={dossierPath(d.id)} className="fcard__more">
          Full details<span className="visually-hidden"> on {d.title}</span> →
        </Link>
        <OfficialLink item={item} />
      </div>
    </article>
  );
}

/** One official page: the law on EUR-Lex once adopted, otherwise the procedure file (Legislative Observatory). */
function OfficialLink({ item }: { item: FeaturedItem }) {
  const celex = item.dossier.celex[0];
  if (celex) return <ExtLink className="fcard__official" href={EURLEX_CELEX(celex)}>Official text on EUR-Lex</ExtLink>;
  if (item.oeil_url) return <ExtLink className="fcard__official" href={item.oeil_url}>Official procedure file</ExtLink>;
  return item.source?.url ? <ExtLink className="fcard__official" href={item.source.url}>Official record</ExtLink> : null;
}

/**
 * The next date fixed in law when there is one (an adopted act's application or transposition dates; the file's page
 * lists them all); otherwise the next procedural step when one is recorded or derivable.
 */
function NextStepText({ item }: { item: FeaturedItem }) {
  const ns = item.next_step;
  const today = new Date().toISOString().slice(0, 10);
  const next = item.dossier.next_date && item.dossier.next_date >= today ? item.dossier.next_date : null;
  if (next) {
    return (
      <>
        Next date fixed in law: <time dateTime={next}>{formatDate(next)}</time>
      </>
    );
  }
  if (ns.basis === 'unknown') return <span className="meta">No next step recorded</span>;
  return (
    <>
      {asOfToday(ns.text, today)} <BasisNote basis={ns.basis} />
    </>
  );
}
