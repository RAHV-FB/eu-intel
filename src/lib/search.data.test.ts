/**
 * Search regressions on the real built index (public/data from `python -m pipeline build`). Skipped when the
 * data has not been built. Each block is a query a reader actually typed and the result they needed.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierSummary, EpVoteSummary, SearchDoc } from '../types/data';
import { createSearchEngine, type SearchHit } from './search';
import { buildHaystacks, keywordScores } from '../features/legislation/explorer';
import { matchVotes, voteHaystacks } from '../features/votes/keyword';

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
});
