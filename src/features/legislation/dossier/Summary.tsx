import type { ApplicationInfo, DossierDetail, ISODate, TimelineEvent } from '../../../types/data';
import { BasisNote, ExtLink, SourceLink, StatusBadge, Term, institutionLabel } from '../../../components/ui';
import { formatDate } from '../../../lib/format';
import { ADOPTED_STAGES } from '../labels';

/** Most recent recorded (done) event on or before today. */
export function latestDone(timeline: TimelineEvent[], today: ISODate): TimelineEvent | null {
  for (let i = timeline.length - 1; i >= 0; i--) {
    const e = timeline[i];
    if (e.state === 'done' && e.date <= today) return e;
  }
  return null;
}

function DateWhen({ date, today }: { date: ISODate; today: ISODate }) {
  const future = date > today;
  return (
    <>
      <time dateTime={date}>{formatDate(date)}</time>
      {future && <span className="dz-upcoming">upcoming</span>}
    </>
  );
}

export function KeyDates({ app, today, instrument }: { app: ApplicationInfo; today: ISODate; instrument?: string | null }) {
  const rows: { label: React.ReactNode; dates: ISODate[] }[] = [];
  if (app.entry_into_force)
    rows.push({
      label: (
        <>
          <Term id="entry-into-force">{app.entry_into_force > today ? 'Enters into force' : 'Entered into force'}</Term>
        </>
      ),
      dates: [app.entry_into_force],
    });
  if (app.application_dates.length)
    rows.push({ label: app.application_dates.length > 1 ? 'Rules apply (in phases) from' : 'Rules apply from', dates: app.application_dates });
  if (app.transposition_deadlines.length)
    rows.push({
      label: (
        <>
          National <Term id="transposition">transposition</Term> deadline{app.transposition_deadlines.length > 1 ? 's' : ''}
        </>
      ),
      dates: app.transposition_deadlines,
    });
  if (!rows.length) return <p className="meta">No application dates are recorded for this act in EUR-Lex.</p>;
  return (
    <dl className="dz-dates">
      {rows.map((r, i) => (
        <div key={i}>
          <dt>{r.label}</dt>
          <dd>
            <ul>
              {[...new Set(r.dates)].sort().map((d) => (
                <li key={d}>
                  <DateWhen date={d} today={today} />
                </li>
              ))}
            </ul>
          </dd>
        </div>
      ))}
      {instrument === 'regulation' && (
        <p className="dz-dates__note meta">
          A <Term id="regulation">regulation</Term> applies directly in every Member State.
        </p>
      )}
    </dl>
  );
}

/** "In 15–30 seconds": what it is, why it matters, where it stands, what's next. */
export function DossierSummaryPanel({ d, today }: { d: DossierDetail; today: ISODate }) {
  const ed = d.editorial;
  const latest = latestDone(d.timeline, today);
  const adopted = ADOPTED_STAGES.has(d.stage);

  return (
    <section className="dz-summary" aria-labelledby="summary-title">
      <h2 id="summary-title" className="visually-hidden">
        Summary
      </h2>

      <div className="dz-what">
        <div className="dz-block">
          <h3 className="dz-label">What is it?</h3>
          {ed?.what ? (
            <p className="dz-what__text">{ed.what}</p>
          ) : (
            <>
              <p className="dz-nocurated">We have not written a plain-language summary for this file yet. Its official title is:</p>
              <p className="dz-what__official">{d.official_title}</p>
            </>
          )}
        </div>
        {ed?.why && (
          <div className="dz-block">
            <h3 className="dz-label">Why it matters</h3>
            <p>{ed.why}</p>
          </div>
        )}
        {ed && (
          <p className="dz-editorial meta">
            <span className="dz-editorial__tag">Editorial summary</span> written by this project, reviewed{' '}
            {formatDate(ed.reviewed)}
            {ed.sources.length > 0 && (
              <>
                {' '}
                · based on{' '}
                {ed.sources.map((s, i) => (
                  <span key={s.url}>
                    {i > 0 && ', '}
                    <ExtLink href={s.url}>{s.label}</ExtLink>
                  </span>
                ))}
              </>
            )}
            . Everything else on this page comes from official records.
          </p>
        )}
      </div>

      <dl className="dz-facts">
        <div className="dz-fact">
          <dt className="dz-label">Current status</dt>
          <dd>
            <StatusBadge stage={d.status.stage} label={d.status.label} blocked={d.officially_blocked} />
            <p className="dz-fact__text">
              {d.status.explanation} <BasisNote basis={d.status.basis} />
            </p>
            {d.status.since && <p className="meta">Since {formatDate(d.status.since)}</p>}
          </dd>
        </div>
        <div className="dz-fact">
          <dt className="dz-label">Latest verified development</dt>
          <dd>
            {latest ? (
              <>
                <p className="dz-fact__date">
                  <time dateTime={latest.date}>{formatDate(latest.date, true)}</time>
                </p>
                <p className="dz-fact__text">
                  {latest.title} <span className="meta">({institutionLabel(latest.institution)})</span>
                </p>
                <SourceLink source={latest.source} />
              </>
            ) : (
              <p className="dz-fact__text meta">No dated procedural step is recorded.</p>
            )}
          </dd>
        </div>
        <div className="dz-fact">
          <dt className="dz-label">What happens next</dt>
          <dd>
            <p className="dz-fact__text">
              {d.next_step.text} <BasisNote basis={d.next_step.basis} />
            </p>
            {d.next_step.institution && <p className="meta">{institutionLabel(d.next_step.institution)}</p>}
          </dd>
        </div>
      </dl>

      {adopted && d.application && (
        <div className="dz-block dz-when">
          <h3 className="dz-label">When it applies</h3>
          <KeyDates app={d.application} today={today} instrument={d.instrument} />
        </div>
      )}
    </section>
  );
}
