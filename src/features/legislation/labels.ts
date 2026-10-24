/**
 * Plain-language labels and small helpers for legislative files (dossiers).
 * Used by the legislation explorer, the dossier page, the homepage and the watchlist.
 */
import { useEffect } from 'react';
import { NotFoundError, useData } from '../../lib/data';
import { institutionLabel } from '../../components/ui';
import type { DossierSummary, LegalInstrument, LifecycleStage, Topic, TranspositionStatus } from '../../types/data';

export const SITE_TITLE = 'EU Legislative Intelligence';

/** The longest page title in the tab, the history and the route announcement (the heading keeps the full title). */
export const TITLE_MAX = 120;

/**
 * A title cut at a word boundary, with "…", to at most `max` characters. scripts/prerender-routes.mjs applies the same
 * rule to the (already shortened) title in dossiers/index.json, so a page's title is the same before and after it loads:
 * the cut of the full title and of its 180-character index form are the same string (src/features/legislation/titles.test.ts).
 */
export function shortTitle(title: string, max = TITLE_MAX): string {
  if (title.length <= max) return title;
  const head = title.slice(0, max);
  const space = head.lastIndexOf(' ');
  const cut = space > 0 ? head.slice(0, space) : title.slice(0, max - 1);
  return `${cut.replace(/[\s,;:(]+$/, '')}…`;
}

/** "<title> (<qualifier>) – EU Legislative Intelligence", or just the site name: the whole text of document.title. */
export function documentTitle(title: string | null | undefined, qualifier?: string | null): string {
  return title ? `${shortTitle(title)}${qualifier ? ` (${qualifier})` : ''} – ${SITE_TITLE}` : SITE_TITLE;
}

/**
 * Sets document.title (see documentTitle). The qualifier tells apart pages of the same title: a file's procedure reference,
 * the date of a vote.
 */
export function useDocumentTitle(title: string | null | undefined, qualifier?: string | null) {
  useEffect(() => {
    document.title = documentTitle(title, qualifier);
  }, [title, qualifier]);
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
  // files with no stage of their own (each row's badge says which): a proposal split into separate files, a report of
  // Parliament (not a legislative act), a procedure completed whose final act is not linked, or one whose stage the
  // records do not show (pipeline/build.py classify, pipeline/analysis/status.py)
  unknown: 'Other (split files, Parliament reports, final act or stage not recorded)',
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
  // not "ended": a rejection at first reading leaves the file awaiting the Council's first-reading position
  ended: { label: 'Withdrawn, rejected or lapsed', stages: ['withdrawn', 'rejected', 'lapsed'] },
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

/** A topic as the pages use it to label a filter, a chip or a tag. */
export type TopicLabel = Pick<Topic, 'slug' | 'label'> & Partial<Pick<Topic, 'description' | 'count'>>;

/**
 * The topics' labels as topics.json gives them (data/curated/topics.yaml), shown when that file cannot be loaded, so that a
 * topic filter is not empty and tags do not read "tech". titles.test.ts compares them with the built data.
 */
export const TOPIC_FALLBACK: TopicLabel[] = [
  { slug: 'tech', label: 'Technology & AI' },
  { slug: 'economy', label: 'Economy & Trade' },
  { slug: 'environment', label: 'Environment & Energy' },
  { slug: 'migration', label: 'Migration & Borders' },
  { slug: 'agriculture', label: 'Agriculture & Food' },
  { slug: 'rights', label: 'Rights & Justice' },
  { slug: 'security', label: 'Security & Defence' },
  { slug: 'transport', label: 'Transport' },
  { slug: 'social', label: 'Employment & Social Policy' },
  { slug: 'health', label: 'Health & Consumers' },
];

/** The topics from topics.json; `failed` when that file could not be loaded (the labels are then the fallback above). */
export function useTopics() {
  const state = useData<Topic[]>('topics.json');
  const failed = !!state.error;
  return { ...state, failed, topics: (state.data ?? (failed ? TOPIC_FALLBACK : [])) as TopicLabel[] };
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

/** Steps whose date the act itself sets (entry into force, application, transposition dates): EUR-Lex records them,
 * it does not take them, so no institution is named after their title. */
const ACT_DATED_KINDS: ReadonlySet<string> = new Set(['entry_into_force', 'application', 'transposition_deadline', 'transposition_application']);

/** Institution label to append after an event title, or '' when the title already names it or the step is dated in
 * the act (`kind`). */
export function institutionSuffix(title: string, institution: string, kind?: string): string {
  if (kind && ACT_DATED_KINDS.has(kind)) return '';
  const label = institutionLabel(institution);
  const t = title.toLowerCase();
  const named = institution === 'EP and Council' ? t.includes('parliament and council') : false;
  return named || t.includes(label.toLowerCase()) || t.includes(institution.toLowerCase()) ? '' : label;
}
