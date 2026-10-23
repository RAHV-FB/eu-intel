/**
 * Plain statements of what the dataset covers, built from meta.json `scope`, so lists and counts never read as
 * "all EU legislation" or "all votes". Each helper returns null when the figures it needs are missing.
 */
import type { CoverageScope } from '../types/data';
import { formatDate, formatNumber } from './format';

const TYPE_NAME: Record<string, string> = {
  COD: 'ordinary legislative',
  CNS: 'consultation',
  APP: 'consent',
};

function joinAnd(items: string[]): string {
  return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/**
 * "Covers files under the ordinary legislative, consultation and consent procedures (COD, CNS, APP) proposed from
 * 2014 onwards, …". `short` gives a one-line version for list pages.
 */
export function legislationScope(scope: CoverageScope | undefined, short = false): string | null {
  if (!scope?.procedure_types.length || !scope.procedures_from_year) return null;
  const names = joinAnd(scope.procedure_types.map((t) => TYPE_NAME[t] ?? t));
  const actsYear = scope.acts_from ? Number(scope.acts_from.slice(0, 4)) : null;
  if (short)
    return (
      `Covers legislative procedures (${scope.procedure_types.join(', ')}) proposed from ${scope.procedures_from_year}` +
      (actsYear ? ` and laws adopted under them since ${actsYear}` : '') +
      '; not delegated or implementing acts.'
    );
  return (
    `Covers files under the ${names} procedures (${scope.procedure_types.join(', ')}) proposed from ` +
    `${scope.procedures_from_year} onwards` +
    (actsYear ? `, and laws adopted under these procedures since ${actsYear}` : '') +
    '. Not included: delegated and implementing acts, non-legislative files' +
    (actsYear ? ` and laws adopted before ${actsYear}` : '') +
    '.'
  );
}

/** "July 2019" — the first month with a Parliament vote in the dataset. */
export function votesSince(scope: CoverageScope | undefined): string | null {
  return scope?.ep_votes_from ? formatDate(scope.ep_votes_from.slice(0, 7), true) : null;
}

/** "18 July 2019 to 22 October 2026" */
export function votesPeriod(scope: CoverageScope | undefined): string | null {
  if (!scope?.ep_votes_from || !scope.ep_votes_to) return null;
  return `${formatDate(scope.ep_votes_from, true)} to ${formatDate(scope.ep_votes_to, true)}`;
}

/** Which roll-call votes carry individual MEP results, for MEP and group pages. */
export function ballotScope(scope: CoverageScope | undefined, withBallots: number | undefined): string {
  const since = scope?.ep_votes_from ? ` from ${formatDate(scope.ep_votes_from, true)} onwards` : '';
  const share =
    scope?.ep_roll_call_votes && withBallots
      ? `: ${formatNumber(withBallots)} of the ${formatNumber(scope.ep_roll_call_votes)} roll-call votes in the Parliament data we use`
      : '';
  return (
    `Only roll-call votes on whole texts (final votes on legislation, resolutions, motions and negotiating mandates)` +
    `${since} are included${share}. Votes on amendments and split or separate votes are not included.`
  );
}
