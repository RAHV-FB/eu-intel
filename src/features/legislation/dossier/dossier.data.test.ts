/**
 * Dossier pages on the real build (public/data): split procedures' parents, Parliament's R/M reports and the
 * "Latest recorded step". Skipped when the data has not been built.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CoverageScope, DossierDetail, Meta, TimelineEvent } from '../../../types/data';
import { institutionSuffix } from '../labels';
import { latestDone } from './Summary';
import { noCouncilVoteNote } from './Votes';
import { currentStepKey } from './WhereIsIt';
import { rapporteurRoleLabel } from '../../people/labels';

const DATA = new URL('../../../../public/data/', import.meta.url);
const built = existsSync(new URL('dossiers/index.json', DATA));
const read = <T>(name: string): T => JSON.parse(readFileSync(new URL(name, DATA), 'utf8')) as T;

const ev = (id: string, date: string, key: boolean): TimelineEvent =>
  ({ id, date, key, state: 'done', title: id, kind: 'other', institution: 'EP' }) as unknown as TimelineEvent;

describe('the latest recorded step', () => {
  it('takes the key step of the latest day, whatever the order of that day’s steps', () => {
    const tl = [ev('vote', '2026-09-15', false), ev('referral', '2026-09-15', true), ev('tabled', '2026-09-15', false)];
    expect(latestDone(tl, '2026-10-23')?.id).toBe('referral');
    expect(latestDone([ev('a', '2026-09-14', true), ev('b', '2026-09-15', false)], '2026-10-23')?.id).toBe('b');
    expect(latestDone([ev('a', '2026-11-01', true)], '2026-10-23')).toBeNull();
  });
});

describe('why a file shows no Council vote', () => {
  const scope = { council_votes_from: '2019-01-28', council_votes_to: '2026-10-19' } as CoverageScope;
  const step = { ...ev('council', '2022-12-14', true), kind: 'council_adoption', title: 'Council adopted the act after consulting Parliament' } as TimelineEvent;

  it('does not call a file adopted within the period of our Council data under discussion or outside it (2021-0433)', () => {
    const note = noCouncilVoteNote([step], '2022-12-14', scope);
    expect(note).toContain('Its timeline records “Council adopted the act after consulting Parliament” on 14 December 2022, within the period');
    expect(note).toContain('28 January 2019 to 19 October 2026');
    expect(note).not.toContain('under discussion');
  });

  it('says when the Council’s step falls before or after the Council votes in our data, and keeps the general reason otherwise', () => {
    expect(noCouncilVoteNote([{ ...step, date: '2018-03-12' }], '2018-03-12', scope)).toContain('before the first Council vote in our data (28 January 2019)');
    expect(noCouncilVoteNote([{ ...step, date: '2026-10-21' }], null, scope)).toContain('after the latest Council vote in our data (19 October 2026)');
    expect(noCouncilVoteNote([], '2020-08-06', scope)).toContain('The file was adopted on 6 August 2020, within the period');
    expect(noCouncilVoteNote([], null, scope)).toContain('files still under discussion, or adopted outside the period covered (28 January 2019 to 19 October 2026)');
    expect(noCouncilVoteNote([step], '2022-12-14', undefined)).toContain('files still under discussion');
  });
});

describe.skipIf(!built)('dossiers on the built data', () => {
  const ids = built ? readdirSync(new URL('dossiers/', DATA)).filter((f) => f !== 'index.json').map((f) => f.replace(/\.json$/, '')) : [];
  const all = ids.map((id) => read<DossierDetail>(`dossiers/${id}.json`));

  it('agrees with "Where is it now?" on the latest milestone when both fall on the same day (2025-0418, 2026-0085)', () => {
    const today = '2026-10-23';
    for (const d of all) {
      const latest = latestDone(d.timeline, today);
      const milestone = [...d.timeline].reverse().find((e) => e.state === 'done' && e.key && e.date <= today);
      if (latest && milestone && latest.date === milestone.date && !latest.after_end_of_validity) expect(latest.id, d.id).toBe(milestone.id);
    }
    const d = all.find((x) => x.id === '2025-0418')!;
    expect(latestDone(d.timeline, today)!.title).toBe('Parliament sent the file back to committee to negotiate with the Council');
  });

  it('dates a split parent by the proposal all its parts record, and lists that proposal (2016-0224)', () => {
    // 2016/0224(COD) read "Proposed: Not recorded"; 2016/0224A and B(COD) record COM(2016)0467 of 13 July 2016
    const parents = all.filter((d) => d.related.some((r) => r.relation === 'Split into'));
    for (const d of parents) {
      const parts = d.related.filter((r) => r.relation === 'Split into').map((r) => all.find((x) => x.id === r.id)!);
      if (!d.started_from_parts) continue;
      for (const x of parts) expect(x.started, `${d.id} ${x.id}`).toBe(d.started);
      const coms = parts.map((x) => x.documents.filter((doc) => doc.id.startsWith('COM(')).map((doc) => doc.id).join());
      expect(new Set(coms).size, d.id).toBe(1);
      expect(d.documents.map((doc) => doc.id), d.id).toContain(coms[0]);
    }
    const p224 = all.find((d) => d.id === '2016-0224')!;
    expect([p224.started, p224.started_from_parts, p224.documents.some((doc) => doc.id === 'COM(2016)0467')]).toEqual(['2016-07-13', true, true]);
    for (const d of all) if (d.started_from_parts) expect(parents, d.id).toContain(d);
  });

  it('never shows a generated name as a split parent’s official title, and tells its parts apart', () => {
    const parents = all.filter((d) => d.related.some((r) => r.relation === 'Split into'));
    expect(parents.length).toBe(12);
    for (const d of parents) {
      expect(d.official_title ?? '', d.id).not.toMatch(/split into/);
      const parts = d.related.filter((r) => r.relation === 'Split into');
      expect(new Set(parts.map((r) => r.ref)).size, d.id).toBe(parts.length);
      for (const r of parts) expect(r.status_label, `${d.id} ${r.id}`).toBeTruthy();
      expect(d.status.named_acts?.map((a) => a.dossier), d.id).toEqual(parts.map((r) => r.id));
    }
    const p400 = parents.find((d) => d.id === '2016-0400')!;
    expect(p400.official_title).toBeNull();
    expect(p400.related.filter((r) => r.relation === 'Split into').map((r) => [r.ref, r.status_label])).toEqual([
      ['2016/0400A(COD)', 'In force'],
      ['2016/0400B(COD)', 'Withdrawn by the Commission'],
    ]);
    expect(parents.find((d) => d.id === '2016-0224')!.official_title?.trim()).toBe('Common procedure for international protection in the Union');
  });

  it('links the main file from a Parliament report’s status and next step, and the report from the main file', () => {
    const reports = all.filter((d) => /^\d{4}-\d{4}[RM]$/.test(d.id));
    expect(reports.map((d) => d.id).sort()).toEqual(['2017-0333R', '2018-0166R', '2020-0112R', '2021-0429R', '2023-0201M', '2023-0201R', '2025-0571R']);
    for (const d of reports) {
      const main = d.id.slice(0, 9);
      const link = d.status.named_acts?.find((a) => a.dossier === main);
      expect(link, d.id).toBeTruthy();
      expect(d.status.explanation).toContain(link!.label);
      expect(d.next_step.text).toContain(link!.label);
      const back = read<DossierDetail>(`dossiers/${main}.json`).related.find((r) => r.id === d.id);
      expect(back?.relation, d.id).toMatch(/^Parliament's (interim )?report$/);
      // the two have the same title (2020/0112(APP) and 2020/0112R(APP)): each link gives the other's reference
      expect(back?.ref, d.id).toBe(d.ref);
      expect(d.related.find((r) => r.relation === 'Report on')?.ref, d.id).toBe(read<DossierDetail>(`dossiers/${main}.json`).ref);
    }
  });

  it('says why a file adopted while our Council data runs has no Council vote, and links CRR II’s (2016-0360A)', () => {
    const scope = read<Meta>('meta.json').scope;
    expect([scope?.council_votes_from, scope?.council_votes_to]).toEqual(['2019-01-28', '2026-10-19']);
    const none = all.filter((d) => d.council_votes.length === 0 && !d.related.some((r) => r.relation === 'Split into'));
    const within = none.filter((d) => noCouncilVoteNote(d.timeline, d.adopted, scope).includes('within the period'));
    // Council Directive (EU) 2020/1151 (2018/0173(CNS)), adopted 29 July 2020; the Pillar Two Directive (2021/0433(CNS))
    // has its adoption from CM 5860/22, "completed on 15 December 2022 at 22:11", Hungary abstaining
    expect(within.map((d) => d.id)).toContain('2018-0173');
    expect(within.map((d) => d.id)).not.toContain('2016-0360A');
    const pillar2 = all.find((d) => d.id === '2021-0433')!;
    expect(pillar2.council_votes.map((v) => [v.id, v.date, v.positions.HU])).toEqual([['CM-5860-2022-2', '2022-12-15', 'abstain']]);
    expect(pillar2.adopted).toBe('2022-12-15');
    expect(pillar2.acts[0].date_document).toBe('2022-12-14'); // "Council Directive (EU) 2022/2523 of 14 December 2022"
    for (const d of none) {
      const step = [...d.timeline].reverse().find((e) => e.state === 'done' && (e.kind === 'council_adoption' || e.kind === 'council_position'));
      if (step || d.adopted) expect(noCouncilVoteNote(d.timeline, d.adopted, scope), d.id).not.toContain('under discussion');
    }
  });

  it('never shows a recorded provisional agreement as not yet reached on the path (2023-0210, 2023-0134)', () => {
    const at = (id: string) => currentStepKey(all.find((d) => d.id === id)!);
    expect(at('2023-0210')).toBe('adopted'); // early second-reading agreement approved in committee on 5 May 2026
    expect(at('2023-0134')).toBe('adopted'); // "Approved by Parliament" on the text agreed with the Council
    expect(at('2018-0332')).toBe('deciding'); // negotiations after the first reading, no agreement recorded
    const order = ['proposed', 'deciding', 'agreement', 'adopted', 'in_force'];
    for (const d of all.filter((x) => x.type === 'COD')) {
      const agreed = d.timeline.some((e) => e.state === 'done' && e.kind === 'provisional_agreement');
      const key = currentStepKey(d);
      if (agreed && key) expect(order.indexOf(key), d.id).toBeGreaterThanOrEqual(order.indexOf('agreement'));
    }
  });

  it('names a rapporteur’s committee as OEIL does where the EP API gives none or a subcommittee', () => {
    const committee = (id: string, mep: string) => all.find((d) => d.id === id)!.rapporteurs.find((r) => r.mep_id === mep)?.committee;
    expect(committee('2021-0240', '96899')).toBe('CONT'); // EP API "org/null"; OEIL: CONT, FERNANDES José Manuel
    expect(committee('2025-0045', '204332')).toBe('AFET'); // EP API DROI; OEIL: AFET, ANDREWS Barry
    expect(all.find((d) => d.id === '2023-0187')!.rapporteurs.filter((r) => r.role === 'rapporteur').map((r) => r.committee)).toEqual(['ECON']);
    for (const d of all) for (const r of d.rapporteurs) expect(r.committee, `${d.id} ${r.mep_id}`).not.toBe('null');
  });

  it('links a rapporteur only to an MEP page that is written, and lists an MEP once per role (2026-0172)', () => {
    const pages = new Set(readdirSync(new URL('people/meps/', DATA)).map((f) => f.replace(/\.json$/, '')));
    let linked = 0;
    let unlinked = 0;
    for (const d of all) {
      const seen = new Set<string>();
      for (const r of d.rapporteurs) {
        expect(!!r.has_page, `${d.id} ${r.mep_id}`).toBe(!!r.mep_id && pages.has(r.mep_id));
        if (r.has_page) linked += 1;
        else unlinked += 1;
        const key = `${r.mep_id} ${r.role} ${r.committee ?? ''}`;
        expect(seen.has(key), `${d.id} ${key}`).toBe(false);
        seen.add(key);
      }
    }
    expect(linked).toBeGreaterThan(0);
    expect(unlinked).toBeGreaterThan(0); // e.g. Timothy Kirkhope (4542) on 2011-0023, who sat before 2019
    // OEIL links her as 10006693, which neither the EP website nor this site has a page for
    const christ = all.find((d) => d.id === '2026-0172')!.rapporteurs.filter((r) => /christ/i.test(r.name));
    expect(christ.map((r) => [r.mep_id, r.name, r.role, r.has_page])).toEqual([['277057', 'Marie-Sophie Christ', 'shadow', true]]);
  });

  it('calls a file joint only when two committees lead it now, and labels earlier-term roles former', () => {
    for (const d of all) {
      const joint = new Set(d.committees.filter((c) => c.role === 'joint' && !c.former).map((c) => c.code));
      expect(joint.size === 0 || joint.size > 1, d.id).toBe(true);
    }
    const roles = (id: string) => all.find((d) => d.id === id)!.committees.map((c) => [c.code, c.role, !!c.former]);
    expect(roles('2023-0226')).toEqual([['ENVI', 'responsible', false], ['AGRI', 'opinion', true]]); // MHE-ENVI and MAIN-ENVI
    expect(roles('2023-0131').slice(0, 2)).toEqual([['SANT', 'responsible', false], ['ENVI', 'responsible', true]]);
    expect(roles('2013-0072').slice(0, 2)).toEqual([['LEGI', 'responsible', false], ['TRAN', 'responsible', true]]);
    expect(rapporteurRoleLabel('rapporteur', 'TRAN', true)).toBe('Former rapporteur (TRAN)');
    expect(rapporteurRoleLabel('shadow', null)).toBe('Shadow rapporteur');
    const shadows = all.find((d) => d.id === '2025-0313')!.rapporteurs.filter((r) => r.role === 'shadow');
    expect(shadows.map((r) => r.group_code).sort()).toEqual(['ECR', 'Greens/EFA', 'PfE', 'Renew', 'The Left']); // OEIL's key players
  });

  it('shows on a joint debate this file’s documents only, and names the other files', () => {
    const reports = new Map(all.map((d) => [d.id, new Set(d.documents.filter((x) => x.kind === 'report').map((x) => x.id))]));
    let joint = 0;
    for (const d of all)
      for (const e of d.timeline.filter((x) => x.kind === 'plenary_debate')) {
        const others = e.docs.filter((x) => /^A-/.test(x.id) && !reports.get(d.id)!.has(x.id));
        expect(others.map((x) => x.id), `${d.id} ${e.id}`).toEqual([]);
        if (e.joint_with?.length) joint += 1;
        expect(e.title === 'Joint debate in Parliament', `${d.id} ${e.id}`).toBe(!!e.joint_with?.length);
      }
    expect(joint).toBeGreaterThan(100);
    const step = all.find((d) => d.id === '2023-0112')!.timeline.find((e) => e.id === 'MTG-PL-2026-03-25-PVCRE-ITM-15')!;
    expect(step.joint_with!.map((j) => [j.ref, j.report?.label])).toEqual([
      ['2023/0111(COD)', 'A10-0067/2026'],
      ['2023/0115(COD)', 'A10-0065/2026'],
    ]);
  });
});

describe('steps dated in the act', () => {
  it('names no institution after them: EUR-Lex records them, the act sets them', () => {
    expect(institutionSuffix('Entered into force', 'EUR-Lex', 'entry_into_force')).toBe('');
    expect(institutionSuffix('Started to apply: The Regulation in general (Art. 93(2))', 'EUR-Lex', 'application')).toBe('');
    expect(institutionSuffix('Published in the Official Journal of the EU', 'EUR-Lex', 'publication')).toBe('EUR-Lex');
  });
});

describe.skipIf(!built)('application dates, act names and sources on the built data', () => {
  const ids = built ? readdirSync(new URL('dossiers/', DATA)).filter((f) => f !== 'index.json').map((f) => f.replace(/\.json$/, '')) : [];
  const all = ids.map((id) => read<DossierDetail>(`dossiers/${id}.json`));
  const byId = (id: string) => all.find((d) => d.id === id)!;

  it('never presents an application date EUR-Lex gives as not recorded as applying from the entry into force (ETIAS, VIS)', () => {
    // Regulation (EU) 2018/1240, Art. 96: "This Regulation shall apply from the date determined by the Commission"
    const etias = byId('2016-0357A');
    expect(etias.application?.application_unrecorded).toEqual([{ partial: false, articles: ['Art. 96'] }]);
    expect(etias.status.explanation).toContain('EUR-Lex records no date from which the act in general applies (it refers to Art. 96).');
    expect(etias.next_step.text).not.toMatch(/^The regulation applies directly/);
    const vis = byId('2018-0152A');
    expect(vis.next_step.text).toContain('EUR-Lex records no date from which this regulation in general applies.');
    for (const d of all)
      if (d.application?.application_unrecorded?.some((x) => !x.partial) && d.instrument === 'regulation' && d.stage === 'in_force')
        expect(d.next_step.text, d.id).not.toMatch(/^The regulation applies directly/);
  });

  it('gives the dates set since by the decision the act refers to (Clinical Trials Regulation, EPPO, PRIMA)', () => {
    const ctr = byId('2012-0192');
    expect(ctr.application?.application_detail).toEqual([{ date: '2022-01-31', partial: false, provisions: 'The Regulation (Art. 99, second paragraph)' }]);
    expect(byId('2013-0255').application?.application_dates).toEqual(['2021-06-01']);
    expect(byId('2016-0325').status.since).toBe('2017-08-07'); // Decision (EU) 2017/1324, Art. 15: twentieth day after 18.7.2017
  });

  it('cites a checked date’s text as its source, never EUR-Lex’s record that lacks it (DSA, Return Regulation)', () => {
    const dated = new Set(['entry_into_force', 'application', 'transposition_deadline', 'transposition_application']);
    let n = 0;
    for (const d of all)
      for (const e of d.timeline)
        if (dated.has(e.kind) && e.source?.label?.includes('(checked ')) {
          n++;
          expect(e.source.url, `${d.id} ${e.id}`).toBe(e.docs?.[0]?.url);
          expect(e.source.label, `${d.id} ${e.id}`).not.toContain('Cellar');
        }
    expect(n).toBeGreaterThan(20);
    const dsa = byId('2020-0361').timeline.find((e) => e.kind === 'application' && e.date === '2024-02-17')!;
    expect(dsa.source?.label).toBe('Regulation (EU) 2022/2065, Article 93 (checked 23 October 2026)');
  });

  it('gives a checked date’s text its own identifier, not the CELEX of the act it dates (AI Act, EUDR, AMMR)', () => {
    // the AI Act's 27 July 2026 read "Regulation (EU) 2026/1744, Article 1, point (40) ↗ 32024R1689", the AI Act's CELEX
    const doc = (id: string, date: string) => byId(id).timeline.find((e) => e.kind === 'application' && e.date === date)!.docs[0];
    expect([doc('2021-0106', '2026-07-27').id, doc('2021-0106', '2026-07-27').date]).toEqual(['32026R1744', null]);
    expect(doc('2021-0366', '2027-12-30').id).toBe('32026R2102');
    const ammr = doc('2020-0279', '2026-06-12');
    expect(ammr.label).toMatch(/^Corrigendum to Regulation \(EU\) 2024\/1351/);
    expect(ammr.id).toBe(ammr.label); // the entry gives no CELEX for the corrigendum: none is shown
    for (const d of all)
      for (const e of d.timeline)
        if (e.source?.label?.includes('(checked '))
          for (const x of e.docs) {
            const m = /^3(\d{4})[A-Z](\d{4})$/.exec(x.id);
            if (m) expect([`${m[1]}/${Number(m[2])}`, `${Number(m[2])}/${m[1]}`].some((num) => x.label?.includes(num)), `${d.id} ${e.id}`).toBe(true);
          }
  });

  it('names an act by its number in its steps, never by a type word and its CELEX id', () => {
    for (const d of all) for (const e of d.timeline) expect(e.detail ?? '', `${d.id} ${e.id}`).not.toMatch(/^(?:Regulation|Directive|Decision|Act) 3\d{4}[A-Z]\d{4}/);
    expect(byId('2016-0002').timeline.find((e) => e.kind === 'entry_into_force')?.detail).toBe('Directive (EU) 2019/884');
  });

  it('calls the first date from which any of an act applies "Rules", not "Further provisions" (PPWR)', () => {
    // Regulation (EU) 2025/40, Art. 71: "It shall apply from 12 August 2026. However, Article 67(5) shall apply from 12 February 2029."
    expect(byId('2022-0396').timeline.find((e) => e.kind === 'application' && e.date === '2026-08-12')?.title).toBe(
      'Rules started to apply (date recorded by EUR-Lex)',
    );
    // Regulation (EU) 2026/1388, Art. 38: "It shall apply from 17 July 2028. However, Articles 29, 30 and 31 shall apply
    // from 16 July 2026": the date it applies from in general, after some provisions, is when its rules start to apply
    expect(byId('2023-0226').timeline.find((e) => e.kind === 'application' && e.date === '2028-07-17')?.title).toBe(
      'Rules start to apply (date recorded by EUR-Lex)',
    );
    // Asylum Procedure Regulation, Regulation (EU) 2024/1348, Art. 79(2): "This Regulation shall apply from 12 June 2026"
    // (after 27 February 2026 for some provisions); the headline read "Further provisions started to apply"
    expect(byId('2016-0224A').timeline.find((e) => e.kind === 'application' && e.date === '2026-06-12')?.title).toBe(
      'Rules started to apply (date recorded by EUR-Lex)',
    );
    // "Further" only after a first date from which the act applies in general (EUR-Lex: 28 November 2023, 1 January 2024)
    const further = all.flatMap((d) => d.timeline.filter((e) => e.kind === 'application' && e.title.startsWith('Further')).map((e) => `${d.id} ${e.date}`));
    expect(further).toEqual(['2023-0252 2024-01-01']);
  });

  it('marks an application date earlier than the act itself as retroactive (Regulation (EU) 2021/23, Art. 97)', () => {
    // "Article 95 which shall apply from 4 July 2020", in the act "of 16 December 2020"
    const step = byId('2016-0365').timeline.find((e) => e.kind === 'application' && e.date === '2020-07-04')!;
    expect(step.title).toBe('Some provisions started to apply retroactively (date recorded by EUR-Lex)');
    expect(step.detail).toContain('earlier than the act itself, dated 16 December 2020');
    for (const d of all)
      for (const e of d.timeline) {
        const act = d.acts.find((a) => e.docs.some((x) => x.id === a.celex));
        if ((e.kind === 'application' || e.kind === 'transposition_application') && act?.date_document && e.date < act.date_document)
          expect(`${e.title} ${e.detail ?? ''}`, `${d.id} ${e.id}`).toMatch(/retroactiv/);
      }
  });

  it('never says a regulation applies in all EU countries, and names enhanced cooperation where its title does', () => {
    // Return Regulation (EU) 2026/2280, recital 67: Denmark "is not bound by it or subject to its application";
    // Art. 20(4) TEU: acts adopted in the framework of enhanced cooperation "shall bind only participating Member States"
    for (const d of all) expect(d.next_step.text, d.id).not.toMatch(/applies directly in (?:all EU countries|every Member State)/);
    expect(byId('2025-0059').next_step.text).toMatch(/^The regulation applies directly; no national transposition is needed\./);
    for (const id of ['2013-0255', '2016-0059', '2016-0060', '2026-0008'])
      expect(byId(id).next_step.text, id).toContain('only in the Member States taking part in the enhanced cooperation it implements (Article 20(4) TEU)');
  });

  it('gives the official title of the adopted act where the procedure’s title leaves out an act it amends (2025-0359)', () => {
    // Regulation (EU) 2026/1744: "amending Regulations (EU) 2024/1689, (EU) 2018/1139 and (EU) 2023/1230"
    expect(byId('2025-0359').official_title).toContain('(EU) 2023/1230');
    expect(byId('2022-0341').official_title).toContain('Directives 98/26/EC and (EU) 2015/2366');
    expect(byId('2012-0288').official_title).toMatch(/^Amendment to the fuel quality directive/);
  });

  it('says under the latest step that an amending act outside our data is not dated, and names it as its text does (EUDR)', () => {
    // Commission Delegated Regulation (EU) 2026/2102 of 13 July 2026 amending Regulation (EU) 2023/1115 (Cellar); its
    // Annex dates a step of the page, so the note no longer says that the act is not in our data
    const eudr = byId('2021-0366');
    expect(eudr.latest_note).toBe(
      'EUR-Lex also lists Commission Delegated Regulation (EU) 2026/2102 as amending this act. Its text was checked for the dates it sets for this act, but its publication is not in our data, so it is not shown and the step above may not be the latest.',
    );
    expect(eudr.related.filter((r) => r.relation === 'Amended by').map((r) => r.title)).toContain('Commission Delegated Regulation (EU) 2026/2102');
  });

  it('names as debated together only files whose own record shows that debate (CAP, 20 October 2020; customs, 8 June 2021)', () => {
    // EP item MTG-PL-2020-10-20-PVCRE-ITM-5 names the three CAP files only; it also cites the VAT Northern Ireland
    // report A9-0200/2020, tabled on 29 October 2020
    for (const id of ['2018-0216', '2018-0217', '2018-0218']) {
      const step = byId(id).timeline.find((e) => e.id === 'MTG-PL-2020-10-20-PVCRE-ITM-5')!;
      expect(step.joint_with?.map((j) => j.ref).sort(), id).toEqual(
        ['2018/0216(COD)', '2018/0217(COD)', '2018/0218(COD)'].filter((r) => r !== byId(id).ref),
      );
    }
    // MTG-PL-2021-06-08-PVCRE-ITM-20, "European Social Fund Plus (ESF+) 2021-2027 ***II (continuation of debate)"
    expect(byId('2018-0258').timeline.filter((e) => e.kind === 'plenary_debate' && e.date === '2021-06-08')).toEqual([]);
    for (const d of all) for (const e of d.timeline) for (const j of e.joint_with ?? []) expect(j.id, `${d.id} ${e.id}`).not.toBeNull();
  });

  it('titles a file after its adopted act where the procedure’s title is a placeholder or names other acts', () => {
    const placeholder = /\[(?:X+|…|\.\.\.)\]|\bX{3,}\b|\.\.\.\/\.\.\./;
    for (const d of all) if (d.acts.length) expect(`${d.title} ${d.official_title ?? ''}`, d.id).not.toMatch(placeholder);
    expect(byId('2023-0393').title).toBe('Extending Directive (EU) 2024/2841 to third-country nationals legally residing in a Member State');
    expect(byId('2021-0395').official_title).not.toContain('2002/465');
    const dk = read<{ transposition: { celex: string; title: string; status: string; status_note?: string | null }[] }>('countries/DK.json');
    const row = (c: string) => dk.transposition.find((t) => t.celex === c)!;
    expect(row('32024L2842').title).not.toMatch(placeholder);
    expect(row('32023L2843').title).toContain('2011/99/EU');
    // Directive (EU) 2023/977 builds upon the Schengen acquis: Denmark decided to implement it (ST 15298/23)
    expect(row('32023L0977').status_note).toContain('Denmark decided to implement it in its national law under Article 4 of Protocol No 22');
  });

  it('links the AI Act to Directive 2014/90/EU, which its Art. 105 amends, not to Implementing Regulation No 90/2014', () => {
    const ai = byId('2021-0106');
    expect(ai.acts[0].amends).toContain('32014L0090');
    expect(ai.acts[0].amends).not.toContain('32014R0090');
    expect(byId('2012-0358').related.filter((r) => r.relation === 'Amended by').map((r) => r.id)).toContain('2021-0106');
  });

  it('cites a split proposal’s parts on its page, not the EUR-Lex record of one part’s act', () => {
    const parents = all.filter((d) => d.related.some((r) => r.relation === 'Split into'));
    for (const d of parents) {
      expect(d.sources.filter((s) => s.institution === 'EUR-Lex'), d.id).toEqual([]);
      for (const s of d.sources) expect(s.label ?? '', d.id).not.toMatch(/\d{4}\/\d{4}[A-Z]\(COD\)$/);
    }
    expect(byId('2016-0400').sources.map((s) => s.label)).toEqual([
      'Legislative Observatory (OEIL) – procedure file 2016/0400A(COD) (separate file)',
      'Legislative Observatory (OEIL) – procedure file 2016/0400B(COD) (separate file)',
    ]);
  });
});
