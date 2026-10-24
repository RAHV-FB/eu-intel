import { Link } from 'react-router-dom';
import type { DossierDetail } from '../../../types/data';
import { dossierPath } from '../labels';

/** The separate files a split proposal became (related "Split into"), e.g. 2016/0224 -> 2016/0224A and 2016/0224B. */
export function splitParts(d: DossierDetail) {
  return d.related.filter((r) => r.relation === 'Split into');
}

/** Id of the list of a split proposal's separate files (SplitParts), which the page's other sections point to. */
export const SPLIT_PARTS_ID = 'split-parts';

/**
 * The separate files, listed once on the page: each with its reference, its title (linked to its page) and its status.
 * The parts' titles can be the same but for their last words ("… - part I", "… - part II"), so each link leads with
 * its reference.
 */
export function SplitParts({ parts }: { parts: DossierDetail['related'] }) {
  return (
    <ul className="dz-parts" id={SPLIT_PARTS_ID}>
      {parts.map((r) => (
        <li key={r.id}>
          <Link to={dossierPath(r.id)}>
            {r.ref && <span className="dz-parts__ref">{r.ref}</span>} <span className="dz-parts__title">{r.title}</span>
          </Link>
          {r.status_label && <span className="dz-parts__status">{r.status_label}</span>}
        </li>
      ))}
    </ul>
  );
}

/** A section of a split proposal's page: what each separate file shows instead, pointing to the list of them. */
export function SplitNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="dz-none">
      This proposal was split: {children}. <a href={`#${SPLIT_PARTS_ID}`}>See the separate files</a>.
    </p>
  );
}
