import type { ApplicationInfo, DossierDetail, ISODate, TimelineEvent } from '../../../types/data';
import { Link } from 'react-router-dom';
import { BasisNote, ExtLink, SourceLink, StatusBadge, Term, institutionLabel } from '../../../components/ui';
import { formatDate } from '../../../lib/format';
import { ADOPTED_STAGES, dossierPath, institutionSuffix } from '../labels';

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
    <>
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
    </dl>
    {instrument === 'regulation' && (
      <p className="dz-dates__note meta">
        A <Term id="regulation">regulation</Term> applies directly in every Member State.
      </p>
    )}
    </>
  );
}

/** First legally fixed date still ahead (application, transposition deadline…). */
export function nextScheduled(timeline: TimelineEvent[], today: ISODate): TimelineEvent | null {
  return timeline.find((e) => e.date > today) ?? null;
}

/**
 * The next procedural step when the records establish one; otherwise the next date fixed in law, if any.
 * Never invents a step.
 */
export function NextStep({ d, today }: { d: DossierDetail; today: ISODate }) {
  const ns = d.next_step;
  const sched = nextScheduled(d.timeline, today);
  if (ns.basis === 'unknown') {
    return sched ? (
      <>
        <p className="dz-fact__date">
          <time dateTime={sched.date}>{formatDate(sched.date, true)}</time>
        </p>
        <p className="dz-fact__text">{sched.title}</p>
        <p className="meta">Date fixed in the law ({institutionLabel(sched.institution)})</p>
      </>
    ) : (
      <p className="dz-fact__text meta">No next step is recorded in the official sources.</p>
    );
  }
  return (
    <>
      <p className="dz-fact__text">
        {ns.text} <BasisNote basis={ns.basis} />
      </p>
      {ns.institution && <p className="meta">{institutionLabel(ns.institution)}</p>}
    </>
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
                  {latest.title}
                  {institutionSuffix(latest.title, latest.institution) && (
                    <span className="meta"> ({institutionSuffix(latest.title, latest.institution)})</span>
                  )}
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
            <NextStep d={d} today={today} />
          </dd>
        </div>
      </dl>

      {adopted && d.application && (
        <div className="dz-block dz-when">
          <h3 className="dz-label">When it applies</h3>
          <KeyDates app={d.application} today={today} instrument={d.instrument} />
          {d.related.some((r) => r.relation === 'Amended by') && (
            <p className="meta dz-amended-note">
              This act has since been amended (see{' '}
              {d.related
                .filter((r) => r.relation === 'Amended by')
                .slice(0, 3)
                .map((r, i) => (
                  <span key={r.id}>
                    {i > 0 && ', '}
                    {/^\d{4}-\d{4}/.test(r.id) ? <Link to={dossierPath(r.id)}>{r.title}</Link> : r.title}
                  </span>
                ))}
              ). The dates above are those EUR-Lex records for the act as first adopted; amendments may have
              changed some of them.
            </p>
          )}
        </div>
      )}

      <CourtRulings d={d} />
    </section>
  );
}

/** Court of Justice judgments that EUR-Lex records as annulling or invalidating (part of) the act. */
function CourtRulings({ d }: { d: DossierDetail }) {
  const rulings = d.acts.flatMap((a) => a.court_rulings ?? []);
  if (!rulings.length) return null;
  return (
    <div className="dz-block dz-rulings" role="note">
      <h3 className="dz-label">Court ruling on this law</h3>
      <ul>
        {rulings.map((r) => (
          <li key={r.celex}>
            <strong>
              {r.case_number ?? r.celex}
              {r.date && <>, {formatDate(r.date)}</>}
            </strong>{' '}
            <span className="meta">({r.kind_label})</span>
            <br />
            {r.summary} <ExtLink href={r.url}>Read the judgment</ExtLink>
          </li>
        ))}
      </ul>
    </div>
  );
}
