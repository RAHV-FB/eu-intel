/**
 * Plain-language labels and small helpers for legislative files (dossiers).
 * Used by the legislation explorer, the dossier page, the homepage and the watchlist.
 */
import { useEffect } from 'react';
import { NotFoundError } from '../../lib/data';
import { institutionLabel } from '../../components/ui';
import type { DossierSummary, LegalInstrument, LifecycleStage, TranspositionStatus } from '../../types/data';

export const SITE_TITLE = 'EU Legislative Intelligence';

/** Sets document.title to "<title> – EU Legislative Intelligence" (or just the site name). */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} – ${SITE_TITLE}` : SITE_TITLE;
  }, [title]);
}

/** Short filter labels for each lifecycle stage (the badge text itself comes from the data). */
export const STAGE_LABEL: Record<LifecycleStage, string> = {
  proposed: 'Proposed – under examination',
  parliament_position: 'Parliament has adopted its position',
  negotiations: 'In negotiations',
  provisional_agreement: 'Provisional agreement reached',
  adopted: 'Adopted – awaiting publication',
  published: 'Published – not yet in force',
  in_force: 'In force',
  takes_effect_on_notification: 'Takes effect on notification (date not recorded)',
  no_longer_in_force: 'No longer in force (repealed or expired)',
  withdrawn: 'Withdrawn',
  rejected: 'Rejected',
  lapsed: 'Lapsed',
  unknown: 'Status not determinable',
};

export const STAGE_ORDER: LifecycleStage[] = [
  'proposed',
  'parliament_position',
  'negotiations',
  'provisional_agreement',
  'adopted',
  'published',
  'in_force',
  'takes_effect_on_notification',
  'no_longer_in_force',
  'withdrawn',
  'rejected',
  'lapsed',
  'unknown',
];

/** Groups of stages offered as quick filters. */
export const STAGE_GROUPS: Record<string, { label: string; stages: LifecycleStage[] }> = {
  active: {
    label: 'Still being decided (any stage)',
    stages: ['proposed', 'parliament_position', 'negotiations', 'provisional_agreement'],
  },
  law: {
    label: 'Adopted (any stage)',
    stages: ['adopted', 'published', 'in_force', 'takes_effect_on_notification', 'no_longer_in_force'],
  },
  ended: { label: 'Ended without becoming law', stages: ['withdrawn', 'rejected', 'lapsed'] },
};

export const ACTIVE_STAGES = new Set<LifecycleStage>(STAGE_GROUPS.active.stages);
export const ADOPTED_STAGES = new Set<LifecycleStage>(STAGE_GROUPS.law.stages);
export const ENDED_STAGES = new Set<LifecycleStage>(STAGE_GROUPS.ended.stages);

/** Resolve a `stage` URL value (a single stage or a group key) to the set of matching stages. */
export function stagesFor(value: string | null): Set<LifecycleStage> | null {
  if (!value) return null;
  if (STAGE_GROUPS[value]) return new Set(STAGE_GROUPS[value].stages);
  if ((STAGE_ORDER as string[]).includes(value)) return new Set([value as LifecycleStage]);
  return null;
}

export function stageFilterLabel(value: string): string {
  return STAGE_GROUPS[value]?.label ?? STAGE_LABEL[value as LifecycleStage] ?? value;
}

export const INSTRUMENT_LABEL: Record<LegalInstrument, string> = {
  regulation: 'Regulation',
  directive: 'Directive',
  decision: 'Decision',
  recommendation: 'Recommendation',
  other: 'Other act',
};

export const TRANSPOSITION_LABEL: Record<TranspositionStatus, string> = {
  measures_notified: 'Measures notified',
  none_found: 'No measures found in the available dataset',
  deadline_not_reached: 'Deadline not yet reached',
  no_deadline: 'No transposition deadline recorded',
  not_participating: 'Not bound (did not take part in adoption)',
  not_required: 'Not required by the directive',
  unavailable: 'Data unavailable',
};

export function dossierPath(id: string): string {
  return `/legislation/${encodeURIComponent(id)}`;
}

/** Proposal year: from the proposal date, else from the procedure reference ("2021/0106(COD)"). */
export function dossierYear(d: Pick<DossierSummary, 'started' | 'ref'>): number | null {
  const y = Number((d.started ?? d.ref ?? '').slice(0, 4));
  return Number.isFinite(y) && y > 1950 ? y : null;
}

/** Official titles are often ALL CAPS or very long; keep them readable without changing words. */
export function isSameTitle(a: string | null | undefined, b: string | null | undefined): boolean {
  const n = (s: string | null | undefined) => (s ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
  return n(a) === n(b);
}

export const EURLEX_CELEX = (celex: string) =>
  `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:${encodeURIComponent(celex)}`;

/**
 * A missing data file is a 404 on GitHub Pages, but a dev/preview server may answer with the SPA's HTML
 * (which fails JSON parsing). Treat both as "not in our dataset".
 */
export function isMissing(e: unknown): boolean {
  return e instanceof NotFoundError || e instanceof SyntaxError;
}

/** Institution label to append after an event title, or '' when the title already names it. */
export function institutionSuffix(title: string, institution: string): string {
  const label = institutionLabel(institution);
  const t = title.toLowerCase();
  const named = institution === 'EP and Council' ? t.includes('parliament and council') : false;
  return named || t.includes(label.toLowerCase()) || t.includes(institution.toLowerCase()) ? '' : label;
}
