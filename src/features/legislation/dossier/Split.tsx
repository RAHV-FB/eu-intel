import { Link } from 'react-router-dom';
import type { DossierDetail } from '../../../types/data';
import { dossierPath } from '../labels';

/** The separate files a split proposal became (related "Split into"), e.g. 2016/0224 -> 2016/0224A and 2016/0224B. */
export function splitParts(d: DossierDetail) {
  return d.related.filter((r) => r.relation === 'Split into');
}

/** "<title A> and <title B>", each linked to its file (long titles shortened). */
export function SplitLinks({ parts }: { parts: DossierDetail['related'] }) {
  return (
    <>
      {parts.map((r, i) => (
        <span key={r.id}>
          {i > 0 && (i === parts.length - 1 ? ' and ' : ', ')}
          <Link to={dossierPath(r.id)}>{r.title.length > 80 ? `${r.title.slice(0, 78).replace(/\s+\S*$/, '')}…` : r.title}</Link>
        </span>
      ))}
    </>
  );
}
