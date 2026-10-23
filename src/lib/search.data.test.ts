/**
 * Search regressions on the real built index (public/data from `python -m pipeline build`). Skipped when the
 * data has not been built. Each block is a query a reader actually typed and the result they needed.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierSummary, EpVoteSummary, SearchDoc } from '../types/data';
import { createSearchEngine, type SearchHit } from './search';
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
