/**
 * The guide's wording on adoption, publication and entry into force, and its list of status labels against the
 * real build (public/data from `python -m pipeline build`; the label checks are skipped when it has not been built).
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { GLOSSARY } from '../../content/glossary';
import type { DossierDetail, DossierSummary, LifecycleStage } from '../../types/data';
import { STAGE_GROUPS } from '../legislation/labels';
import { STEPS } from './PathwayDiagram';
import { LISTED_STATUS_LABELS, STATUS_LABEL_GROUPS } from './statusLabels';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));

/** Stages before an act is adopted: the guide lists only the common labels of these. */
const BEFORE_ADOPTION = new Set<LifecycleStage>(['proposed', 'parliament_position', 'negotiations', 'provisional_agreement']);

const groupOf = (label: string) => STATUS_LABEL_GROUPS.find((g) => g.rows.some((r) => r.labels.some((x) => x.label === label)))!;
const rowOf = (label: string) => STATUS_LABEL_GROUPS.flatMap((g) => g.rows).find((r) => r.labels.some((x) => x.label === label))!;
const dossier = (id: string): DossierDetail => JSON.parse(readFileSync(new URL(`dossiers/${id}.json`, DATA), 'utf8'));

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

  it('does not say that an act enters into force once published (Art. 297 TFEU): it can on adoption, or on notification', () => {
    const adopted = rowOf('Adopted by the Council');
    expect(adopted).toBe(rowOf('Signed, awaiting publication'));
    expect(adopted.text).not.toMatch(/once published/i);
    expect(adopted.text).toMatch(/which can be the day of its adoption, or, if it sets none, on the twentieth day after publication/);
    expect(adopted.text).toMatch(/non-legislative directive not addressed to all Member States, or decision addressed to specific recipients, takes effect when they are notified \(Article 297 TFEU\)/);
    expect(GLOSSARY['entry-into-force'].short).toMatch(/non-legislative directive not addressed to all Member States, or decision addressed to specific recipients, takes effect when they are notified/);
    // the group of adopted acts makes no claim about entry into force: a Council act can be in force on adoption
    expect(groupOf('Adopted by the Council').heading).not.toMatch(/force/i);
  });

  it('keeps "Takes effect on notification" out of "In force", with no Treaty rule: these decisions are legislative acts', () => {
    const g = groupOf('Takes effect on notification');
    expect(g.id).not.toBe('in-force');
    expect(g.heading).toBe('Published: not recorded as in force');
    expect(rowOf('Takes effect on notification').text).not.toMatch(/Article|297/);
    expect(rowOf('Takes effect on notification').text).toContain('does not mark the decision as in force');
    const inForce = STATUS_LABEL_GROUPS.find((x) => x.id === 'in-force')!;
    expect(inForce.rows.flatMap((r) => [...r.labels, ...(r.also ?? [])]).map((x) => x.stage)).toEqual(['in_force']);
  });

  it('defines labels no more narrowly than the Treaties and the records (Arts 288 and 289 TFEU; OEIL "lapsed or withdrawn")', () => {
    expect(rowOf('In force').text).not.toMatch(/each Member State/);
    expect(rowOf('In force').text).toContain('by the Member States it is addressed to'); // Art. 288 TFEU
    expect(rowOf('Published in the Official Journal').text).not.toMatch(/itself sets that date/);
    const lapsed = rowOf('Lapsed or withdrawn');
    expect(lapsed.labels.map((x) => x.label)).toEqual(['Lapsed', 'Lapsed or withdrawn']);
    expect(lapsed.text).toContain('lapsed or was withdrawn, without saying which');
    expect(STEPS[0].text).toMatch(/regulation, directive or decision/); // Art. 289(1) TFEU
  });

  it('describes unanimity and the blocking minority as the Treaties do (Art. 16(4) TEU, Art. 238(4) TFEU)', () => {
    expect(GLOSSARY.unanimity.short).not.toMatch(/must agree/);
    expect(GLOSSARY.unanimity.short).toContain('an abstention does not');
    expect(GLOSSARY['blocking-minority'].short).toContain('or 13 Member States whatever their population');
  });
});

describe.skipIf(!built)('status labels on the built data', () => {
  const index: DossierSummary[] = built ? JSON.parse(readFileSync(new URL('dossiers/index.json', DATA), 'utf8')) : [];
  const labels = [...new Map(index.map((d) => [`${d.stage}|${d.status_label}`, d])).values()];

  it('has a build to check', () => {
    expect(labels.length).toBeGreaterThan(5);
  });

  it('explains every label of an adopted, published, in force, repealed or ended file, and every label naming no stage', () => {
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

  it('defines the labels that name no stage: "Procedure completed" (2021/0415(CNS)) and an unlinked act (2025/0806(CNS))', () => {
    expect(labels.filter((d) => d.stage === 'unknown').map((d) => d.status_label)).toEqual(
      expect.arrayContaining(['Procedure completed', 'Final act not linked in the official records', 'Split into separate procedures']),
    );
    expect(index.find((d) => d.id === '2021-0415')?.status_label).toBe('Procedure completed');
    expect(index.find((d) => d.id === '2025-0806')?.status_label).toBe('Final act not linked in the official records');
    expect(groupOf('Procedure completed').id).toBe('other');
    expect(groupOf('Final act not linked in the official records').id).toBe('other');
  });

  it('matches the records the guide wording rests on: an act in force before publication, a legislative decision notified', () => {
    // Council Decision (EU) 2017/1908, Art. 2: "This Decision shall enter into force on the date of its adoption"
    const d = dossier('2017-0808').acts.find((a) => a.celex === '32017D1908')!;
    expect([d.entry_into_force, d.date_publication]).toEqual(['2017-10-12', '2017-10-19']);
    // Decision (EU) 2020/1531 of the European Parliament and of the Council (2020/0160(COD)): not in force for EUR-Lex
    const n = dossier('2020-0160');
    expect([n.type, n.status.stage, n.acts[0].in_force, n.status.since]).toEqual(['COD', 'takes_effect_on_notification', false, n.acts[0].date_publication]);
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
