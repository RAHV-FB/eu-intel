import { describe, expect, it } from 'vitest';
import type { ApplyingRule, RuleWhere } from '../../types/data';
import {
  addYear,
  byMonth,
  concerns,
  feedPath,
  headlineOn,
  inWindow,
  isAhead,
  monthLabel,
  participation,
  unknownNote,
  whereLead,
  windowKey,
} from './applies';

const ALL = ['AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK'];
const everywhere: RuleWhere = { bound: ALL, not_bound: [], unknown: [] };

function row(date: string, kind: ApplyingRule['kind'] = 'applies', title = 'Some provisions start to apply', where = everywhere): ApplyingRule {
  return {
    id: `32099R0001/${kind}/${date}`,
    date,
    kind,
    partial: true,
    title,
    provisions: null,
    articles: [],
    source: { institution: 'EUR-Lex', url: 'https://eur-lex.europa.eu/' },
    act: { celex: '32099R0001', label: 'Regulation (EU) 2099/1', type: 'regulation', names: [], url: 'https://eur-lex.europa.eu/' },
    dossier_id: '2099-0001',
    dossier_title: 'Testing Act',
    topics: ['tech'],
    where,
  };
}

describe('dates on the reader’s date', () => {
  it('has a date from which rules apply come on its day, and a transposition deadline pass only once its day is over', () => {
    expect(isAhead(row('2026-12-02'), '2026-12-01')).toBe(true);
    expect(isAhead(row('2026-12-02'), '2026-12-02')).toBe(false);
    expect(isAhead(row('2026-12-02', 'entry_into_force'), '2026-12-02')).toBe(false);
    expect(isAhead(row('2026-12-02', 'transposition_deadline'), '2026-12-02')).toBe(true);
    expect(isAhead(row('2026-12-02', 'transposition_deadline'), '2026-12-03')).toBe(false);
  });

  it('puts each date in the windows of the reader’s date, not of the build', () => {
    const today = '2026-11-05';
    const at = (d: string, kind: ApplyingRule['kind'] = 'applies') => ['30', '90', '12m', 'all', 'past'].filter((w) => inWindow(row(d, kind), windowKey(w), today));
    expect(at('2026-12-05')).toEqual(['30', '90', '12m', 'all']); // 30 days ahead
    expect(at('2026-12-06')).toEqual(['90', '12m', 'all']);
    expect(at('2027-02-03')).toEqual(['90', '12m', 'all']); // 90 days ahead
    expect(at('2027-02-04')).toEqual(['12m', 'all']);
    expect(at('2027-11-05')).toEqual(['12m', 'all']); // the same day a year later
    expect(at('2027-11-06')).toEqual(['all']);
    // today: a date from which rules apply has come (the last 30 days); a deadline is still ahead
    expect(at('2026-11-05')).toEqual(['past']);
    expect(at('2026-11-05', 'transposition_deadline')).toEqual(['30', '90', '12m', 'all']);
    expect(at('2026-10-06')).toEqual(['past']); // 30 days ago
    expect(at('2026-10-05')).toEqual([]);
    // a week after the build, a date of the build's next 30 days may have come: it moves to the last 30 days
    expect(inWindow(row('2026-11-10'), '30', '2026-11-05')).toBe(true);
    expect(inWindow(row('2026-11-10'), '30', '2026-11-12')).toBe(false);
    expect(inWindow(row('2026-11-10'), 'past', '2026-11-12')).toBe(true);
  });

  it('reads an unknown window in the address as the next 90 days, and counts a year to the same day', () => {
    expect([windowKey(null), windowKey('7'), windowKey('12m'), windowKey('past')]).toEqual(['90', '90', '12m', 'past']);
    expect([addYear('2026-11-05'), addYear('2028-02-29')]).toEqual(['2027-11-05', '2029-02-28']);
  });

  it('says what happens in the tense of the reader’s date', () => {
    const r = row('2026-12-02');
    expect(headlineOn(r, '2026-12-01')).toBe('Some provisions start to apply');
    expect(headlineOn(r, '2026-12-02')).toBe('Some provisions started to apply');
    expect(headlineOn(row('2026-12-02', 'entry_into_force', 'Enters into force'), '2026-12-03')).toBe('Entered into force');
    expect(headlineOn(row('2026-12-02', 'applies', 'Rules start to apply'), '2026-12-03')).toBe('Rules started to apply');
    const deadline = row('2026-12-02', 'transposition_deadline', 'Deadline for Member States to transpose the directive');
    expect(headlineOn(deadline, '2026-12-02')).toBe('Deadline for Member States to transpose the directive');
    expect(headlineOn(deadline, '2026-12-03')).toBe('Deadline for Member States to transpose the directive (passed)');
    const national = row('2026-12-02', 'national_application', 'Application date for the national measures');
    expect(headlineOn(national, '2026-12-03')).toBe('Application date for the national measures');
  });
});

describe('where', () => {
  const notDk: RuleWhere = {
    bound: ALL.filter((c) => c !== 'DK'),
    not_bound: [{ country: 'DK', reason: 'Under Protocol No 22, Denmark is not taking part in its adoption and is not bound by it (recital 63).', url: null }],
    unknown: [],
  };
  const unknownDkIe: RuleWhere = { bound: ALL.filter((c) => c !== 'DK' && c !== 'IE'), not_bound: [], unknown: ['DK', 'IE'] };
  const decision: RuleWhere = { bound: [], not_bound: [], unknown: ALL, note: 'A decision binds those to whom it is addressed.' };

  it('says “All 27 Member States” only when all 27 are bound', () => {
    expect(whereLead(everywhere)).toBe('All 27 Member States');
    expect(whereLead(notDk)).toBe('26 Member States, not Denmark');
    expect(whereLead(unknownDkIe)).toBe('25 Member States; not known for Denmark and Ireland');
    expect(whereLead(decision)).toBe('Not recorded in our data');
    // a few Member States are named
    expect(whereLead({ bound: ['AT', 'BE'], not_bound: [], unknown: ALL.slice(2) })).toMatch(/^Austria and Belgium; not known for Bulgaria, Cyprus, /);
    for (const w of [notDk, unknownDkIe, decision]) expect(whereLead(w)).not.toMatch(/\ball\b/i);
  });

  it('says why whom it binds is not known, and nothing when it is', () => {
    expect(unknownNote(everywhere)).toBeNull();
    expect(unknownNote(notDk)).toBeNull();
    expect(unknownNote(unknownDkIe)).toMatch(/Protocols No 21 and 22 .* whether Denmark and Ireland took part in this one\.$/);
    expect(unknownNote(decision)).toBe(decision.note);
  });

  it('lists for a Member State the acts that bind it and those not known to, never those that do not', () => {
    expect(participation(notDk, 'DK')).toBe('not_bound');
    expect(participation(unknownDkIe, 'IE')).toBe('unknown');
    expect(participation(notDk, 'FR')).toBe('bound');
    expect(concerns(row('2026-12-02', 'applies', 't', notDk), 'DK')).toBe(false);
    expect(concerns(row('2026-12-02', 'applies', 't', unknownDkIe), 'DK')).toBe(true);
    expect(concerns(row('2026-12-02', 'applies', 't', decision), 'FR')).toBe(true);
  });
});

describe('months and feeds', () => {
  it('groups the dates by month, the latest first for the last 30 days', () => {
    const rows = [row('2026-11-20'), row('2026-11-30'), row('2026-12-02'), row('2027-01-01')];
    expect(byMonth(rows).map((g) => [g.month, g.rows.length])).toEqual([
      ['2026-11', 2],
      ['2026-12', 1],
      ['2027-01', 1],
    ]);
    expect(byMonth(rows, true).map((g) => [g.month, g.rows.map((r) => r.date)])).toEqual([
      ['2027-01', ['2027-01-01']],
      ['2026-12', ['2026-12-02']],
      ['2026-11', ['2026-11-30', '2026-11-20']],
    ]);
    expect(monthLabel('2026-12')).toBe('December 2026');
  });

  it('subscribes to the feed and the calendar of every date, of a topic or of a Member State', () => {
    expect(feedPath({}, 'xml')).toMatch(/data\/feeds\/applies\/all\.xml$/);
    expect(feedPath({ topic: 'tech' }, 'ics')).toMatch(/data\/feeds\/applies\/topics\/tech\.ics$/);
    expect(feedPath({ topic: 'tech', country: 'IE' }, 'xml')).toMatch(/data\/feeds\/applies\/countries\/IE\.xml$/);
  });
});
