import type { ISODate } from '../types/data';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** "13 Mar 2024" — parsed manually so time zones never shift the date. */
export function formatDate(d: ISODate | null | undefined, long = false): string {
  if (!d) return '—';
  const [y, m, day] = d.slice(0, 10).split('-').map(Number);
  if (!y || !m) return d;
  const mon = (long ? MONTHS_LONG : MONTHS)[m - 1];
  return day ? `${day} ${mon} ${y}` : `${mon} ${y}`;
}

export function formatDateTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return `${formatDate(ts.slice(0, 10))}, ${d.toISOString().slice(11, 16)} UTC`;
}

/** Whole days between an ISO date and today (UTC). */
export function daysSince(d: ISODate, today = new Date()): number {
  const t = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  const [y, m, day] = d.split('-').map(Number);
  return Math.round((t - Date.UTC(y, m - 1, day)) / 86_400_000);
}

export function isFuture(d: ISODate, today = new Date()): boolean {
  return daysSince(d, today) < 0;
}

// ------------------------------------------------------------------ dates stated when the data was built
// The data is rebuilt weekly, so a date that was ahead then may have passed by the time a visitor reads it.
// Dated statements are compared with the visitor's date here, as the build does with its own.

/** Items dated after `today` (e.g. the home page's "Coming up", computed when the data was built). */
export function stillAhead<T extends { date?: ISODate | null }>(items: T[], today: ISODate): T[] {
  return items.filter((it) => !!it.date && it.date > today);
}

const LONG_DATE = `(\\d{1,2}) (${MONTHS_LONG.join('|')}) (\\d{4})`;

function isoFromLong(day: string, month: string, year: string): ISODate {
  return `${year}-${String(MONTHS_LONG.indexOf(month) + 1).padStart(2, '0')}-${day.padStart(2, '0')}`;
}

/** The build's sentences about a date still ahead (pipeline/analysis/status.py, next steps), and the wording it
 * uses for the same facts once the date has passed. */
const PAST_TENSE: [RegExp, (date: string) => string][] = [
  [new RegExp(`The act enters into force on ${LONG_DATE}\\.`, 'g'), (d) => `The act entered into force on ${d}.`],
  [
    new RegExp(`The Member States bound by the directive must transpose it into national law by ${LONG_DATE}\\.`, 'g'),
    (d) => `The transposition deadline (${d}) has passed: the Member States bound by the directive were required to adopt national measures by then.`,
  ],
  [
    // a directive whose own text gives some Member States more time or exempts them (Directive (EU) 2016/798)
    new RegExp(`The Member States bound by the directive must transpose it into national law by ${LONG_DATE}, except as its text provides\\.`, 'g'),
    (d) =>
      `The transposition deadline (${d}) has passed: the Member States bound by the directive were required to adopt national measures by then, except as its text provides.`,
  ],
  [new RegExp(`The national measures are to apply from ${LONG_DATE}`, 'g'), (d) => `The national measures were to apply from ${d}`],
];

/** A sentence written when the data was built, in the past tense for the dates in it that have passed by `today`
 * (on that day or before); anything else is returned unchanged. */
export function asOfToday(text: string, today: ISODate): string {
  let out = text;
  for (const [re, past] of PAST_TENSE) {
    out = out.replace(re, (whole, day: string, month: string, year: string) =>
      isoFromLong(day, month, year) <= today ? past(`${day} ${month} ${year}`) : whole,
    );
  }
  return out;
}

export function formatNumber(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString('en-GB');
}

export function pct(n: number, total: number, digits = 0): string {
  if (!total) return '—';
  return `${((n / total) * 100).toFixed(digits)}%`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${formatNumber(n)} ${n === 1 ? one : many}`;
}

export const COUNTRY_NAMES: Record<string, string> = {
  AT: 'Austria', BE: 'Belgium', BG: 'Bulgaria', HR: 'Croatia', CY: 'Cyprus', CZ: 'Czechia',
  DK: 'Denmark', EE: 'Estonia', FI: 'Finland', FR: 'France', DE: 'Germany', GR: 'Greece',
  HU: 'Hungary', IE: 'Ireland', IT: 'Italy', LV: 'Latvia', LT: 'Lithuania', LU: 'Luxembourg',
  MT: 'Malta', NL: 'Netherlands', PL: 'Poland', PT: 'Portugal', RO: 'Romania', SK: 'Slovakia',
  SI: 'Slovenia', ES: 'Spain', SE: 'Sweden', GB: 'United Kingdom',
};

export function countryName(code: string | null | undefined): string {
  if (!code) return '—';
  return COUNTRY_NAMES[code] ?? code;
}

/** Only allow http(s) links to be rendered from ingested data. */
export function safeUrl(u: string | null | undefined): string | undefined {
  if (!u) return undefined;
  try {
    const url = new URL(u);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}
