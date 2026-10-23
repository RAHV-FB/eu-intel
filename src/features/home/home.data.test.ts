/**
 * Home lists and the activity feed on the real build (public/data from `python -m pipeline build`). Skipped when the
 * data has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ActivityItem, EpVoteSummary, HomeData } from '../../types/data';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('home.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

/** A decision on discharge for the EU budget (procedure DEC, "Discharge 2020: …", "2019 Discharge: …"). */
const isDischarge = (v: EpVoteSummary) =>
  (v.procedure_ref ?? '').endsWith('(DEC)') || /^(discharge \d{4}|\d{4} discharge)\b/i.test(v.display_title);

describe.skipIf(!built)('home lists and feed on the built data', () => {
  const home = built ? read<HomeData>('home.json') : { lists: [], featured: [], topics: [] };
  const votes = new Map((built ? read<EpVoteSummary[]>('votes/index.json') : []).map((v) => [v.id, v]));
  const activity = built ? read<ActivityItem[]>('activity.json') : [];
  const list = (id: string) => home.lists.find((l) => l.id === id)!;

  it('keeps discharge decisions out of the lists of votes on texts (142787 granted discharge, 149084 refused it)', () => {
    for (const id of ['close_votes', 'rejected']) {
      for (const it of list(id).items.filter((i) => i.vote_id)) expect(isDischarge(votes.get(it.vote_id!)!), it.vote_id!).toBe(false);
    }
    const ids = [...list('close_votes').items, ...list('rejected').items].map((i) => i.vote_id);
    expect(ids).not.toContain('142787');
    expect(ids).not.toContain('149084');
  });

  it('names the procedure in plain words on the "Under discussion" list, not by its code', () => {
    const items = list('under_debate').items;
    expect(items.length).toBeGreaterThan(0);
    for (const it of items) expect(it.badge ?? '', it.dossier_id!).not.toMatch(/^[A-Z]{3}$/);
  });

  it('says on the EUDR card that EUR-Lex lists an amending act the latest step does not include', () => {
    const eudr = home.featured.find((f) => f.dossier.id === '2021-0366');
    if (eudr) expect(eudr.latest_note ?? '').toContain('Regulation 2026/2102');
  });

  it('lists the officially blocked files in a stated order and says how many of them it shows', () => {
    const stalled = list('stalled');
    const blocked = stalled.items.filter((i) => i.badge === 'Officially blocked');
    const total = read<{ id: string; officially_blocked?: boolean }[]>('dossiers/index.json').filter((d) => d.officially_blocked).length;
    expect(blocked.length).toBeGreaterThan(0);
    if (blocked.length < total) expect(stalled.description).toContain(`${blocked.length} of ${total} shown`);
    // the same Train date for all: the longest without a recorded procedural step (the date shown) first
    const asOf = (i: (typeof blocked)[number]) => /as of (.+)\)$/.exec(i.subtitle ?? '')?.[1];
    for (let k = 1; k < blocked.length; k++)
      if (asOf(blocked[k]) === asOf(blocked[k - 1])) expect(blocked[k - 1].date! <= blocked[k].date!, blocked[k].dossier_id!).toBe(true);
  });

  it('gives no two activity items the same date and headline (motions 195775 and 195807 of 9 July 2026)', () => {
    const seen = new Map<string, string>();
    for (const it of activity) {
      const key = `${it.date} ${it.title}`;
      expect(seen.get(key), it.id).toBeUndefined();
      seen.set(key, it.id);
    }
  });

  it('headlines a motion to reject by what became of the text', () => {
    for (const it of activity.filter((i) => i.kind === 'ep_vote' && i.vote_id)) {
      const v = votes.get(it.vote_id!);
      if (v?.kind_detail === 'reject_proposal' || v?.kind_detail === 'reject_council_position') {
        expect(it.title, it.id).toMatch(/^Parliament (did not reject|rejected) the (Commission proposal|Council's position): /);
      }
    }
    const methane = activity.find((i) => i.id === 'vote:199567');
    if (methane) expect(methane.title).toMatch(/^Parliament did not reject the Commission proposal: Reduction of methane emissions/);
  });
});
