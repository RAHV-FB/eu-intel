import { describe, expect, it } from 'vitest';
import type { SearchDoc } from '../types/data';
import {
  createSearchEngine,
  familyStems,
  hasWord,
  keywordTokens,
  normalize,
  similarWords,
  singular,
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
    expect(all('travelers')).toEqual(expect.arrayContaining(['2023-0435~', '2012-0184~'])); // listed last
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
