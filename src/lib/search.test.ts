import { describe, expect, it } from 'vitest';
import type { SearchDoc } from '../types/data';
import { createSearchEngine, normalize } from './search';

// TEST-ONLY index: a small hand-written sample shaped like pipeline/build.py output
// (`a` = " | "-separated alternative names, `x` = keywords/identifiers). Not real site data.
const DOCS: SearchDoc[] = [
  {
    id: '2021-0106', k: 'dossier', t: 'Artificial Intelligence Act', s: '2021/0106(COD) · In force',
    a: 'AI Act | EU AI Act | AI regulation | Harmonised rules on artificial intelligence',
    x: '2021/0106(COD) 2021/0106 32024R1689 COM(2021)0206 COM(2021)206 COM/2021/206 ai',
    u: '/legislation/2021-0106', w: 3, d: '2026-08-02',
  },
  {
    id: '2022-0303', k: 'dossier', t: 'AI Liability Directive', s: '2022/0303(COD) · Withdrawn',
    a: 'AILD | AI liability', x: '2022/0303(COD) 2022/0303 ai', u: '/legislation/2022-0303', w: 3, d: '2025-03-01',
  },
  {
    id: '2012-0011', k: 'dossier', t: 'General Data Protection Regulation', s: '2012/0011(COD) · In force',
    a: 'GDPR | data protection regulation', x: '2012/0011(COD) 2012/0011 32016R0679 gdpr',
    u: '/legislation/2012-0011', w: 3, d: '2018-05-25',
  },
  {
    id: '2022-0155', k: 'dossier', t: 'Child sexual abuse regulation', s: '2022/0155(COD) · Proposed',
    a: 'CSA Regulation | CSAR | CSAM regulation | chat control', x: '2022/0155(COD) 2022/0155 csam',
    u: '/legislation/2022-0155', w: 3, d: '2025-11-26',
  },
  {
    id: '2016-0224', k: 'dossier', t: 'Asylum procedure regulation', s: '2016/0224(COD) · In force',
    x: '2016/0224(COD) 2016/0224', u: '/legislation/2016-0224', w: 1.2, d: '2024-05-22',
  },
  {
    id: '2013-0024', k: 'dossier', t: 'Air quality and cleaner air for Europe', s: '2022/0347(COD) · In force',
    x: '2022/0347(COD) 2022/0347', u: '/legislation/2013-0024', w: 1.2, d: '2024-12-10',
  },
  { id: '197443', k: 'mep', t: 'Nacho Sánchez Amor', s: 'MEP · Spain · S&D', u: '/people/meps/197443', w: 1.5 },
  { id: '124700', k: 'mep', t: 'Viola von Cramon-Taubadel', s: 'Former MEP · Germany · Greens/EFA', u: '/people/meps/124700', w: 0.7 },
  { id: '96899', k: 'mep', t: 'Esteban González Pons', s: 'MEP · Spain · EPP', u: '/people/meps/96899', w: 1.5 },
  {
    id: 'epp', k: 'group', t: "Group of the European People's Party (Christian Democrats)", s: 'Political group · 188 MEPs',
    a: "EPP | European People's Party | PPE | Christian Democrats", u: '/people/groups/epp', w: 4,
  },
  {
    id: 's-d', k: 'group', t: 'Group of the Progressive Alliance of Socialists and Democrats in the European Parliament',
    s: 'Political group · 136 MEPs', a: 'S&D | S and D | Socialists and Democrats | Socialists', u: '/people/groups/s-d', w: 4,
  },
  { id: '7001', k: 'party', t: 'Partido Popular', s: 'National party · Spain', a: 'PP', u: '/people/parties/7001', w: 1.3 },
  { id: 'ES', k: 'country', t: 'Spain', s: 'EU Member State', a: 'Spanish | Spaniard | España | ES', u: '/countries/ES', w: 5 },
  { id: 'DE', k: 'country', t: 'Germany', s: 'EU Member State', a: 'German | Deutschland | DE', u: '/countries/DE', w: 5 },
  {
    id: 'tech', k: 'topic', t: 'Technology & AI', s: 'Topic · 120 files',
    a: 'AI | artificial intelligence | digital | internet', u: '/legislation?topic=tech', w: 3,
  },
  {
    id: 'migration', k: 'topic', t: 'Migration & asylum', s: 'Topic · 40 files', a: 'migrants | asylum | refugees',
    u: '/legislation?topic=migration', w: 3,
  },
  {
    id: 'council-voting', k: 'page', t: 'How the Council votes: qualified majority and unanimity', s: 'How the EU works',
    a: 'qualified majority | QMV | unanimity | veto | blocking minority', u: '/how-the-eu-works#council-voting', w: 2,
  },
  {
    id: 'implementation', k: 'page', t: 'Transposition: how directives become national law', s: 'How the EU works',
    a: 'transposition | transpose | national measures', u: '/how-the-eu-works#implementation', w: 2,
  },
  {
    id: 'olp', k: 'page', t: 'How an EU law is made (ordinary legislative procedure)', s: 'How the EU works',
    a: 'ordinary legislative procedure | trilogue | trilogues | interinstitutional negotiations',
    u: '/how-the-eu-works#olp', w: 2,
  },
]; // prettier-ignore

const engine = createSearchEngine(DOCS);
const ids = (q: string, limit = 5) => engine.search(q, { limit }).map((h) => `${h.doc.k}:${h.doc.id}`);
const top = (q: string) => ids(q, 1)[0];

describe('normalize', () => {
  it('is case and accent insensitive', () => {
    expect(normalize('Sánchez')).toBe(normalize('SANCHEZ'));
    expect(normalize('Straße Øresund')).toBe('strasse oresund');
  });
});

describe('search ranking', () => {
  it('finds the AI Act by its common names', () => {
    expect(top('AI Act')).toBe('dossier:2021-0106');
    expect(top('ai act')).toBe('dossier:2021-0106');
    expect(top('ai law')).toBe('dossier:2021-0106');
    expect(ids('artificial intelligence', 3)).toContain('dossier:2021-0106');
    expect(top('artificial intelligence act')).toBe('dossier:2021-0106');
  });

  it('matches identifiers exactly and first', () => {
    expect(top('32024R1689')).toBe('dossier:2021-0106');
    expect(top('32024r1689')).toBe('dossier:2021-0106');
    expect(top('2021/0106(COD)')).toBe('dossier:2021-0106');
    expect(top('2021/0106')).toBe('dossier:2021-0106');
    expect(top('2021/0106 (COD)')).toBe('dossier:2021-0106');
    expect(top('COM(2021)206')).toBe('dossier:2021-0106');
    expect(engine.search('2021/0106(COD)')[0].score).toBeGreaterThan(engine.search('2021/0106(COD)')[1]?.score ?? 0);
  });

  it('finds well-known abbreviations and curated aliases', () => {
    expect(top('GDPR')).toBe('dossier:2012-0011');
    expect(top('gdpr')).toBe('dossier:2012-0011');
    expect(top('chat control')).toBe('dossier:2022-0155');
  });

  it('finds countries by name and demonym', () => {
    expect(top('Spain')).toBe('country:ES');
    expect(top('spanish')).toBe('country:ES');
    expect(top('German')).toBe('country:DE');
  });

  it('finds political groups by abbreviation', () => {
    expect(top('EPP')).toBe('group:epp');
    expect(top('S&D')).toBe('group:s-d');
    expect(top('s&d')).toBe('group:s-d');
    expect(top('socialists')).toBe('group:s-d');
  });

  it('is accent-insensitive for people', () => {
    expect(top('Sánchez')).toBe('mep:197443');
    expect(top('sanchez')).toBe('mep:197443');
    expect(top('gonzalez pons')).toBe('mep:96899');
  });

  it('tolerates small typos without outranking clear matches', () => {
    expect(top('migraton')).toBe('topic:migration');
    expect(top('artifical intelligence')).toBe('dossier:2021-0106');
    // an exact word match beats a fuzzy one
    const hits = engine.search('asylum');
    expect(hits[0].doc.id === 'migration' || hits[0].doc.id === '2016-0224').toBe(true);
  });

  it('returns nothing irrelevant for people who are not MEPs', () => {
    expect(() => engine.search('von der leyen')).not.toThrow();
    expect(ids('von der leyen')).toEqual([]);
    expect(ids('ursula von der leyen')).toEqual([]);
  });

  it('finds guide pages for procedural terms', () => {
    expect(top('qualified majority')).toBe('page:council-voting');
    expect(top('veto')).toBe('page:council-voting');
    expect(top('transposition')).toBe('page:implementation');
    expect(top('trilogue')).toBe('page:olp');
  });

  it('supports prefixes while typing', () => {
    expect(ids('artific', 3)).toContain('dossier:2021-0106');
    expect(top('Spa')).toBe('country:ES');
  });

  it('filters by kind and respects limit', () => {
    const hits = engine.search('spain', { kinds: ['mep'] });
    expect(hits.every((h) => h.doc.k === 'mep')).toBe(true);
    expect(engine.search('a', { limit: 2 }).length).toBeLessThanOrEqual(2);
    expect(engine.search('   ')).toEqual([]);
    expect(engine.search('!!!')).toEqual([]);
  });

  it('does not let static boosts override a clearly better match', () => {
    // "Air quality" must win over the boosted AI Act for an "air" query
    expect(top('air quality')).toBe('dossier:2013-0024');
  });
});
