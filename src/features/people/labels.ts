import { useMemo } from 'react';
import type { GroupSummary, PartyDetail } from '../../types/data';
import { useData } from '../../lib/data';
import { countryName, formatDate } from '../../lib/format';

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

/** "2019–2024 term", "2019–2024 and 2024–2029 terms": the years a record covers, as search subtitles name them. */
export function termYears(terms: number[] | null | undefined): string {
  const spans = [...(terms ?? [])].sort((x, y) => x - y).map((t) => `${1979 + 5 * (t - 1)}–${1984 + 5 * (t - 1)}`);
  return spans.length ? `${spans.join(' and ')} term${spans.length > 1 ? 's' : ''}` : '';
}

/** A party name compared as pipeline/build.py compares them (_norm_key) to find records of the same party:
 * without accents, case, punctuation or spacing ('"Visu Latvijai!"-"Tēvzemei…' and '"Visu Latvijai!" - "Tēvzemei…'). */
export function partyNameKey(label: string): string {
  return label
    .normalize('NFD')
    .replace(/\p{Mn}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

/** A party record's period: "2 Jul 2019 – 15 Jul 2024", or "from 16 Jul 2024" for a record still open. */
export function recordPeriod(start?: string | null, end?: string | null): string {
  if (!start) return 'dates not recorded';
  return end ? `${formatDate(start)} – ${formatDate(end)}` : `from ${formatDate(start)}`;
}

/** A party page's title (also written by scripts/prerender-routes.mjs): records of the same party in other terms
 * share its name, so the title names the term, and the period when another record of that name covers the same
 * term (Azione 6103 and 6478, both 2019–2024). */
export function partyRecordTitle(p: Pick<PartyDetail, 'label' | 'country' | 'terms' | 'start' | 'end' | 'same_name'>): string {
  const term = termYears(p.terms);
  const others = p.same_name ?? [];
  if (!others.length || !term) return `${p.label} (${countryName(p.country)})`;
  const sameTerm = others.some((r) => termYears(r.terms) === term);
  return `${p.label} (${countryName(p.country)}, ${term}${sameTerm ? `, ${recordPeriod(p.start, p.end)}` : ''})`;
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

/** Rapporteur roles on a legislative file (Rapporteur.role in the snapshot). */
const RAPPORTEUR_ROLE_LABEL: Record<string, string> = {
  rapporteur: 'Rapporteur',
  shadow: 'Shadow rapporteur',
  opinion_rapporteur: 'Rapporteur for an opinion',
  shadow_opinion: 'Shadow rapporteur for an opinion',
};

/** "Rapporteur for an opinion (ENVI)": the role in plain words, with the committee it was held in when recorded;
 * "Former rapporteur (TRAN)" for an appointment of an earlier parliamentary term (Rapporteur.former). */
export function rapporteurRoleLabel(role: string, committee?: string | null, former?: boolean): string {
  const base = RAPPORTEUR_ROLE_LABEL[role] ?? roleLabel(role) ?? role;
  const label = former ? `Former ${base.charAt(0).toLowerCase()}${base.slice(1)}` : base;
  return committee ? `${label} (${committee})` : label;
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
