import type { ApplicationInfo, DossierDetail, ISODate, NamedAct, TimelineEvent, TranspositionDateInfo } from '../../../types/data';
import { Link } from 'react-router-dom';
import { BasisNote, ExtLink, SourceLink, StatusBadge, Term, institutionLabel } from '../../../components/ui';
import { asOfToday, eventOn, formatDate } from '../../../lib/format';
import { ADOPTED_STAGES, dossierPath, institutionSuffix } from '../labels';
import { SplitLinks, splitParts } from './Split';

/**
 * Most recent recorded (done) event on or before today; not a date an act records for after its validity ended.
 * A step the build had scheduled counts once its date has passed, with the title the build gives it then.
 * Of several steps on that day, the key one (the milestone "Where is it now?" names), else the last listed: the
 * sources give no order within a day, so a document tabled that day is not shown as following the decision.
 */
export function latestDone(timeline: TimelineEvent[], today: ISODate): TimelineEvent | null {
  let latest: TimelineEvent | null = null;
  for (let i = timeline.length - 1; i >= 0; i--) {
    const e = eventOn(timeline[i], today);
    if (e.state !== 'done' || e.date > today || e.after_end_of_validity) continue;
    if (latest && e.date !== latest.date) break;
    if (!latest) latest = e;
    if (e.key) return e;
  }
  return latest;
}

/** A status explanation with the acts it names (e.g. the repealing act) linked: to their file here, else EUR-Lex. */
export function ExplanationText({ text, acts }: { text: string; acts?: NamedAct[] | null }) {
  const named = [...(acts ?? [])].filter((a) => a.label).sort((a, b) => b.label.length - a.label.length);
  if (!named.length) return <>{text}</>;
  const escape = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${named.map((a) => escape(a.label)).join('|')})`));
  const linked = new Set<string>();
  return (
    <>
      {parts.map((part, i) => {
        const a = named.find((x) => x.label === part);
        if (!a || linked.has(a.label)) return part;
        linked.add(a.label);
        return a.dossier ? (
          <Link key={i} to={dossierPath(a.dossier)}>
            {part}
          </Link>
        ) : (
          <ExtLink key={i} href={a.url}>
            {part}
          </ExtLink>
        );
      })}
    </>
  );
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

/** A directive's transposition dates by kind; data without the classification counts as deadlines. */
export function transpositionDates(app: ApplicationInfo | null | undefined): TranspositionDateInfo[] {
  if (!app) return [];
  return app.transposition ?? app.transposition_deadlines.map((date, i) => ({ date, kind: i ? 'further_deadline' : 'deadline', articles: [] }));
}

type DateItem = { date: ISODate; note?: string };

/** " (it refers to Art. 99)": the articles EUR-Lex refers to for an application date it gives as not recorded. */
function refersTo(articles: string[]): string {
  return articles.length ? ` (it refers to ${articles.join(', ')})` : '';
}

export function KeyDates({ app, today, instrument }: { app: ApplicationInfo; today: ISODate; instrument?: string | null }) {
  const rows: { label: React.ReactNode; items: DateItem[]; text?: string }[] = [];
  const plain = (ds: ISODate[]) => [...new Set(ds)].sort().map((date) => ({ date }));
  // an application date's exceptions in the directive's text follow its article (CSDDD, Art. 37(1): Article 16 later)
  const withArticles = (xs: TranspositionDateInfo[]) =>
    xs.map((x) => ({ date: x.date, note: [x.articles.join(', '), x.exceptions].filter(Boolean).join('. ') || undefined }));
  if (app.entry_into_force)
    rows.push({
      label: (
        <>
          <Term id="entry-into-force">{app.entry_into_force > today ? 'Enters into force' : 'Entered into force'}</Term>
        </>
      ),
      items: plain([app.entry_into_force]),
    });
  else if (app.entry_into_force_pending)
    rows.push({
      label: <Term id="entry-into-force">Entry into force</Term>,
      items: [],
      text: `Not yet: EUR-Lex records no date. ${app.entry_into_force_condition ?? 'The act enters into force once a condition it sets is met.'}`,
    });
  else if (app.effect_on_notification)
    rows.push({
      label: 'Takes effect',
      items: [],
      text: 'On notification to those to whom the decision is addressed, according to EUR-Lex, which does not record the date of notification.',
    });
  // EUR-Lex gives the date from which the act in general, or some provisions, apply as not recorded (ETIAS, Regulation
  // (EU) 2018/1240, Art. 96: "from the date determined by the Commission"): never shown as applying from entry into force
  const unrecorded = (partial: boolean) => app.application_unrecorded?.find((x) => x.partial === partial);
  const noGeneral = unrecorded(false);
  const noPartial = unrecorded(true);
  if (app.application_detail?.length) {
    const general = app.application_detail.filter((x) => !x.partial);
    const partial = app.application_detail.filter((x) => x.partial);
    const items = (xs: typeof general) => xs.map((x) => ({ date: x.date, note: x.provisions ?? undefined }));
    if (general.length) rows.push({ label: 'Rules apply from', items: items(general) });
    if (partial.length) rows.push({ label: 'Some provisions apply from', items: items(partial) });
  } else if (app.application_dates.length || app.partial_on_entry_into_force || noGeneral || noPartial) {
    const partialSet = new Set(app.partial_application_dates ?? []);
    const general = app.application_dates.filter((d) => !partialSet.has(d));
    const partial = app.application_dates.filter((d) => partialSet.has(d));
    // EUR-Lex marks the entry-into-force date too: some provisions apply from it
    const onEif = app.partial_on_entry_into_force && app.entry_into_force ? [{ date: app.entry_into_force, note: 'On entry into force' }] : [];
    if (general.length) rows.push({ label: general.length > 1 ? 'Rules apply (in phases) from' : 'Rules apply from', items: plain(general) });
    else if (noGeneral) rows.push({ label: 'Rules apply from', items: [], text: `Not recorded: EUR-Lex gives no date${refersTo(noGeneral.articles)}.` });
    if (partial.length || onEif.length || noPartial)
      rows.push({
        label: 'Some provisions apply from',
        items: [...onEif, ...plain(partial)],
        text: noPartial ? `EUR-Lex gives no date for some provisions${refersTo(noPartial.articles)}.` : undefined,
      });
    // EUR-Lex records the entry into force for some provisions and no date for the others
    if (onEif.length && !app.application_dates.length && !noGeneral)
      rows.push({ label: 'Other provisions apply from', items: [], text: 'Not recorded: EUR-Lex gives no date.' });
  }
  const tr = transpositionDates(app);
  const general = tr.filter((x) => x.kind === 'deadline');
  const further = tr.filter((x) => x.kind === 'further_deadline');
  const applies = tr.filter((x) => x.kind === 'application');
  const other = tr.filter((x) => x.kind === 'other');
  if (general.length)
    rows.push({
      label: (
        <>
          National <Term id="transposition">transposition</Term> deadline
        </>
      ),
      items: withArticles(general),
    });
  if (further.length)
    rows.push({ label: `Transposition deadline${further.length > 1 ? 's' : ''} for specific provisions`, items: withArticles(further) });
  if (applies.length)
    rows.push({ label: `Application date${applies.length > 1 ? 's' : ''} for national measures`, items: withArticles(applies) });
  if (other.length) rows.push({ label: `Other date${other.length > 1 ? 's' : ''} recorded by EUR-Lex`, items: withArticles(other) });
  if (!rows.length) return <p className="meta">No application dates are recorded for this act in EUR-Lex.</p>;
  const ended = new Set(app.after_end_of_validity ?? []);
  return (
    <>
    <dl className="dz-dates">
      {rows.map((r, i) => (
        <div key={i}>
          <dt>{r.label}</dt>
          <dd>
            {r.text && <p>{r.text}</p>}
            {r.items.length > 0 && (
              <ul>
                {r.items.map((it) => (
                  <li key={it.date}>
                    <DateWhen date={it.date} today={today} />
                    {it.note && <span className="meta dz-dates__prov">{it.note}</span>}
                    {ended.has(it.date) && (
                      <span className="meta dz-dates__prov">A date after the act’s validity ended</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      ))}
    </dl>
    {app.dates_note && (
      <p className="dz-dates__note meta">
        <strong>Dates checked against the act’s text.</strong> {app.dates_note.reason}{' '}
        {app.dates_note.sources.map((s, i) => (
          <span key={s.url}>
            {i > 0 && ' · '}
            <ExtLink href={s.url}>{s.label}</ExtLink>
          </span>
        ))}
        {app.dates_note.reviewed && <> (checked {formatDate(app.dates_note.reviewed)})</>}
      </p>
    )}
    {(further.length > 0 || applies.length > 0 || other.length > 0) && (
      <p className="dz-dates__note meta">
        Transposition dates as recorded by EUR-Lex, with the article that sets each one. The directive’s text says which
        provisions each date covers{other.length > 0 && ' and what the other dates are'}.
      </p>
    )}
    {instrument === 'regulation' && (
      <p className="dz-dates__note meta">
        A <Term id="regulation">regulation</Term> applies directly, without national transposition, in the Member States it
        binds.
      </p>
    )}
    </>
  );
}

/** First legally fixed date still ahead (application, transposition deadline…; a deadline on its day). */
export function nextScheduled(timeline: TimelineEvent[], today: ISODate): TimelineEvent | null {
  return timeline.map((e) => eventOn(e, today)).find((e) => e.state === 'scheduled' && e.date >= today) ?? null;
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
      <p className="dz-fact__text meta">
        {ns.text.startsWith('Not determined:') ? ns.text : 'No next step is recorded in the official sources.'}
      </p>
    );
  }
  return (
    <>
      <p className="dz-fact__text">
        <ExplanationText text={asOfToday(ns.text, today)} acts={d.status.named_acts} /> <BasisNote basis={ns.basis} />
      </p>
      {ns.institution && <p className="meta">{institutionLabel(ns.institution)}</p>}
    </>
  );
}

/** "In 15–30 seconds": what it is, why it matters, where it stands, what's next. */
export function DossierSummaryPanel({ d, today }: { d: DossierDetail; today: ISODate }) {
  const ed = d.editorial;
  const latest = latestDone(d.timeline, today);
  // a status recorded when the data was built can state a date that has passed since (the label stays as recorded)
  const explanation = asOfToday(d.status.explanation, today);
  const adopted = ADOPTED_STAGES.has(d.stage);
  const amendedBy = d.related.filter((r) => r.relation === 'Amended by');
  const amendedLinks = amendedBy.slice(0, 3).map((r, i) => (
    <span key={r.id}>
      {i > 0 && ', '}
      {/^\d{4}-\d{4}/.test(r.id) ? <Link to={dossierPath(r.id)}>{r.title}</Link> : r.title}
    </span>
  ));

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
          ) : d.official_title ? (
            <>
              <p className="dz-nocurated">We have not written a plain-language summary for this file yet. Its official title is:</p>
              <p className="dz-what__official">{d.official_title}</p>
            </>
          ) : (
            <>
              <p className="dz-nocurated">We have not written a plain-language summary for this file yet.</p>
              {splitParts(d).length > 0 && (
                <p className="dz-what__text">
                  This is the file the proposal {d.ref} was split from. It was split into separate procedures, each with its own page:{' '}
                  <SplitLinks parts={splitParts(d)} />.
                </p>
              )}
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
              <ExplanationText text={explanation} acts={d.status.named_acts} /> <BasisNote basis={d.status.basis} />
            </p>
            {explanation !== d.status.explanation && (
              <p className="meta">Status as recorded at the last data refresh, before the date above had passed.</p>
            )}
            {d.status.since && <p className="meta">Since {formatDate(d.status.since)}</p>}
            {splitParts(d).length > 0 && (
              <p className="meta">
                Separate files: <SplitLinks parts={splitParts(d)} />.
              </p>
            )}
            {adopted && amendedBy.length > 0 && (
              <p className="meta">
                Amended since by {amendedLinks}
                {amendedBy.length > 3 && <> and {amendedBy.length - 3} more</>}.
              </p>
            )}
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
                  {institutionSuffix(latest.title, latest.institution, latest.kind) && (
                    <span className="meta"> ({institutionSuffix(latest.title, latest.institution, latest.kind)})</span>
                  )}
                </p>
                <SourceLink source={latest.source} />
                {d.latest_note && <p className="meta">{d.latest_note}</p>}
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
          {amendedBy.length > 0 && !d.application.dates_note && (
            <p className="meta dz-amended-note">
              This act has since been amended (see {amendedLinks}). The dates above are those EUR-Lex currently records
              for it; they may not yet reflect every change made by the amending acts.
            </p>
          )}
          {d.dates_set_for?.map((x) => (
            <p key={x.id} className="meta dz-amended-note">
              This act set dates from which (parts of) <Link to={dossierPath(x.id)}>{x.title}</Link> apply:{' '}
              {x.dates.map((date, i) => (
                <span key={date}>
                  {i > 0 && (i === x.dates.length - 1 ? ' and ' : ', ')}
                  <time dateTime={date}>{formatDate(date, true)}</time>
                </span>
              ))}
              . See “When it applies” on that page.
            </p>
          ))}
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
