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
