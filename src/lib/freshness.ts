/**
 * How fresh the data is on the reader's date. The data is rebuilt weekly but read for a week or more, so whether a
 * source is up to date is judged here against the reader's clock (as src/lib/format.ts does for dated wording), from
 * what the build states in meta.json: each source's last successful retrieval and its threshold
 * (pipeline/freshness.py). No threshold is set here.
 */
import type { ISODateTime, Meta, SourceStatusInfo } from '../types/data';
import { formatDate } from './format';

const DAY_MS = 86_400_000;

/** Days from a retrieval to `now` (with a fraction, as pipeline/freshness.py counts them); null if there is none. */
export function ageInDays(at: ISODateTime | null | undefined, now: Date | number): number | null {
  if (!at) return null;
  const t = Date.parse(at);
  return Number.isNaN(t) ? null : (+now - t) / DAY_MS;
}

/** Whether a source is not up to date on `now`: its last successful retrieval is older than its threshold, or it has
 * none. A source without a threshold in the data is not judged. */
export function isStale(s: SourceStatusInfo, now: Date | number): boolean {
  if (s.stale_after_days == null) return false;
  const age = ageInDays(s.fetched_at, now);
  return age === null || age > s.stale_after_days;
}

export interface Freshness {
  /** The headline date: the oldest last successful retrieval of the core sources (statuses, votes and acts). */
  coreAt: ISODateTime | null;
  /** The sources not up to date on the reader's date, in the order of meta.json. */
  stale: SourceStatusInfo[];
  /** Whether one of them is a core source (then the headline date itself is old). */
  coreStale: boolean;
}

export function freshness(meta: Meta, now: Date | number): Freshness {
  const stale = meta.sources.filter((s) => isStale(s, now));
  return { coreAt: meta.core_data_at ?? null, stale, coreStale: stale.some((s) => s.core) };
}

/** "a", "a and b", "a, b and c" */
const joinNames = (names: string[]) =>
  names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0];

/** "Not up to date: Legislative Train (last retrieved 22 Oct 2026)", the sources last retrieved on the same day named
 * together ("Parliament votes and Council votes (last retrieved 2 Nov 2026); …"); '' when every source is up to date. */
export function staleNote(f: Freshness): string {
  if (!f.stale.length) return '';
  const byDay = new Map<string, string[]>();
  for (const s of f.stale) {
    const when = s.fetched_at ? `last retrieved ${formatDate(s.fetched_at)}` : 'never retrieved';
    byDay.set(when, [...(byDay.get(when) ?? []), s.short_name || s.name]);
  }
  return `Not up to date: ${[...byDay].map(([when, names]) => `${joinNames(names)} (${when})`).join('; ')}`;
}

// ------------------------------------------------------------------ official classifications

/** A source's official classifications on the reader's date (the Legislative Train's "Blocked"). */
export interface Classifications {
  source: SourceStatusInfo;
  /** Our last successful retrieval of them. */
  retrievedAt: ISODateTime | null;
  /** Shown as current: retrieved, and at most `labels_expire_after_days` ago. */
  current: boolean;
  /** That limit, in days (null: the data sets none). */
  expireAfterDays: number | null;
}

/** The classifications of source `id` on `now`; null while meta.json is not loaded or does not list the source (then
 * nothing is shown as current). */
export function classifications(meta: Meta | undefined, now: Date | number, id = 'train'): Classifications | null {
  const source = meta?.sources.find((s) => s.id === id);
  if (!source) return null;
  const age = ageInDays(source.fetched_at, now);
  const limit = source.labels_expire_after_days ?? null;
  return {
    source,
    retrievedAt: source.fetched_at ?? null,
    current: age !== null && (limit === null || age <= limit),
    expireAfterDays: limit,
  };
}

/** Whether a file is shown as officially blocked: the Legislative Train says so, and that is still current. */
export function blockedNow(officiallyBlocked: boolean, train: Classifications | null): boolean {
  return officiallyBlocked && !!train?.current;
}

/** Rows (file summaries or details) with `officially_blocked` as shown on the reader's date: unless the Legislative
 * Train's classification is current (`blockedShown`, from `classifications`), no file is shown as blocked, so that
 * lists, filters, counts and sorting agree. */
export function asShownNow<T extends { officially_blocked: boolean }>(rows: T[], blockedShown: boolean): T[] {
  if (blockedShown || !rows.some((d) => d.officially_blocked)) return rows;
  return rows.map((d) => (d.officially_blocked ? { ...d, officially_blocked: false } : d));
}

/** "Legislative Train, as retrieved 22 Oct 2026" */
export function asRetrieved(c: Classifications, long = false): string {
  return `${c.source.short_name || c.source.name}, as retrieved ${c.retrievedAt ? formatDate(c.retrievedAt, long) : '(never retrieved)'}`;
}

/** Why the classifications are not shown: "our latest copy of the Legislative Train was retrieved on 22 Oct 2026,
 * more than 42 days ago" (or "has never been retrieved"). */
export function expiredReason(c: Classifications, long = false): string {
  const name = c.source.short_name || c.source.name;
  if (!c.retrievedAt) return `our copy of the ${name} has never been retrieved`;
  return `our latest copy of the ${name} was retrieved on ${formatDate(c.retrievedAt, long)}, more than ${c.expireAfterDays} days ago`;
}
