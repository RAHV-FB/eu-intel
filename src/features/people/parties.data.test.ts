/**
 * Party pages on the real build (public/data): Parliament's data keeps one record per party per term, and a party
 * page must not call a sitting MEP a former MEP because their membership of this record ended (Jordan Bardella on
 * 5494, the Rassemblement national record of 2019–2024; the Platforma Obywatelska MEPs on 6703, now under
 * Koalicja Obywatelska 7979). Skipped when the data has not been built.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { MepSummary, PartyDetail, PartySummary } from '../../types/data';
import { partyNameKey, partyRecordTitle, termYears } from './labels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('people/parties.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

it('compares party names as the build does, without spacing or punctuation', () => {
  // records 5288 (2019–2024) and 6685 (2024–2029) of the same Latvian party
  expect(partyNameKey('Nacionālā apvienība "Visu Latvijai!"-"Tēvzemei un Brīvībai/LNNK"')).toBe(
    partyNameKey('Nacionālā apvienība "Visu Latvijai!" - "Tēvzemei un Brīvībai/LNNK"'),
  );
  expect(partyNameKey('Les Républicains')).toBe('les republicains');
});

it('names a record’s term as search subtitles do', () => {
  expect(termYears([9])).toBe('2019–2024 term');
  expect(termYears([10, 9])).toBe('2019–2024 and 2024–2029 terms');
  expect(termYears([])).toBe('');
});

describe.skipIf(!built)('party records on the built data', () => {
  const meps = new Map((built ? read<MepSummary[]>('people/meps.json') : []).map((m) => [m.id, m]));
  const ids = built ? readdirSync(new URL('people/parties/', DATA)).map((f) => f.replace(/\.json$/, '')) : [];
  const parties = new Map(ids.map((id) => [id, read<PartyDetail>(`people/parties/${id}.json`)]));

  it('gives every MEP row the MEP’s own status, and a sitting MEP who left the record the record they are in now', () => {
    for (const p of parties.values())
      for (const r of p.meps) {
        expect(r.mep_active, `${p.id} ${r.id}`).toBe(meps.get(r.id)!.active);
        if (r.active) expect(r.mep_active).toBe(true);
        if (r.now_party) {
          expect(r.mep_active && !r.active, `${p.id} ${r.id}`).toBe(true);
          expect(parties.has(r.now_party)).toBe(true);
          expect(p.now_parties!.map((x) => x.id)).toContain(r.now_party);
        }
      }
  });

  it('says which term a record covers and links the same party’s other records', () => {
    const rn = parties.get('5494')!;
    expect(rn.terms).toEqual([9]);
    expect([rn.start, rn.end]).toEqual(['2019-07-02', '2024-07-15']);
    expect(rn.same_name!.map((x) => [x.id, x.terms])).toEqual([['6848', [10]]]);
    const bardella = rn.meps.find((r) => r.id === '131580')!;
    expect([bardella.active, bardella.mep_active, bardella.now_party]).toEqual([false, true, '6848']);
    expect(parties.get('6848')!.same_name!.map((x) => x.id)).toEqual(['5494']);
    // records of the same name in the same term (Azione 6103 and 6478) both list each other
    expect(parties.get('6103')!.same_name!.map((x) => x.id)).toContain('6478');
  });

  it('shows where the MEPs of a record that lost them all sit now (PO 6703 -> KO 7979)', () => {
    const po = parties.get('6703')!;
    expect(po.members_active).toBe(0);
    expect(po.now_parties![0]).toMatchObject({ id: '7979', label: 'Koalicja Obywatelska', meps: 18 });
  });

  it('counts, next to a record’s current MEPs, those now under another record: together they are its “Current MEP” rows', () => {
    // Platforma Obywatelska 6703: 0 in the record and 18 under Koalicja Obywatelska; RN 6848: 29 and Malika Sorel
    let open = 0;
    for (const p of parties.values()) {
      if (p.end && p.members_active === 0) continue; // a closed record shows its period, not current MEPs
      open++;
      const current = p.meps.filter((r) => r.active || r.mep_active).length;
      const elsewhere = (p.now_parties ?? []).reduce((n, r) => n + (r.meps ?? 0), 0);
      expect(p.members_active + elsewhere, p.id).toBe(current);
    }
    expect(open).toBeGreaterThan(200);
    const po = parties.get('6703')!;
    expect([po.members_active, po.now_parties![0].meps]).toEqual([0, 18]);
  });

  it('states a membership that runs outside the record’s own period (PSD 5320 ends on 15 Jul 2024; Dan Nica from 16 Jul 2024)', () => {
    const psd = parties.get('5320')!;
    expect([psd.start, psd.end, psd.terms]).toEqual(['2019-07-02', '2024-07-15', [9, 10]]);
    expect(psd.outside_period).toEqual([{ id: '124784', name: 'Dan Nica', from: '2024-07-16', to: null }]);
    expect([...parties.values()].filter((p) => p.outside_period?.length).map((p) => p.id)).toEqual(['5320']);
  });

  it('gives records of the same party different page titles: the term, and the period when they share it', () => {
    expect(partyRecordTitle(parties.get('5494')!)).toBe('Rassemblement national (France, 2019–2024 term)');
    expect(partyRecordTitle(parties.get('6848')!)).toBe('Rassemblement national (France, 2024–2029 term)');
    expect(partyRecordTitle(parties.get('6103')!)).toBe('Azione (Italy, 2019–2024 term, 20 Nov 2019 – 8 Nov 2022)');
    expect(partyRecordTitle(parties.get('6478')!)).toBe('Azione (Italy, 2019–2024 term, 6 Dec 2023 – 15 Jul 2024)');
    expect(partyRecordTitle(parties.get('7952')!)).toBe('GroenLinks-PvdA (Netherlands)'); // no other record of that name
    const titles = new Map<string, string[]>();
    for (const p of parties.values()) titles.set(partyRecordTitle(p), [...(titles.get(partyRecordTitle(p)) ?? []), p.id]);
    expect([...titles].filter(([, ids]) => ids.length > 1)).toEqual([]);
    // the records the build lists as having the same name are the ones the names compare equal for
    for (const p of parties.values())
      for (const r of p.same_name ?? []) expect(partyNameKey(r.label), `${p.id} ${r.id}`).toBe(partyNameKey(p.label));
  });

  it('builds a page for every party an MEP page links, including the two without a recorded name', () => {
    const listed = new Set(read<PartySummary[]>('people/parties.json').map((p) => p.id));
    expect(listed.has('5719') || listed.has('5500')).toBe(false);
    expect(parties.has('5719') && parties.has('5500')).toBe(true);
    for (const p of read<PartySummary[]>('people/parties.json')) expect(p.terms?.length, p.id).toBeGreaterThan(0);
  });
});
