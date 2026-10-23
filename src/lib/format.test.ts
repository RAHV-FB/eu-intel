import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, DossierSummary, HomeData, Meta, TimelineEvent } from '../types/data';
import { aheadOn, asOfToday, eventOn, stepTitle, stillAhead } from './format';

// Next steps and status explanations of the build of 23 October 2026 (public/data/dossiers/<id>.json), and what
// the pipeline itself writes for the same files when it is run on a later date (pipeline/analysis/status.py
// _next_step, pipeline/build.py amending_deadlines; checked by running the build with that date).

// 2021/0171(COD), Consumer Credit Directive (EU) 2023/2225. Art. 48(1): Member States "shall apply those measures
// from 20 November 2026".
const CCD =
  'The transposition deadline (20 November 2025) has passed: the Member States bound by the directive were required to adopt ' +
  'national measures by then. The national measures are to apply from 20 November 2026.';
const CCD_PASSED = CCD.replace(' The national measures are to apply from 20 November 2026.', '');

describe('dated statements on the visitor’s date', () => {
  it('keeps a sentence whose date is still ahead', () => {
    expect(asOfToday(CCD, '2026-11-19')).toBe(CCD);
  });

  it('leaves out a date of application once it has come, as the build does when no later date follows', () => {
    // a build of 16 November 2026, read on 22 November, said "are to apply from 20 November 2026"
    expect(asOfToday(CCD, '2026-11-20')).toBe(CCD_PASSED);
    expect(asOfToday(CCD, '2026-11-22')).toBe(CCD_PASSED);
    // 2021/0341(COD), Directive (EU) 2024/1619: the general date is stated to set the later one apart from it
    const crd =
      'The transposition deadline (10 January 2026) has passed: the Member States bound by the directive were required to adopt ' +
      'national measures by then. The national measures were to apply from 11 January 2026. EUR-Lex records a later ' +
      'application date for specific provisions: 11 January 2027.';
    expect(asOfToday(crd, '2027-01-10')).toBe(crd);
    expect(asOfToday(crd, '2027-01-11')).toBe(crd.slice(0, crd.indexOf(' The national measures')));
    // 2022/0407(CNS): a passed general date stays while later ones remain
    const vat =
      'The Member States bound by the directive must transpose it into national law by 31 December 2026. The national measures are to ' +
      'apply from 1 January 2027. EUR-Lex records later application dates for specific provisions: 1 July 2028 and ' +
      '1 January 2035.';
    expect(asOfToday(vat, '2027-01-02')).toBe(
      'The transposition deadline (31 December 2026) has passed: the Member States bound by the directive were required to adopt ' +
        'national measures by then. The national measures were to apply from 1 January 2027. EUR-Lex records later ' +
        'application dates for specific provisions: 1 July 2028 and 1 January 2035.',
    );
    expect(asOfToday(vat, '2028-07-01')).toContain('EUR-Lex records a later application date for specific provisions: 1 January 2035.');
  });

  it('treats a transposition deadline as passed only once its day is over', () => {
    // Directive (EU) 2024/2853 (Product Liability), Art. 22(1): "Member States shall bring into force the laws,
    // regulations and administrative provisions necessary to comply with this Directive by 9 December 2026."
    const pld = 'The Member States bound by the directive must transpose it into national law by 9 December 2026.';
    expect(asOfToday(pld, '2026-12-09')).toBe(pld);
    expect(asOfToday(pld, '2026-12-10')).toBe(
      'The transposition deadline (9 December 2026) has passed: the Member States bound by the directive were required to adopt ' +
        'national measures by then.',
    );
    // with exceptions in the directive's text (data/curated/transposition.yaml `exceptions`), which follow unchanged
    const tail = ' Under Art. 33(4), the obligation to transpose and implement the directive does not apply to Cyprus and Malta.';
    expect(
      asOfToday(`The Member States bound by the directive must transpose it into national law by 9 December 2026, except as its text provides.${tail}`, '2026-12-10'),
    ).toBe(
      `The transposition deadline (9 December 2026) has passed: the Member States bound by the directive were required to adopt national measures by then, except as its text provides.${tail}`,
    );
    expect(aheadOn('2026-12-09', '2026-12-09', true)).toBe(true);
    expect(aheadOn('2026-12-09', '2026-12-09')).toBe(false);
  });

  it('puts an entry into force that has come in the past tense', () => {
    expect(asOfToday('The act enters into force on 2 December 2026. More.', '2026-12-02')).toBe('The act entered into force on 2 December 2026. More.');
    expect(asOfToday('The act enters into force on 2 December 2026.', '2026-12-01')).toBe('The act enters into force on 2 December 2026.');
    // status.py explanation of a published act not yet in force
    expect(asOfToday('The act was published in the Official Journal on 1 December 2026. It enters into force on 21 December 2026.', '2026-12-21')).toBe(
      'The act was published in the Official Journal on 1 December 2026. It entered into force on 21 December 2026.',
    );
  });

  it('lists only the later dates still ahead', () => {
    // 2021/0106(COD), AI Act (Regulation (EU) 2024/1689)
    const ai =
      'The regulation applies directly in all EU countries; no national transposition is needed. Later dates from which ' +
      '(parts of) the act apply: 2 December 2026, 2 December 2027 and 2 August 2028.';
    expect(asOfToday(ai, '2026-12-02')).toBe(ai.replace('2 December 2026, ', ''));
    expect(asOfToday(ai, '2027-12-02')).toBe(ai.replace('dates', 'date').replace('2 December 2026, 2 December 2027 and ', ''));
    expect(asOfToday(ai, '2028-08-02')).toBe('The regulation applies directly in all EU countries; no national transposition is needed.');
    // 2021/0250(COD), AMLD6 (Directive (EU) 2024/1640), Art. 78(1): 10 July 2027; Article 18 by 10 July 2029
    const amld6 =
      'The Member States bound by the directive must transpose it into national law by 10 July 2027. EUR-Lex records earlier ' +
      'transposition deadlines for specific provisions, which have passed: 10 July 2025 and 10 July 2026. EUR-Lex ' +
      'records a later transposition deadline for specific provisions: 10 July 2029.';
    expect(asOfToday(amld6, '2027-07-10')).toBe(amld6);
    expect(asOfToday(amld6, '2027-07-11')).toBe(
      'The transposition deadline (10 July 2027) has passed: the Member States bound by the directive were required to adopt ' +
        'national measures by then. EUR-Lex records a later transposition deadline for specific provisions: 10 July 2029.',
    );
    expect(asOfToday(amld6, '2029-07-11')).toBe(
      'The transposition deadline (10 July 2027) has passed: the Member States bound by the directive were required to adopt ' +
        'national measures by then.',
    );
    // an earlier deadline is marked once it has passed
    const early = 'The Member States bound by the directive must transpose it into national law by 26 November 2028. EUR-Lex records an earlier transposition deadline for specific provisions: 26 November 2027.';
    expect(asOfToday(early, '2027-11-27')).toBe(early.replace('provisions: 26 November 2027.', 'provisions, which has passed: 26 November 2027.'));
  });

  it('follows the deadlines of the directives that amend a directive', () => {
    // 2018/0105(COD), Directive (EU) 2019/1153, amended by Directive (EU) 2024/1654
    const amended =
      'The transposition deadline (1 August 2021) has passed: the Member States bound by the directive were required to adopt national ' +
      'measures by then. Directive (EU) 2024/1654 amends this directive (Article 1); Member States must transpose the ' +
      'amendments by 10 July 2027 (those in Article 1, points (4) and (5), by 10 July 2029).';
    expect(asOfToday(amended, '2027-07-10')).toBe(amended);
    expect(asOfToday(amended, '2027-07-11')).toBe(
      'The transposition deadline (1 August 2021) has passed: the Member States bound by the directive were required to adopt national ' +
        'measures by then. Directive (EU) 2024/1654 amends this directive (Article 1); those in Article 1, points (4) ' +
        'and (5), must be transposed by 10 July 2029.',
    );
    expect(asOfToday(amended, '2029-07-11')).toBe(amended.slice(0, amended.indexOf(' Directive (EU) 2024/1654')));
    // 2018/0106(COD), Directive (EU) 2019/1937
    const two =
      'The transposition deadline (17 December 2021) has passed: the Member States bound by the directive were required to adopt ' +
      'national measures by then. Directive (EU) 2024/1640 amends this directive (Article 75); Member States must ' +
      'transpose the amendments by 10 July 2027. Directive (EU) 2024/1760, which amends this directive, must be ' +
      'transposed by 26 July 2028.';
    expect(asOfToday(two, '2027-07-11')).toBe(two.replace(' Directive (EU) 2024/1640 amends this directive (Article 75); Member States must transpose the amendments by 10 July 2027.', ''));
    expect(asOfToday(two, '2028-07-27')).toBe(two.slice(0, two.indexOf(' Directive (EU) 2024/1640')));
    // 2013/0025(COD), Directive (EU) 2015/849: Directive (EU) 2024/1640, Art. 77, "is repealed with effect from 10 July 2027"
    const repealed =
      'The transposition deadline (26 June 2017) has passed: the Member States bound by the directive were required to adopt national ' +
      'measures by then. Directive (EU) 2024/1640 repeals this directive with effect from 10 July 2027.';
    expect(asOfToday(repealed, '2027-07-10')).toBe(repealed.replace('repeals this', 'repealed this'));
    const status =
      'The act has been in force since 25 June 2015. EUR-Lex records that its validity ends on 9 July 2027 and that ' +
      'Directive (EU) 2024/1640 repeals it.';
    expect(asOfToday(status, '2027-07-09')).toBe(status);
    expect(asOfToday(status, '2027-07-10')).toBe(status.replace('ends on', 'ended on'));
  });

  it('leaves out of "Coming up" the dates that have passed, keeping a deadline on its day', () => {
    const items = [{ date: '2026-11-20' }, { date: '2026-11-21' }, { date: '2026-12-02' }, { date: null }];
    expect(stillAhead(items, '2026-11-20')).toEqual([{ date: '2026-11-21' }, { date: '2026-12-02' }]);
    expect(stillAhead([{ date: '2026-12-09', badge: 'Deadline' }, { date: '2026-12-09', badge: 'Applies' }], '2026-12-09')).toEqual([
      { date: '2026-12-09', badge: 'Deadline' },
    ]);
  });

  it('gives a timeline step the state and title the build would give it on the visitor’s date', () => {
    // 2021/0367(COD), Regulation (EU) 2024/1157; 2022/0167(COD), Directive (EU) 2024/1260
    const applies = { id: 'a', kind: 'application', date: '2026-11-21', state: 'scheduled', title: 'Some provisions start to apply (date recorded by EUR-Lex)' } as TimelineEvent;
    expect(eventOn(applies, '2026-11-20')).toBe(applies);
    expect(eventOn(applies, '2026-11-21')).toMatchObject({ state: 'done', title: 'Some provisions started to apply (date recorded by EUR-Lex)' });
    const deadline = { id: 'd', kind: 'transposition_deadline', date: '2026-11-23', state: 'scheduled', title: 'Deadline for Member States to transpose the directive' } as TimelineEvent;
    expect(eventOn(deadline, '2026-11-23')).toBe(deadline);
    expect(eventOn(deadline, '2026-11-24')).toMatchObject({ state: 'done', title: 'Deadline for Member States to transpose the directive (passed)' });
    // a build run on the deadline day itself marks it passed
    expect(eventOn({ ...deadline, state: 'done', title: `${deadline.title} (passed)` }, '2026-11-23')).toMatchObject(deadline);
    expect(stepTitle('Transposition deadline for specific provisions (Art. 9(2), points (j) and (k))', true)).toBe(
      'Transposition deadline for specific provisions (Art. 9(2), points (j) and (k)) (passed)',
    );
    expect(stepTitle('Enters into force; some provisions start to apply: Article 54', true)).toBe('Entered into force; some provisions started to apply: Article 54');
    const vote = { id: 'v', kind: 'plenary_vote', date: '2026-11-21', state: 'done', title: 'Plenary vote' } as TimelineEvent;
    expect(eventOn(vote, '2026-01-01')).toBe(vote);
  });
});

// ------------------------------------------------------------------ the built data
const DATA = new URL('../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

const D = '\\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \\d{4}';
const DS = `${D}(?: \\(passed\\))?(?:, ${D}(?: \\(passed\\))?)*(?: and ${D}(?: \\(passed\\))?)?`;
/** Every wording in which the build states a date as still ahead, and whether that date is a deadline (passed only
 * once its day is over: measures due "by" it, or an act's last day of validity). Written out here, apart from
 * format.ts, so that a wording the build adds fails the first test below until it is handled. */
const FUTURE: [RegExp, boolean][] = (
  [
    [`enters into force on ${D}`, false],
    [`must transpose the directive into national law by ${D}`, true],
    [`must transpose it into national law by ${D}`, true],
    [`Member States must transpose the directive by ${D}`, true],
    [`national measures are to apply from ${D}`, false],
    [`EUR-Lex records (?:an earlier transposition deadline|earlier transposition deadlines) for specific provisions: ${DS}`, true],
    [`EUR-Lex records (?:a later transposition deadline|later transposition deadlines) for specific provisions: ${DS}`, true],
    [`EUR-Lex records (?:a later application date|later application dates) for specific provisions: ${DS}`, false],
    [`EUR-Lex records (?:a date|dates) from which national measures are to apply: ${DS}`, false],
    [`Later dates? from which \\(parts of\\) the act apply: ${DS}`, false],
    [`Further provisions apply from ${D}`, false],
    [`must be transposed by ${D}`, true],
    [`must transpose the amendments by ${D}(?: \\([^.]+\\))?`, true],
    [`repeals this directive with effect from ${D}`, false],
    [`its validity ends on ${D}`, true],
  ] as [string, boolean][]
).map(([s, deadline]) => [new RegExp(s, 'g'), deadline]);
/** Wordings of dates that stay true once passed. */
const PAST = [
  /(?:has|have) passed/, /were to apply from/, /entered into force on/, /has been in force since/, /validity ended on/,
  /published in the Official Journal on/, / since \d/, /(?:gave its consent|had rejected the proposal) on/,
  /information updated as of/, /partial end of its validity on/,
  /which is dated/, /as the end of (?:its|the act's) validity/, /repealed this directive with effect from/, /started to apply on/,
  /repealed by .+ \(?with effect from/, /had until \d/,
];
const isoOf = (long: string) => {
  const [day, month, year] = long.split(' ');
  const m = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'].indexOf(month) + 1;
  return `${year}-${String(m).padStart(2, '0')}-${day.padStart(2, '0')}`;
};
/** The dates a text states as still ahead (not those marked "(passed)"), each with whether it is a deadline. */
function statedAhead(text: string): [string, boolean][] {
  const out: [string, boolean][] = [];
  for (const [re, deadline] of FUTURE)
    for (const m of text.matchAll(re))
      for (const d of m[0].matchAll(new RegExp(`(${D})(?! \\(passed\\))`, 'g'))) out.push([isoOf(d[1]), deadline]);
  return out;
}
const sentences = (text: string) => text.split(/(?<=\.) (?=[A-Z])/);

describe.skipIf(!built)('dated statements in the built data', () => {
  const index = built ? read<DossierSummary[]>('dossiers/index.json') : [];
  const all = index.map((d) => read<DossierDetail>(`dossiers/${d.id}.json`));
  const texts = all.flatMap((d) => [[d.id, d.next_step.text], [d.id, d.status.explanation]] as [string, string][]);
  const buildDay = built ? read<Meta>('meta.json').built_at.slice(0, 10) : '';

  it('states every date in a wording known to be still ahead, or one that stays true', () => {
    const unknown = texts.flatMap(([id, text]) =>
      sentences(text)
        .filter((s) => new RegExp(D).test(s) && !FUTURE.some(([re]) => new RegExp(re.source).test(s)) && !PAST.some((re) => re.test(s)))
        .map((s) => `${id}: ${s}`),
    );
    expect(unknown).toEqual([]);
    expect(texts.filter(([, t]) => statedAhead(t).length).length).toBeGreaterThan(100);
  });

  it('reads on the day it was built as the build wrote it', () => {
    for (const [id, text] of texts) expect(asOfToday(text, buildDay), id).toBe(text);
    for (const d of all) for (const e of d.timeline) expect(eventOn(e, buildDay), `${d.id} ${e.id}`).toBe(e);
  });

  it('states no date as ahead once it has passed, and keeps every date still ahead, with the clock moved forward', () => {
    const dated = texts.filter(([, t]) => statedAhead(t).length);
    const days = new Set(['2100-01-01']);
    for (const [, t] of dated)
      for (const [d] of statedAhead(t)) {
        days.add(d);
        days.add(new Date(Date.parse(d) + 86_400_000).toISOString().slice(0, 10));
      }
    expect(days.size).toBeGreaterThan(50);
    for (const day of days)
      for (const [id, text] of dated) {
        const out = asOfToday(text, day);
        for (const [d, deadline] of statedAhead(out)) expect(aheadOn(d, day, deadline), `${id} on ${day}: ${out}`).toBe(true);
        const kept = new Set(statedAhead(out).map(([d]) => d));
        for (const [d, deadline] of statedAhead(text)) if (aheadOn(d, day, deadline)) expect(kept.has(d), `${id} on ${day}: ${d} in ${out}`).toBe(true);
      }
  });

  it('gives every dated timeline step a title for both states, in the wording the build uses for passed steps', () => {
    const DATED = ['entry_into_force', 'application', 'transposition_deadline', 'transposition_application'];
    const steps = all.flatMap((d) => d.timeline.filter((e) => DATED.includes(e.kind)));
    // the wording without what is particular to a step (provisions, articles)
    const shape = (e: TimelineEvent) => `${e.kind} ${e.title.replace(/: .*/, ': …').replace(/ \((?!passed\)|date recorded)[^)]*(\([^)]*\)[^)]*)*\)/g, ' (…)')}`;
    const passedShapes = new Set(steps.filter((e) => e.state === 'done').map(shape));
    const scheduled = steps.filter((e) => e.state === 'scheduled');
    expect(scheduled.length).toBeGreaterThan(0);
    for (const e of scheduled) {
      const later = eventOn(e, '2100-01-01');
      expect(later.state).toBe('done');
      expect(passedShapes.has(shape(later)), `${e.id}: ${later.title}`).toBe(true);
      if (e.kind !== 'transposition_application') expect(later.title, e.id).not.toBe(e.title);
    }
    for (const e of steps) {
      const other = e.state === 'done' ? eventOn(e, '1900-01-01') : eventOn(e, '2100-01-01');
      expect(eventOn(other, e.state === 'done' ? '2100-01-01' : '1900-01-01').title, e.id).toBe(e.title);
    }
  });

  it('has only dates still ahead of the build in "Coming up"', () => {
    const home = read<HomeData>('home.json');
    const upcoming = home.lists.find((l) => l.id === 'upcoming')!.items;
    const first = upcoming[0]?.date ?? '';
    expect(stillAhead(upcoming, '2000-01-01')).toEqual(upcoming);
    expect(stillAhead(upcoming, first).length).toBeLessThan(upcoming.length);
  });
});
