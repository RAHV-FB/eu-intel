import { Link } from 'react-router-dom';
import type { ApplyingRule, ISODate, RuleWhere } from '../../types/data';
import { ExtLink } from '../../components/ui';
import { countryName, formatDate } from '../../lib/format';
import { dossierPath } from '../legislation/labels';
import { headlineOn, unknownNote, whereLead } from './applies';

/** Which Member States the act binds, and why the data leave some out or cannot tell. */
function Where({ w }: { w: RuleWhere }) {
  const note = unknownNote(w);
  const why = w.not_bound.length > 0 || !!note || !!w.opted_in?.length;
  return (
    <div className="ap__where">
      <p>
        <span className="ap__label">Where:</span> {whereLead(w)}
      </p>
      {why && (
        <ul className="ap__why">
          {w.not_bound.map((x) => (
            <li key={x.country}>
              {x.reason}
              {x.url && (
                <>
                  {' '}
                  <ExtLink href={x.url}>Record</ExtLink>
                </>
              )}
            </li>
          ))}
          {w.opted_in?.map((x) => (
            <li key={x.country}>
              {countryName(x.country)} took part after its adoption: <ExtLink href={x.url}>{x.label}</ExtLink> confirms it
              (Protocol No 21, Article 4).
            </li>
          ))}
          {note && <li>{note}</li>}
        </ul>
      )}
    </div>
  );
}

/**
 * One date: what happens on it in the tense of the reader's date, the file and the act's names (linked to the file's
 * page), what applies (checked against the act's text, or the articles EUR-Lex names), where, and the act, its topics
 * and the record the date comes from.
 */
export function AppliesItem({ r, today, topicLabel }: { r: ApplyingRule; today: ISODate; topicLabel: (slug: string) => string }) {
  const checked = r.checked;
  return (
    <li className="ch ap">
      <div className="ch__date">
        <time dateTime={r.date}>{formatDate(r.date)}</time>
      </div>
      <div className="ch__body">
        <p className="ch__event">
          {headlineOn(r, today)}
          {r.articles.length > 0 && <span className="ap__arts"> ({r.articles.join(', ')})</span>}
        </p>
        <p className="ch__file">
          <Link to={dossierPath(r.dossier_id)}>{r.dossier_title}</Link>
          {r.act.names.length > 0 && <span className="ap__names"> ({r.act.names.join(', ')})</span>}
        </p>
        {r.provisions ? (
          <p className="ap__prov">
            <span className="ap__label">What applies:</span> {r.provisions}
          </p>
        ) : (
          r.kind === 'applies' &&
          (r.partial || r.further) && (
            <p className="ap__prov ap__prov--none">
              EUR-Lex records the date, not which provisions apply from it: the <ExtLink href={r.act.url}>act’s text</ExtLink> says.
            </p>
          )
        )}
        {r.exceptions && <p className="ap__prov">{r.exceptions}</p>}
        <Where w={r.where} />
      </div>
      <p className="ch__meta dot-list">
        <span>{r.act.label}</span>
        {r.topics.length > 0 && <span>{r.topics.map(topicLabel).join(', ')}</span>}
        <span>
          Source: <ExtLink href={r.source.url}>{r.source.label || 'EUR-Lex'}</ExtLink>
        </span>
        {checked ? (
          checked.eurlex ? (
            <span>Checked against the act’s text</span>
          ) : (
            <span>
              Date set by the act’s text; EUR-Lex records another or none (
              <Link to={`${dossierPath(r.dossier_id)}#when-it-applies`}>the file’s page says why</Link>)
            </span>
          )
        ) : (
          <span>Date as EUR-Lex records it</span>
        )}
      </p>
    </li>
  );
}
