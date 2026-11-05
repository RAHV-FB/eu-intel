import { describe, expect, it } from 'vitest';
import { addMonths, afterDeadline, deadlinePassed, fromToday, monthsAndDays, spanText, statusOn } from './deadline';

// NIS 2 (Directive (EU) 2022/2555): transposition deadline 17 October 2024. The reader's date is injected, as the page
// passes todayISO(); the build's date plays no part.
const NIS2 = '2024-10-17';

describe('calendar months', () => {
  it('adds months to the same day, or to the last day of a shorter month', () => {
    expect(addMonths('2024-10-17', 24)).toBe('2026-10-17');
    expect(addMonths('2024-01-31', 1)).toBe('2024-02-29'); // a leap year
    expect(addMonths('2025-01-31', 1)).toBe('2025-02-28');
    expect(addMonths('2026-11-05', -36)).toBe('2023-11-05');
    expect(addMonths('2028-02-29', -36)).toBe('2025-02-28');
  });

  it('counts whole months, then the days left', () => {
    expect(monthsAndDays(NIS2, '2026-11-05')).toEqual({ months: 24, days: 19 });
    expect(monthsAndDays(NIS2, '2024-11-16')).toEqual({ months: 0, days: 30 });
    expect(monthsAndDays(NIS2, '2024-11-17')).toEqual({ months: 1, days: 0 });
    expect(monthsAndDays('2024-01-31', '2024-03-30')).toEqual({ months: 1, days: 30 });
    expect(monthsAndDays('2024-01-31', '2024-02-29')).toEqual({ months: 1, days: 0 });
    expect(monthsAndDays(NIS2, NIS2)).toEqual({ months: 0, days: 0 });
    expect(monthsAndDays('2026-11-05', NIS2)).toEqual({ months: 0, days: 0 }); // never negative
  });

  it('says a span in days below a month, in months below two years, then in years and months', () => {
    expect(spanText(NIS2, '2024-10-18')).toBe('1 day');
    expect(spanText(NIS2, '2024-11-16')).toBe('30 days');
    expect(spanText(NIS2, '2024-11-17')).toBe('1 month');
    expect(spanText(NIS2, '2026-10-16')).toBe('23 months');
    expect(spanText(NIS2, '2026-10-17')).toBe('2 years');
    expect(spanText(NIS2, '2026-11-17')).toBe('2 years and 1 month');
    expect(spanText(NIS2, '2027-12-01')).toBe('3 years and 1 month');
  });
});

describe('a deadline on the reader’s date', () => {
  it('passes only once its day is over', () => {
    expect(deadlinePassed(NIS2, '2024-10-16')).toBe(false);
    expect(deadlinePassed(NIS2, NIS2)).toBe(false);
    expect(deadlinePassed(NIS2, '2024-10-18')).toBe(true);
  });

  it('is told from the reader’s date: ahead, on the day, or how long ago', () => {
    expect(fromToday(NIS2, '2024-06-17')).toBe('in 4 months');
    expect(fromToday(NIS2, '2024-10-10')).toBe('in 7 days');
    expect(fromToday(NIS2, NIS2)).toBe('today');
    expect(fromToday(NIS2, '2024-10-18')).toBe('1 day ago');
    expect(fromToday(NIS2, '2026-11-05')).toBe('2 years ago');
  });

  it('says how long after the deadline the reader is, only once it has passed', () => {
    expect(afterDeadline(NIS2, '2024-10-16')).toBeNull();
    expect(afterDeadline(NIS2, NIS2)).toBeNull();
    expect(afterDeadline(NIS2, '2024-10-25')).toBe('8 days after the deadline');
    expect(afterDeadline(NIS2, '2025-10-17')).toBe('12 months after the deadline');
    expect(afterDeadline(NIS2, '2026-11-05')).toBe('2 years after the deadline');
    expect(afterDeadline(null, '2026-11-05')).toBeNull();
  });

  it('moves with the reader’s clock, not the build’s', () => {
    // the same build read a week and a month later
    expect(afterDeadline('2026-10-29', '2026-11-05')).toBe('7 days after the deadline');
    expect(afterDeadline('2026-10-29', '2026-12-05')).toBe('1 month after the deadline');
  });
});

describe('a Member State’s status on the reader’s date', () => {
  it('becomes “No measures found” once the deadline has passed since the build', () => {
    // built on 5 November 2026 with a deadline of 6 November: "Deadline not yet reached"; read on 7 November
    expect(statusOn('deadline_not_reached', '2026-11-06', '2026-11-06')).toBe('deadline_not_reached');
    expect(statusOn('deadline_not_reached', '2026-11-06', '2026-11-07')).toBe('none_found');
  });

  it('is “Deadline not yet reached” on the deadline’s own day, as the timeline says it', () => {
    expect(statusOn('none_found', '2026-11-05', '2026-11-05')).toBe('deadline_not_reached');
    expect(statusOn('none_found', '2026-11-05', '2026-11-06')).toBe('none_found');
  });

  it('leaves every other status as built', () => {
    for (const s of ['measures_notified', 'not_participating', 'not_required', 'no_deadline', 'unavailable'] as const) {
      expect(statusOn(s, '2026-11-05', '2026-11-04')).toBe(s);
      expect(statusOn(s, '2026-11-05', '2026-11-07')).toBe(s);
    }
    expect(statusOn('deadline_not_reached', null, '2030-01-01')).toBe('deadline_not_reached');
  });
});
