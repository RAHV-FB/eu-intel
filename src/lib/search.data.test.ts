/**
 * Search regressions on the real built index (public/data from `python -m pipeline build`). Skipped when the
 * data has not been built. Each block is a query a reader actually typed and the result they needed.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CountryDetail, DossierSummary, EpVoteSummary, SearchDoc } from '../types/data';
import { createSearchEngine, queryParts, similarWords, type SearchHit } from './search';
import { buildHaystacks, keywordScores } from '../features/legislation/explorer';
import { matchVoteDetails, matchVotes, voteHaystacks } from '../features/votes/keyword';

const DATA = new URL('../../public/data/', import.meta.url);
const built = existsSync(new URL('search.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe.skipIf(!built)('search on the built index', () => {
  const engine = createSearchEngine(built ? read<SearchDoc[]>('search.json') : []);
  const rows = built ? read<DossierSummary[]>('dossiers/index.json') : [];
  const votes = built ? read<EpVoteSummary[]>('votes/index.json') : [];
  const key = (h: SearchHit) => `${h.doc.k}:${h.doc.id}`;
  const ids = (q: string, limit = 10) => engine.search(q, { limit }).map(key);
  const typed = (q: string, limit = 8) => engine.search(q, { limit, typing: true }).map(key);
  const top = (q: string) => ids(q, 1)[0];

  it('finds an act by its official number or CELEX, above files that mention it', () => {
    expect(top('Regulation (EU) 2024/1689')).toBe('dossier:2021-0106');
    expect(top('2024/1689')).toBe('dossier:2021-0106');
    expect(top('CELEX:32024R1689')).toBe('dossier:2021-0106');
    expect(top('2016/679')).toBe('dossier:2012-0011');
    expect(top('2023/1115')).toBe('dossier:2021-0366');
    expect(top('Directive (EU) 2022/2464')).toBe('dossier:2021-0104');
    expect(top('2022/2065')).toBe('dossier:2020-0361');
  });

  it('gives the legislation explorer the same matches as the search page', () => {
    const hay = buildHaystacks(rows);
    for (const q of ['AI Act', 'ai', 'Le Pen', 'act', 'eu', 'rule of law', 'battery']) {
      const page = engine.search(q, { limit: 5000, kinds: ['dossier', 'act'] }).length;
      expect(keywordScores(rows, hay, engine, q).size, q).toBe(page);
    }
    const ai = keywordScores(rows, hay, engine, 'ai');
    expect(ai.has('2021-0106')).toBe(true);
    expect(ai.has('2020-0163')).toBe(false); // "AIEM tax in the Canary Islands"
    expect(ai.has('2014-0014')).toBe(false); // "Aid scheme for ... fruit"
    // the AI Act and the files whose official title cites it (Regulation (EU) 2024/1689), not every "act"
    expect(keywordScores(rows, hay, engine, 'AI Act').size).toBeLessThanOrEqual(5);
  });

  it('puts the best match first: groups, parties and countries are not buried under prefix matches', () => {
    expect(ids('EPP')).toEqual(['group:epp']);
    expect(top('Renew')).toBe('group:renew');
    expect(top('Greens')).toBe('group:greens-efa');
    expect(ids('ECR')).toEqual(['group:ecr']);
    expect(top('Hungary')).toBe('country:HU');
    expect(top('Germany')).toBe('country:DE');
    expect(ids('PiS').every((k) => k.startsWith('party:'))).toBe(true);
  });

  it('keeps unfinished words to suggestions, below whole-word matches', () => {
    expect(typed('ai')[0]).not.toBe('topic:transport');
    expect(typed('ai', 3)).toEqual(expect.arrayContaining(['topic:tech', 'dossier:2021-0106']));
    expect(typed('Le Pen')).not.toContain('party:6915'); // "Alianța pentru Unirea Românilor"
    expect(typed('Le Pen')).not.toContain('topic:social');
    expect(ids('Le Pen')).toEqual([]);
    expect(typed('car', 3).some((k) => k.startsWith('mep:'))).toBe(false);
    expect(ids('car', 50).some((k) => k.startsWith('mep:'))).toBe(false);
  });

  it('finds well-known files by their official common names', () => {
    expect(top('cyber resilience act')).toBe('dossier:2022-0272');
    expect(top('right to repair')).toBe('dossier:2023-0083');
    expect(ids('pharma package', 2).sort()).toEqual(['dossier:2023-0131', 'dossier:2023-0132']);
    const pact = ids('migration pact', 20);
    for (const id of ['2020-0278', '2021-0046', '2020-0279', '2016-0224A', '2016-0224B', '2020-0277', '2016-0132', '2016-0222', '2016-0223', '2016-0225']) {
      expect(pact, id).toContain(`dossier:${id}`);
    }
    expect(ids('car CO2', 3)).toContain('dossier:2021-0197');
    expect(ids('petrol and diesel cars 2035', 3)).toContain('dossier:2021-0197');
    expect(top('new batteries regulation')).toBe('dossier:2020-0353');
    // files amending the AI Act cite Regulation (EU) 2024/1689 in their official title (aliases.yaml "ai act")
    expect(top('AI Act')).toBe('dossier:2021-0106');
    expect(ids('AI Act', 3)).toContain('dossier:2025-0359');
    // the Legislative Observatory's title of 2025/0429(COD); the contested "chat control" stays with 2022/0155
    expect(ids('child sexual abuse', 5)).toContain('dossier:2025-0429');
    expect(top('child sexual abuse')).toBe('dossier:2022-0155');
    expect(ids('chat control', 10)).not.toContain('dossier:2025-0429');
  });

  it('ranks the parts of a split procedure, which hold the acts, above the split parent', () => {
    const ets = ids('ETS revision', 5);
    expect(ets.indexOf('dossier:2021-0211A')).toBeGreaterThanOrEqual(0);
    expect(ets.indexOf('dossier:2021-0211A')).toBeLessThan(ets.indexOf('dossier:2021-0211'));
    expect(top('common procedure for international protection')).toBe('dossier:2016-0224A');
    expect(top('APR')).toBe('dossier:2016-0224A');
    expect(ids('APR', 10)).not.toContain('dossier:2016-0224'); // curated keywords stay on the parts
  });

  it('tells same-name party records apart by term, current term first', () => {
    const afd = engine.search('AfD', { limit: 5 });
    expect(afd.map((h) => h.doc.id)).toEqual(['6802', '5369']);
    expect(afd[0].doc.s).toMatch(/2024–2029 term$/);
    expect(afd[1].doc.s).toMatch(/2019–2024 term$/);
  });

  it('does not let generic synonyms flood multi-word queries', () => {
    expect(engine.search('rule of law', { limit: 1000 }).length).toBeLessThan(20);
    expect(ids('rule of law', 3)).toContain('dossier:2018-0136');
    expect(top('regulation vs directive')).toBe('page:instruments');
  });

  it('matches singular queries to plural titles', () => {
    expect(top('battery')).toBe('dossier:2020-0353');
    expect(ids('car', 6)).toContain('dossier:2021-0197');
  });

  it('matches vote keywords as whole words and through the linked file', () => {
    const hay = voteHaystacks(votes);
    const titles = (q: string) => {
      const hits = matchVotes(votes, hay, q, engine);
      return votes.filter((v) => hits?.has(v.id) ?? true);
    };
    expect(titles('gaza').some((v) => /pagazaurtund/i.test(v.title))).toBe(false);
    const ai = titles('AI Act');
    expect(ai.length).toBeGreaterThan(0);
    expect(ai.every((v) => v.dossier_id === '2021-0106' || v.dossier_id === '2025-0359')).toBe(true); // AI Act, its amendment
    expect(ai.some((v) => v.kind === 'final')).toBe(true);
    expect(titles('résolution').length).toBe(titles('resolution').length);
  });

  it('finds word families below the whole-word matches, and the explorer counts them too', () => {
    const hay = buildHaystacks(rows);
    const families: [string, string][] = [
      ['fish', '2018-0193'], // "Fisheries control"
      ['cyber', '2020-0359'], // "... cybersecurity across the Union"
      ['farming', '2024-0319'], // "... position of farmers in the food supply chain"
      ['children', '2022-0155'], // "... child sexual abuse online"
      ['banking', '2025-0806'], // "... by the European Central Bank"
    ];
    for (const [q, related] of families) {
      const hits = engine.search(q, { limit: 5000 });
      const at = hits.findIndex((h) => h.doc.id === related);
      expect(at, q).toBeGreaterThan(0);
      expect(hits[at].partial, q).toBe(true);
      expect(hits.slice(at).every((h) => h.partial), q).toBe(true); // nothing whole-word below it
      const page = hits.filter((h) => h.doc.k === 'dossier' || h.doc.k === 'act').length;
      const partial = new Set<string>();
      expect(keywordScores(rows, hay, engine, q, partial).size, q).toBe(page);
      expect(partial.has(related), q).toBe(true);
    }
    // the 2,3-letter words and abbreviations stay whole: "ai" is not "aid", "SAFE" not "safeguard"
    expect(engine.search('ai', { limit: 100 }).some((h) => h.partial)).toBe(false);
    expect(engine.search('car', { limit: 100 }).some((h) => h.partial)).toBe(false);
    expect(engine.search('SAFE', { limit: 100 }).some((h) => h.partial)).toBe(false);
    expect(ids('safe', 50)).not.toContain('dossier:2016-0030'); // "safeguard the security of gas supply"
    expect(ids('euro', 50)).not.toContain('dossier:2013-0256'); // Eurojust
  });

  it('does not answer a name query with another person through name particles', () => {
    expect(ids('von der Leyen').filter((k) => k.startsWith('mep:'))).toEqual([]);
    expect(ids('Ursula von der Leyen')).toEqual([]);
    expect(top('Carlos')).toMatch(/^mep:/);
    expect(engine.search('Carlos', { limit: 1 })[0].doc.t).toMatch(/^Carlos /);
    expect(engine.search('Nicolas', { limit: 1 })[0].doc.t).toMatch(/^Nicolas /);
  });

  it('matches a generic word through its synonyms when one file says it literally', () => {
    expect(ids('asylum rules', 3)).toContain('dossier:2020-0279'); // Asylum and Migration Management Regulation
    expect(ids('crypto rules', 5)).toContain('dossier:2020-0265'); // Markets in Crypto-assets
    expect(engine.search('rule of law', { limit: 1000 }).length).toBeLessThan(20);
  });

  it('finds the law in force for "combustion engine ban", not the proposal to revise it', () => {
    expect(top('combustion engine ban')).toBe('dossier:2021-0197'); // Regulation (EU) 2023/851
    expect(top('ban on combustion engines')).toBe('dossier:2021-0197');
    expect(ids('combustion engine ban')).not.toContain('dossier:2025-0420');
  });

  it('finds files by the names the institutions use for them', () => {
    expect(top('ecodesign regulation')).toBe('dossier:2022-0095');
    expect(top('anti-SLAPP directive')).toBe('dossier:2022-0117');
    expect(top('eIDAS 2')).toBe('dossier:2021-0136');
    expect(top('FuelEU Maritime')).toBe('dossier:2021-0210');
    expect(top('single-use plastics')).toBe('dossier:2018-0172');
    expect(top('Copyright directive')).toBe('dossier:2016-0280');
    expect(top('pay transparency directive')).toBe('dossier:2021-0050');
    expect(ids('AMLA')).toEqual(['dossier:2021-0240']); // the Authority, not every anti-money-laundering file
    expect(ids('medicine', 50)).toContain('dossier:2023-0132'); // "Union code relating to medicinal products"
  });

  it('ranks the act of the cited type, and the file owning a number cited next to its name, first', () => {
    expect(top('Council Decision No 376/2014/EU')).toBe('dossier:2014-0064'); // CELEX 32014D0376
    expect(top('Regulation (EU) No 376/2014')).toBe('dossier:2012-0361'); // CELEX 32014R0376
    expect(top('GDPR 2016/679')).toBe('dossier:2012-0011');
  });

  it('names countries and tells same-name party records apart in search subtitles', () => {
    const docs = read<SearchDoc[]>('search.json');
    expect(docs.filter((d) => / · GB\b/.test(d.s ?? '')).length).toBe(0);
    expect(docs.find((d) => d.k === 'mep' && d.id === '111011')?.s).toBe('Former MEP · United Kingdom · ECR');
    const azione = docs.filter((d) => d.k === 'party' && d.t === 'Azione').map((d) => d.s);
    expect(new Set(azione).size).toBe(azione.length);
    expect(docs.find((d) => d.k === 'party' && d.id === '6103')?.s).toBe(
      'National party · Italy · 2019–2024 term · 20 November 2019 – 8 November 2022',
    );
    // EP open data names corporate bodies 5500 and 5719 only "-"
    expect(docs.some((d) => d.k === 'party' && (d.id === '5500' || d.id === '5719'))).toBe(false);
    const parties = read<{ id: string }[]>('people/parties.json');
    expect(parties.some((p) => p.id === '5500' || p.id === '5719')).toBe(false);
    expect(read<{ label: string }>('people/parties/5500.json').label).toBe('Party name not recorded');
  });

  it('matches references in the vote search whole, and the vote subject', () => {
    const hay = voteHaystacks(votes);
    const refsOf = (q: string) => {
      const hits = matchVotes(votes, hay, q, engine);
      return votes.filter((v) => hits?.has(v.id));
    };
    for (const ref of ['2023/2116(INI)', '2023/0134(COD)', '2021/0106(COD)']) {
      const hits = refsOf(ref);
      expect(hits.length, ref).toBeGreaterThan(0);
      expect(hits.every((v) => v.procedure_ref === ref), ref).toBe(true);
      const bare = refsOf(ref.replace(/\(.*$/, ''));
      expect(bare.map((v) => v.id).sort(), ref).toEqual(hits.map((v) => v.id).sort());
    }
    // a document number, and an act number cited in the titles
    expect(refsOf('A9-0050/2024').map((v) => v.id)).toContain('166145');
    const cites = (v: EpVoteSummary) => /2016\/679/.test(`${v.display_title} ${v.title} ${v.subject ?? ''}`);
    expect(refsOf('2016/679').every((v) => cites(v) || v.dossier_id === '2012-0011')).toBe(true);
    // a label printing the number with another dash (175067 "A10–0049/2025", 155928 "A9‑0256/2020"), and a
    // query typed with one (171364 has an en dash, 179280 a hyphen)
    expect(refsOf('A10-0049/2025').map((v) => v.id)).toContain('175067');
    expect(refsOf('A9-0256/2020').map((v) => v.id)).toContain('155928');
    expect(refsOf('A10\u20130029/2024').map((v) => v.id)).toEqual(expect.arrayContaining(['171364', '179280']));
    // vote 195775 is titled after the act it amends; its subject names the ePrivacy Directive
    expect(hay.get('195775')?.has('eprivacy')).toBe(true);
    expect(matchVotes(votes, hay, 'ePrivacy', null)?.has('195775')).toBe(true);
  });

  it('labels typo matches, ranks them last, and keeps them out of the whole-word vote matches', () => {
    // "Macron" is not in the data: 22 macro-financial assistance files, all flagged with the similar word
    const macron = engine.search('Macron', { limit: 1000 });
    expect(macron.length).toBeGreaterThan(0);
    expect(macron.every((h) => h.approximate && h.similar?.includes('macro'))).toBe(true);
    expect(engine.search('Macron', { limit: 8, typing: true }).every((h) => h.approximate)).toBe(true);
    for (const q of ['Merz', 'Barnier', 'abortion', 'interrail', 'withdrawn', 'iran']) {
      expect(engine.search(q, { limit: 1000 }).every((h) => h.approximate), q).toBe(true);
    }
    // the explorer counts the same files and knows they match only approximately
    const hay = buildHaystacks(rows);
    const approximate = new Map<string, string[]>();
    const lx = keywordScores(rows, hay, engine, 'Macron', undefined, approximate);
    expect(lx.size).toBe(macron.filter((h) => h.doc.k === 'dossier').length);
    expect(approximate.size).toBe(lx.size);
    // /votes: the vote titles that say "abortion", not the votes on files that say "adoption"
    const vh = voteHaystacks(votes);
    const abortion = matchVoteDetails(votes, vh, 'abortion', engine);
    expect([...(abortion?.ids ?? [])].sort()).toEqual(['125483', '136129', '145778', '147305', '168054', '182713', '182767']);
    expect(abortion?.approximate).toBeUndefined();
    expect(matchVotes(votes, vh, 'iran', engine)?.has('166653')).toBe(false); // EBRD file citing "Iraq"
    const m = matchVoteDetails(votes, vh, 'Macron', engine);
    expect(m?.partial).toBe(false); // not "words that start with it"
    expect(m?.approximate).toBe(true);
    expect(m?.similar).toEqual(['macro']);
  });

  it('ranks the typo correction first, not the word family of the misspelt word', () => {
    expect(top('packageing')).toBe('dossier:2022-0396'); // Packaging and Packaging Waste Regulation
    expect(typed('packageing')[0]).toBe('dossier:2022-0396');
    expect(engine.search('packageing', { limit: 1000 }).some((h) => h.partial)).toBe(false);
    expect(top('manageing')).toBe('dossier:2012-0163');
    expect(top('measureing')).toBe('dossier:2011-0353'); // "... measuring instruments"
    // two edits from "backed": the word family ("blocking minority", "geo-blocking") comes first
    expect(ids('blocked', 3)).toEqual(['page:council-voting', 'dossier:2016-0152', 'dossier:2018-0171']);
    // whole words, then other forms of a word, then approximate matches
    for (const q of ['blocked', 'fish', 'farming', 'packageing', 'Macron', 'children', 'cyber', 'AI Act vote']) {
      const hits = engine.search(q, { limit: 5000 });
      const rank = (h: SearchHit) => (h.approximate ? 2 : h.partial ? 1 : 0);
      expect(hits.every((h, k) => k === 0 || rank(hits[k - 1]) <= rank(h)), q).toBe(true);
    }
  });

  it('does not count single letters left by apostrophes and "&" as matched words', () => {
    const vh = voteHaystacks(votes);
    expect(matchVotes(votes, vh, 'S&D', engine)?.size).toBe(0); // 174881, 174880, 130845, 108941 before
    expect(ids('S&D')).toEqual(['group:s-d']);
    const children = ids("children's rights", 50);
    for (const id of ['2019-0273', '2012-0359', '2014-0174', '2022-0068']) expect(children).not.toContain(`dossier:${id}`);
    expect(matchVotes(votes, vh, "children's rights", engine)?.has('135950')).toBe(true); // custody rights ... children
    expect(ids("EU's AI Act")).toEqual(ids('EU AI Act'));
    // 2025/0045(COD)'s committee decision, mandate and final votes, and the two motions to reject the proposal
    expect([...(matchVotes(votes, vh, 'Omnibus I', engine) ?? [])].sort()).toEqual(['180328', '180948', '180983', '182518', '182614']);
  });

  it('finds parties by their acronyms without the dots EP data writes', () => {
    expect(top('ND')).toBe('party:6730'); // Nea Demokratia ("N.D.")
    expect(top('DIKO')).toBe('party:6766'); // Democratic Party ("DI.KO.")
    expect(top('DISY')).toBe('party:6764'); // Democratic Rally ("DI.SY.")
    expect(top('KS EDEK')).toBe('party:5190');
    expect(top('N.D.')).toBe('party:6730');
    expect(top('Spa')).toBe('country:ES'); // "SP.A" is not made "SPA"
    expect(typed('Spa')[0]).toBe('country:ES');
  });

  it('finds files by the words the acts and the institutions use for them', () => {
    for (const q of ['whistleblower', 'whistleblowers', 'whistleblowing', 'whistle-blower']) expect(top(q), q).toBe('dossier:2018-0106');
    expect(ids('whistleblower', 5)).toEqual(['dossier:2018-0106']); // not the files amending Directive (EU) 2019/1937
    expect(top('USB-C')).toBe('dossier:2021-0291');
    expect(top('USB Type-C')).toBe('dossier:2021-0291');
    for (const q of ['stability and growth pact', 'fiscal rules']) expect(ids(q, 5).sort(), q).toEqual(['dossier:2023-0137', 'dossier:2023-0138']);
    expect(top('defense fund')).toBe('dossier:2018-0254'); // European Defence Fund
    expect(top('European Defense Fund')).toBe('dossier:2018-0254');
    expect(top('EP')).toBe('page:parliament');
    const fit55 = ids('Fit for 55', 50);
    expect(fit55).toHaveLength(21); // the 20 carriages' files and 2021/0211(COD), which the ETS carriage names
    for (const id of ['2021-0197', '2021-0211', '2021-0211A', '2021-0211B', '2021-0213', '2021-0214', '2021-0424']) expect(fit55).toContain(`dossier:${id}`);
    expect(fit55[20]).toBe('dossier:2021-0211'); // the split parent, below the files holding acts
    for (const id of ['2021-0213', '2021-0211']) {
      expect(read<{ known_as: { part_of?: string[] } }>(`dossiers/${id}.json`).known_as.part_of, id).toEqual(['Fit for 55 package']);
    }
    const vh = voteHaystacks(votes);
    expect(matchVotes(votes, vh, 'USB-C', engine)?.has('148323')).toBe(true); // common charger, final vote
    const sgp = matchVotes(votes, vh, 'stability and growth pact', engine);
    expect(sgp?.has('168292') && sgp?.has('168426')).toBe(true);
  });

  it('lists only the owner for an exact identifier, and nothing for one no file has', () => {
    const hay = buildHaystacks(rows);
    const only: [string, string][] = [
      ['COM(2016) 26', '2016-0011'],
      ['2023/0134(COD)', '2023-0134'],
      ['2011/0297(COD)', '2011-0297'],
      ['COM(2011)0349', '2011-0153'],
      ['Directive 2014/24/EU', '2011-0438'],
    ];
    for (const [q, id] of only) {
      expect(ids(q, 50), q).toEqual([`dossier:${id}`]);
      expect(keywordScores(rows, hay, engine, q).size, q).toBe(1);
    }
    expect(ids('2008/0028(COD)', 50)).toEqual([]); // "Food information to consumers", not in the data
    expect(ids('COM(2008) 40', 50)).toEqual([]);
    expect(ids('2024/1689', 10)).toEqual(expect.arrayContaining(['dossier:2021-0106', 'dossier:2025-0359'])); // cites it
  });

  it('finds the parts of a split procedure by number and letter, without the procedure type', () => {
    const hay = buildHaystacks(rows);
    // "2016/0224A" found nothing and the page said no file has the reference; "2016/0400A" only the split parent
    for (const [q, id] of [
      ['2016/0224A', '2016-0224A'],
      ['2016/0224 A', '2016-0224A'],
      ['2016/0224B', '2016-0224B'],
      ['2016/0400A', '2016-0400A'],
      ['2021/0211A', '2021-0211A'],
      ['2016/0357B', '2016-0357B'],
    ]) {
      expect(top(q), q).toBe(`dossier:${id}`);
      expect(typed(q)[0], q).toBe(`dossier:${id}`);
      expect(keywordScores(rows, hay, engine, q).has(id), q).toBe(true);
    }
    expect(ids('2016/0400A', 10)).toEqual(['dossier:2016-0400A', 'dossier:2016-0400']);
    // /votes reads the part the same way: 167632 is the final vote on 2016/0224A(COD), 166936 that on the B part
    const vh = voteHaystacks(votes);
    for (const q of ['2016/0224A', '2016/0224 A', '2016/0224 A(COD)']) expect([...(matchVotes(votes, vh, q, engine) ?? [])], q).toEqual(['167632']);
    expect([...(matchVotes(votes, vh, '2016/0224 B', engine) ?? [])]).toEqual(['166936']);
    // typing the reference keeps the file, never "all but one of the words"
    for (const q of ['2021/0106(', '2021/0106(C', '2021/0106(CO', '2021/0106(COD', '2016/0224A(C', '2016/0224A(CO']) {
      const hits = engine.search(q, { limit: 8, typing: true });
      expect(hits[0]?.doc.id, q).toBe(q.startsWith('2021') ? '2021-0106' : '2016-0224A');
      expect(hits.some((h) => h.approximate), q).toBe(false);
    }
    // a reference no file has: nothing, also while typing (it used to suggest files sharing "2023" and "COD")
    for (const q of ['2023/9999(COD)', 'COM(2015) 26', 'COM(2008) 40', 'Regulation (EU) 2024/9999']) {
      expect(ids(q, 50), q).toEqual([]);
      expect(typed(q), q).toEqual([]);
    }
  });

  it('keeps the word family of a regular word form that is one edit from another word', () => {
    // these used to be taken for typos of "trailers", "proposed", "making", "fueleu" and "banking"
    expect(top('travelers')).toBe('dossier:2018-0186'); // EU Emergency Travel Document
    expect(ids('travelers', 16)).toContain('dossier:2013-0246'); // Package travel
    expect(top('promoted')).toBe('dossier:2016-0287'); // Promotion of Internet connectivity
    expect(top('marking')).toBe('dossier:2013-0088'); // Community trade mark
    expect(engine.search('fueled', { limit: 100 }).filter((h) => h.partial).length).toBeGreaterThanOrEqual(10); // fuels
    expect(top('banning')).toBe('dossier:2021-0197'); // "EU ban on the sale of new petrol and diesel cars"
    for (const q of ['travelers', 'promoted', 'marking', 'banning']) {
      const hits = engine.search(q, { limit: 5000 });
      const rank = (h: SearchHit) => (h.approximate ? 2 : h.partial ? 1 : 0);
      expect(hits.every((h, k) => k === 0 || rank(hits[k - 1]) <= rank(h)), q).toBe(true);
    }
    // the summary's similar words are those of the first results shown
    const banning = engine.search('banning', { limit: 1000 }).filter((h) => h.approximate);
    expect(similarWords(banning.map((h) => h.similar))[0]).toBe(banning[0].similar?.[0]);
  });

  it('says when results only start with the word typed', () => {
    for (const q of ['Spa', 'mold', 'pharma package']) {
      const hits = engine.search(q, { limit: 1000 });
      expect(hits.length, q).toBeGreaterThan(0);
      expect(hits.every((h) => h.partial && h.wordStart), q).toBe(true);
    }
  });

  it('finds a file by its common name and the type of its act', () => {
    for (const q of ['whistleblower directive', 'whistleblowing directive', 'whistleblower rules', 'EU whistleblower directive']) {
      expect(top(q), q).toBe('dossier:2018-0106');
      expect(engine.search(q)[0].approximate, q).toBeUndefined();
    }
    for (const q of ['USB-C regulation', 'USB-C directive', 'common charger regulation']) expect(top(q), q).toBe('dossier:2021-0291');
    expect(top('batteries regulation')).toBe('dossier:2020-0353');
  });

  it('gives RED II, RED III and the NIS Directive their own files', () => {
    expect(ids('RED II', 50)).toEqual(['dossier:2016-0382']); // Directive (EU) 2018/2001
    expect(ids('RED III', 50)).toEqual(['dossier:2021-0218']); // Directive (EU) 2023/2413
    expect(ids('NIS', 10).sort()).toEqual(['dossier:2013-0027', 'dossier:2020-0359']);
    expect(top('NIS Directive')).toBe('dossier:2013-0027');
    expect(read<{ known_as: { names?: string[] } }>('dossiers/2021-0218.json').known_as.names).toContain('RED III');
  });

  it('matches vote rapporteurs only as written: a first name has no plural', () => {
    const vh = voteHaystacks(votes);
    const of = (q: string) => matchVotes(votes, vh, q, engine) ?? new Set<string>();
    expect(of('Carlos').has('190668')).toBe(false); // "A10-0088/2026 – Carlo Fidanza – …"
    expect(of('Carlos').has('125367')).toBe(false); // "A9-0197/2020 - Carlo Calenda - Resolution"
    expect(of('Carlos').has('160141')).toBe(true); // Carlos Zorrinho
    expect(of('Carlo').has('190668')).toBe(true);
    expect(of('Carlo').has('160141')).toBe(false);
    expect(of('Nicolas').has('158114')).toBe(false); // Nicola Beer
    expect(of('Marcos').has('167417')).toBe(false); // Marco Campomenosi
    expect(of('agreements').size).toBe(of('agreement').size); // "Provisional agreement" in the labels
  });

  it('finds an act by its number as readers write it: "EU Regulation 2016/679", "Reg 2016/679", "EU 2016/679"', () => {
    for (const q of [
      'EU Regulation 2016/679', 'Regulation EU 2016/679', 'Reg. (EU) 2016/679', 'Reg 2016/679', 'EU 2016/679',
      'Regulation 2016/679 EU', 'EU GDPR',
    ]) { // prettier-ignore
      expect(top(q), q).toBe('dossier:2012-0011'); // CELEX 32016R0679, the GDPR
      expect(engine.search(q)[0].approximate, q).toBeUndefined();
    }
    for (const q of ['EU Directive 2019/1937', 'Dir 2019/1937', 'Dir. (EU) 2019/1937']) expect(top(q), q).toBe('dossier:2018-0106');
    expect(top('EU Data Act')).toBe('dossier:2022-0047');
    expect(engine.search('EU Data Act')[0].approximate).toBeUndefined();
  });

  it('finds every act from 2015 on first by its number in those forms', { timeout: 60_000 }, () => {
    const T: Record<string, [string, string]> = { R: ['Regulation', 'Reg'], L: ['Directive', 'Dir'], D: ['Decision', 'Dec'] };
    const missed: string[] = [];
    let n = 0;
    for (const d of read<SearchDoc[]>('search.json')) {
      if (d.k !== 'dossier') continue;
      for (const t of (d.x ?? '').split(/\s+/)) {
        const m = /^3(\d{4})([RLD])0*(\d+)$/.exec(t);
        if (!m || Number(m[1]) < 2015) continue;
        const [type, abbr] = T[m[2]];
        // one form per act, in turn (all four for every act take half a minute)
        const forms = [`EU ${type} ${m[1]}/${m[3]}`, `${type} EU ${m[1]}/${m[3]}`, `${abbr} ${m[1]}/${m[3]}`, `EU ${m[1]}/${m[3]}`];
        const q = forms[n++ % forms.length];
        const hits = engine.search(q, { limit: 50 });
        const at = hits.findIndex((h) => h.doc.id === d.id);
        if (at < 0 || hits[at].score !== hits[0].score || hits[at].approximate) missed.push(`${q} ${d.id}`);
      }
    }
    expect(n).toBeGreaterThan(1000);
    expect(missed).toEqual([]);
  });

  it('ranks a file named with another act type than its own first', () => {
    expect(top('GDPR directive')).toBe('dossier:2012-0011'); // not only the Digital Omnibus, which mentions both words
    expect(top('simplification omnibus regulation')).toBe('dossier:2025-0045'); // Omnibus I
    expect(top('packaging waste directive')).toBe('dossier:2015-0276'); // the directives on packaging waste stay first
    expect(top('GDPR regulation')).toBe('dossier:2012-0011');
  });

  it('answers "<country, group or party> MEPs" with it and links the MEP directory, not files on "Member States"', () => {
    const first = (q: string) => engine.search(q, { limit: 5 })[0];
    for (const [q, want] of [
      ['Spanish MEPs', 'country:ES'], ['MEPs from Spain', 'country:ES'], ['German MEPs', 'country:DE'],
      ['Greens MEPs', 'group:greens-efa'], ['ECR MEPs', 'group:ecr'], ['EPP MEPs', 'group:epp'], ['S&D MEPs', 'group:s-d'],
    ]) { // prettier-ignore
      expect(key(first(q)), q).toBe(want);
      expect(first(q).meps, q).toBe(true);
    }
    expect(ids('Greens MEPs', 50)).not.toContain('dossier:2021-0071'); // certificates for third-country nationals
    expect(ids('ECR MEPs', 50).some((k) => k.startsWith('dossier:'))).toBe(false); // not ECRIS-TCN
    expect(ids('former MEPs', 50)).not.toContain('dossier:2014-0199'); // "the former Yugoslav Republic of Macedonia"
    expect(top('election of MEPs')).toBe('dossier:2025-0900'); // "... the election of the members of the European Parliament"
    expect(top('MEP statute')).toBe('dossier:2026-0900'); // "... the Statute for Members of the European Parliament"
  });

  it('matches plurals in -ves and -oes, US spellings and a dropped "e" as forms of the word', () => {
    const vh = voteHaystacks(votes);
    expect(top('wolves')).toBe('dossier:2025-0058'); // "... the protection status of the wolf"
    expect(matchVotes(votes, vh, 'wolves', engine)?.has('176305')).toBe(true);
    expect(top('vetoes')).toBe('page:council-voting');
    expect(top('potato')).toBe('dossier:2023-0062'); // "... seed potatoes"
    expect(engine.search('potato')[0].approximate).toBeUndefined();
    const forms = (q: string) => engine.search(q, { limit: 1000 });
    expect(forms('labeled').map(key)).toContain('dossier:2015-0149'); // "Energy efficiency labelling"
    expect(forms('labeled').every((h) => h.partial)).toBe(true);
    expect(forms('canceled').map(key)).toEqual(['dossier:2013-0072']); // "... cancellation ..."
    expect(forms('emissions trade').length).toBe(forms('emissions trading').length); // "trading"
    expect(forms('emissions trade').every((h) => h.partial)).toBe(true);
    expect(forms('directives').length).toBe(forms('directive').length);
    expect(forms('packageing').every((h) => h.approximate)).toBe(true); // still a typo of "packaging"
  });

  it('does not count the act type of a file as another form of a word', () => {
    // each file found for "regulated" has a word starting with "regulat" in its names or keywords
    const docs = new Map(read<SearchDoc[]>('search.json').map((d) => [`${d.k}:${d.id}`, d]));
    const shown = (d: SearchDoc) => `${d.t} ${d.a ?? ''} ${(d.x ?? '').split(/\s+/).filter((x) => x !== 'regulation').join(' ')}`;
    const regulated = engine.search('regulated', { limit: 5000 });
    expect(regulated.length).toBeLessThan(500);
    expect(regulated.filter((h) => !/\bregulat/i.test(shown(docs.get(key(h))!))).map(key)).toEqual([]);
    expect(engine.search('regulation', { limit: 5000 }).map(key)).toContain('dossier:2022-0047'); // the Data Act, by its act type
    expect(top('whistleblower directive')).toBe('dossier:2018-0106');
  });

  it('describes word starts in the explorer as the search page does', () => {
    const hay = buildHaystacks(rows);
    const partial = new Set<string>();
    const starts = new Set<string>();
    expect(keywordScores(rows, hay, engine, 'Spa', partial, undefined, starts).size).toBeGreaterThan(0);
    expect([...partial].sort()).toEqual([...starts].sort()); // "Space", "spatial": words starting with "Spa"
    const fish = new Set<string>();
    const fishStarts = new Set<string>();
    keywordScores(rows, hay, engine, 'fish', fish, undefined, fishStarts);
    expect(fish.size).toBeGreaterThan(0);
    expect(fishStarts.size).toBe(0); // "fisheries" is another form of the word
  });

  it('says what each part of a query finds when nothing matches all of it', () => {
    const parts = (q: string) => queryParts(engine, q)?.map((p) => [p.text, p.hits[0] ? key(p.hits[0]) : null]);
    expect(engine.search('NIS2 Ireland')).toEqual([]);
    expect(parts('NIS2 Ireland')).toEqual([['NIS2', 'dossier:2020-0359'], ['Ireland', 'country:IE']]);
    expect(parts('GDPR Ireland')).toEqual([['GDPR', 'dossier:2012-0011'], ['Ireland', 'country:IE']]);
    expect(parts('von der leyen')).toBeUndefined();
    // the directive's row on the Ireland page, which the search page links to
    const ie = read<CountryDetail>('countries/IE.json');
    expect(ie.transposition.find((r) => r.dossier_id === '2020-0359')?.act).toBe('Directive (EU) 2022/2555');
    expect(ie.transposition.some((r) => r.dossier_id === '2012-0011')).toBe(false); // a regulation: no transposition
  });

  it("finds a file by the site's own id, and lists only its votes", () => {
    const vh = voteHaystacks(votes);
    const fileOf = new Map(votes.map((v) => [v.id, v.dossier_id]));
    for (const [q, file] of [['2021-0106', '2021-0106'], ['2021 0106', '2021-0106'], ['2023-0134', '2023-0134']]) {
      expect(ids(q), q).toEqual([`dossier:${file}`]);
      const found = matchVotes(votes, vh, q, engine)!;
      expect(found.size, q).toBeGreaterThan(0);
      expect([...found].every((id) => fileOf.get(id) === file), q).toBe(true); // not the discharge reports A9-0106/2023
    }
    // pairs of years are not file ids
    expect(matchVotes(votes, vh, 'Erasmus 2021-2027', engine)?.has('163025')).toBe(true);
    expect(matchVotes(votes, vh, '2019-2024', engine)!.size).toBeGreaterThan(10);
    expect(ids('2021-2027', 50).length).toBeGreaterThan(10);
  });

  it('does not match vote rapporteurs by the start of their names', () => {
    const hay = voteHaystacks(votes);
    const pis = matchVoteDetails(votes, hay, 'PiS', engine);
    expect(pis?.ids.has('166145')).toBe(false); // "A9-0050/2024 – Dragoş Pîslaru – …"
    expect(pis?.ids.has('150117')).toBe(false); // "A9-0252/2022 - Giuliano Pisapia - …"
    expect(matchVoteDetails(votes, hay, 'Left', engine)?.ids.has('142256')).toBe(false); // "Lefteris Christoforou"
    const artific = matchVoteDetails(votes, hay, 'artific', engine);
    expect(artific?.partial).toBe(true);
    expect(artific?.ids.has('166051')).toBe(true); // Artificial Intelligence Act — final vote
  });
});
