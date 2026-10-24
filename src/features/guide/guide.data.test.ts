/**
 * The guide's wording on adoption, publication and entry into force, and its list of status labels against the
 * real build (public/data from `python -m pipeline build`; the label checks are skipped when it has not been built).
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { GLOSSARY } from '../../content/glossary';
import type { DossierSummary, LifecycleStage } from '../../types/data';
import { STAGE_GROUPS } from '../legislation/labels';
import { STEPS } from './PathwayDiagram';
import { LISTED_STATUS_LABELS, STATUS_LABEL_GROUPS } from './statusLabels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));

/** Stages before an act is adopted: the guide lists only the common labels of these. */
const BEFORE_ADOPTION = new Set<LifecycleStage>(['proposed', 'parliament_position', 'negotiations', 'provisional_agreement', 'unknown']);

describe('adoption, signature, publication, entry into force and application', () => {
  const rows = STATUS_LABEL_GROUPS.flatMap((g) => g.rows.map((r) => r.text));
  const texts = [...STEPS.map((s) => s.text), ...rows, GLOSSARY['entry-into-force'].short, GLOSSARY['official-journal'].short];

  it('never says that publication, or entry into force, makes an act "EU law", "applicable law" or a law that "exists"', () => {
    for (const t of texts) {
      expect(t, t).not.toMatch(/\b(EU|applicable) law\b/i);
      expect(t, t).not.toMatch(/legally exists?|from then on/i);
    }
  });

  it('keeps signature and publication apart from entry into force, and entry into force from application', () => {
    const titles = STEPS.map((s) => s.title);
    expect(titles).toContain('Signature & publication');
    expect(titles).toContain('Entry into force & application');
    const eif = STEPS.find((s) => s.title.startsWith('Entry into force'))!.text;
    expect(eif).toMatch(/twentieth day after publication/); // Article 297(1) TFEU
    expect(eif).toMatch(/apply later/);
    expect(GLOSSARY['entry-into-force'].short).toMatch(/twentieth day after publication/);
    expect(GLOSSARY['entry-into-force'].short).toMatch(/start to apply later/);
  });
});

describe.skipIf(!built)('status labels on the built data', () => {
  const index: DossierSummary[] = built ? JSON.parse(readFileSync(new URL('dossiers/index.json', DATA), 'utf8')) : [];
  const labels = [...new Map(index.map((d) => [`${d.stage}|${d.status_label}`, d])).values()];

  it('has a build to check', () => {
    expect(labels.length).toBeGreaterThan(5);
  });

  it('explains every label of an adopted, published, in force, repealed or ended file', () => {
    const missing = labels
      .filter((d) => !BEFORE_ADOPTION.has(d.stage) && !LISTED_STATUS_LABELS.has(d.status_label))
      .map((d) => `${d.stage}: ${d.status_label}`);
    expect(missing).toEqual([]);
  });

  it('lists each label that the build produces under the stage the build gives it', () => {
    for (const d of labels) {
      const listed = LISTED_STATUS_LABELS.get(d.status_label);
      if (listed) expect(listed, d.status_label).toBe(d.stage);
    }
  });

  it('puts no label of a stage before adoption among the adopted, in force or ended groups', () => {
    const early = new Set(labels.filter((d) => BEFORE_ADOPTION.has(d.stage)).map((d) => d.status_label));
    for (const g of STATUS_LABEL_GROUPS.filter((x) => x.id !== 'not-adopted')) {
      for (const r of g.rows) for (const x of [...r.labels, ...(r.also ?? [])]) expect(early.has(x.label), `${g.id}: ${x.label}`).toBe(false);
    }
  });
});

describe('rejected and withdrawn files in the status labels', () => {
  const group = STATUS_LABEL_GROUPS.find((g) => g.rows.some((r) => r.labels.some((x) => x.label === 'Rejected by Parliament')))!;
  const row = group.rows.find((r) => r.labels.some((x) => x.label === 'Rejected by Parliament'))!;

  it('does not file a rejection at first reading under an ended procedure (2023/0413(COD), awaiting the Council’s position)', () => {
    expect(group.heading).toBe('Withdrawn, rejected or lapsed');
    expect(STAGE_GROUPS.ended.label).toBe('Withdrawn, rejected or lapsed');
    expect(row.text).toContain('A rejection at first reading is Parliament’s first-reading position');
    expect(row.text).toContain('(Article 294(5) TFEU) unless the Commission withdraws the proposal');
    expect(row.text).toContain('(Article 294(7)(b) and (13) TFEU)');
  });
});
