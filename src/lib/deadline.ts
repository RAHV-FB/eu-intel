/**
 * Time between a transposition deadline and the reader's date. The data is rebuilt daily but read for a week or more,
 * so, as src/lib/freshness.ts judges a source's age, nothing here uses the build's date: `today` is the reader's (an
 * ISO date from their clock, `todayISO()`), injected so that tests can move it. A deadline (measures due "by" that
 * date) has passed only once its day is over (src/lib/format.ts `aheadOn`): on its day it is still ahead.
 */
import type { ISODate, TranspositionStatus } from '../types/data';
import { aheadOn, plural } from './format';

const DAY_MS = 86_400_000;

const parts = (d: ISODate) => d.slice(0, 10).split('-').map(Number) as [number, number, number];
const utc = (d: ISODate) => {
  const [y, m, day] = parts(d);
  return Date.UTC(y, m - 1, day);
};

/** The same day `months` later, or the month's last day when it has no such day (31 January + 1 month: 28 or 29
 * February). */
export function addMonths(d: ISODate, months: number): ISODate {
  const [y, m, day] = parts(d);
  const index = y * 12 + (m - 1) + months;
  const ty = Math.floor(index / 12);
  const tm = index - ty * 12; // 0-based
  const last = new Date(Date.UTC(ty, tm + 1, 0)).getUTCDate();
  return new Date(Date.UTC(ty, tm, Math.min(day, last))).toISOString().slice(0, 10);
}

/** Whole calendar months from `from` to `to` (not before it), and the days left after them: from 17 October 2024 to 5
 * November 2026 is 24 months and 19 days. */
export function monthsAndDays(from: ISODate, to: ISODate): { months: number; days: number } {
  if (to <= from) return { months: 0, days: 0 };
  const [fy, fm] = parts(from);
  const [ty, tm] = parts(to);
  let months = (ty - fy) * 12 + (tm - fm);
  while (months > 0 && addMonths(from, months) > to) months--;
  const days = Math.round((utc(to) - utc(addMonths(from, months))) / DAY_MS);
  return { months, days };
}

/** How long from `from` to `to`: in days below a month ("19 days"), in months below two years ("1 month", "23 months"),
 * then in years and months ("2 years", "3 years and 1 month"). */
export function spanText(from: ISODate, to: ISODate): string {
  const { months, days } = monthsAndDays(from, to);
  if (months === 0) return plural(days, 'day');
  if (months < 24) return plural(months, 'month');
  const years = Math.floor(months / 12);
  const rest = months % 12;
  return `${plural(years, 'year')}${rest ? ` and ${plural(rest, 'month')}` : ''}`;
}

/** Whether the deadline has passed on `today`: its day is over. */
export function deadlinePassed(deadline: ISODate, today: ISODate): boolean {
  return !aheadOn(deadline, today, true);
}

/** The deadline seen from `today`: "in 4 months", "today", "19 days ago", "2 years ago". */
export function fromToday(deadline: ISODate, today: ISODate): string {
  if (deadline === today) return 'today';
  return deadline > today ? `in ${spanText(today, deadline)}` : `${spanText(deadline, today)} ago`;
}

/** "19 days after the deadline", "2 years and 1 month after the deadline" once it has passed on `today`; else null. */
export function afterDeadline(deadline: ISODate | null | undefined, today: ISODate): string | null {
  return deadline && deadlinePassed(deadline, today) ? `${spanText(deadline, today)} after the deadline` : null;
}

/**
 * A Member State's status as the build would state it on `today` (the build states it on its own date): no measures in
 * the dataset is "Deadline not yet reached" while the deadline is ahead, and "No measures found in the available dataset"
 * once its day is over. Every other status stands as built.
 */
export function statusOn(status: TranspositionStatus, deadline: ISODate | null | undefined, today: ISODate): TranspositionStatus {
  if (!deadline) return status;
  if (status === 'deadline_not_reached' && deadlinePassed(deadline, today)) return 'none_found';
  if (status === 'none_found' && !deadlinePassed(deadline, today)) return 'deadline_not_reached';
  return status;
}
