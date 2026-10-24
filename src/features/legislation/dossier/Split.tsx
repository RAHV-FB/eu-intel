import { Link } from 'react-router-dom';
import type { DossierDetail } from '../../../types/data';
import { dossierPath } from '../labels';

/** The separate files a split proposal became (related "Split into"), e.g. 2016/0224 -> 2016/0224A and 2016/0224B. */
export function splitParts(d: DossierDetail) {
  return d.related.filter((r) => r.relation === 'Split into');
}

const shorten = (t: string) => (t.length > 80 ? `${t.slice(0, 78).replace(/\s+\S*$/, '')}…` : t);

/**
 * "<ref A> – <title A> (status) and <ref B> – <title B> (status)", each linked to its file. The parts' titles can
 * be the same but for their last words ("… - part I", "… - part II"), so each link leads with its reference.
 */
export function SplitLinks({ parts }: { parts: DossierDetail['related'] }) {
  return (
    <>
      {parts.map((r, i) => (
        <span key={r.id}>
          {i > 0 && (i === parts.length - 1 ? ' and ' : ', ')}
          <Link to={dossierPath(r.id)}>
            {r.ref && (
              <>
                <span className="ref">{r.ref}</span> –{' '}
              </>
            )}
            {shorten(r.title)}
          </Link>
          {r.status_label && <> ({r.status_label})</>}
        </span>
      ))}
    </>
  );
}
