import { describe, expect, it } from 'vitest';
import type { SearchDoc } from '../types/data';
import { createSearchEngine, familyStems, hasWord, keywordTokens, normalize, singular, wordSet } from './search';

// TEST-ONLY index: a small hand-written sample shaped like pipeline/build.py output
// (`a` = " | "-separated alternative names, `x` = keywords/identifiers). Not real site data.
const DOCS: SearchDoc[] = [
  {
    id: '2021-0106', k: 'dossier', t: 'Artificial Intelligence Act', s: '2021/0106(COD) · In force',
    a: 'AI Act | EU AI Act | AI regulation | Harmonised rules on artificial intelligence',
    x: '2021/0106(COD) 2021/0106 32024R1689 2024/1689 COM(2021)0206 COM(2021)206 COM/2021/206 ai',
    u: '/legislation/2021-0106', w: 3, d: '2026-08-02',
  },
  {
    id: '2025-0404', k: 'dossier', t: 'Amending Regulations (EU) 2017/745 and (EU) 2024/1689 as regards medical devices',
    s: '2025/0404(COD) · Proposed', x: '2025/0404(COD) 2025/0404', u: '/legislation/2025-0404', w: 1.2, d: '2026-09-01',
  },
  {
    id: '2020-0353', k: 'dossier', t: 'Batteries and waste batteries', s: '2020/0353(COD) · In force',
    a: 'New Batteries Regulation', x: '2020/0353(COD) 2020/0353 32023R1542 2023/1542', u: '/legislation/2020-0353', w: 1.2,
    d: '2025-08-18',
  },
  {
    id: '2021-0197', k: 'dossier', t: 'CO2 emission performance standards for new passenger cars and vans',
    s: '2021/0197(COD) · In force', x: '2021/0197(COD) 2021/0197 32023R0851 2023/851 co2', u: '/legislation/2021-0197',
    w: 1.2, d: '2023-05-15',
  },
  {
    id: '2018-0136', k: 'dossier', t: "Protection of the Union's budget in case of generalised deficiencies as regards the rule of law",
    s: '2018/0136(COD) · In force', x: '2018/0136(COD) 2018/0136', u: '/legislation/2018-0136', w: 1.2, d: '2020-12-22',
  },
  {
    id: '2025-0059', k: 'dossier', t: 'Return Regulation', s: '2025/0059(COD) · In force',
    a: 'Returns regulation | Common system for returns, repealing Directive 2008/115/EC', x: '2025/0059(COD) 2025/0059',
    u: '/legislation/2025-0059', w: 3, d: '2026-06-01',
  },
  {
    id: '2017-0143', k: 'dossier', t: 'Pan-European Personal Pension Product', s: '2017/0143(COD) · In force',
    a: 'PEPP', x: '2017/0143(COD) 2017/0143', u: '/legislation/2017-0143', w: 1.2, d: '2022-03-22',
  },
  {
    id: '2013-0255', k: 'dossier', t: "Establishment of the European Public Prosecutor's Office ('the EPPO')",
    s: '2013/0255(APP) · In force', x: '2013/0255(APP) 2013/0255', u: '/legislation/2013-0255', w: 1.2, d: '2017-10-31',
  },
  {
    id: '2020-0163', k: 'dossier', t: 'AIEM tax in the Canary Islands', s: '2020/0163(CNS) · In force',
    x: '2020/0163(CNS) 2020/0163', u: '/legislation/2020-0163', w: 0.8, d: '2020-12-01',
  },
  {
    id: '2023-0131', k: 'dossier', t: 'Union procedures for the authorisation of medicinal products for human use',
    s: '2023/0131(COD) · Negotiations', a: 'pharmaceutical package | Pharmaceutical Regulation',
    x: '2023/0131(COD) 2023/0131', u: '/legislation/2023-0131', w: 1.2, d: '2026-10-12',
  },
  { id: '6915', k: 'party', t: 'Alianța pentru Unirea Românilor', s: 'National party · Romania', a: 'AUR', u: '/people/parties/6915', w: 1.3 },
  { id: '6702', k: 'party', t: 'Prawo i Sprawiedliwość', s: 'National party · Poland', a: 'PiS', u: '/people/parties/6702', w: 1.3 },
  { id: '257071', k: 'mep', t: 'Carla Tavares', s: 'MEP · Portugal · S&D', u: '/people/meps/257071', w: 1.5 },
  { id: '97133', k: 'mep', t: 'Derk Jan Eppink', s: 'Former MEP · Netherlands · ECR', u: '/people/meps/97133', w: 0.7 },
  { id: '204414', k: 'mep', t: 'Margarita de la Pisa Carrión', s: 'MEP · Spain · PfE', u: '/people/meps/204414', w: 1.5 },
  {
    id: 'transport', k: 'topic', t: 'Transport', s: 'Topic · 149 files', a: 'air passengers | cars | rail | trains',
    u: '/legislation?topic=transport', w: 3,
  },
  {
    id: 'rights', k: 'topic', t: 'Rights & Justice', s: 'Topic · 161 files', a: 'rule of law | fundamental rights',
    u: '/legislation?topic=rights', w: 3,
  },
  {
    id: 'instruments', k: 'page', t: 'Regulations, directives and decisions', s: 'How the EU works',
    a: 'regulation | directive | decision | legal act', u: '/how-the-eu-works#instruments', w: 2,
  },
  {
    id: '2022-0303', k: 'dossier', t: 'AI Liability Directive', s: '2022/0303(COD) · Withdrawn',
    a: 'AILD | AI liability', x: '2022/0303(COD) 2022/0303 ai', u: '/legislation/2022-0303', w: 3, d: '2025-03-01',
  },
  {
    id: '2012-0011', k: 'dossier', t: 'General Data Protection Regulation', s: '2012/0011(COD) · In force',
    a: 'GDPR | data protection regulation', x: '2012/0011(COD) 2012/0011 32016R0679 2016/679 gdpr',
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
  {
    id: '2018-0074', k: 'dossier', t: 'Multiannual plan for fish stocks in the Western Waters and adjacent waters',
    s: '2018/0074(COD) · In force', x: '2018/0074(COD) 2018/0074', u: '/legislation/2018-0074', w: 1.2, d: '2019-03-20',
  },
  {
    id: '2018-0193', k: 'dossier', t: 'Fisheries control', s: '2018/0193(COD) · In force', x: '2018/0193(COD) 2018/0193',
    u: '/legislation/2018-0193', w: 1.2, d: '2024-01-09',
  },
  {
    id: '2020-0359', k: 'dossier', t: 'Measures for a high common level of cybersecurity across the Union',
    s: '2020/0359(COD) · In force', x: '2020/0359(COD) 2020/0359', u: '/legislation/2020-0359', w: 1.2, d: '2024-10-18',
  },
  {
    id: '2016-0030', k: 'dossier', t: 'Measures to safeguard the security of gas supply', s: '2016/0030(COD) · In force',
    x: '2016/0030(COD) 2016/0030', u: '/legislation/2016-0030', w: 1.2, d: '2017-11-01',
  },
  {
    id: '2022-0272', k: 'dossier', t: 'Horizontal cybersecurity requirements for products with digital elements',
    s: '2022/0272(COD) · In force', a: 'Cyber Resilience Act', x: '2022/0272(COD) 2022/0272',
    u: '/legislation/2022-0272', w: 1.2, d: '2024-12-10',
  },
  {
    id: '2023-0212', k: 'dossier', t: 'Digital euro', s: '2023/0212(COD) · Negotiations', x: '2023/0212(COD) 2023/0212',
    u: '/legislation/2023-0212', w: 3, d: '2026-06-01',
  },
  {
    id: '2013-0256', k: 'dossier', t: 'EU Agency for Criminal Justice Cooperation (Eurojust)', s: '2013/0256(COD) · In force',
    x: '2013/0256(COD) 2013/0256', u: '/legislation/2013-0256', w: 1.2, d: '2018-12-11',
  },
  {
    id: '2018-0196', k: 'dossier', t: 'Common provisions on the funds, and financial rules for those and for the Asylum and Migration Fund',
    s: '2018/0196(COD) · In force', x: '2018/0196(COD) 2018/0196', u: '/legislation/2018-0196', w: 1.2, d: '2021-06-30',
  },
  {
    id: '2012-0361', k: 'dossier', t: 'Occurrence reporting in civil aviation', s: '2012/0361(COD) · In force',
    x: '2012/0361(COD) 2012/0361 32014R0376 376/2014', u: '/legislation/2012-0361', w: 1.2, d: '2018-08-22',
  },
  {
    id: '2014-0064', k: 'dossier', t: 'Authorisation for Portugal to apply a reduced rate of excise duty in Madeira and the Azores',
    s: '2014/0064(CNS) · No longer in force', x: '2014/0064(CNS) 2014/0064 32014D0376 376/2014', u: '/legislation/2014-0064',
    w: 0.8, d: '2014-07-01',
  },
  {
    id: '2025-0360', k: 'dossier', t: 'Digital Omnibus (data, privacy and cybersecurity rules)', s: '2025/0360(COD) · Proposed',
    a: 'Digital Omnibus | GDPR reform | Amending Regulations (EU) 2016/679, (EU) 2018/1724 and Directive 2002/58/EC',
    x: '2025/0360(COD) 2025/0360', u: '/legislation/2025-0360', w: 3, d: '2026-07-27',
  },
  { id: '256966', k: 'mep', t: 'Michael von der Schulenburg', s: 'MEP · Germany · NI', u: '/people/meps/256966', w: 1.5 },
  { id: '96810', k: 'mep', t: 'Carlo Fidanza', s: 'MEP · Italy · ECR', u: '/people/meps/96810', w: 1.5 },
  { id: '1892', k: 'mep', t: 'Carlos Coelho', s: 'Former MEP · Portugal · EPP', u: '/people/meps/1892', w: 0.7 },
  { id: '256979', k: 'mep', t: 'Oliver Schenk', s: 'MEP · Germany · EPP', u: '/people/meps/256979', w: 1.5 },
  {
    id: '2011-0453', k: 'dossier', t: 'Imports of olive oil and other agricultural products from Turkey',
    s: '2011/0453(COD) · In force', x: '2011/0453(COD) 2011/0453', u: '/legislation/2011-0453', w: 1.2, d: '2013-12-11',
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

  it('reads a session document number typed with another dash as the official one', () => {
    expect(normalize('A10\u20130049/2025 \u2013 Gilles Boyer')).toBe('a10-0049/2025 gilles boyer');
    expect(normalize('RC-B9\u20110107/2023')).toBe('rc-b9-0107/2023');
    expect(normalize('2014\u20132020')).toBe('2014 2020'); // other dashes stay word separators
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

describe('official act numbers', () => {
  it('finds the act by its number however it is cited, above files that mention the number', () => {
    for (const q of ['2024/1689', 'Regulation (EU) 2024/1689', 'regulation (eu) 2024/1689', 'CELEX:32024R1689', 'celex 32024R1689']) {
      expect(top(q), q).toBe('dossier:2021-0106');
    }
    expect(ids('Regulation (EU) 2024/1689')).toContain('dossier:2025-0404');
    expect(top('Regulation (EU) 2023/1542')).toBe('dossier:2020-0353');
    expect(top('2023/851')).toBe('dossier:2021-0197');
  });
});

describe('whole words first', () => {
  it('does not match short queries inside longer words on the results page', () => {
    expect(ids('ai', 10)).not.toContain('dossier:2020-0163'); // "AIEM"
    expect(ids('ai', 10)).not.toContain('topic:transport'); // "air passengers"
    expect(ids('EPP', 10)).toEqual(['group:epp']); // not EPPO, not Eppink
    expect(ids('PiS', 10)).toEqual(['party:6702']); // not "de la Pisa"
    expect(ids('Le Pen', 10)).toEqual([]); // not "pension", not "pentru"
  });

  it('ranks an exact topic alias like a title match', () => {
    expect(top('ai')).toBe('topic:tech');
    expect(ids('ai', 3)).toContain('dossier:2021-0106');
  });

  it('completes the word being typed in suggestions, below whole-word matches', () => {
    const typed = (q: string) => engine.search(q, { typing: true, limit: 10 }).map((h) => `${h.doc.k}:${h.doc.id}`);
    expect(typed('Spa')[0]).toBe('country:ES');
    expect(typed('car')[0]).not.toBe('mep:257071');
    expect(typed('car')).toContain('dossier:2021-0197');
    expect(typed('car').indexOf('dossier:2021-0197')).toBeLessThan(typed('car').indexOf('mep:257071'));
    expect(typed('ai')).not.toContain('topic:transport'); // 2 letters: no completion
  });

  it('falls back to word starts only when nothing matches whole words, and says so', () => {
    const hits = engine.search('pharma package');
    expect(hits.map((h) => h.doc.id)).toEqual(['2023-0131']);
    expect(hits[0].partial).toBe(true);
    expect(engine.search('pharmaceutical package')[0].partial).toBeUndefined();
  });
});

describe('singular and plural', () => {
  it('matches plural titles for singular queries and the reverse', () => {
    expect(top('battery')).toBe('dossier:2020-0353');
    expect(top('batteries')).toBe('dossier:2020-0353');
    expect(ids('car', 10)).toContain('dossier:2021-0197');
    expect(ids('car CO2', 3)).toContain('dossier:2021-0197');
  });

  it('forms light singulars', () => {
    expect(singular('batteries')).toBe('battery');
    expect(singular('cars')).toBe('car');
    expect(singular('taxes')).toBe('tax');
    expect(singular('processes')).toBe('process');
    expect(singular('access')).toBe('access');
    expect(singular('status')).toBe('status');
    expect(singular('news')).toBe('news');
    expect(singular('gas')).toBe('gas');
  });
});

describe('synonyms', () => {
  it('does not expand a phrase that matches as typed', () => {
    const hits = ids('rule of law', 20);
    expect(hits).toContain('dossier:2018-0136');
    expect(hits).toContain('topic:rights');
    expect(hits).not.toContain('dossier:2025-0059'); // a Regulation is not "rule of law"
  });

  it('expands one word when nothing matches as typed', () => {
    expect(top('ai law')).toBe('dossier:2021-0106');
  });

  it('puts the guide first for "regulation vs directive"', () => {
    expect(top('regulation vs directive')).toBe('page:instruments');
  });
});

describe('keyword helpers for list filters', () => {
  it('match whole words only, accent-insensitively', () => {
    const words = wordSet('A9-0377/2023 – Maite Pagazaurtundúa – Motion for a résolution');
    expect(hasWord(words, 'gaza')).toBe(false);
    expect(hasWord(words, 'resolution')).toBe(true);
    expect(hasWord(words, 'resolutions')).toBe(true);
    expect(hasWord(words, 'pagazaurtundua')).toBe(true);
    expect(hasWord(words, 'pagaz', true)).toBe(true);
    expect(keywordTokens('the AI Act')).toEqual(['ai', 'act']);
  });
});

describe('word families', () => {
  const all = (q: string) => engine.search(q, { limit: 100 });
  it('finds longer words built on a query word below the whole-word matches, flagged as partial', () => {
    const fish = all('fish');
    expect(fish[0].doc.id).toBe('2018-0074'); // "fish stocks": whole word first
    expect(fish[0].partial).toBeUndefined();
    const fisheries = fish.find((h) => h.doc.id === '2018-0193'); // "Fisheries control"
    expect(fisheries?.partial).toBe(true);
    const cyber = all('cyber').map((h) => h.doc.id);
    expect(cyber[0]).toBe('2022-0272'); // "Cyber Resilience Act"
    expect(cyber).toContain('2020-0359'); // "cybersecurity"
  });

  it('matches other endings of a word: "farming" -> "farm", "children" -> "child"', () => {
    expect(familyStems('farming')).toEqual(['farming', 'farm']);
    expect(familyStems('fisheries')).toEqual(['fisheries', 'fish']);
    expect(familyStems('children')).toEqual(['children', 'child']);
    expect(familyStems('water')).toEqual(['water']); // "wat" is too short
  });

  it('keeps short words, abbreviations and names out of word families', () => {
    expect(ids('ai', 20)).not.toContain('dossier:2020-0163'); // "AIEM"
    expect(all('euro').map((h) => h.doc.id)).toEqual(['2023-0212']); // not "Eurojust"
    expect(all('EPP').map((h) => h.doc.id)).toEqual(['epp']); // an abbreviation: not "EPPO"
    expect(all('olive').map((h) => h.doc.id)).toEqual(['2011-0453']); // not Oliver Schenk
  });
});

describe('generic words and synonyms', () => {
  it('matches a generic word through its synonyms below the literal matches', () => {
    const hits = engine.search('asylum rules', { limit: 10 }).map((h) => h.doc.id);
    expect(hits[0]).toBe('2018-0196'); // "... financial rules for ... the Asylum and Migration Fund"
    expect(hits).toContain('2016-0224'); // "Asylum procedure regulation"
  });

  it('keeps names whole: "rule of law" is not "rules" and "law"', () => {
    expect(ids('rule of law', 20)).not.toContain('dossier:2025-0059');
  });
});

describe('names', () => {
  it('does not let name particles count as matched words', () => {
    expect(ids('von der leyen')).toEqual([]);
    expect(ids('von der Leyen')).toEqual([]);
    expect(top('von der Schulenburg')).toBe('mep:256966');
  });

  it('does not treat first names as plurals', () => {
    expect(ids('Carlos')).toEqual(['mep:1892']); // not Carlo Fidanza
    expect(ids('Carlo')).toEqual(['mep:96810']);
  });
});

describe('act citations', () => {
  it('puts the act of the cited type first when two acts share a number', () => {
    expect(ids('Council Decision No 376/2014/EU', 2)).toEqual(['dossier:2014-0064', 'dossier:2012-0361']);
    expect(ids('Regulation (EU) No 376/2014', 2)).toEqual(['dossier:2012-0361', 'dossier:2014-0064']);
  });

  it('ranks the file that owns a number above files that cite it, also next to its name', () => {
    expect(ids('GDPR 2016/679', 2)).toEqual(['dossier:2012-0011', 'dossier:2025-0360']);
  });
});
