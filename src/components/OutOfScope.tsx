import type { CoverageScope } from '../types/data';
import { coversSentence, eurlexSearchUrl, notCovered } from '../lib/scope';
import { ExtLink } from './ui';

/**
 * For a search or a filter query that finds nothing: what the site covers, what it does not, and the same query on
 * EUR-Lex, the official database of EU law (a plain link: nothing is sent from this page). "glyphosate" finds nothing
 * here: the approvals of an active substance are implementing acts.
 */
export function OutOfScope({ q, scope }: { q: string; scope: CoverageScope | undefined }) {
  return (
    <div className="out-of-scope">
      <p>
        <strong>What this site covers:</strong> {coversSentence(scope)}
      </p>
      <p>It does not cover:</p>
      <ul>
        {notCovered(scope).map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      {q.trim() && (
        <p>
          <ExtLink href={eurlexSearchUrl(q)}>Search EUR-Lex for “{q.trim()}”</ExtLink>, the EU’s official database of legal acts,
          implementing and delegated acts included.
        </p>
      )}
    </div>
  );
}
