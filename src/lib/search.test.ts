import { describe, expect, it } from 'vitest';
import type { SearchDoc } from '../types/data';
import {
  actTypes,
  createSearchEngine,
  dossierScores,
  familyStems,
  filterKey,
  hasWord,
  isIdentifier,
  isMepQuery,
  keywordTokens,
  normalize,
  queryParts,
  similarWords,
  singular,
  stemSpellings,
  typedAbbreviations,
  wordSet,
  type SearchHit,
} from './search';

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

  it('leaves no one-letter words from apostrophes, and keeps "S&D" whole', () => {
    expect(normalize("children's rights")).toBe('children rights');
    expect(normalize('Ukraine’s accession')).toBe('ukraine accession');
    expect(normalize("Fratelli d'Italia")).toBe('fratelli italia');
    expect(normalize('Décision d’engager des négociations')).toBe('decision engager des negociations');
    expect(normalize("O'Sullivan")).toBe('o sullivan');
    expect(normalize('S&D')).toBe('s&d');
    expect(normalize('Rights & Justice')).toBe('rights justice');
    expect(keywordTokens('S&D')).toEqual(['s&d']);
    expect([...wordSet("A9-0038/2019 - Bernd Lange - procédure d'approbation")]).not.toContain('d');
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
    expect(singular('crises')).toBe('crisis');
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

  it('reads an act number as readers write it: "EU" before or after the type, abbreviated types', () => {
    for (const q of [
      'EU Regulation 2016/679', 'Regulation EU 2016/679', 'Reg. (EU) 2016/679', 'Reg 2016/679', 'EU 2016/679',
      'Regulation 2016/679 EU', 'EU Reg 2016/679',
    ]) { // prettier-ignore
      expect(isIdentifier(q), q).toBe(true);
      const hits = engine.search(q);
      expect(hits.map((h) => h.doc.id), q).toEqual(['2012-0011', '2025-0360']); // the owner, then the file citing it
      expect(hits[0].approximate, q).toBeUndefined();
      expect(engine.search(q, { typing: true })[0].doc.id, q).toBe('2012-0011');
    }
    // the cited type still decides between acts sharing a number
    expect(ids('EU Decision 376/2014', 2)).toEqual(['dossier:2014-0064', 'dossier:2012-0361']);
    expect(ids('Dec 376/2014', 2)).toEqual(['dossier:2014-0064', 'dossier:2012-0361']);
    expect(ids('Reg 376/2014', 2)).toEqual(['dossier:2012-0361', 'dossier:2014-0064']);
    expect(isIdentifier('EU 2024')).toBe(false);
  });

  it('lets "EU" qualify a name without being required', () => {
    expect(top('EU GDPR')).toBe('dossier:2012-0011'); // its entry has no "EU"; the Digital Omnibus' has "(EU)"
    expect(engine.search('EU GDPR')[0].approximate).toBeUndefined();
    expect(top('EU Return Regulation')).toBe('dossier:2025-0059');
  });

  it("ranks a file named with another act type than its own first, above files that only mention both words", () => {
    // the GDPR is a regulation; the Digital Omnibus has "GDPR reform" and "Directive 2002/58/EC" in its names
    expect(ids('GDPR directive', 2)).toEqual(['dossier:2012-0011', 'dossier:2025-0360']);
  });

  it('reads a citation copied from an official title, and an EUR-Lex or ELI address, as the act number', () => {
    for (const q of [
      'Regulation (EU) 2016/679 of the European Parliament and of the Council',
      'Regulation (EU) 2016/679 of the European Parliament and of the Council of 27 April 2016',
      'Regulation (EU) 2016/679 of the European Parliament and of the Council of 27 April 2016 on the protection of natural persons with regard to the processing of personal data and on the free movement of such data, and repealing Directive 95/46/EC (General Data Protection Regulation)',
      'Regulation (EU) 2016/679 on the protection of natural persons',
      'https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679',
      'https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=celex%3A32016R0679&from=EN',
      'eur-lex.europa.eu/eli/reg/2016/679/oj',
      'http://data.europa.eu/eli/reg/2016/679/oj',
    ]) { // prettier-ignore
      expect(isIdentifier(q), q).toBe(true);
      expect(top(q), q).toBe('dossier:2012-0011');
      expect(engine.search(q)[0].approximate, q).toBeUndefined();
      expect(engine.search(q, { typing: true })[0].doc.id, q).toBe('2012-0011');
    }
    // the act type of the official title still decides between acts sharing a number
    expect(ids('Council Decision No 376/2014/EU of 24 April 2014', 2)).toEqual(['dossier:2014-0064', 'dossier:2012-0361']);
    expect(ids('Regulation (EU) No 376/2014 of the European Parliament and of the Council', 2)).toEqual([
      'dossier:2012-0361',
      'dossier:2014-0064',
    ]);
    // a file's name with a number in it is not cut ("... amending Regulation (EU) 2016/679 of the ...")
    expect(isIdentifier('Amending Regulation (EU) 2016/679 of the European Parliament')).toBe(false);
  });
});

describe('MEPs', () => {
  // TEST-ONLY documents with the names of real files, groups and countries
  const docs: SearchDoc[] = [
    { id: 'ES', k: 'country', t: 'Spain', s: 'EU Member State', a: 'Spanish | Spaniard | España | ES', u: '/countries/ES', w: 5 },
    { id: 'greens-efa', k: 'group', t: 'Group of the Greens/European Free Alliance', s: 'Political group · 53 MEPs', a: 'Greens/EFA | Greens | Verts/ALE | European Free Alliance', u: '/people/groups/greens-efa', w: 4 },
    { id: '6737', k: 'party', t: 'Fidesz-Magyar Polgári Szövetség-Kereszténydemokrata Néppárt', s: 'National party · Hungary', u: '/people/parties/6737', w: 1.3 },
    { id: '2021-0071', k: 'dossier', t: 'Framework for the issuance, verification and acceptance of interoperable certificates on vaccination, testing and recovery to third-country nationals legally staying or legally residing in the territories of Member States', s: '2021/0071(COD) · No longer in force', a: 'Digital Green Certificate (third-country nationals)', x: '2021/0071(COD) 2021/0071 regulation', u: '/legislation/2021-0071', w: 1.2, d: '2021-06-15' },
    { id: '2014-0199', k: 'dossier', t: 'Stabilisation and Association Agreement between the European Communities and their Member States, of the one part, and the former Yugoslav Republic of Macedonia', s: '2014/0199(COD) · In force', x: '2014/0199(COD) 2014/0199', u: '/legislation/2014-0199', w: 1.2, d: '2015-03-01' },
    { id: '2026-0900', k: 'dossier', t: 'Amendments to the Decision of the European Parliament of 28 September 2005 adopting the Statute for Members of the European Parliament', s: '2026/0900(APP) · Under examination in Parliament', x: '2026/0900(APP) 2026/0900', u: '/legislation/2026-0900', w: 1.2, d: '2026-09-01' },
    { id: '2025-0900', k: 'dossier', t: 'Amending the Act concerning the election of the members of the European Parliament by direct universal suffrage', s: '2025/0900(APP) · Published, not yet in force', x: '2025/0900(APP) 2025/0900', u: '/legislation/2025-0900', w: 1.2, d: '2026-05-01' },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.k}:${h.doc.id}${h.meps ? '!' : ''}`);

  it('answers a country, group or party next to "MEPs" with it, flagged for the MEP directory', () => {
    for (const q of ['Spanish MEPs', 'MEPs from Spain', 'Spain MEPs', 'Spanish members of the European Parliament', 'Spanish MEP'])
      expect(all(q), q).toEqual(['country:ES!']);
    expect(all('Greens MEPs')).toEqual(['group:greens-efa!']); // not the certificates for "Member States" nationals
    expect(all('Green MEPs')).toEqual(['group:greens-efa!']);
    expect(all('Greens/EFA MEPs')).toEqual(['group:greens-efa!']);
    expect(all('Fidesz MEPs')).toEqual(['party:6737!']); // a name holding the word
    expect(all('Spain')).toEqual(['country:ES']); // no flag without the words for MEPs
  });

  it('reads "MEP" as "Member of the European Parliament", not "Member States"', () => {
    expect(all('former MEPs')).toEqual([]); // not "... Member States ... the former Yugoslav Republic"
    expect(all('MEP statute')).toEqual(['dossier:2026-0900']); // "Statute for Members of the European Parliament"
    expect(all('election of MEPs')).toEqual(['dossier:2025-0900']);
    expect(isMepQuery('former MEPs')).toBe(true);
    expect(isMepQuery('members of the European Parliament')).toBe(true);
    expect(isMepQuery('Member States')).toBe(false);
  });
});

describe('MEP queries that name no country, group or party', () => {
  // TEST-ONLY documents with the names of real groups, parties and files (search.json entries, shortened)
  const docs: SearchDoc[] = [
    { id: 'the-left', k: 'group', t: 'The Left group in the European Parliament - GUE/NGL', s: 'Political group · 45 MEPs', a: 'The Left | Left | GUE/NGL', u: '/people/groups/the-left', w: 4 },
    { id: 's-d', k: 'group', t: 'Group of the Progressive Alliance of Socialists and Democrats in the European Parliament', s: 'Political group · 135 MEPs', a: 'S&D | S and D | Socialists and Democrats | Socialists', u: '/people/groups/s-d', w: 4 },
    { id: 'pfe', k: 'group', t: 'Patriots for Europe Group', s: 'Political group · 85 MEPs', a: 'PfE | Patriots | Patriots for Europe', u: '/people/groups/pfe', w: 4 },
    { id: 'renew', k: 'group', t: 'Renew Europe Group', s: 'Political group · 78 MEPs', a: 'Renew | Renew Europe | liberals', u: '/people/groups/renew', w: 4 },
    { id: '6737', k: 'party', t: 'Fidesz-Magyar Polgári Szövetség-Kereszténydemokrata Néppárt', s: 'National party · Hungary · 2024–2029 term', a: 'Fidesz-KDNP', u: '/people/parties/6737', w: 1.3 },
    { id: '5253', k: 'party', t: 'Fidesz-Magyar Polgári Szövetség-Kereszténydemokrata Néppárt', s: 'National party · Hungary · 2019–2024 term', a: 'Fidesz-KDNP', u: '/people/parties/5253', w: 0.5 },
    { id: '6766', k: 'party', t: 'Democratic Party', s: 'National party · Cyprus · 2024–2029 term', a: 'DI.KO. | DIKO', u: '/people/parties/6766', w: 1.3 },
    { id: '7022', k: 'party', t: 'Labour Party', s: 'National party · Ireland', a: 'LABOUR', u: '/people/parties/7022', w: 1.3 },
    { id: 'IE', k: 'country', t: 'Ireland', s: 'EU Member State', a: 'Irish | IE', u: '/countries/IE', w: 5 },
    { id: '2026-0900', k: 'dossier', t: 'Amendments to the Decision of the European Parliament of 28 September 2005 adopting the Statute for Members of the European Parliament', s: '2026/0900(APP) · Under examination in Parliament', x: '2026/0900(APP) 2026/0900', u: '/legislation/2026-0900', w: 1.2, d: '2026-09-01' },
    { id: '2025-0900', k: 'dossier', t: 'Amending the Act concerning the election of the members of the European Parliament by direct universal suffrage', s: '2025/0900(APP) · Published, not yet in force', x: '2025/0900(APP) 2025/0900', u: '/legislation/2025-0900', w: 1.2, d: '2026-05-01' },
    { id: '2023-0135', k: 'dossier', t: 'Combating corruption, replacing Council Framework Decision 2003/568/JHA and the Convention on the fight against corruption involving officials of the European Communities or officials of Member States of the European Union and amending Directive (EU) 2017/1371 of the European Parliament and of the Council', s: '2023/0135(COD) · In force', x: '2023/0135(COD) 2023/0135 directive', u: '/legislation/2023-0135', w: 1.2, d: '2026-05-31' },
    { id: '2016-0231', k: 'dossier', t: 'Binding annual greenhouse gas emission reductions by Member States from 2021 to 2030 for a resilient Energy Union and to meet commitments under the Paris Agreement and amending Regulation No 525/2013 of the European Parliament and the Council on a mechanism for monitoring and reporting greenhouse gas emissions and other information relevant to climate change', s: '2016/0231(COD) · In force', x: '2016/0231(COD) 2016/0231 regulation', u: '/legislation/2016-0231', w: 1.2, d: '2023-04-26' },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.k}:${h.doc.id}${h.meps ? '!' : ''}${h.approximate ? '~' : ''}`);

  it('flags no group for the Parliament itself, whose name two groups contain', () => {
    for (const q of [
      'European Parliament MEPs', 'MEPs european parliament', 'MEPs in parliament', 'members of parliament',
      'member of parliament', 'Parliament members', 'european parliament members', 'MEPs of the European Parliament',
    ]) { // prettier-ignore
      expect(all(q).sort(), q).toEqual(['dossier:2025-0900', 'dossier:2026-0900']); // the files on MEPs, not The Left and S&D
      expect(isMepQuery(q), q).toBe(true); // so the search page links the MEP directory
    }
  });

  it('flags no country, group or party for a word several of their names have', () => {
    for (const q of ['party MEPs', 'group MEPs', 'Europe MEPs']) expect(all(q).filter((k) => k.includes('!')), q).toEqual([]);
    expect(all('Fidesz MEPs')).toEqual(['party:6737!', 'party:5253!']); // one name, recorded for each term
    expect(all('Labour MEPs')).toEqual(['party:7022!']);
  });

  it('keeps the stop words inside a name, not those around it', () => {
    for (const q of [
      'Patriots for Europe MEPs', 'MEPs of Patriots for Europe', 'members of the European Parliament from Patriots for Europe',
    ]) // prettier-ignore
      expect(all(q), q).toEqual(['group:pfe!']);
    expect(all('Socialists and Democrats MEPs')).toEqual(['group:s-d!']);
    expect(all('MEPs from Ireland')).toEqual(['country:IE!']);
    expect(all('MEPs in the European Parliament from Ireland')).toEqual(['country:IE!']);
    expect(all('The Left group in the European Parliament - GUE/NGL MEPs')).toEqual(['group:the-left!']);
    expect(all('Left MEPs')).toEqual(['group:the-left!']);
  });

  it('reads "members of the European Parliament" as MEPs, not as "Member States" and "European Parliament"', () => {
    for (const q of ['Members of the European Parliament', 'Member of the European Parliament', 'members European Parliament'])
      expect(all(q).sort(), q).toEqual(['dossier:2025-0900', 'dossier:2026-0900']);
    expect(all('Member States European Parliament')).toEqual(['dossier:2023-0135', 'dossier:2016-0231']);
    expect(all('election of members of the European Parliament')).toEqual(['dossier:2025-0900']);
  });
});

describe('approximate matches', () => {
  // TEST-ONLY documents shaped like real ones: typo tolerance must be labelled and ranked last
  const docs: SearchDoc[] = [
    {
      id: '2022-0396', k: 'dossier', t: 'Packaging and Packaging Waste Regulation', s: '2022/0396(COD) · In force',
      x: '2022/0396(COD) 2022/0396', u: '/legislation/2022-0396', w: 1.2, d: '2025-02-11',
    },
    {
      id: '2013-0246', k: 'dossier', t: 'Package travel and assisted travel arrangements', s: '2013/0246(COD) · In force',
      x: '2013/0246(COD) 2013/0246', u: '/legislation/2013-0246', w: 1.2, d: '2015-12-11',
    },
    {
      id: '2016-0039', k: 'dossier', t: 'Macro-financial assistance to Tunisia', s: '2016/0039(COD) · In force',
      x: '2016/0039(COD) 2016/0039', u: '/legislation/2016-0039', w: 1.2, d: '2016-07-06',
    },
    {
      id: 'council-voting', k: 'page', t: 'How the Council votes: qualified majority and unanimity', s: 'How the EU works',
      a: 'blocking minority', u: '/how-the-eu-works#council-voting', w: 2,
    },
    {
      id: '2018-0171', k: 'dossier', t: 'Sovereign bond-backed securities', s: '2018/0171(COD) · Proposed',
      x: '2018/0171(COD) 2018/0171', u: '/legislation/2018-0171', w: 1.2, d: '2019-04-16',
    },
    {
      id: '2019-0273', k: 'dossier', t: "Exercise of the Union's rights for the application and enforcement of international trade rules",
      s: '2019/0273(COD) · In force', x: '2019/0273(COD) 2019/0273', u: '/legislation/2019-0273', w: 1.2, d: '2021-02-12',
    },
    {
      id: 'rights', k: 'topic', t: 'Rights & Justice', s: 'Topic · 161 files', a: 'fundamental rights', u: '/legislation?topic=rights', w: 3,
    },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const flagged = (h: SearchHit) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`;
  const all = (q: string) => e.search(q, { limit: 50 }).map(flagged);

  it('flags typo matches and names the similar words: "Macron" is not a name in the data', () => {
    const hits = e.search('Macron');
    expect(hits.map(flagged)).toEqual(['2016-0039~']);
    expect(hits[0].similar).toEqual(['macro']);
    expect(e.search('Macron', { typing: true }).every((h) => h.approximate)).toBe(true);
  });

  it('takes a word one edit from an index word as a typo, without its word family ("packageing")', () => {
    expect(all('packageing')).toEqual(['2022-0396~']); // not "Package travel"
    expect(e.search('packageing', { typing: true })[0].doc.id).toBe('2022-0396');
  });

  it('keeps the word family of a word two edits away, above the approximate matches ("blocked")', () => {
    expect(all('blocked')).toEqual(['council-voting*', '2018-0171~']); // "blocking minority", then "backed"
  });

  it('does not count a possessive as a matched word ("children\'s rights")', () => {
    expect(all("children's rights")).toEqual(all('children rights'));
    expect(all("children's rights")).not.toContain('2019-0273~');
    expect(all("children's rights")).not.toContain('2019-0273');
  });
});

describe('identifier queries', () => {
  // TEST-ONLY documents: two files share number fragments with the identifier of a third
  const docs: SearchDoc[] = [
    {
      id: '2016-0011', k: 'dossier', t: 'Rules against tax avoidance practices', s: '2016/0011(CNS) · In force',
      x: '2016/0011(CNS) 2016/0011 32016L1164 2016/1164 COM(2016)0026 COM(2016)26 COM/2016/26', u: '/legislation/2016-0011',
      w: 1.2, d: '2016-07-12',
    },
    {
      id: '2013-0013', k: 'dossier', t: 'Amending Directive 98/26/EC and Directive (EU) 2016/2337', s: '2013/0013(COD) · In force',
      x: '2013/0013(COD) 2013/0013 COM(2013)0026 COM(2013)26 COM/2013/26', u: '/legislation/2013-0013', w: 1.2, d: '2017-01-01',
    },
    {
      id: '2023-0134', k: 'dossier', t: 'Amending Directive 1999/62/EC as regards weights and dimensions', s: '2023/0134(COD) · Proposed',
      x: '2023/0134(COD) 2023/0134', u: '/legislation/2023-0134', w: 1.2, d: '2026-01-01',
    },
    {
      id: '2025-0134', k: 'dossier', t: 'Amending Regulations (EU) 2016/424 and (EU) 2023/1230 as regards digitalisation',
      s: '2025/0134(COD) · Proposed', x: '2025/0134(COD) 2025/0134', u: '/legislation/2025-0134', w: 1.2, d: '2026-07-14',
    },
    {
      id: '2021-0106', k: 'dossier', t: 'Artificial Intelligence Act', s: '2021/0106(COD) · In force',
      x: '2021/0106(COD) 2021/0106 32024R1689 2024/1689', u: '/legislation/2021-0106', w: 3, d: '2026-08-02',
    },
    {
      id: '2025-0404', k: 'dossier', t: 'Amending Regulations (EU) 2017/745 and (EU) 2024/1689 as regards medical devices',
      s: '2025/0404(COD) · Proposed', x: '2025/0404(COD) 2025/0404', u: '/legislation/2025-0404', w: 1.2, d: '2026-09-01',
    },
    {
      id: '2025-0059', k: 'dossier', t: 'Return Regulation', s: '2025/0059(COD) · In force',
      a: 'Common system for returns, repealing Directive 2008/115/EC', x: '2025/0059(COD) 2025/0059 COM(2025)0101',
      u: '/legislation/2025-0059', w: 3, d: '2026-06-01',
    },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string, typing = false) => e.search(q, { limit: 50, typing }).map((h) => h.doc.id);

  it('lists only the owner, not files sharing number fragments', () => {
    expect(all('COM(2016) 26')).toEqual(['2016-0011']);
    expect(all('2023/0134(COD)')).toEqual(['2023-0134']);
    expect(all('2023/0134(COD)', true)).toEqual(['2023-0134']);
  });

  it('still lists the files whose names cite an act number', () => {
    expect(all('2024/1689')).toEqual(['2021-0106', '2025-0404']);
    expect(all('Regulation 2024/1689')).toEqual(['2021-0106', '2025-0404']);
  });

  it('finds nothing for a reference no file has', () => {
    expect(all('2008/0028(COD)')).toEqual([]);
    expect(all('COM(2008) 40')).toEqual([]);
  });

  it('still completes an unfinished identifier while typing', () => {
    expect(all('2025/013', true)).toContain('2025-0134');
    expect(all('2023/01', true)).toEqual(['2023-0134']); // the identifiers it begins, not files sharing "2023"
  });

  it('does not suggest files sharing parts of a reference no file has, while it is typed', () => {
    // "2023" and "cod" are in 2023/0134(COD): all but one of the words, which an identifier is not
    expect(all('2023/9999(COD)', true)).toEqual([]);
    expect(all('COM(2008) 40', true)).toEqual([]); // "COM(2025)0101" and "Directive 2008/115/EC" of the Return Regulation
  });

  it('keeps the file while a procedure type is being typed, and does not call it approximate', () => {
    for (const q of ['2023/0134(', '2023/0134(C', '2023/0134(CO', '2023/0134(COD']) {
      const hits = e.search(q, { typing: true, limit: 8 });
      expect(hits.map((h) => h.doc.id), q).toEqual(['2023-0134']);
      expect(hits[0].approximate, q).toBeUndefined();
    }
  });
});

describe('split procedures', () => {
  // TEST-ONLY documents shaped like pipeline/build.py output: a split procedure and its parts, which hold the acts
  const docs: SearchDoc[] = [
    {
      id: '2016-0224', k: 'dossier', t: 'Common procedure for international protection in the Union',
      s: '2016/0224(COD) · Split into separate procedures', x: '2016/0224(COD) 2016/0224', u: '/legislation/2016-0224', w: 0.4,
      d: '2019-10-21',
    },
    {
      id: '2016-0224A', k: 'dossier', t: 'Asylum Procedure Regulation', s: '2016/0224A(COD) · In force',
      x: '2016/0224A(COD) 2016/0224 32024R1348 2024/1348 regulation', u: '/legislation/2016-0224A', w: 1.2, d: '2026-06-12',
    },
    {
      id: '2016-0224B', k: 'dossier', t: 'Establishing a return border procedure', s: '2016/0224B(COD) · In force',
      x: '2016/0224B(COD) 2016/0224 32024R1349 2024/1349 regulation', u: '/legislation/2016-0224B', w: 1.2, d: '2024-06-11',
    },
    {
      id: '2016-0400', k: 'dossier', t: 'Proposal 2016/0400(COD), split into 2016/0400A(COD) and 2016/0400B(COD)',
      s: '2016/0400(COD) · Split into separate procedures', x: '2016/0400(COD) 2016/0400', u: '/legislation/2016-0400', w: 0.4,
    },
    {
      id: '2016-0400A', k: 'dossier', t: 'Adapting a number of legal acts to Articles 290 and 291 TFEU - part I',
      s: '2016/0400A(COD) · In force', x: '2016/0400A(COD) 2016/0400 32019R1243 2019/1243 regulation',
      u: '/legislation/2016-0400A', w: 1.2, d: '2022-12-23',
    },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string, typing = false) =>
    e.search(q, { limit: 50, typing }).map((h) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`);

  it('finds a part by its number and letter, without the procedure type', () => {
    for (const q of ['2016/0224A', '2016/0224 A', '2016/0224a', '2016/0224A(COD)', '2016/0224 A(COD)']) {
      expect(all(q), q).toEqual(['2016-0224A']);
    }
    expect(all('2016/0224B')).toEqual(['2016-0224B']);
    expect(all('2016/0400A')).toEqual(['2016-0400A', '2016-0400']); // and the parent, whose title names the part
    expect(all('2016/0224')).toEqual(['2016-0224A', '2016-0224B', '2016-0224']);
    expect(all('2016/0224C')).toEqual([]);
  });

  it('keeps the part while its reference is typed', () => {
    for (const q of ['2016/0224A', '2016/0224A(', '2016/0224A(C', '2016/0224A(CO', '2016/0224A(COD', '2016/0224A(COD)']) {
      expect(all(q, true), q).toEqual(['2016-0224A']);
    }
  });
});

describe('regular word forms', () => {
  // TEST-ONLY documents with the titles of real files (and of the files a typo correction would find instead)
  const docs: SearchDoc[] = [
    { id: '2018-0186', k: 'dossier', t: 'EU Emergency Travel Document', s: '2018/0186(CNS) · In force', x: '2018/0186(CNS) 2018/0186', u: '/legislation/2018-0186', w: 1.2, d: '2019-06-20' },
    { id: '2013-0246', k: 'dossier', t: 'Package travel and assisted travel arrangements', s: '2013/0246(COD) · In force', x: '2013/0246(COD) 2013/0246', u: '/legislation/2013-0246', w: 1.2, d: '2015-12-11' },
    { id: '2012-0184', k: 'dossier', t: 'Periodic roadworthiness tests for motor vehicles and their trailers', s: '2012/0184(COD) · In force', x: '2012/0184(COD) 2012/0184', u: '/legislation/2012-0184', w: 1.2, d: '2014-04-29' },
    { id: '2023-0435', k: 'dossier', t: 'Amending Directive (EU) 2015/2302 to make the protection of travellers more effective', s: '2023/0435(COD) · Proposed', x: '2023/0435(COD) 2023/0435', u: '/legislation/2023-0435', w: 1.2, d: '2024-04-23' },
    { id: '2016-0287', k: 'dossier', t: 'Promotion of Internet connectivity in local communities', s: '2016/0287(COD) · In force', x: '2016/0287(COD) 2016/0287', u: '/legislation/2016-0287', w: 1.2, d: '2017-09-13' },
    { id: '2023-0315', k: 'dossier', t: 'European cross-border associations', s: '2023/0315(COD) · Proposed', a: 'proposed directive on European cross-border associations', x: '2023/0315(COD) 2023/0315', u: '/legislation/2023-0315', w: 1.2, d: '2024-03-13' },
    { id: '2013-0088', k: 'dossier', t: 'Community trade mark', s: '2013/0088(COD) · In force', x: '2013/0088(COD) 2013/0088', u: '/legislation/2013-0088', w: 1.2, d: '2015-12-24' },
    { id: '2021-0366', k: 'dossier', t: 'EU Deforestation Regulation', s: '2021/0366(COD) · In force', a: 'Making available on the Union market of certain commodities', x: '2021/0366(COD) 2021/0366', u: '/legislation/2021-0366', w: 3, d: '2025-12-23' },
    { id: '2021-0197', k: 'dossier', t: 'CO2 emission performance standards for new passenger cars and vans', s: '2021/0197(COD) · In force', a: 'EU ban on the sale of new petrol and diesel cars from 2035', x: '2021/0197(COD) 2021/0197', u: '/legislation/2021-0197', w: 1.2, d: '2023-05-15' },
    { id: '2017-0326', k: 'dossier', t: 'Location of the seat of the European Banking Authority', s: '2017/0326(COD) · In force', x: '2017/0326(COD) 2017/0326', u: '/legislation/2017-0326', w: 1.2, d: '2018-11-14' },
    { id: '2014-0136', k: 'dossier', t: 'Appliances burning gaseous fuels', s: '2014/0136(COD) · In force', x: '2014/0136(COD) 2014/0136', u: '/legislation/2014-0136', w: 1.2, d: '2016-03-31' },
    { id: '2022-0396', k: 'dossier', t: 'Packaging and Packaging Waste Regulation', s: '2022/0396(COD) · In force', x: '2022/0396(COD) 2022/0396', u: '/legislation/2022-0396', w: 1.2, d: '2025-02-11' },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`);

  it('undoes a doubled final consonant for the word family', () => {
    expect(familyStems('banning')).toEqual(['banning', 'bann', 'ban']);
    expect(familyStems('travelled')).toEqual(['travelled', 'travell', 'travel']);
    expect(familyStems('missed')).toEqual(['missed', 'miss']); // not "mis"
  });

  it('does not take a regular form of index words for a typo, and lists its word family first', () => {
    // "travelers" is one edit from "travellers", but it is "travel" + "ers"
    expect(all('travelers').slice(0, 2).sort()).toEqual(['2013-0246*', '2018-0186*']);
    // "travellers", the British spelling, is another form of the word; "trailers" only a similar word, listed last
    expect(all('travelers')).toEqual(['2018-0186*', '2013-0246*', '2023-0435*', '2012-0184~']);
    expect(all('promoted')[0]).toBe('2016-0287*'); // "promotion", above "proposed"
    expect(all('marking')[0]).toBe('2013-0088*'); // "mark", above "making"
    expect(all('banning')[0]).toBe('2021-0197*'); // "ban", above "banking" and "burning"
  });

  it('still takes a misspelt form for a typo: a final "e" goes before an ending', () => {
    expect(all('packageing')).toEqual(['2022-0396~']); // "packaging", not "package travel"
  });

  it('tells word starts from other forms of a word when nothing matches whole words', () => {
    const fueled = e.search('fueled'); // "fuel" + "ed": the "fuels" of a title, another form of the word
    expect(fueled.map((h) => h.doc.id)).toEqual(['2014-0136']);
    expect(fueled[0].partial).toBe(true);
    expect(fueled[0].wordStart).toBeUndefined();
    const spa = engine.search('Spa'); // the start of "Spain"
    expect(spa[0].doc.id).toBe('ES');
    expect(spa.every((h) => h.wordStart)).toBe(true);
    expect(engine.search('pharma package')[0].wordStart).toBe(true);
    expect(engine.search('fish').some((h) => h.wordStart)).toBe(false); // whole words matched: no fallback
  });

  it('passes the word starts on to the legislation explorer', () => {
    const partial = new Set<string>();
    const starts = new Set<string>();
    expect([...dossierScores(engine, 'batt', { partial, wordStart: starts }).keys()]).toEqual(['2020-0353']); // "Batteries"
    expect([...starts]).toEqual(['2020-0353']);
    const forms = new Set<string>();
    dossierScores(e, 'fueled', { partial, wordStart: forms });
    expect(partial.has('2014-0136')).toBe(true);
    expect(forms.size).toBe(0); // another form of the word, not a word starting with it
  });
});

describe('plurals in -ves and -oes, US spellings and a dropped "e"', () => {
  // TEST-ONLY documents with the titles of real files
  const docs: SearchDoc[] = [
    { id: '2025-0058', k: 'dossier', t: 'Amending Council Directive 92/43/EEC as regards the protection status of the wolf (Canis lupus)', s: '2025/0058(COD) · In force', x: '2025/0058(COD) 2025/0058 directive', u: '/legislation/2025-0058', w: 1.2, d: '2025-06-01' },
    { id: '2023-0062', k: 'dossier', t: 'Specific rules relating to the entry into Northern Ireland of certain consignments of seed potatoes', s: '2023/0062(COD) · In force', x: '2023/0062(COD) 2023/0062 regulation', u: '/legislation/2023-0062', w: 1.2, d: '2023-06-01' },
    { id: '2015-0149', k: 'dossier', t: 'Energy efficiency labelling', s: '2015/0149(COD) · In force', x: '2015/0149(COD) 2015/0149 regulation', u: '/legislation/2015-0149', w: 1.2, d: '2017-07-28' },
    { id: '2013-0072', k: 'dossier', t: 'Air passenger rights in the event of denied boarding, cancellation or long delay of flights', s: '2013/0072(COD) · In force', x: '2013/0072(COD) 2013/0072', u: '/legislation/2013-0072', w: 1.2, d: '2025-06-01' },
    { id: '2021-0211', k: 'dossier', t: 'EU Emissions Trading System', s: '2021/0211(COD) · In force', x: '2021/0211(COD) 2021/0211 directive', u: '/legislation/2021-0211', w: 1.2, d: '2023-05-16' },
    { id: '2017-0114', k: 'dossier', t: 'Charging of heavy goods vehicles for the use of certain infrastructures', s: '2017/0114(COD) · In force', x: '2017/0114(COD) 2017/0114 directive', u: '/legislation/2017-0114', w: 1.2, d: '2022-03-24' },
    { id: '2009-0001', k: 'dossier', t: 'Control of rats and other pests', s: '2009/0001(COD) · In force', x: '2009/0001(COD) 2009/0001', u: '/legislation/2009-0001', w: 1.2, d: '2010-01-01' },
    { id: '2009-0002', k: 'dossier', t: 'Nationally determined contributions', s: '2009/0002(COD) · In force', x: '2009/0002(COD) 2009/0002', u: '/legislation/2009-0002', w: 1.2, d: '2010-01-01' },
    { id: '2016-0374', k: 'dossier', t: 'Rates of value added tax applied to books', s: '2016/0374(CNS) · In force', x: '2016/0374(CNS) 2016/0374 directive', u: '/legislation/2016-0374', w: 1.2, d: '2018-11-06' },
    { id: '2013-0443', k: 'dossier', t: 'Reduction of national emissions of certain atmospheric pollutants', s: '2013/0443(COD) · In force', x: '2013/0443(COD) 2013/0443 directive', u: '/legislation/2013-0443', w: 1.2, d: '2016-12-31' },
    { id: '2022-0396', k: 'dossier', t: 'Packaging and Packaging Waste Regulation', s: '2022/0396(COD) · In force', x: '2022/0396(COD) 2022/0396 regulation', u: '/legislation/2022-0396', w: 1.2, d: '2025-02-11' },
    { id: '2013-0246', k: 'dossier', t: 'Package travel and assisted travel arrangements', s: '2013/0246(COD) · In force', x: '2013/0246(COD) 2013/0246 directive', u: '/legislation/2013-0246', w: 1.2, d: '2015-12-11' },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`);

  it('singularises a curated list of plurals in -ves and -oes, not "directives" or "shoes"', () => {
    expect(singular('wolves')).toBe('wolf');
    expect(singular('vetoes')).toBe('veto');
    expect(singular('potatoes')).toBe('potato');
    expect(singular('directives')).toBe('directive');
    expect(singular('derivatives')).toBe('derivative');
    expect(singular('shoes')).toBe('shoe');
    expect(all('wolves')).toEqual(['2025-0058']);
    expect(all('potato')).toEqual(['2023-0062']);
    expect(all('directives')).toEqual(all('directive'));
  });

  it('finds US spellings and a dropped "e" among the other forms of a word', () => {
    expect(stemSpellings('trade')).toEqual([['trad', new Set(['ing', 'ings'])]]);
    expect(stemSpellings('label')[0][0]).toBe('labell');
    expect(stemSpellings('free')).toEqual([]);
    expect(all('labeled')).toEqual(['2015-0149*']); // "labelling"
    expect(all('labeling')).toEqual(['2015-0149*']);
    expect(all('canceled')).toEqual(['2013-0072*']); // "cancellation"
    expect(all('emissions trade')).toEqual(['2021-0211*']); // "trading"
    expect(all('vehicle charge')).toEqual(['2017-0114*']); // "charging"
    expect(all('rate')).toEqual(['2016-0374']); // not "rats"
    expect(all('national')).toEqual(['2013-0443']); // not "nationally"
    expect(all('packageing')).toEqual(['2022-0396~']); // still a typo of "packaging", not "package"
  });
});

describe('plurals in -ses of words in -s', () => {
  // TEST-ONLY documents with the titles of real files
  const docs: SearchDoc[] = [
    { id: '2012-0305', k: 'dossier', t: 'Fluorinated greenhouse gases', s: '2012/0305(COD) · No longer in force', x: '2012/0305(COD) 2012/0305 regulation', u: '/legislation/2012-0305', w: 1.2, d: '2015-01-01' },
    { id: '2023-0266', k: 'dossier', t: 'Accounting of greenhouse gas emissions of transport services', s: '2023/0266(COD) · In force', x: '2023/0266(COD) 2023/0266 regulation', u: '/legislation/2023-0266', w: 1.2, d: '2025-12-01' },
    { id: '2017-0288', k: 'dossier', t: 'Common rules for access to the international market for coach and bus services', s: '2017/0288(COD) · Withdrawn by the Commission', x: '2017/0288(COD) 2017/0288', u: '/legislation/2017-0288', w: 1.2, d: '2025-10-06' },
    { id: '2009-0003', k: 'dossier', t: 'Use of cases', s: '2009/0003(COD) · In force', x: '2009/0003(COD) 2009/0003', u: '/legislation/2009-0003', w: 1.2, d: '2010-01-01' },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`);

  it('singularises a curated list ("gases", "buses"), not "cases" or "uses"', () => {
    expect(singular('gases')).toBe('gas');
    expect(singular('buses')).toBe('bus');
    expect(singular('statuses')).toBe('status');
    expect(singular('cases')).toBe('case');
    expect(singular('uses')).toBe('use');
    expect(all('greenhouse gas')).toEqual(['2012-0305', '2023-0266']);
    expect(all('greenhouse gases')).toEqual(['2012-0305', '2023-0266']);
    expect(all('buses')).toEqual(['2017-0288']);
    expect(all('uses')).toEqual(['2009-0003']);
    expect(hasWord(wordSet('coach and bus services'), 'buses')).toBe(true); // the list filters too
  });
});

describe('words written apart', () => {
  // TEST-ONLY documents with the titles of real files
  const docs: SearchDoc[] = [
    { id: '2017-0225', k: 'dossier', t: 'ENISA, the "EU Cybersecurity Agency", and repealing Regulation (EU) 526/2013, and on Information and Communication Technology cybersecurity certification (\'\'Cybersecurity Act\'\')', s: '2017/0225(COD) · In force', a: 'Cybersecurity Act', x: '2017/0225(COD) 2017/0225 regulation', u: '/legislation/2017-0225', w: 1.2, d: '2025-01-15' },
    { id: '2020-0359', k: 'dossier', t: 'Measures for a high common level of cybersecurity across the Union', s: '2020/0359(COD) · In force', a: 'NIS2 | NIS 2 Directive', x: '2020/0359(COD) 2020/0359 directive', u: '/legislation/2020-0359', w: 1.2, d: '2024-10-18' },
    { id: '2016-0030', k: 'dossier', t: 'Measures to safeguard the security of gas supply', s: '2016/0030(COD) · In force', x: '2016/0030(COD) 2016/0030 regulation', u: '/legislation/2016-0030', w: 1.2, d: '2017-11-01' },
    { id: '2023-0373', k: 'dossier', t: 'Preventing plastic pellet losses to reduce microplastic pollution', s: '2023/0373(COD) · In force', x: '2023/0373(COD) 2023/0373 regulation', u: '/legislation/2023-0373', w: 1.2, d: '2025-12-16' },
    { id: '256966', k: 'mep', t: 'Michael von der Schulenburg', s: 'MEP · Germany · NI', u: '/people/meps/256966', w: 1.5 },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`);

  it('matches two words that the index has as one word, as that word', () => {
    for (const q of ['cyber security', 'Cyber Security', 'cyber-security']) expect(all(q).sort(), q).toEqual(['2017-0225', '2020-0359']);
    expect(all('cyber security act')[0]).toBe('2017-0225'); // its alias "Cybersecurity Act"
    expect(all('cyber security directive')).toEqual(['2020-0359']);
    expect(all('micro plastic')).toEqual(['2023-0373']);
    expect(all('security')).toEqual(['2016-0030']); // the words typed alone are unchanged
    expect(all('von der')).toEqual(['256966']); // name particles are not joined
  });
});

describe('list filters', () => {
  it('compare names and labels accent- and case-insensitively, with hyphens as spaces', () => {
    const has = (name: string, typed: string) => filterKey(name).includes(filterKey(typed));
    expect(has('Iratxe García Pérez', 'Garcia')).toBe(true);
    expect(has('Iratxe García Pérez', 'García')).toBe(true);
    expect(has('Iratxe García Pérez', 'garcia perez')).toBe(true);
    expect(has('José Manuel García-Margallo y Marfil', 'Garcia Margallo')).toBe(true);
    expect(has('Łukasz Kohut', 'Lukasz')).toBe(true);
    expect(has('Dragoş Pîslaru', 'Dragoș')).toBe(true); // comma below, as a Romanian keyboard types it, and the cedilla
    expect(has('Dragoş Pîslaru', 'Dragos')).toBe(true);
    expect(has('Sinn Féin', 'Sinn Fein')).toBe(true);
    expect(has('Bündnis 90/Die Grünen', 'Bundnis')).toBe(true);
    expect(has('Se Acabó La Fiesta', 'se acabo la fiesta')).toBe(true);
    expect(has('Fratelli d’Italia', "Fratelli d'Italia")).toBe(true);
    expect(has('Fratelli d’Italia', 'Fratelli d')).toBe(true); // while the name is typed
    expect(has('Iratxe García Pérez', 'Garcia Lopez')).toBe(false);
    expect(filterKey('  ')).toBe('');
  });
});

describe('act types', () => {
  // TEST-ONLY documents: pipeline/build.py gives each file the types of its acts ("directive") among its keywords
  const docs: SearchDoc[] = [
    {
      id: '2018-0106', k: 'dossier', t: 'Protection of persons reporting on breaches of Union law', s: '2018/0106(COD) · In force',
      x: '2018/0106(COD) 2018/0106 32019L1937 2019/1937 whistleblower whistleblowers whistleblowing directive',
      u: '/legislation/2018-0106', w: 1.2, d: '2024-12-12',
    },
    {
      id: '2021-0291', k: 'dossier', t: 'Amending Directive 2014/53/EU on the making available on the market of radio equipment',
      s: '2021/0291(COD) · In force', a: 'Common charger for electronic devices', x: '2021/0291(COD) 2021/0291 32022L2380 2022/2380 usb-c directive',
      u: '/legislation/2021-0291', w: 1.2, d: '2024-12-28',
    },
    {
      id: '2020-0353', k: 'dossier', t: 'Batteries and waste batteries', s: '2020/0353(COD) · In force', a: 'New Batteries Regulation',
      x: '2020/0353(COD) 2020/0353 32023R1542 2023/1542 regulation', u: '/legislation/2020-0353', w: 1.2, d: '2025-08-18',
    },
    {
      id: '2003-0282', k: 'dossier', t: 'Batteries and accumulators and waste batteries and accumulators', s: '2003/0282(COD) · Repealed',
      a: 'Batteries Directive', x: '2003/0282(COD) 2003/0282 32006L0066 2006/66 directive', u: '/legislation/2003-0282', w: 1.2,
      d: '2006-09-26',
    },
    {
      id: '2022-0047', k: 'dossier', t: 'Data Act', s: '2022/0047(COD) · In force', x: '2022/0047(COD) 2022/0047 32023R2854 2023/2854 regulation',
      u: '/legislation/2022-0047', w: 3, d: '2025-09-12',
    },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`);

  it('finds a file by a common name and the type of its act', () => {
    expect(all('whistleblower directive')).toEqual(['2018-0106']);
    expect(all('whistleblowing directive')).toEqual(['2018-0106']);
    expect(all('EU whistleblower directive')).toEqual(['2018-0106']); // "EU": "Union"
    expect(all('whistleblower rules')).toEqual(['2018-0106']);
  });

  it('lets one act type stand for another only when no file has the type typed', () => {
    expect(all('USB-C regulation')).toEqual(['2021-0291']); // the common charger is a directive
    expect(all('common charger regulation')).toEqual(['2021-0291']);
    expect(all('batteries regulation')).toEqual(['2020-0353']); // not the Batteries Directive
    expect(all('batteries directive')[0]).toBe('2003-0282');
  });

  it('matches an act type as the whole word only, not through the forms or the start of another word', () => {
    expect(all('regulation')).toEqual(['2020-0353', '2022-0047']); // in a name first, then as the act type
    expect(all('regulations')).toEqual(['2020-0353', '2022-0047']);
    expect(all('directive').sort()).toEqual(['2003-0282', '2018-0106', '2021-0291']);
    // the Data Act's entry has the word only as its act type; the Batteries Regulation has it in a name
    expect(all('regulated')).toEqual(['2020-0353*']);
    expect(all('regulating')).toEqual(['2020-0353*']);
    expect(e.search('regul', { typing: true }).map((h) => h.doc.id)).toEqual(['2020-0353']);
    expect(actTypes(docs.find((d) => d.id === '2022-0047')!)).toEqual(['regulation']); // shown on the search page
  });
});

describe('query parts', () => {
  // TEST-ONLY documents with the names of real files, countries and MEPs
  const docs: SearchDoc[] = [
    { id: '2020-0359', k: 'dossier', t: 'Measures for a high common level of cybersecurity across the Union', s: '2020/0359(COD) · In force', a: 'NIS2 | NIS 2 Directive | NIS 2', x: '2020/0359(COD) 2020/0359 32022L2555 2022/2555 directive', u: '/legislation/2020-0359', w: 3, d: '2023-01-16' },
    { id: 'IE', k: 'country', t: 'Ireland', s: 'EU Member State', a: 'Irish | Éire | IE', u: '/countries/IE', w: 5 },
    { id: '256966', k: 'mep', t: 'Michael von der Schulenburg', s: 'MEP · Germany · NI', u: '/people/meps/256966', w: 1.5 },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const parts = (q: string) => queryParts(e, q)?.map((p) => `${p.text}: ${p.hits.map((h) => `${h.doc.k}:${h.doc.id}`).join(' ')}`);

  it('says what each part of a query that matches nothing as a whole finds on its own', () => {
    expect(e.search('NIS2 Ireland')).toEqual([]);
    expect(parts('NIS2 Ireland')).toEqual(['NIS2: dossier:2020-0359', 'Ireland: country:IE']);
    expect(parts('NIS 2 Ireland')).toEqual(['NIS 2: dossier:2020-0359', 'Ireland: country:IE']);
    expect(parts('NIS2 in Ireland')).toEqual(['NIS2: dossier:2020-0359', 'Ireland: country:IE']);
    expect(parts('NIS2 Irelnd')).toEqual(['NIS2: dossier:2020-0359', 'Irelnd: ']); // a misspelling finds nothing here
  });

  it('does not make a part of name particles, and leaves single words and identifiers alone', () => {
    expect(parts('von der Leyen')).toBeUndefined(); // one word that counts: not Michael von der Schulenburg
    expect(parts('Ursula von der Leyen')).toEqual(['Ursula: ', 'von der Leyen: ']);
    expect(parts('Ireland')).toBeUndefined();
    expect(parts('2021/0106(COD)')).toBeUndefined();
  });
});

describe('capitals, people’s names, words with a number, short last words and names after "European"', () => {
  // TEST-ONLY documents with the titles of real files and the names of real MEPs (search.json entries, shortened)
  const docs: SearchDoc[] = [
    { id: '2018-0074', k: 'dossier', t: 'Multiannual plan for fish stocks in the Western Waters and adjacent waters', s: '2018/0074(COD) · In force', x: '2018/0074(COD) 2018/0074 regulation', u: '/legislation/2018-0074', w: 1.2, d: '2019-07-25' },
    { id: '2018-0193', k: 'dossier', t: 'Fisheries control', s: '2018/0193(COD) · In force', x: '2018/0193(COD) 2018/0193 regulation', u: '/legislation/2018-0193', w: 1.2, d: '2026-01-10' },
    { id: '2022-0365', k: 'dossier', t: 'Type-approval of motor vehicles and engines ... with respect to their emissions and battery durability (Euro 7)', s: '2022/0365(COD) · In force', x: '2022/0365(COD) 2022/0365 regulation', u: '/legislation/2022-0365', w: 1.2, d: '2024-05-28' },
    { id: '2020-0310', k: 'dossier', t: 'Adequate minimum wages in the European Union', s: '2020/0310(COD) · In force', x: '2020/0310(COD) 2020/0310 directive', u: '/legislation/2020-0310', w: 1.2, d: '2025-11-11' },
    { id: '2020-0036', k: 'dossier', t: 'Establishing the framework for achieving climate neutrality and amending Regulation (EU) 2018/1999 (European Climate Law)', s: '2020/0036(COD) · In force', a: 'European Climate Law', x: '2020/0036(COD) 2020/0036 regulation', u: '/legislation/2020-0036', w: 1.2, d: '2026-03-18' },
    { id: '2025-0524', k: 'dossier', t: '2040 climate target (European Climate Law amendment)', s: '2025/0524(COD) · In force', a: '2040 climate target | Climate Law amendment', x: '2025/0524(COD) 2025/0524 regulation', u: '/legislation/2025-0524', w: 3, d: '2026-04-07' },
    { id: 'council', k: 'page', t: 'The Council of the European Union', s: 'How the EU works', a: 'Council of the EU | Council of the European Union', u: '/how-the-eu-works#council', w: 2 },
    { id: 'european-council', k: 'page', t: 'The European Council (heads of state or government)', s: 'How the EU works', a: 'European Council | summit', u: '/how-the-eu-works#european-council', w: 2 },
    { id: '256859', k: 'mep', t: 'Annamária Vicsek', s: 'MEP · Hungary · PfE', u: '/people/meps/256859', w: 1.5 },
    { id: '257131', k: 'mep', t: 'Anna Maria Cisint', s: 'MEP · Italy · PfE', u: '/people/meps/257131', w: 1.5 },
  ]; // prettier-ignore
  const e = createSearchEngine(docs);
  const all = (q: string) => e.search(q, { limit: 50 }).map((h) => `${h.doc.id}${h.partial ? '*' : ''}${h.approximate ? '~' : ''}`);
  const typed = (q: string) => e.search(q, { limit: 8, typing: true }).map((h) => h.doc.id);

  it('reads a query typed all in capitals as its words, and capitals inside a word as an abbreviation', () => {
    expect(typedAbbreviations('FISH')).toEqual(new Set());
    expect(typedAbbreviations('CHILDREN AND FAMILIES')).toEqual(new Set());
    expect(typedAbbreviations('AMLA regulation')).toEqual(new Set(['amla']));
    expect(typedAbbreviations('SAFE loans')).toEqual(new Set(['safe']));
    expect(typedAbbreviations('MiCA')).toEqual(new Set(['mica']));
    expect(all('fish')).toEqual(['2018-0074', '2018-0193*']);
    expect(all('FISH')).toEqual(all('fish')); // caps lock: "Fisheries control" too
    expect(all('FISH stocks')).toEqual(['2018-0074']); // "FISH" among lowercase words is an abbreviation: whole word only
  });

  it('matches a person’s name as typed, not as one word ("Anna Maria" is not "Annamária")', () => {
    expect(all('Anna Maria')).toEqual(['257131']);
    expect(all('Annamaria')).toEqual(['256859']);
  });

  it('matches a word and a number written together as the index has them apart', () => {
    for (const q of ['euro7', 'EURO7', 'Euro 7', 'Euro-7']) expect(all(q), q).toEqual(['2022-0365']);
    expect(typed('euro7')).toEqual(['2022-0365']);
  });

  it('keeps suggestions while the last word has one or two letters', () => {
    expect(typed('minimum wa')).toEqual(['2020-0310']);
    expect(typed('minimum w')).toEqual(['2020-0310']);
    expect(typed('minimum wag')).toEqual(['2020-0310']);
    expect(typed('Anna Ma')).toEqual(['257131', '256859']); // those of "Anna", as typed first
    expect(all('minimum wa')).toEqual([]); // the results page: as typed
    expect(typed('EU')).not.toEqual([]);
    expect(typed('EU-US')).toEqual([]); // "EU" alone is no subject
  });

  it('ranks a name given without its leading "European" as that name, for two words or more', () => {
    expect(all('climate law')).toEqual(['2020-0036', '2025-0524']); // not the amendment first
    expect(all('EU climate law')[0]).toBe('2020-0036');
    expect(all('council')[0]).toBe('council'); // one word: not the European Council
  });
});

describe('similar words in a summary', () => {
  it('lists them in the order of the hits, best match first', () => {
    expect(similarWords([['burning'], ['banking'], ['binding'], ['banking'], ['binding'], ['bunting']])).toEqual([
      'burning',
      'banking',
      'binding',
    ]);
    expect(similarWords([undefined, ['macro', 'macron']], 1)).toEqual(['macro']);
  });
});
