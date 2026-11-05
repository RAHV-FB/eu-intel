/**
 * A file's latest recorded step as lists name it ("Council adopted the act · 26 Oct 2026"), on the reader's date. The
 * build names the step recorded on `last_event` (`last_step`) and lists the steps dated in the law just after it
 * (`steps_ahead`: an entry into force, an application or transposition date); one of those whose date has passed by the
 * reader's date is the latest step, as the file's own page counts it (latestDone, src/lib/format.ts eventOn).
 */
import type { EventKind, ISODate, LatestStep, StepAhead, TimelineEvent } from '../../types/data';
import { latestDone } from './dossier/Summary';

export interface NamedStep {
  date: ISODate;
  title: string;
  kind: EventKind;
}

/** What a list knows of a file's steps: a summary in dossiers/index.json, or the same fields from search.json. */
export interface StepsKnown {
  last_event?: ISODate | null;
  last_step?: LatestStep | null;
  steps_ahead?: StepAhead[] | null;
}

const asEvent = (s: NamedStep & { key: boolean }, state: TimelineEvent['state'], i: number): TimelineEvent => ({
  id: `step-${i}`,
  date: s.date,
  kind: s.kind,
  title: s.title,
  institution: 'EUR-Lex',
  state,
  key: s.key,
  docs: [],
});

/** The latest recorded step on `today`, or null when the file has none (or only a date without a named step). */
export function latestStepOn(d: StepsKnown, today: ISODate): NamedStep | null {
  const last = d.last_event && d.last_step ? { date: d.last_event, ...d.last_step } : null;
  const ahead = d.steps_ahead ?? [];
  if (!ahead.length) return last;
  const timeline = [
    ...(last ? [asEvent({ ...last, key: true }, 'done', 0)] : []),
    ...ahead.map((s, i) => asEvent(s, 'scheduled', i + 1)),
  ];
  const e = latestDone(timeline, today);
  return e ? { date: e.date, title: e.title, kind: e.kind } : null;
}

/** The date of the latest recorded step on `today` (for sorting and counting): that of latestStepOn, else `last_event`. */
export function latestDateOn(d: StepsKnown, today: ISODate): ISODate | null {
  return latestStepOn(d, today)?.date ?? d.last_event ?? null;
}

/** Rows as of `today`: a row whose step dated in the law has passed since the build gets that step as its latest
 * (`last_event`, `last_step`), so that lists, sorting and the file's page agree. Other rows are returned as they are, and
 * the list itself when no row changed. */
export function withLatestStepOn<T extends StepsKnown>(rows: T[], today: ISODate): T[] {
  let changed = false;
  const out = rows.map((d) => {
    if (!d.steps_ahead?.length) return d;
    const s = latestStepOn(d, today);
    if (!s || s.date === d.last_event) return d;
    changed = true;
    return { ...d, last_event: s.date, last_step: { title: s.title, kind: s.kind } };
  });
  return changed ? out : rows;
}
