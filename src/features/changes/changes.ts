/**
 * "What changed": the items of activity.json as the What changed page and the home page's "This week in EU law" tell
 * them. A status change and the step that gave the status (the build pairs them: `step_id`, pipeline/analysis/changes.py)
 * are one change, as in the Atom feeds. Changes are grouped by the week in which our data refresh first recorded them
 * (`detected_at`); a step already in the records when recording began has no detection time, and is grouped by its own
 * date instead.
 */
import type { ActivityItem, ISODate, ISODateTime, SourceRef } from '../../types/data';

export type ActivityKind = ActivityItem['kind'];

export interface Change {
  id: string; // the item's id; a status change told with its step: the status change's
  date: ISODate; // the date of the step
  detectedAt: ISODateTime | null; // when our data refresh first recorded it (null: not tracked)
  week: ISODate; // the Monday of the week it was recorded in, or of its date when that was not tracked
  kinds: ActivityKind[];
  event: string | null; // what happened, without the file's title; null: the headline is read whole
  headline: string; // the item's own headline (a vote's, a Council vote's)
  fileTitle: string | null; // the file's title as the headline gives it (shortened), when it does
  status: { now: string; was: string | null } | null; // the status a status change gave the file
  dossierId: string | null;
  voteId: string | null;
  sources: SourceRef[]; // the official records the items cite
}

const DAY = 86_400_000;

/** The Monday of the week of a date (weeks run Monday to Sunday). */
export function mondayOf(d: ISODate): ISODate {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  const t = Date.UTC(y, m - 1, day);
  const offset = (new Date(t).getUTCDay() + 6) % 7;
  return new Date(t - offset * DAY).toISOString().slice(0, 10);
}

/** "2026-11-08" for the week of "2026-11-02". */
export function sundayOf(monday: ISODate): ISODate {
  const [y, m, day] = monday.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, day) + 6 * DAY).toISOString().slice(0, 10);
}

const STATUS = /status now “(.+?)”(?: \(previously “(.+?)”\))?$/;

/** The new and the previous status a status change names (its headline: "…: status now “X” (previously “Y”)"). */
export function statusOf(it: ActivityItem): Change['status'] {
  if (it.kind !== 'status_change') return null;
  const m = STATUS.exec(it.title);
  return m ? { now: m[1], was: m[2] ?? null } : null;
}

/** The file's title as an item's headline gives it (shortened): the headline before ": <event>", or after "New file: ";
 * null when the headline does not name the file that way. */
export function headlineFile(it: ActivityItem): string | null {
  const ev = it.event;
  if (!ev) return null;
  if (it.kind === 'new_dossier' && it.title.startsWith('New file: ')) return it.title.slice('New file: '.length);
  for (const e of [ev, ev[0].toLowerCase() + ev.slice(1)]) if (it.title.endsWith(`: ${e}`)) return it.title.slice(0, -(e.length + 2));
  return null;
}

function sourcesOf(...items: (ActivityItem | undefined)[]): SourceRef[] {
  const out: SourceRef[] = [];
  for (const it of items) if (it?.source?.url && !out.some((s) => s.url === it.source!.url)) out.push(it.source);
  return out;
}

/** The changes the items tell, newest first: a status change with the item of its step as one change. */
export function changesOf(items: ActivityItem[]): Change[] {
  const byId = new Map(items.map((it) => [it.id, it]));
  const told = new Set(items.flatMap((it) => (it.kind === 'status_change' && it.step_id && byId.has(it.step_id) ? [it.step_id] : [])));
  const out: Change[] = [];
  for (const it of items) {
    if (told.has(it.id)) continue;
    const step = it.kind === 'status_change' && it.step_id ? byId.get(it.step_id) : undefined;
    const status = statusOf(it);
    const detectedAt = it.detected_at ?? step?.detected_at ?? null;
    out.push({
      id: it.id,
      date: it.date,
      detectedAt,
      week: mondayOf(detectedAt ?? it.date),
      kinds: step ? [step.kind, it.kind] : [it.kind],
      // a status change alone says what it changed in its status line
      event: step ? (step.event ?? step.title) : it.kind === 'status_change' && status ? null : (it.event ?? null),
      headline: (step ?? it).title,
      fileTitle: headlineFile(step ?? it) ?? headlineFile(it),
      status,
      dossierId: it.dossier_id ?? null,
      voteId: (step ?? it).vote_id ?? null,
      sources: sourcesOf(it, step),
    });
  }
  return out.sort(
    (a, b) =>
      b.date.localeCompare(a.date) || (b.detectedAt ?? '').localeCompare(a.detectedAt ?? '') || a.id.localeCompare(b.id),
  );
}

// ------------------------------------------------------------------ filters

/** The kinds of change a reader can filter by (`?kind=`), with the activity kinds each covers and how a count of them
 * reads (one, several). */
export const CHANGE_KINDS: Record<string, { label: string; kinds: ActivityKind[]; count: [string, string] }> = {
  status: { label: 'Status changes', kinds: ['status_change'], count: ['status change', 'status changes'] },
  new: { label: 'New files', kinds: ['new_dossier'], count: ['new file', 'new files'] },
  step: { label: 'Procedural steps', kinds: ['milestone'], count: ['procedural step', 'procedural steps'] },
  publication: {
    label: 'Signature, publication and entry into force',
    kinds: ['publication'],
    count: ['signature, publication or entry into force', 'signatures, publications and entries into force'],
  },
  ep_vote: { label: 'Parliament votes', kinds: ['ep_vote'], count: ['Parliament vote', 'Parliament votes'] },
  council_vote: { label: 'Council votes', kinds: ['council_vote'], count: ['Council vote', 'Council votes'] },
  deadline: { label: 'Deadlines', kinds: ['deadline'], count: ['deadline', 'deadlines'] },
  implementation: { label: 'National implementation', kinds: ['implementation'], count: ['implementation step', 'implementation steps'] },
};

/** "3 status changes", "1 Parliament vote" */
export function countLabel(key: string, n: number): string {
  const k = CHANGE_KINDS[key];
  return `${n.toLocaleString('en-GB')} ${k ? k.count[n === 1 ? 0 : 1] : key}`;
}

export function kindKeys(c: Change): string[] {
  return Object.entries(CHANGE_KINDS)
    .filter(([, k]) => c.kinds.some((x) => k.kinds.includes(x)))
    .map(([key]) => key);
}

/** The label of a change's kind, for its row ("Status change · Procedural step"). */
export const KIND_LABEL: Record<ActivityKind, string> = {
  status_change: 'Status change',
  new_dossier: 'New file',
  milestone: 'Procedural step',
  publication: 'Signature, publication or entry into force',
  ep_vote: 'Parliament vote',
  council_vote: 'Council vote',
  deadline: 'Deadline',
  implementation: 'National implementation',
};

/** `?topic=none`: changes on files that no topic covers, and votes on texts that are not files of the dataset. */
export const OTHER = 'none';

/** The topics of a change: its file's (dossiers/index.json), or none. */
export type TopicsOf = (dossierId: string | null) => string[];

export function matches(c: Change, topicsOf: TopicsOf, topic: string | null, kind: string | null): boolean {
  if (kind && !kindKeys(c).includes(kind)) return false;
  if (!topic) return true;
  const ts = topicsOf(c.dossierId);
  return topic === OTHER ? ts.length === 0 : ts.includes(topic);
}

// ------------------------------------------------------------------ grouping

export interface WeekGroup {
  week: ISODate; // its Monday
  changes: Change[];
  tracked: number; // of them, recorded with a detection time
  topics: { slug: string; changes: Change[] }[]; // in the order of `order`, then OTHER; a change in each of its file's topics
}

/** Changes by week (newest first) and, within a week, by topic: a change is listed under each topic of its file, and
 * under OTHER when its file has none or it is on no file of the dataset. */
export function byWeek(changes: Change[], topicsOf: TopicsOf, order: string[]): WeekGroup[] {
  const weeks = new Map<ISODate, Change[]>();
  for (const c of changes) weeks.set(c.week, [...(weeks.get(c.week) ?? []), c]);
  return [...weeks.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([week, cs]) => {
      const topics = [...order, OTHER]
        .map((slug) => ({
          slug,
          changes: cs.filter((c) => {
            const ts = topicsOf(c.dossierId);
            return slug === OTHER ? !ts.some((t) => order.includes(t)) : ts.includes(slug);
          }),
        }))
        .filter((t) => t.changes.length > 0);
      return { week, changes: cs, tracked: cs.filter((c) => c.detectedAt).length, topics };
    });
}

// ------------------------------------------------------------------ the home page's strip

export interface Latest {
  changes: Change[]; // newest first
  /** The latest detection time (null when none is tracked: the changes are then the latest dated ones). */
  recordedAt: ISODateTime | null;
  /** The days of the detections in the window ("2026-11-02", "2026-11-05"). */
  days: ISODate[];
  /** The first day of the window. */
  from: ISODate;
  /** Whether the latest detection is at most `CURRENT_DAYS` old on the reader's date (then it is "this week"). */
  current: boolean;
}

export const WINDOW_DAYS = 7;
export const UNTRACKED_WINDOW_DAYS = 14;

const minusDays = (d: ISODate, n: number): ISODate => {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, day) - n * DAY).toISOString().slice(0, 10);
};

/** The changes of the last week of recording (the 7 days to the latest detection), or, when no detection is tracked,
 * the steps dated in the 14 days to the latest. `now`: the reader's clock. */
export function latestChanges(changes: Change[], now: Date | number): Latest {
  const recordedAt = changes.reduce<string | null>((m, c) => (c.detectedAt && (!m || c.detectedAt > m) ? c.detectedAt : m), null);
  if (recordedAt) {
    const from = minusDays(recordedAt, WINDOW_DAYS - 1);
    const sel = changes.filter((c) => c.detectedAt && c.detectedAt.slice(0, 10) >= from);
    const days = [...new Set(sel.map((c) => c.detectedAt!.slice(0, 10)))].sort();
    const age = +now - Date.parse(recordedAt);
    return { changes: sel, recordedAt, days, from, current: age >= -DAY && age <= WINDOW_DAYS * DAY };
  }
  const last = changes.reduce<string | null>((m, c) => (!m || c.date > m ? c.date : m), null);
  if (!last) return { changes: [], recordedAt: null, days: [], from: '', current: false };
  const from = minusDays(last, UNTRACKED_WINDOW_DAYS - 1);
  return { changes: changes.filter((c) => c.date >= from), recordedAt: null, days: [], from, current: false };
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Days as a list: "5 Nov 2026", "2 and 5 Nov 2026", "30 Oct and 2 Nov 2026", "29 Dec 2026 and 4 Jan 2027" (the month
 * and year said once where they are the same). */
export function formatDays(ds: ISODate[]): string {
  const parts = [...new Set(ds)].sort().map((d) => d.split('-').map(Number));
  const out = parts.map(([y, m, d], i) => {
    const next = parts[i + 1];
    if (!next) return `${d} ${MONTHS[m - 1]} ${y}`;
    if (next[0] !== y) return `${d} ${MONTHS[m - 1]} ${y}`;
    return next[1] !== m ? `${d} ${MONTHS[m - 1]}` : `${d}`;
  });
  return out.length < 2 ? (out[0] ?? '') : `${out.slice(0, -1).join(', ')} and ${out[out.length - 1]}`;
}

/** A span of days: "2–8 Nov 2026", "28 Sep – 4 Oct 2026", "29 Dec 2025 – 4 Jan 2026". */
export function formatRange(from: ISODate, to: ISODate): string {
  const [ya, ma, da] = from.split('-').map(Number);
  const [yb, mb, db] = to.split('-').map(Number);
  if (ya !== yb) return `${da} ${MONTHS[ma - 1]} ${ya} – ${db} ${MONTHS[mb - 1]} ${yb}`;
  if (ma !== mb) return `${da} ${MONTHS[ma - 1]} – ${db} ${MONTHS[mb - 1]} ${yb}`;
  return `${da}–${db} ${MONTHS[mb - 1]} ${yb}`;
}

/** Counts of the changes by kind of change, in the order of CHANGE_KINDS (a change counts once for each of its kinds). */
export function countByKind(changes: Change[]): { key: string; label: string; n: number }[] {
  return Object.entries(CHANGE_KINDS)
    .map(([key, k]) => ({ key, label: k.label, n: changes.filter((c) => kindKeys(c).includes(key)).length }))
    .filter((x) => x.n > 0);
}
