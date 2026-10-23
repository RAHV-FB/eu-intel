/**
 * Vote lists on the real build (public/data from `python -m pipeline build`): the home page's "Close votes" and
 * "Rejected" lists must deliver what their titles and the /votes page say. Skipped when the data has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { EpVoteSummary, HomeData } from '../../types/data';
import { isClose } from './labels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('home.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe('close votes', () => {
  const margin = { rule: 'votes_cast', rule_label: '', threshold: 301, distance: 10, relative: 0.0164, label: '' } as const;
  it('needs an established outcome as well as a margin', () => {
    expect(isClose({ margin, outcome: 'adopted' })).toBe(true);
    expect(isClose({ margin, outcome: 'unknown' })).toBe(false);
    expect(isClose({ margin, outcome: 'lapsed' })).toBe(false);
    expect(isClose({ margin: null, outcome: 'adopted' })).toBe(false);
  });
});

describe.skipIf(!built)('home vote lists on the built data', () => {
  const home = built ? read<HomeData>('home.json') : { lists: [], featured: [], topics: [] };
  const votes = new Map((built ? read<EpVoteSummary[]>('votes/index.json') : []).map((v) => [v.id, v]));
  const list = (id: string) => home.lists.find((l) => l.id === id)!;

  it('lists as close only votes the /votes page marks close (193557 was the only one of the ten in Oct 2026)', () => {
    const items = list('close_votes').items;
    expect(items.length).toBeGreaterThan(0);
    for (const it of items) {
      const v = votes.get(it.vote_id!)!;
      expect(v.kind, it.vote_id!).toBe('final');
      expect(isClose(v), it.vote_id!).toBe(true);
    }
    expect(items[0].vote_id).toBe('193557');
  });

  it('lists what Parliament rejected, not rejected objections or censure motions', () => {
    const items = list('rejected').items;
    const ids = items.map((i) => i.vote_id);
    for (const it of items.filter((i) => i.vote_id)) {
      const v = votes.get(it.vote_id!)!;
      const rejectsProposal = (v.kind_detail === 'reject_proposal' || v.kind_detail === 'reject_council_position') && v.outcome === 'adopted';
      expect(rejectsProposal || (v.kind === 'final' && v.outcome === 'rejected'), it.vote_id!).toBe(true);
    }
    // the one Commission proposal Parliament rejected by a motion (2023/0413(COD), 21 Oct 2025) leads to its file
    expect(items.find((i) => i.vote_id === '179804')?.dossier_id).toBe('2023-0413');
    // rejected at first reading, then adopted after the second reading (Regulation (EU) 2026/1881)
    expect(items.find((i) => i.vote_id === '189270')?.subtitle).toContain('the act was adopted on 23 July 2026');
    // a consultation opinion is not binding on the Council
    expect(items.find((i) => i.vote_id === '193822')?.subtitle).toContain('opinion is not binding');
    expect(ids).not.toContain('198885'); // a rejected objection: the Commission measure stands
    expect(ids).not.toContain('183538'); // a rejected motion of censure
  });

  it('never shows a margin label that reads as a law passing', () => {
    for (const v of votes.values()) if (v.margin) expect(v.margin.label, v.id).toMatch(/^Majority (reached|not reached)/);
  });
});
