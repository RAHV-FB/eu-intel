/**
 * The implementation tracker (/legislation/transposition, transposition.json): the directives whose transposition
 * deadline falls in its window on the reader's date, and where each Member State stands on them. Everything here is
 * judged on the reader's date (`today`, from `todayISO()`), as src/lib/freshness.ts judges a source's age: the window,
 * whether a deadline has passed, and each Member State's status (src/lib/deadline.ts statusOn).
 *
 * Nothing here ranks or scores a Member State: a directive's Member States are counted by status, the bound ones only,
 * and the opt-outs and exemptions are named apart; no count is added up across directives or Member States.
 */
import type { ISODate, TrackedDirective, TranspositionStatus, TranspositionTracker } from '../../types/data';
import { addMonths, deadlinePassed, statusOn } from '../../lib/deadline';

export type When = 'passed' | 'ahead';

/** The window on `today`: the first and last deadline listed. */
export function windowOn(t: Pick<TranspositionTracker, 'window'>, today: ISODate): { from: ISODate; to: ISODate } {
  return { from: addMonths(today, -12 * t.window.years_back), to: addMonths(today, t.window.months_ahead) };
}

/** Whether the list may lack directives of the window's far end: read more than the month the build adds to it after
 * the build (pipeline/analysis/tracker.py MARGIN_DAYS). */
export function builtTooLongAgo(t: Pick<TranspositionTracker, 'built_on'>, today: ISODate): boolean {
  const limit = new Date(Date.parse(`${t.built_on}T00:00:00Z`) + 31 * 86_400_000).toISOString().slice(0, 10);
  return today > limit;
}

/** The directives in the window on `today`, each with its Member States' statuses as on `today`. */
export function directivesOn(t: TranspositionTracker, today: ISODate): TrackedDirective[] {
  const { from, to } = windowOn(t, today);
  return t.directives
    .filter((d) => d.deadline >= from && d.deadline <= to)
    .map((d) => ({ ...d, countries: d.countries.map((c) => ({ ...c, status: statusOn(c.status, d.first_deadline ?? d.deadline, today) })) }));
}

/** The order in which a directive's bound Member States are counted (as on its own page). */
export const BOUND_ORDER: TranspositionStatus[] = ['measures_notified', 'none_found', 'deadline_not_reached', 'no_deadline', 'unavailable'];

export interface StatusCounts {
  /** The Member States the directive binds as far as the records show, by status, in BOUND_ORDER; none at 0. */
  bound: [TranspositionStatus, number][];
  /** Recorded as not taking part in its adoption (Treaty opt-outs): not bound. */
  notBound: string[];
  /** Exempted or not addressed by the directive's own text. */
  exempt: string[];
  /** Denmark or Ireland without measures, where no record says whether the directive binds it: not counted as bound. */
  unknown: string[];
  /** Whether national measures were queried for the directive (else every row is "Data unavailable"). */
  covered: boolean;
}

/** A directive's Member States by status: the bound ones counted, the others named. */
export function statusCounts(d: TrackedDirective): StatusCounts {
  const counts = new Map<TranspositionStatus, number>();
  const out: StatusCounts = { bound: [], notBound: [], exempt: [], unknown: [], covered: false };
  for (const c of d.countries) {
    if (c.status !== 'unavailable') out.covered = true;
    if (c.status === 'not_participating') out.notBound.push(c.country);
    else if (c.status === 'not_required') out.exempt.push(c.country);
    else if (c.participation_unknown) out.unknown.push(c.country);
    else counts.set(c.status, (counts.get(c.status) ?? 0) + 1);
  }
  out.bound = BOUND_ORDER.filter((s) => counts.get(s)).map((s) => [s, counts.get(s)!]);
  return out;
}

/** The Commission's open cases on the directive for not notifying transposition measures (one per Member State). */
export function openNonCommunication(d: TrackedDirective): number {
  return d.countries.reduce((n, c) => n + (c.cases ?? []).filter((k) => k.non_communication).length, 0);
}

export interface Filters {
  topic: string | null;
  when: When | null;
}

export function matches(d: TrackedDirective, f: Filters, today: ISODate): boolean {
  if (f.topic && !d.topics.includes(f.topic)) return false;
  if (f.when === 'passed' && !deadlinePassed(d.deadline, today)) return false;
  if (f.when === 'ahead' && deadlinePassed(d.deadline, today)) return false;
  return true;
}

/** The two lists the page shows: deadlines still ahead, the soonest first; deadlines passed, the latest first. */
export function split(ds: TrackedDirective[], today: ISODate): { ahead: TrackedDirective[]; passed: TrackedDirective[] } {
  const ahead = ds.filter((d) => !deadlinePassed(d.deadline, today)).sort((a, b) => a.deadline.localeCompare(b.deadline) || a.celex.localeCompare(b.celex));
  const passed = ds.filter((d) => deadlinePassed(d.deadline, today)).sort((a, b) => b.deadline.localeCompare(a.deadline) || a.celex.localeCompare(b.celex));
  return { ahead, passed };
}
