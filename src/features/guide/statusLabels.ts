/**
 * The status labels a legislative file can carry, grouped by whether its act has been adopted, published and is in
 * force (shown on /how-the-eu-works#status-labels). The labels and their stages are those of pipeline/analysis/status.py
 * and pipeline/build.py; guide.data.test.ts checks them against the built data: every label of an adopted, published,
 * in force, repealed or ended file, and every label that names no stage, must be listed here. Labels of steps before
 * adoption are listed only when they are common; the page says that the others name a step of the procedure.
 */
import type { LifecycleStage } from '../../types/data';

export interface StatusLabel {
  stage: LifecycleStage;
  label: string;
}

export interface StatusLabelRow {
  /** badge texts as the site shows them */
  labels: StatusLabel[];
  /** rarer labels with the same meaning, shown as plain text */
  also?: StatusLabel[];
  text: string;
}

export interface StatusLabelGroup {
  id: string;
  heading: string;
  rows: StatusLabelRow[];
}

const l = (stage: LifecycleStage, label: string): StatusLabel => ({ stage, label });

export const STATUS_LABEL_GROUPS: StatusLabelGroup[] = [
  {
    id: 'not-adopted',
    heading: 'Not adopted: not law yet',
    rows: [
      {
        labels: [l('proposed', 'Proposal under examination')],
        also: [l('proposed', 'Under examination in Parliament')],
        text: 'Parliament is examining the proposal and has not adopted its position. No institution has adopted the act.',
      },
      {
        labels: [l('negotiations', 'Mandate to negotiate with the Council'), l('negotiations', 'Negotiations with the Council')],
        text: 'Parliament has a mandate to negotiate the text with the Council; with “Negotiations”, talks (trilogues) are recorded. Any agreement must still be adopted by both.',
      },
      {
        labels: [l('provisional_agreement', 'Provisional agreement reached')],
        text: 'Negotiators have agreed a text and Parliament’s committee has approved it (also called a “political agreement”). Parliament as a whole and the Council must still adopt it.',
      },
      {
        labels: [l('parliament_position', 'Approved by Parliament')],
        also: [l('parliament_position', 'Parliament adopted its first-reading position')],
        text: 'Parliament has adopted its first-reading position. The act is not adopted until the Council has also agreed.',
      },
      {
        labels: [l('parliament_position', 'Parliament gave its opinion'), l('parliament_position', 'Parliament gave its consent')],
        text: 'Special procedures: the Council takes the final decision after Parliament’s opinion (consultation), which does not bind it, or with Parliament’s consent.',
      },
    ],
  },
  {
    id: 'adopted',
    heading: 'Adopted: not recorded as published',
    rows: [
      {
        labels: [l('adopted', 'Signed, awaiting publication'), l('adopted', 'Adopted by the Council')],
        also: [
          l('adopted', 'Adopted by Parliament and Council'),
          l('adopted', 'Adopted at second reading'),
          l('adopted', 'Adopted by Parliament'),
          l('adopted', 'Adopted, awaiting publication'),
          l('adopted', 'Adopted'),
        ],
        text: 'The act has been adopted (“Signed” adds that it has been signed). It is not recorded as published in the Official Journal yet. It enters into force on the date it sets, which can be the day of its adoption, or, if it sets none, on the twentieth day after publication; a non-legislative directive not addressed to all Member States, or decision addressed to specific recipients, takes effect when they are notified (Article 297 TFEU).',
      },
    ],
  },
  {
    id: 'published',
    heading: 'Published: not recorded as in force',
    rows: [
      {
        labels: [l('published', 'Published, not yet in force')],
        text: 'Published in the Official Journal, but EUR-Lex records the act as not yet in force. The page gives the date of entry into force, or the condition the act sets for it, where recorded.',
      },
      {
        labels: [l('published', 'Published in the Official Journal')],
        text: 'Published; our data does not record when the act enters into force.',
      },
      {
        labels: [l('takes_effect_on_notification', 'Takes effect on notification')],
        text: 'A decision addressed to specific recipients: EUR-Lex gives its date of effect as the date of notification to them, which it does not record, and does not mark the decision as in force.',
      },
    ],
  },
  {
    id: 'in-force',
    heading: 'In force',
    rows: [
      {
        labels: [l('in_force', 'In force')],
        text: 'The act has entered into force. Its rules may apply only from later dates, and a directive must be transposed by the Member States it is addressed to, by the deadline it sets. The file’s page lists the dates.',
      },
    ],
  },
  {
    id: 'no-longer',
    heading: 'No longer in force',
    rows: [
      {
        labels: [l('no_longer_in_force', 'No longer in force')],
        text: 'EUR-Lex records that the act’s validity has ended, for example because a later act repealed or replaced it. Its rules can continue in that act.',
      },
    ],
  },
  {
    id: 'ended',
    heading: 'Withdrawn, rejected or lapsed',
    rows: [
      {
        labels: [l('withdrawn', 'Withdrawn by the Commission'), l('withdrawn', 'Replaced by a new Commission proposal')],
        text: 'The Commission withdrew the proposal, or replaced it with a new one. This is a decision of the Commission, not a vote of Parliament.',
      },
      {
        labels: [l('rejected', 'Rejected by Parliament'), l('rejected', 'Consent refused by Parliament')],
        text: 'Parliament voted to reject the proposal, or refused its consent. A rejection at first reading is Parliament’s first-reading position: the procedure formally continues with the Council’s first-reading position (Article 294(5) TFEU) unless the Commission withdraws the proposal. A rejection of the Council’s position at second reading or of a conciliation text ends it (Article 294(7)(b) and (13) TFEU), and without Parliament’s consent the Council cannot adopt the act. The file’s page says which applies.',
      },
      {
        labels: [l('lapsed', 'Lapsed'), l('lapsed', 'Lapsed or withdrawn')],
        text: 'The procedure lapsed without the act being adopted. “Lapsed or withdrawn”: the Legislative Observatory records that it lapsed or was withdrawn, without saying which.',
      },
    ],
  },
  {
    id: 'other',
    heading: 'Other labels',
    rows: [
      {
        labels: [l('unknown', 'Split into separate procedures')],
        text: 'The file was split into separate procedures, each with its own status; its page links them.',
      },
      {
        labels: [l('unknown', 'Parliament report (not a legislative act)')],
        text: 'A report Parliament adopted on another procedure: a resolution, not a legislative act. Its page links that procedure.',
      },
      {
        labels: [l('unknown', 'Procedure completed')],
        text: 'The Legislative Observatory records the procedure as completed, but our data records no final act, so we cannot say what it produced.',
      },
      {
        labels: [l('unknown', 'Final act not linked in the official records')],
        text: 'A published act cites a step of this procedure, such as Parliament’s opinion, but no official record links the two. The file’s page names the act.',
      },
    ],
  },
];

const rows = STATUS_LABEL_GROUPS.flatMap((g) => g.rows);

/** Every label listed above, with its stage. */
export const LISTED_STATUS_LABELS: ReadonlyMap<string, LifecycleStage> = new Map(
  rows.flatMap((r) => [...r.labels, ...(r.also ?? [])]).map((x) => [x.label, x.stage] as const),
);
