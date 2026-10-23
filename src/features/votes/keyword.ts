/**
 * Keyword matching for the votes list. Words are matched whole (accent- and case-insensitive, singular or
 * plural), so "gaza" no longer matches a rapporteur called Pagazaurtundúa. A vote linked to a legislative
 * file also matches when the site search finds that file, so its common names work: "AI Act" finds the
 * votes on the Artificial Intelligence Act.
 */
import type { EpVoteSummary } from '../../types/data';
import { dossierScores, hasWord, keywordTokens, wordSet, type SearchEngine } from '../../lib/search';

export function voteHaystacks(votes: EpVoteSummary[]): Map<string, Set<string>> {
  const m = new Map<string, Set<string>>();
  for (const v of votes) m.set(v.id, wordSet(v.display_title, v.title, v.dossier_ref, v.id));
  return m;
}

/**
 * Ids of the votes matching `q`, or null when the query has no words. If nothing matches whole words,
 * words that start with what was typed count too ("artific" -> "artificial"), as on the search page.
 */
export function matchVotes(
  votes: EpVoteSummary[],
  haystacks: Map<string, Set<string>>,
  q: string,
  engine: SearchEngine | null,
): Set<string> | null {
  const tokens = keywordTokens(q);
  if (!tokens.length) return null;
  const pass = (prefix: boolean, viaFiles: Map<string, number>) => {
    const out = new Set<string>();
    for (const v of votes) {
      const words = haystacks.get(v.id);
      if ((words && tokens.every((t) => hasWord(words, t, prefix))) || (v.dossier_id && viaFiles.has(v.dossier_id))) {
        out.add(v.id);
      }
    }
    return out;
  };
  const none = new Map<string, number>();
  const exact = pass(false, engine ? dossierScores(engine, q, { wholeWords: true }) : none);
  return exact.size ? exact : pass(true, engine ? dossierScores(engine, q) : none);
}
