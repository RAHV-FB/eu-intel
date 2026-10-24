/**
 * The political groups' names shown when people/groups.json cannot be loaded (GROUP_FALLBACK) are those of the built data;
 * every role code of the built MEP pages has a label; a former MEP's group is named as it was when they left.
 * Skipped when the data has not been built.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { GroupSummary, MepDetail, MepSummary } from '../../types/data';
import { GROUP_FALLBACK, ROLE_LABEL, partySeating, roleLabel } from './labels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('people/groups.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

it('labels group roles as the EP roles vocabulary does', () => {
  // https://data.europarl.europa.eu/def/ep-roles/CHAIR_VICE_FIRST and .../CHAIR_VICE_BUREAU_TREASURER (English labels)
  expect(roleLabel('CHAIR_VICE_FIRST')).toBe('First Vice-Chair'); // was "Chair vice first"
  expect(roleLabel('CHAIR_VICE_BUREAU_TREASURER')).toBe('Treasurer/Vice-Chair/Member of the Bureau');
});

it('tells political groups from the non-attached members, who form no group', () => {
  expect(partySeating(['ni'])).toBe('non-attached');
  expect(partySeating(['epp', 'ni'])).toBe('both');
  expect(partySeating(['renew', 'epp'])).toBe('groups');
  expect(partySeating([])).toBeNull();
});

describe.skipIf(!built)('MEP pages on the built data', () => {
  const meps = built ? read<MepSummary[]>('people/meps.json') : [];
  const files = built ? readdirSync(new URL('people/meps/', DATA)) : [];
  const details = files.map((f) => read<MepDetail>(`people/meps/${f}`));

  it('has a label of its own for every role code, not one made from the code', () => {
    const codes = new Set(details.flatMap((m) => [...m.groups, ...m.committees, ...m.parties].map((p) => p.role).filter(Boolean)));
    expect(codes.size).toBeGreaterThan(5);
    for (const c of codes) expect(ROLE_LABEL[c!], c!).toBeDefined();
  });

  it('names a former MEP’s last group as it was then: GUE/NGL for those who left before it became The Left', () => {
    // Martina Anderson (113959) left on 31 Jan 2020: "last recorded group: The Left"
    const anderson = meps.find((m) => m.id === '113959')!;
    expect([anderson.group, anderson.group_code]).toEqual(['the-left', 'GUE/NGL']);
    const byId = new Map(details.map((m) => [m.id, m]));
    for (const m of meps) {
      const groups = byId.get(m.id)!.groups;
      if (!groups.length) continue;
      const ongoing = groups.filter((g) => !g.to);
      const last = ongoing.length
        ? ongoing.reduce((a, b) => ((b.from ?? '') > (a.from ?? '') ? b : a))
        : groups.reduce((a, b) => ((b.to ?? '') > (a.to ?? '') ? b : a));
      expect(m.group_code, m.id).toBe(last.code ?? last.label);
    }
  });
});

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
