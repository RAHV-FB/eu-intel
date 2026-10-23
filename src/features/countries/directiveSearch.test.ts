/**
 * Country pages' directive search: by the directive's own number however it is written, and by the names its
 * file is known by. On the real build (public/data) when present: Ireland's rows, where "NIS2", "2022/2555" and
 * "Directive (EU) 2022/2555" used to find nothing and "2022/2464" found only the act amending the CSRD.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CountryDetail } from '../../types/data';
import { directiveNumber, matchDirectives, queryNumber } from './directiveSearch';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('countries/IE.json', DATA));

describe('act numbers', () => {
  it('reads the number a query names, however it is written', () => {
    expect(queryNumber('2022/2555')).toBe('2022/2555');
    expect(queryNumber('Directive (EU) 2022/2555')).toBe('2022/2555');
    expect(queryNumber('Directive 2014/35/EU')).toBe('2014/35');
    expect(queryNumber('32022L2555')).toBe('2022/2555');
    expect(queryNumber('Directive 93/13/EEC')).toBe('1993/13');
    expect(queryNumber('NIS2')).toBeNull();
    expect(queryNumber('cybersecurity')).toBeNull();
  });
  it("reads a directive's own number from its CELEX id", () => {
    expect(directiveNumber('32022L2555')).toBe('2022/2555');
    expect(directiveNumber('32014L0035')).toBe('2014/35');
    expect(directiveNumber('32024R1689')).toBeNull();
  });
});

describe('matching', () => {
  const rows = [
    { celex: '32022L2555', title: 'Measures for a high common level of cybersecurity across the Union, repealing Directive (EU) 2016/1148', act: 'Directive (EU) 2022/2555', names: ['NIS 2 Directive'] },
    { celex: '32022L2464', title: 'Corporate Sustainability Reporting Directive', act: 'Directive (EU) 2022/2464', names: [] },
    { celex: '32025L0794', title: 'Amending Directives (EU) 2022/2464 and (EU) 2024/1760 as regards the dates', act: 'Directive (EU) 2025/794', names: [] },
  ];
  const ids = (q: string) => matchDirectives(rows, q).rows.map((r) => r.celex);
  it('finds a directive by its common name, also written without a space', () => {
    expect(ids('NIS2')).toEqual(['32022L2555']);
    expect(ids('nis 2')).toEqual(['32022L2555']);
  });
  it('finds a directive by its own number and marks the acts whose titles only cite it', () => {
    const m = matchDirectives(rows, 'Directive (EU) 2022/2464');
    expect(m.rows.map((r) => r.celex)).toEqual(['32022L2464', '32025L0794']);
    expect([...m.own]).toEqual(['32022L2464']);
    expect([...m.citing]).toEqual(['32025L0794']);
    expect(ids('2016/1148')).toEqual(['32022L2555']); // only the act repealing it is in the list
    expect(matchDirectives(rows, '2016/1148').citing.has('32022L2555')).toBe(true);
  });
  it('does not take a regulation of the same number for the directive', () => {
    expect(matchDirectives(rows, 'Regulation (EU) 2022/2464').own.size).toBe(0);
  });
  it('matches files the site search found for the query', () => {
    const withFile = [{ ...rows[1], dossier_id: '2021-0104' }];
    expect(matchDirectives(withFile, 'ESG reporting', new Set(['2021-0104'])).rows).toHaveLength(1);
    expect(matchDirectives(withFile, 'ESG reporting', null).rows).toHaveLength(0);
  });
});

describe.skipIf(!built)('Ireland on the built data', () => {
  const ie = built ? (JSON.parse(readFileSync(new URL('countries/IE.json', DATA), 'utf8')) as CountryDetail) : null;
  const rows = ie?.transposition ?? [];
  const first = (q: string) => matchDirectives(rows, q).rows.filter((r) => matchDirectives(rows, q).own.has(r.celex))[0]?.celex;
  it('carries each directive’s own number as its title cites it', () => {
    const nis2 = rows.find((r) => r.celex === '32022L2555')!;
    expect(nis2.act).toBe('Directive (EU) 2022/2555');
    expect(nis2.names).toContain('NIS 2 Directive');
    expect(rows.find((r) => r.celex === '32014L0035')!.act).toBe('Directive 2014/35/EU'); // not "Directive (EU) 2014/35"
    expect(rows.filter((r) => !r.act).map((r) => r.celex)).toEqual([]);
  });
  it('finds NIS 2 however it is searched for', () => {
    for (const q of ['NIS2', 'NIS 2', '2022/2555', 'Directive (EU) 2022/2555', 'Directive 2022/2555', '32022L2555', 'cybersecurity'])
      expect(matchDirectives(rows, q).rows.map((r) => r.celex), q).toContain('32022L2555');
  });
  it('lists the directive whose number was searched for first, not only the acts amending it', () => {
    expect(first('2022/2464')).toBe('32022L2464'); // CSRD, not 32025L0794
    expect(first('2018/2001')).toBe('32018L2001'); // RED II, not 32023L2413 / 32024L1711
    expect(first('2015/2366')).toBe('32015L2366'); // PSD2, not 32022L2556
    expect(first('Directive 2014/35/EU')).toBe('32014L0035');
  });
});
