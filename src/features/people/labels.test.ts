/**
 * The political groups' names shown when people/groups.json cannot be loaded (GROUP_FALLBACK) are those of the built data.
 * Skipped when the data has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { GroupSummary } from '../../types/data';
import { GROUP_FALLBACK } from './labels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('people/groups.json', DATA));

describe.skipIf(!built)('GROUP_FALLBACK on the built data', () => {
  it('has the slug, code and official name of every group in people/groups.json, and no other', () => {
    // a group that appears with a new term needs an entry here, or the pages show its slug when groups.json fails to load
    const groups = JSON.parse(readFileSync(new URL('people/groups.json', DATA), 'utf8')) as GroupSummary[];
    const key = (g: { id: string }) => g.id;
    expect([...GROUP_FALLBACK].sort((a, b) => key(a).localeCompare(key(b)))).toEqual(
      groups.map((g) => ({ id: g.id, code: g.code, name: g.name })).sort((a, b) => key(a).localeCompare(key(b))),
    );
  });
});
