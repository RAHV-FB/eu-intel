import { Link } from 'react-router-dom';
import { ExtLink, institutionLabel } from '../../components/ui';
import { formatDate } from '../../lib/format';
import { dossierPath } from '../legislation/labels';
import { KIND_LABEL, type Change } from './changes';

/**
 * One change: its date, what happened (and the status it gave the file), the file it happened on (linked to its page),
 * and the official records it cites. `fileTitle`: the file's title from dossiers/index.json, when loaded (else the one
 * the headline gives); `compact`: the home page's strip, without the kind and the day it was recorded, and its records
 * named by institution.
 */
export function ChangeItem({ c, fileTitle, compact = false }: { c: Change; fileTitle?: string | null; compact?: boolean }) {
  const title = fileTitle ?? c.fileTitle;
  const what = c.event ?? (c.status ? null : c.headline);
  const vote = c.voteId ? `/votes/${encodeURIComponent(c.voteId)}` : null;
  return (
    <li className={`ch${compact ? ' ch--compact' : ''}`}>
      <div className="ch__date">
        <time dateTime={c.date}>{formatDate(c.date)}</time>
      </div>
      <div className="ch__body">
        {what && (
          <p className="ch__event">
            {/* a vote on no file of the dataset: its headline leads to the vote's page */}
            {!c.dossierId && vote ? <Link to={vote}>{what}</Link> : what}
          </p>
        )}
        {c.status && (
          <p className="ch__status">
            Status now “{c.status.now}”{c.status.was && <span className="ch__was"> (previously “{c.status.was}”)</span>}
          </p>
        )}
        {c.dossierId && (
          <p className="ch__file">
            <Link to={dossierPath(c.dossierId)}>{title ?? c.dossierId}</Link>
            {vote && !compact && (
              <>
                {' '}
                · <Link to={vote}>the vote</Link>
              </>
            )}
          </p>
        )}
      </div>
      <p className="ch__meta dot-list">
        {!compact && <span>{c.kinds.map((k) => KIND_LABEL[k]).join(' · ')}</span>}
        {c.sources.length > 0 && (
          <span>
            {c.sources.length > 1 ? 'Sources' : 'Source'}:{' '}
            {c.sources.map((s, i) => (
              <span key={s.url}>
                {i > 0 && ', '}
                <ExtLink href={s.url}>{(!compact && s.label) || institutionLabel(s.institution)}</ExtLink>
              </span>
            ))}
          </span>
        )}
        {!compact && c.detectedAt && c.detectedAt.slice(0, 10) !== c.date && <span>Recorded {formatDate(c.detectedAt)}</span>}
      </p>
    </li>
  );
}
