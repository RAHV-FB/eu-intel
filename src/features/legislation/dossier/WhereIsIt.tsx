import type { DossierDetail, EventKind, ISODate, LifecycleStage, TimelineEvent } from '../../../types/data';
import { ExtLink, Term, institutionLabel } from '../../../components/ui';
import { asOfToday, formatDate, noUpdateText } from '../../../lib/format';
import { institutionSuffix } from '../labels';

interface Step {
  key: string;
  label: React.ReactNode;
  stages: LifecycleStage[];
  kinds: EventKind[];
}

/** Simplified path of the ordinary legislative procedure, keyed to lifecycle stages (not to event order). */
const OLP_STEPS: Step[] = [
  { key: 'proposed', label: 'Commission proposal', stages: ['proposed'], kinds: ['proposal'] },
  {
    key: 'deciding',
    label: (
      <>
        Parliament and Council positions &amp; <Term id="trilogue">negotiations</Term>
      </>
    ),
    stages: ['parliament_position', 'negotiations'],
    kinds: [],
  },
  {
    key: 'agreement',
    label: <Term id="provisional-agreement">Provisional agreement</Term>,
    stages: ['provisional_agreement'],
    kinds: ['provisional_agreement'],
  },
  { key: 'adopted', label: 'Formal adoption & publication', stages: ['adopted', 'published'], kinds: ['signature', 'council_adoption', 'publication'] },
  { key: 'in_force', label: <Term id="entry-into-force">In force</Term>, stages: ['in_force'], kinds: ['entry_into_force'] },
];

function firstOf(timeline: TimelineEvent[], kinds: EventKind[]): TimelineEvent | undefined {
  return timeline.find((e) => e.state === 'done' && kinds.includes(e.kind));
}

function lastKeyDone(timeline: TimelineEvent[], today: ISODate): TimelineEvent | null {
  for (let i = timeline.length - 1; i >= 0; i--) {
    const e = timeline[i];
    if (e.state === 'done' && e.key && e.date <= today) return e;
  }
  return null;
}

/** "Where is it?" — for files still being decided. */
export function WhereIsIt({ d, today }: { d: DossierDetail; today: ISODate }) {
  const currentIdx = OLP_STEPS.findIndex((s) => s.stages.includes(d.stage));
  const showPath = d.type === 'COD' && currentIdx >= 0;
  const milestone = lastKeyDone(d.timeline, today);
  const stall = d.stall;

  return (
    <section className="dz-section" id="where" aria-labelledby="where-title">
      <h2 id="where-title">Where is it now?</h2>

      {showPath && (
        <>
          <ol className="dz-path" aria-label="Typical path of the ordinary legislative procedure">
            {OLP_STEPS.map((s, i) => {
              const ev = s.key === 'proposed' ? undefined : firstOf(d.timeline, s.kinds);
              const date = s.key === 'proposed' ? d.started : ev?.date;
              const state = i < currentIdx ? 'done' : i === currentIdx ? 'current' : 'todo';
              return (
                <li key={s.key} className={`dz-path__step is-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
                  <span className="dz-path__mark" aria-hidden="true" />
                  <span className="dz-path__label">{s.label}</span>
                  <span className="dz-path__meta">
                    {state === 'current' ? 'Current stage' : state === 'done' ? (date ? formatDate(date) : 'Done') : 'Not yet'}
                  </span>
                </li>
              );
            })}
          </ol>
          <p className="meta dz-path__note">
            Simplified path of the <Term id="olp">ordinary legislative procedure</Term>. Not every law follows every step:
            many are agreed before Parliament’s first vote, and some never reach agreement.
          </p>
        </>
      )}

      <dl className="dz-where">
        <div>
          <dt>Latest milestone</dt>
          <dd>
            {milestone ? (
              <>
                <time dateTime={milestone.date}>{formatDate(milestone.date, true)}</time> — {milestone.title}
                {institutionSuffix(milestone.title, milestone.institution) && (
                  <span className="meta"> ({institutionSuffix(milestone.title, milestone.institution)})</span>
                )}
              </>
            ) : (
              <span className="meta">No milestone recorded yet.</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Next institutional step</dt>
          <dd>
            {asOfToday(d.next_step.text, today)}
            {d.next_step.institution && <span className="meta"> ({institutionLabel(d.next_step.institution)})</span>}
            {d.next_step.basis !== 'source' && (
              <span className="meta"> — {d.next_step.basis === 'derived' ? 'derived from the stage reached' : 'not determinable from the records'}</span>
            )}
          </dd>
        </div>
        {stall && (
          <div>
            <dt>Recorded activity</dt>
            <dd>
              {stall.days_since_last_event > 0 || (stall.last_event_date && stall.last_event_date < today) ? (
                <>{noUpdateText(stall.days_since_last_event, stall.last_event_date, today)}.</>
              ) : (
                <>A procedural update was recorded today.</>
              )}{' '}
              <span className="meta">
                This measures only the official procedure file; work can continue between recorded steps.
              </span>
            </dd>
          </div>
        )}
      </dl>

      {stall?.official_label && (
        <div className={`dz-official-status${d.officially_blocked ? ' is-blocked' : ''}`}>
          <p className="dz-official-status__label">
            {d.officially_blocked ? 'Officially reported as blocked' : 'Official monitoring status'}
          </p>
          <p>
            The European Parliament’s Legislative Train Schedule lists this file as: <q>{stall.official_label}</q>
            {stall.official_label_date && <> (information updated as of {formatDate(stall.official_label_date, true)})</>}.
          </p>
          {stall.official_source_url && (
            <p className="meta">
              <ExtLink href={stall.official_source_url}>Legislative Train Schedule entry</ExtLink>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
