import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, DossierSummary, HomeData } from '../types/data';
import { asOfToday, stillAhead } from './format';

// What happens next for the Consumer Credit Directive (2021/0171(COD), Directive (EU) 2023/2225) in the build of
// 23 October 2026. Art. 48(1): Member States "shall apply those measures from 20 November 2026".
const CCD =
  'The transposition deadline (20 November 2025) has passed: the Member States bound by the directive were required to ' +
  'adopt national measures by then. The national measures are to apply from 20 November 2026.';

describe('dated statements on the visitor’s date', () => {
  it('keeps a sentence whose date is still ahead', () => {
    expect(asOfToday(CCD, '2026-11-19')).toBe(CCD);
  });

  it('puts it in the past tense from that date on, as the build would', () => {
    // a build of 16 November 2026, read on 22 November, said "are to apply from 20 November 2026"
    const past = CCD.replace('are to apply', 'were to apply');
    expect(asOfToday(CCD, '2026-11-20')).toBe(past);
    expect(asOfToday(CCD, '2026-11-22')).toBe(past);
    expect(asOfToday(`${CCD.slice(0, -1)} at the latest.`, '2026-11-22')).toBe(`${past.slice(0, -1)} at the latest.`);
  });

  it('turns a transposition deadline and an entry into force that have passed into the build’s past wording', () => {
    expect(asOfToday('The Member States bound by the directive must transpose it into national law by 9 December 2026.', '2026-12-09')).toBe(
      'The transposition deadline (9 December 2026) has passed: the Member States bound by the directive were required to adopt national measures by then.',
    );
    // with exceptions in the directive's text (data/curated/transposition.yaml `exceptions`), which follow unchanged
    const tail = ' Under Art. 33(4), the obligation to transpose and implement the directive does not apply to Cyprus and Malta.';
    expect(
      asOfToday(`The Member States bound by the directive must transpose it into national law by 9 December 2026, except as its text provides.${tail}`, '2026-12-10'),
    ).toBe(
      `The transposition deadline (9 December 2026) has passed: the Member States bound by the directive were required to adopt national measures by then, except as its text provides.${tail}`,
    );
    expect(asOfToday('The act enters into force on 2 December 2026. More.', '2026-12-03')).toBe(
      'The act entered into force on 2 December 2026. More.',
    );
    expect(asOfToday('The act enters into force on 2 December 2026.', '2026-12-01')).toBe(
      'The act enters into force on 2 December 2026.',
    );
  });

  it('leaves out of "Coming up" the dates that have passed', () => {
    const items = [{ date: '2026-11-20' }, { date: '2026-11-21' }, { date: '2026-12-02' }, { date: null }];
    expect(stillAhead(items, '2026-11-20')).toEqual([{ date: '2026-11-21' }, { date: '2026-12-02' }]);
  });
});

const DATA = new URL('../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;
const DATED_FUTURE = /(enters into force on|must transpose it into national law by|are to apply from) \d{1,2} [A-Z][a-z]+ \d{4}/;

describe.skipIf(!built)('dated statements in the built data', () => {
  it('has no next step left in the future tense once its dates have passed', () => {
    // the build's wording must stay what asOfToday() recognises (pipeline/analysis/status.py, next steps)
    const index = read<DossierSummary[]>('dossiers/index.json');
    let dated = 0;
    for (const d of index) {
      const text = read<DossierDetail>(`dossiers/${d.id}.json`).next_step.text;
      if (DATED_FUTURE.test(text)) dated += 1;
      expect(asOfToday(text, '2100-01-01'), d.id).not.toMatch(DATED_FUTURE);
    }
    expect(dated).toBeGreaterThan(0);
  });

  it('has only dates still ahead of the build in "Coming up"', () => {
    const home = read<HomeData>('home.json');
    const upcoming = home.lists.find((l) => l.id === 'upcoming')!.items;
    const first = upcoming[0]?.date ?? '';
    expect(stillAhead(upcoming, '2000-01-01')).toEqual(upcoming);
    expect(stillAhead(upcoming, first).length).toBeLessThan(upcoming.length);
  });
});
