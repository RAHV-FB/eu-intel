/**
 * "When new rules apply" (/legislation/applies): the dates of applies.json (pipeline/analysis/applies.py) on the
 * reader's date. The data is rebuilt weekly and read for a week or more after, so which dates are ahead, and which
 * window holds them, is judged against the reader's clock, by the rule src/lib/format.ts applies to the dates a file's
 * page states: an entry into force, or a date from which rules apply, has come on its day; a transposition deadline
 * passes only once its day is over. These dates are fixed in law: they are not plans that can move (unlike the steps
 * the Council and Parliament schedule, src/features/legislation/dossier/ScheduledNext.tsx).
 */
import type { ApplyingRule, ISODate, RuleWhere } from '../../types/data';
import { DATA_BASE } from '../../lib/data';
import { aheadOn, countryName, stepTitle } from '../../lib/format';

/** The Member States, as applies.json lists them in `where` (the United Kingdom is not one). */
export const MEMBER_STATE_COUNT = 27;

export type WindowKey = '30' | '90' | '12m' | 'all' | 'past';

/** The windows a reader can choose (`?when=`), the default first in the address's absence. */
export const WINDOWS: { key: WindowKey; label: string; phrase: string }[] = [
  { key: '30', label: 'Next 30 days', phrase: 'in the next 30 days' },
  { key: '90', label: 'Next 90 days', phrase: 'in the next 90 days' },
  { key: '12m', label: 'Next 12 months', phrase: 'in the next 12 months' },
  { key: 'all', label: 'All dates ahead', phrase: 'ahead' },
  { key: 'past', label: 'Last 30 days', phrase: 'in the last 30 days' },
];
export const DEFAULT_WINDOW: WindowKey = '90';

export function windowKey(v: string | null): WindowKey {
  return WINDOWS.some((w) => w.key === v) ? (v as WindowKey) : DEFAULT_WINDOW;
}

const DAY = 86_400_000;
const utc = (d: ISODate) => {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  return Date.UTC(y, m - 1, day);
};

export function addDays(d: ISODate, n: number): ISODate {
  return new Date(utc(d) + n * DAY).toISOString().slice(0, 10);
}

/** The same day a year later; 28 February for 29 February. */
export function addYear(d: ISODate): ISODate {
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  const t = new Date(Date.UTC(y + 1, m - 1, day));
  return (t.getUTCMonth() === m - 1 ? t : new Date(Date.UTC(y + 1, m, 0))).toISOString().slice(0, 10);
}

/** Whether a row's date is still ahead on `today`: a transposition deadline until its day is over. */
export function isAhead(r: Pick<ApplyingRule, 'date' | 'kind'>, today: ISODate): boolean {
  return aheadOn(r.date, today, r.kind === 'transposition_deadline');
}

/** Whether a row's date falls in the window on `today`: ahead and within 30 or 90 days or 12 months, any date ahead,
 * or (`past`) come in the last 30 days. */
export function inWindow(r: Pick<ApplyingRule, 'date' | 'kind'>, w: WindowKey, today: ISODate): boolean {
  const ahead = isAhead(r, today);
  if (w === 'past') return !ahead && r.date >= addDays(today, -30);
  if (!ahead) return false;
  if (w === 'all') return true;
  return r.date <= (w === '12m' ? addYear(today) : addDays(today, Number(w)));
}

/** What happens on the date, in the tense of the reader's date: "Some provisions start to apply" while ahead, "Some
 * provisions started to apply" once it has come, a deadline "(passed)" once its day is over (format.ts stepTitle). */
export function headlineOn(r: Pick<ApplyingRule, 'date' | 'kind' | 'title'>, today: ISODate): string {
  return isAhead(r, today) ? r.title : stepTitle(r.title, true);
}

// ------------------------------------------------------------------ where

export type Participation = 'bound' | 'not_bound' | 'unknown';

export function participation(w: RuleWhere, code: string): Participation {
  if (w.bound.includes(code)) return 'bound';
  if (w.not_bound.some((x) => x.country === code)) return 'not_bound';
  return 'unknown';
}

/** A row for a Member State's view: the act binds it, or whether it does is not known (never one that does not). */
export function concerns(r: Pick<ApplyingRule, 'where'>, code: string): boolean {
  return participation(r.where, code) !== 'not_bound';
}

/** "a", "a and b", "a, b and c" */
export function joinNames(names: string[]): string {
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : (names[0] ?? '');
}

/** Where, in a line: "All 27 Member States" only when all 27 are bound; "26 Member States, not Denmark"; "25 Member
 * States; not known for Denmark and Ireland"; "Not recorded" when whom it binds is not in the data (a decision). */
export function whereLead(w: RuleWhere): string {
  const n = w.bound.length;
  if (n === MEMBER_STATE_COUNT && !w.not_bound.length && !w.unknown.length) return 'All 27 Member States';
  if (!n) return w.unknown.length ? 'Not recorded in our data' : 'No Member State';
  const count = n > 5 ? `${n} Member States` : joinNames(w.bound.map(countryName));
  const not = w.not_bound.length ? `, not ${joinNames(w.not_bound.map((x) => countryName(x.country)))}` : '';
  const unknown = w.unknown.length ? `; not known for ${joinNames(w.unknown.map(countryName))}` : '';
  return `${count}${not}${unknown}`;
}

/** Why some Member States are left out of "where" being known: the act's addressees, or no record of Denmark's and
 * Ireland's participation. */
export function unknownNote(w: RuleWhere): string | null {
  if (w.note) return w.note;
  if (!w.unknown.length) return null;
  const names = joinNames(w.unknown.map(countryName));
  return `Denmark and Ireland do not take part in some measures on freedom, security and justice (Protocols No 21 and 22 to the Treaties). No record in our data (a Council voting result with each country’s position, or a directive’s recitals) says whether ${names} took part in this one.`;
}

// ------------------------------------------------------------------ months

export interface MonthGroup {
  month: string; // "2026-12"
  rows: ApplyingRule[];
}

/** Rows by month, in the order given (applies.json lists them by date); the latest first for `newestFirst`. */
export function byMonth(rows: ApplyingRule[], newestFirst = false): MonthGroup[] {
  const groups: MonthGroup[] = [];
  const ordered = newestFirst ? [...rows].sort((a, b) => b.date.localeCompare(a.date)) : rows;
  for (const r of ordered) {
    const month = r.date.slice(0, 7);
    const last = groups[groups.length - 1];
    if (last?.month === month) last.rows.push(r);
    else groups.push({ month, rows: [r] });
  }
  return groups;
}

const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/** "December 2026" */
export function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return `${MONTHS_LONG[m - 1]} ${y}`;
}

// ------------------------------------------------------------------ feeds

/** The feeds of a selection (pipeline/analysis/applies.py build_feeds): everything, a topic or a Member State. */
export function feedPath(scope: { topic?: string | null; country?: string | null }, ext: 'xml' | 'ics'): string {
  const key = scope.country ? `countries/${encodeURIComponent(scope.country)}` : scope.topic ? `topics/${encodeURIComponent(scope.topic)}` : 'all';
  return `${DATA_BASE}feeds/applies/${key}.${ext}`;
}
