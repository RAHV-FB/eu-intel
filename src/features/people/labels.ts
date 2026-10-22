import { useMemo } from 'react';
import type { GroupSummary } from '../../types/data';
import { useData } from '../../lib/data';
import { formatDate } from '../../lib/format';

/** European Parliament terms (direct elections since 1979, five-year terms). */
export const TERM_LABEL: Record<number, string> = {
  1: '1st term (1979–1984)',
  2: '2nd term (1984–1989)',
  3: '3rd term (1989–1994)',
  4: '4th term (1994–1999)',
  5: '5th term (1999–2004)',
  6: '6th term (2004–2009)',
  7: '7th term (2009–2014)',
  8: '8th term (2014–2019)',
  9: '9th term (2019–2024)',
  10: '10th term (2024–2029)',
};

/** A term is fully covered by our dataset when it holds at least this many MEPs (Parliament has 705–751 seats). */
export const FULL_TERM_MIN_MEPS = 600;

export function termLabel(t: number): string {
  return TERM_LABEL[t] ?? `Term ${t}`;
}

/** Short form: "9th (2019–2024)". */
export function termShort(t: number): string {
  return termLabel(t).replace(' term', '');
}

const ROLE_LABEL: Record<string, string> = {
  MEMBER: 'Member',
  MEMBER_SUBSTITUTE: 'Substitute member',
  SUBSTITUTE: 'Substitute member',
  CHAIR: 'Chair',
  CHAIR_VICE: 'Vice-Chair',
  CHAIR_CO: 'Co-Chair',
  PRESIDENT: 'President',
  PRESIDENT_VICE: 'Vice-President',
  PRESIDENT_CO: 'Co-President',
  MEMBER_BUREAU: 'Member of the Bureau',
  TREASURER: 'Treasurer',
  TREASURER_CO: 'Co-Treasurer',
  QUAESTOR: 'Quaestor',
};

/** Official EP role codes ("CHAIR_VICE") → readable labels; passes through already-readable text. */
export function roleLabel(role: string | null | undefined): string | null {
  if (!role) return null;
  if (ROLE_LABEL[role]) return ROLE_LABEL[role];
  if (/^[A-Z_]+$/.test(role)) {
    const s = role.toLowerCase().replace(/_/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  return role;
}

export function periodText(from?: string | null, to?: string | null): string {
  if (!from && !to) return 'Dates not recorded';
  if (from && !to) return `Since ${formatDate(from)}`;
  if (!from && to) return `Until ${formatDate(to)}`;
  return `${formatDate(from)} – ${formatDate(to)}`;
}

/** Group lookup (slug → summary) from people/groups.json. */
export function useGroups() {
  const state = useData<GroupSummary[]>('people/groups.json');
  const byId = useMemo(() => new Map((state.data ?? []).map((g) => [g.id, g])), [state.data]);
  return { ...state, byId };
}

export const EP_MEP_URL = (id: string) => `https://www.europarl.europa.eu/meps/en/${encodeURIComponent(id)}`;
