/**
 * What changed on the real build (public/data/activity.json): every item told once, a status change with the step of
 * its file and day, what happened named apart from the file's title. Skipped when the data has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ActivityItem, DossierSummary } from '../../types/data';
import { changesOf, latestChanges } from './changes';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('activity.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe.skipIf(!built)('What changed on the built data', () => {
  const items = built ? read<ActivityItem[]>('activity.json') : [];
  const files = new Map((built ? read<DossierSummary[]>('dossiers/index.json') : []).map((d) => [d.id, d]));
  const byId = new Map(items.map((i) => [i.id, i]));

  it('pairs a status change only with a step of the same file and day', () => {
    const paired = items.filter((i) => i.step_id);
    for (const s of paired) {
      const step = byId.get(s.step_id!);
      expect(s.kind, s.id).toBe('status_change');
      expect(step, s.id).toBeDefined();
      expect([step!.dossier_id, step!.date], s.id).toEqual([s.dossier_id, s.date]);
      expect(step!.kind, s.id).not.toBe('status_change');
    }
    // one step for one status change
    expect(new Set(paired.map((s) => s.step_id)).size).toBe(paired.length);
  });

  it('tells every item once, and each change of a file links a file of the dataset', () => {
    const cs = changesOf(items);
    const told = new Set(items.filter((i) => i.step_id && byId.has(i.step_id)).map((i) => i.step_id));
    expect(cs).toHaveLength(items.length - told.size);
    expect(new Set(cs.map((c) => c.id)).size).toBe(cs.length);
    for (const c of cs) {
      if (c.dossierId) expect(files.has(c.dossierId), c.id).toBe(true);
      // what happened, or the headline of a vote; never nothing
      expect(c.event ?? c.status?.now ?? c.headline, c.id).toBeTruthy();
      expect(c.sources.every((s) => /^https:\/\//.test(s.url)), c.id).toBe(true);
    }
  });

  it('names what happened apart from the file’s title in every headline of a file’s step', () => {
    for (const i of items.filter((x) => x.dossier_id && x.kind !== 'ep_vote' && x.kind !== 'council_vote')) {
      expect(i.event, i.id).toBeTruthy();
      if (i.kind !== 'new_dossier' && i.kind !== 'status_change') expect(i.title.endsWith(`: ${i.event}`), i.id).toBe(true);
    }
  });

  it('has changes for the home page’s strip', () => {
    const l = latestChanges(changesOf(items), Date.parse(read<{ built_at: string }>('meta.json').built_at));
    expect(l.changes.length).toBeGreaterThan(0);
  });
});
