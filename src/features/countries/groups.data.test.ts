/**
 * The number of political groups a country's MEPs sit in (country pages and the Countries table): the non-attached
 * members (NI) are not a group, so France, with 1 NI MEP, has 8 groups, not 9. Data checks are skipped when the data
 * has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CountrySummary, GroupSummary } from '../../types/data';
import { politicalGroupCount } from './CountryTable';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('countries/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

it('does not count the non-attached members as a group', () => {
  expect(politicalGroupCount({ epp: 10, 's-d': 3, ni: 1 })).toBe(2);
  expect(politicalGroupCount({ epp: 10, renew: 0 })).toBe(1);
});

describe.skipIf(!built)('political groups by country on the built data', () => {
  const countries = built ? read<CountrySummary[]>('countries/index.json') : [];
  const by = new Map(countries.map((c) => [c.code, c]));

  it('gives France 8 groups and 1 non-attached MEP, and Italy, with no NI MEP, 8 groups', () => {
    expect(politicalGroupCount(by.get('FR')!.groups)).toBe(8);
    expect(by.get('FR')!.groups.ni).toBe(1);
    expect(politicalGroupCount(by.get('IT')!.groups)).toBe(8);
    expect(by.get('IT')!.groups.ni ?? 0).toBe(0);
  });

  it('never counts more groups for a country than Parliament has today', () => {
    const groups = read<GroupSummary[]>('people/groups.json').filter((g) => g.active && g.members > 0 && g.id !== 'ni');
    for (const c of countries) expect(politicalGroupCount(c.groups), c.code).toBeLessThanOrEqual(groups.length);
    expect(countries.filter((c) => (c.groups.ni ?? 0) > 0).length).toBeGreaterThan(5);
  });
});
