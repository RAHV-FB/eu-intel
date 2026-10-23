import type { ISODate, TimelineEvent } from '../types/data';

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

/** "No recorded procedural update in 9 days" on `today`: the build counts the days since a file's last recorded step
 * (`days`) on its own date, up to a week before the visitor's; `last` is that step's date. Never fewer than the
 * build counted. */
export function noUpdateText(days: number, last: ISODate | null | undefined, today: ISODate): string {
  const n = last ? Math.max(days, daysSince(last, new Date(`${today}T00:00:00Z`))) : days;
  return `No recorded procedural update in ${plural(n, 'day')}`;
}

export function isFuture(d: ISODate, today = new Date()): boolean {
  return daysSince(d, today) < 0;
}

// ------------------------------------------------------------------ dates stated when the data was built
// The data is rebuilt weekly, so a date that was ahead then may have passed by the time a visitor reads it.
// Dated statements are compared with the visitor's date here, by the rules the build applies to its own.

/** Whether `date` is still ahead on `today`. A deadline (measures due "by" that date: a transposition deadline,
 * or the last day of an act's validity) has passed only once its day is over; an entry into force or a date from
 * which provisions apply has come on its day. */
export function aheadOn(date: ISODate, today: ISODate, deadline = false): boolean {
  return deadline ? date >= today : date > today;
}

/** Items still ahead on `today` (the home page's "Coming up", computed when the data was built): a deadline is
 * kept on its day. */
export function stillAhead<T extends { date?: ISODate | null; badge?: string | null }>(items: T[], today: ISODate): T[] {
  return items.filter((it) => !!it.date && aheadOn(it.date, today, it.badge === 'Deadline'));
}

const DATE = `\\d{1,2} (?:${MONTHS_LONG.join('|')}) \\d{4}`;
const DATES = `${DATE}(?:, ${DATE})*(?: and ${DATE})?`;
const MARKED_DATE = `${DATE}(?: \\(passed\\))?`; // an earlier transposition deadline, marked once it has passed
const MARKED_DATES = `${MARKED_DATE}(?:, ${MARKED_DATE})*(?: and ${MARKED_DATE})?`;

/** "9 December 2026" -> "2026-12-09" */
function isoFromLong(long: string): ISODate {
  const [day, month, year] = long.split(' ');
  return `${year}-${String(MONTHS_LONG.indexOf(month) + 1).padStart(2, '0')}-${day.padStart(2, '0')}`;
}

const datesIn = (list: string): string[] => list.match(new RegExp(DATE, 'g')) ?? [];
const ahead = (long: string, today: ISODate, deadline = false) => aheadOn(isoFromLong(long), today, deadline);

/** "a, b and c", as the build joins dates (status.py _join_dates). */
function joinDates(ds: string[]): string {
  return ds.length === 1 ? ds[0] : `${ds.slice(0, -1).join(', ')} and ${ds[ds.length - 1]}`;
}

/** The dates of a list still ahead, written by `write`; '' (the sentence is left out) when none is. */
function stillListed(list: string, today: ISODate, deadline: boolean, write: (ds: string[], many: boolean) => string): string {
  const ds = datesIn(list).filter((d) => ahead(d, today, deadline));
  return ds.length ? write(ds, ds.length > 1) : '';
}

const re = (source: string) => new RegExp(source, 'g');
const SENTENCE_START = '(?<=^|\\. )';

type Groups = (string | undefined)[];
/** A sentence of the build about a date ahead (pipeline/analysis/status.py next steps and status explanations,
 * pipeline/build.py derived_next_step and amending_deadlines), and what the build writes instead once that date
 * has passed: the past tense, the dates still ahead, or nothing ('') when it then leaves the sentence out.
 * `general`: the directive's general transposition deadline stated in the same text; `text`: the text so far. */
const DATED: { re: RegExp; to: (g: Groups, today: ISODate, general: string | null, text: string) => string }[] = [
  {
    re: re(`(The act|It) enters into force on (${DATE})\\.`),
    to: ([s, who, d], t) => (ahead(d!, t) ? s! : `${who} entered into force on ${d}.`),
  },
  {
    // status.py, and build.py derived_next_step ("Member States must transpose the directive by …"); a directive whose
    // own text gives some Member States more time or exempts them (data/curated/transposition.yaml `exceptions`)
    re: re(
      `(?:The Member States bound by the directive must transpose it into national law|EU countries must transpose the directive into national law|Member States must transpose the directive) by (${DATE})(, except as its text provides)?\\.`,
    ),
    to: ([s, d, unless], t) =>
      ahead(d!, t, true)
        ? s!
        : `The transposition deadline (${d}) has passed: the Member States bound by the directive were required to adopt national measures by then${unless ?? ''}.`,
  },
  {
    // listed only while the general deadline is ahead
    re: re(`EUR-Lex records (?:an earlier transposition deadline|earlier transposition deadlines) for specific provisions(?:, which (?:has|have) passed)?: (${MARKED_DATES})\\.`),
    to: ([, list], t, general) => {
      if (general && !ahead(general, t, true)) return '';
      const ds = datesIn(list!);
      const passed = ds.filter((d) => !ahead(d, t, true));
      const many = ds.length > 1;
      const tail =
        passed.length === ds.length
          ? `, which ${many ? 'have' : 'has'} passed: ${joinDates(ds)}`
          : `: ${joinDates(ds.map((d) => (passed.includes(d) ? `${d} (passed)` : d)))}`;
      return `EUR-Lex records ${many ? 'earlier transposition deadlines' : 'an earlier transposition deadline'} for specific provisions${tail}.`;
    },
  },
  {
    re: re(`EUR-Lex records (?:a later transposition deadline|later transposition deadlines) for specific provisions: (${DATES})\\.`),
    to: ([, list], t) =>
      stillListed(list!, t, true, (ds, many) =>
        `EUR-Lex records ${many ? 'later transposition deadlines' : 'a later transposition deadline'} for specific provisions: ${joinDates(ds)}.`,
      ),
  },
  {
    re: re(`EUR-Lex records (?:a later application date|later application dates) for specific provisions: (${DATES})\\.`),
    to: ([, list], t) =>
      stillListed(list!, t, false, (ds, many) =>
        `EUR-Lex records ${many ? 'later application dates' : 'a later application date'} for specific provisions: ${joinDates(ds)}.`,
      ),
  },
  {
    // a past one is stated only to set the later application dates apart from it
    re: re(`The national measures (?:are|were) to apply from (${DATE})( at the latest)?\\.`),
    to: ([s, d, latest], t, _general, text) =>
      ahead(d!, t)
        ? s!
        : / later application dates? for specific provisions: /.test(text)
          ? `The national measures were to apply from ${d}${latest ?? ''}.`
          : '',
  },
  {
    re: re(`EUR-Lex records (?:a date|dates) from which national measures are to apply: (${DATES})\\.`),
    to: ([, list], t) =>
      stillListed(list!, t, false, (ds, many) =>
        `EUR-Lex records ${many ? 'dates' : 'a date'} from which national measures are to apply: ${joinDates(ds)}.`,
      ),
  },
  {
    re: re(`Later dates? from which \\(parts of\\) the act apply: (${DATES})\\.`),
    to: ([, list], t) =>
      stillListed(list!, t, false, (ds, many) => `Later date${many ? 's' : ''} from which (parts of) the act apply: ${joinDates(ds)}.`),
  },
  {
    re: re(`Further provisions apply from (${DATE})\\.`),
    to: ([s, d], t) => (ahead(d!, t) ? s! : `Further provisions started to apply on ${d}.`),
  },
  {
    re: re(`${SENTENCE_START}([^.]+?), which amends this directive, must be transposed by (${DATE})\\.`),
    to: ([s, , d], t) => (ahead(d!, t, true) ? s! : ''),
  },
  {
    // "…; Member States must transpose the amendments by A (those in Article 1, points (4) and (5), by B)."
    // (one sentence: no part of it contains a full stop)
    re: re(
      `${SENTENCE_START}([^.]+?) amends this directive \\(([^.;]+?)\\); (?:([^.;]+?) must be transposed by|Member States must transpose the amendments by) (${DATE})(?: \\(([^.]+?)\\))?\\.(?= |$)`,
    ),
    to: ([s, label, provision, what, d, rest], t) => {
      const dated: [string, string | undefined][] = [[d!, what]];
      for (const part of rest ? rest.split('; ') : []) {
        const m = new RegExp(`^(.+) by (${DATE})$`).exec(part);
        if (!m) return s!;
        dated.push([m[2], m[1]]);
      }
      const still = dated.filter(([x]) => ahead(x, t, true));
      if (still.length === dated.length) return s!;
      if (!still.length) return '';
      const [[first, w], ...more] = still;
      const extra = more.map(([x, mw]) => `${mw} by ${x}`).join('; ');
      return (
        `${label} amends this directive (${provision}); ` +
        (w ? `${w} must be transposed by ${first}` : `Member States must transpose the amendments by ${first}`) +
        (extra ? ` (${extra})` : '') +
        '.'
      );
    },
  },
  {
    re: re(`${SENTENCE_START}([^.]+?) repeals this directive with effect from (${DATE})\\.`),
    to: ([s, label, d], t) => (ahead(d!, t) ? s! : `${label} repealed this directive with effect from ${d}.`),
  },
  {
    // an act is still valid on its last day of validity
    re: re(`EUR-Lex records that its validity ends on (${DATE})`),
    to: ([s, d], t) => (ahead(d!, t, true) ? s! : `EUR-Lex records that its validity ended on ${d}`),
  },
];

const GENERAL_DEADLINE = new RegExp(`(?:must transpose (?:the directive|it) into national law by |The transposition deadline \\()(${DATE})`);

/** A text written when the data was built (a next step, a status explanation), as the build would write it on
 * `today`: dates that have passed are in the past tense, or left out of the lists of dates still to come. Anything
 * else is returned unchanged. */
export function asOfToday(text: string, today: ISODate): string {
  const general = GENERAL_DEADLINE.exec(text)?.[1] ?? null;
  let out = text;
  let dropped = false;
  for (const { re: pattern, to } of DATED) {
    out = out.replace(pattern, (...args: unknown[]) => {
      const groups = args.slice(0, args.findIndex((a) => typeof a === 'number')) as Groups;
      const r = to(groups, today, general, args[args.length - 1] as string);
      dropped ||= r === '';
      return r;
    });
  }
  return dropped ? out.replace(/ {2,}/g, ' ').trim() : out;
}

/** Timeline steps dated in the law, which the build marks "scheduled" while their date is ahead. */
const DATED_STEPS: ReadonlySet<string> = new Set(['entry_into_force', 'application', 'transposition_deadline', 'transposition_application']);
/** The opening words of such a step's title while it is ahead and once it has passed (pipeline/build.py timeline
 * steps of an act, and PAST_TITLES), longest first; a deadline's title ends in " (passed)" once it has passed. */
const STEP_TENSES: [string, string][] = [
  ['Enters into force; some provisions start to apply', 'Entered into force; some provisions started to apply'],
  ['Enters into force and starts to apply', 'Entered into force and started to apply'],
  ['Enters into force', 'Entered into force'],
  ['Starts to apply', 'Started to apply'],
  ['Some provisions start to apply', 'Some provisions started to apply'],
  ['Further provisions start to apply', 'Further provisions started to apply'],
  ['Rules start to apply', 'Rules started to apply'],
];
const DEADLINE_TITLE = /^(Deadline for Member States to transpose the directive|Transposition deadline for specific provisions\b.*?)( \(passed\))?$/;

/** A dated step's title as the build writes it while the step is ahead (`passed` false) or once it has passed. */
export function stepTitle(title: string, passed: boolean): string {
  const deadline = DEADLINE_TITLE.exec(title);
  if (deadline) return passed ? `${deadline[1]} (passed)` : deadline[1];
  for (const [future, past] of STEP_TENSES) {
    const [from, to] = passed ? [future, past] : [past, future];
    if (title.startsWith(from)) return to + title.slice(from.length);
  }
  return title;
}

/** A timeline step on `today`: a step dated in the law is scheduled while its date is ahead (a transposition
 * deadline until its day is over), with the build's title for that state; other steps are as recorded. */
export function eventOn(e: TimelineEvent, today: ISODate): TimelineEvent {
  if (!DATED_STEPS.has(e.kind)) return e;
  const state = aheadOn(e.date, today, e.kind === 'transposition_deadline') ? 'scheduled' : 'done';
  return state === e.state ? e : { ...e, state, title: stepTitle(e.title, state === 'done') };
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
