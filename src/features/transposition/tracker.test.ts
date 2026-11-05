import { describe, expect, it } from 'vitest';
import type { TrackedCountry, TrackedDirective, TranspositionTracker } from '../../types/data';
import { builtTooLongAgo, directivesOn, matches, openNonCommunication, split, statusCounts, windowOn } from './tracker';

const row = (country: string, status: TrackedCountry['status'], extra: Partial<TrackedCountry> = {}): TrackedCountry => ({
  country,
  status,
  measures: status === 'measures_notified' ? 2 : 0,
  ...extra,
});

const directive = (celex: string, deadline: string, countries: TrackedCountry[], topics = ['tech']): TrackedDirective => ({
  celex,
  title: `Directive ${celex}`,
  act: `Directive (EU) ${celex}`,
  names: [],
  dossier_id: `id-${celex}`,
  deadline,
  topics,
  countries,
});

// built on 5 November 2026: the build wrote the window with a month more at each end
const T: TranspositionTracker = {
  built_on: '2026-11-05',
  window: { years_back: 3, months_ahead: 12 },
  directives: [
    directive('A', '2023-10-10', [row('DE', 'none_found')]), // in the build's margin only
    directive('B', '2023-11-05', [row('DE', 'measures_notified')]),
    directive('C', '2026-11-06', [row('DE', 'deadline_not_reached'), row('FR', 'deadline_not_reached')], ['economy']),
    directive('D', '2027-11-05', [row('DE', 'deadline_not_reached')]),
    directive('E', '2027-12-01', [row('DE', 'deadline_not_reached')]), // in the build's margin only
  ],
};

describe('the window on the reader’s date', () => {
  it('runs from three years before today to twelve months after', () => {
    expect(windowOn(T, '2026-11-05')).toEqual({ from: '2023-11-05', to: '2027-11-05' });
    expect(directivesOn(T, '2026-11-05').map((d) => d.celex)).toEqual(['B', 'C', 'D']);
  });

  it('moves with the reader’s date, within what the build wrote', () => {
    // read a week later: B's deadline has left the window, E's has not yet entered it
    expect(directivesOn(T, '2026-11-12').map((d) => d.celex)).toEqual(['C', 'D']);
    expect(directivesOn(T, '2026-12-01').map((d) => d.celex)).toEqual(['C', 'D', 'E']);
    expect(builtTooLongAgo(T, '2026-12-06')).toBe(false);
    expect(builtTooLongAgo(T, '2026-12-07')).toBe(true);
  });

  it('restates each status on the reader’s date', () => {
    // C's deadline (6 November 2026) is still ahead on its day, and has passed the day after
    const on = (today: string) => directivesOn(T, today).find((d) => d.celex === 'C')!.countries.map((c) => c.status);
    expect(on('2026-11-06')).toEqual(['deadline_not_reached', 'deadline_not_reached']);
    expect(on('2026-11-07')).toEqual(['none_found', 'none_found']);
  });

  it('lists the deadlines ahead soonest first and those passed latest first', () => {
    const ds = [...T.directives, directive('F', '2025-01-01', [row('DE', 'none_found')])];
    const { ahead, passed } = split(ds, '2026-11-06');
    expect(ahead.map((d) => d.celex)).toEqual(['C', 'D', 'E']);
    expect(passed.map((d) => d.celex)).toEqual(['F', 'B', 'A']);
  });

  it('filters by topic and by whether the deadline has passed', () => {
    const c = T.directives[2];
    expect(matches(c, { topic: 'economy', when: null }, '2026-11-05')).toBe(true);
    expect(matches(c, { topic: 'tech', when: null }, '2026-11-05')).toBe(false);
    expect(matches(c, { topic: null, when: 'ahead' }, '2026-11-06')).toBe(true);
    expect(matches(c, { topic: null, when: 'passed' }, '2026-11-07')).toBe(true);
    expect(matches(c, { topic: null, when: 'ahead' }, '2026-11-07')).toBe(false);
  });
});

describe('a directive’s Member States by status', () => {
  const d = directive('G', '2025-06-01', [
    row('AT', 'measures_notified', { cases: [{ id: 'INFR(2025)0001', stage: 'Reasoned opinion', date: '2026-01-01', non_communication: true, url: 'u' }] }),
    row('BE', 'none_found', { cases: [{ id: 'INFR(2025)0002', stage: 'Formal notice', date: '2025-08-01', non_communication: true, url: 'u' }] }),
    row('CY', 'not_required'),
    row('DE', 'measures_notified', { cases: [{ id: 'INFR(2025)0003', stage: 'Formal notice', date: '2025-08-01', non_communication: false, url: 'u' }] }),
    row('DK', 'not_participating'),
    row('IE', 'none_found', { participation_unknown: true }),
  ]);

  it('counts the bound Member States only, and names the others apart', () => {
    expect(statusCounts(d)).toEqual({
      bound: [
        ['measures_notified', 2],
        ['none_found', 1],
      ],
      notBound: ['DK'],
      exempt: ['CY'],
      unknown: ['IE'],
      covered: true,
    });
  });

  it('says when national measures were not queried for the directive', () => {
    expect(statusCounts(directive('H', '2025-06-01', [row('AT', 'unavailable'), row('BE', 'unavailable')])).covered).toBe(false);
  });

  it('counts the open cases for not notifying measures, not the others', () => {
    expect(openNonCommunication(d)).toBe(2);
  });
});
