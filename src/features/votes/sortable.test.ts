import { describe, expect, it } from 'vitest';
import { compareValues } from './sortable';

describe('sortable tables', () => {
  it('sort names case- and accent-insensitively in English order, numbers by value and empty cells last', () => {
    // TEST-ONLY values shaped like the ballot and MEP tables (names, country names, group codes, positions)
    const names = ['Łukasz Kohut', 'Iratxe García Pérez', 'iratxe garcia', 'Zorrinho', 'Ábel Kovács', 'de Lange', 'De Lange', 'Österreich'];
    const sorted = [...names].sort((a, b) => compareValues(a, b, 'asc'));
    expect(sorted).toEqual([...names].sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' })));
    expect(compareValues('García', 'garcia', 'asc')).toBe(0);
    expect([3, null, 1, Number.NaN, 2].sort((a, b) => compareValues(a, b, 'desc'))).toEqual([3, 2, 1, null, Number.NaN]);
    expect(['b', undefined, 'a'].sort((a, b) => compareValues(a, b, 'asc'))).toEqual(['a', 'b', undefined]);
  });
});
