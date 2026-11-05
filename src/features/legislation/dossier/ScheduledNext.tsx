import type { DocRef, ISODate, ISODateTime, ScheduledStep } from '../../../types/data';
import { ExtLink, institutionLabel } from '../../../components/ui';
import { formatDate, plannedAhead } from '../../../lib/format';

/**
 * "Scheduled next": the steps the Council and Parliament have scheduled on a file, as they publish them
 * (pipeline/analysis/scheduled.py). The build gives only steps dated after its own date; the data is rebuilt weekly, so
 * a step is judged on the reader's date: ahead until its day is over, then said to have been scheduled. It is never
 * shown as done: only the procedure's records, in a later build, say what took place.
 */

/** A planned step's state on `today`. */
export function plannedState(step: Pick<ScheduledStep, 'date'>, today: ISODate): 'ahead' | 'passed' {
  return plannedAhead(step.date, today) ? 'ahead' : 'passed';
}

/** What the page says of a step whose date has passed since the data was built. */
export function passedNote(step: Pick<ScheduledStep, 'date'>): string {
  return `Was scheduled for ${formatDate(step.date, true)}; not yet recorded as done.`;
}

/** "Vote in EP plenary (second reading)" */
export function stepLabel(step: Pick<ScheduledStep, 'label' | 'phase'>): string {
  return step.phase ? `${step.label} (${step.phase.toLowerCase()})` : step.label;
}

/** A document the plan names: the meeting's agenda, Parliament's report, a Council document; linked only where the
 * build found a public copy. */
function DocName({ doc }: { doc: DocRef }) {
  const id = doc.label ?? doc.id;
  const text = doc.kind === 'agenda' ? `Agenda ${id}` : doc.kind === 'report' ? `Report ${id}` : id;
  return doc.url ? <ExtLink href={doc.url}>{text}</ExtLink> : <>{text}</>;
}

/** `retrieved`: when the schedules were last retrieved (meta.json, source "agenda"), if known. */
export function ScheduledNext({ steps, today, retrieved }: { steps: ScheduledStep[]; today: ISODate; retrieved?: ISODateTime | null }) {
  return (
    <>
      <ol className="dz-plan">
        {steps.map((s, i) => {
          const passed = plannedState(s, today) === 'passed';
          return (
            <li key={`${s.date}-${s.label}-${i}`} className={passed ? 'dz-plan__step is-passed' : 'dz-plan__step'}>
              <span className="dz-plan__date">
                <time dateTime={s.date}>{formatDate(s.date, true)}</time>
              </span>
              <span className="dz-plan__what">
                <span className="dz-plan__label">{stepLabel(s)}</span>
                {passed && <span className="dz-plan__passed">{passedNote(s)}</span>}
                <span className="meta dot-list">
                  <span>{s.meeting || institutionLabel(s.institution)}</span>
                  {s.documents.map((d) => (
                    <span key={d.id}>
                      <DocName doc={d} />
                    </span>
                  ))}
                </span>
                <span className="source">
                  {s.sources.length > 1 ? 'Sources: ' : 'Source: '}
                  {s.sources.map((src, j) => (
                    <span key={`${src.url}-${j}`}>
                      {j > 0 && ' · '}
                      <ExtLink href={src.url}>{src.label || institutionLabel(src.institution)}</ExtLink>
                    </span>
                  ))}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="meta">
        Planned dates as the Council and Parliament publish them{retrieved ? <>, retrieved {formatDate(retrieved)}</> : null}. They can
        change; a step is shown as taken only once the procedure’s records show it.
      </p>
    </>
  );
}
