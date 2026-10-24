/**
 * "What happens next" for a regulation in force (Summary.tsx regulationNextStep): the dates still to come lead, the
 * general rule follows; once none is ahead, that no step follows. On the real build when it has been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierDetail, DossierSummary } from '../../../types/data';
import { asOfToday } from '../../../lib/format';
import { regulationNextStep } from './Summary';

const DIRECTLY = 'As a regulation, it applies directly in all EU countries; no national transposition is needed.';

describe('what happens next for a regulation in force', () => {
  // 2021/0106(COD), the AI Act (Regulation (EU) 2024/1689), as pipeline/analysis/status.py writes it
  const ai =
    'The regulation applies directly in all EU countries; no national transposition is needed. Later dates from which ' +
    '(parts of) the act apply: 2 December 2026, 2 December 2027 and 2 August 2028.';

  it('leads with the dates from which provisions still start to apply', () => {
    expect(regulationNextStep(ai)).toEqual({
      text: `Provisions of the act start to apply on 2 December 2026, 2 December 2027 and 2 August 2028. ${DIRECTLY}`,
      later: true,
    });
    // on the visitor's date, as the build would write it then: the dates that have come are left out
    expect(regulationNextStep(asOfToday(ai, '2027-12-02'))).toEqual({
      text: `Provisions of the act start to apply on 2 August 2028. ${DIRECTLY}`,
      later: true,
    });
  });

  it('says that no step follows once no date is ahead, and never names a general rule as the next step', () => {
    expect(regulationNextStep(asOfToday(ai, '2028-08-02'))).toEqual({ text: `No further step in the procedure. ${DIRECTLY}`, later: false });
  });

  it('leaves every other text as the build wrote it', () => {
    // ETIAS, Regulation (EU) 2018/1240: no date from which it applies in general
    const unrecorded =
      'A regulation applies directly in all EU countries; no national transposition is needed. EUR-Lex records no date ' +
      'from which this regulation in general applies (it refers to Art. 96).';
    expect(regulationNextStep(unrecorded)).toEqual({ text: unrecorded, later: false });
    const enters = `The act enters into force on 1 December 2026. ${ai}`;
    expect(regulationNextStep(enters)).toEqual({ text: enters, later: false });
    const directive = 'The transposition deadline (17 October 2024) has passed: the Member States bound by the directive were required to adopt national measures by then.';
    expect(regulationNextStep(directive)).toEqual({ text: directive, later: false });
  });
});

const DATA = new URL('../../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

describe.skipIf(!built)('regulations in force on the built data', () => {
  it('are all written in a form that leads with the dates still to come', () => {
    const texts = read<DossierSummary[]>('dossiers/index.json')
      .filter((d) => d.stage === 'in_force' && d.instrument === 'regulation')
      .map((d) => [d.id, read<DossierDetail>(`dossiers/${d.id}.json`).next_step.text] as const)
      .filter(([, t]) => t.startsWith('The regulation applies directly'));
    expect(texts.length).toBeGreaterThan(50);
    for (const [id, t] of texts) {
      const next = regulationNextStep(t);
      expect(next.text, id).not.toBe(t);
      expect(next.text.endsWith(DIRECTLY), id).toBe(true);
    }
  });
});
