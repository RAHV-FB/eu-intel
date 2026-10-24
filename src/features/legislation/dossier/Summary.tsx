import type { ApplicationInfo, DossierDetail, ISODate, NamedAct, TimelineEvent, TranspositionDateInfo } from '../../../types/data';
import { Link } from 'react-router-dom';
import { BasisNote, ExtLink, SourceLink, Term, institutionLabel } from '../../../components/ui';
import { asOfToday, eventOn, formatDate, safeUrl } from '../../../lib/format';
import { ADOPTED_STAGES, EURLEX_CELEX, dossierPath, institutionSuffix, isSameTitle } from '../labels';
import { SplitParts, splitParts } from './Split';

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

/**
 * One step of "When it applies": a date and what it is, or a statement that EUR-Lex records no date (`when` then
 * says so in the date column). `rank` orders steps of the same day: entry into force, then application, then
 * transposition dates.
 */
type ScheduleStep = { date?: ISODate; when?: string; what: React.ReactNode; note?: string; rank: number };

/**
 * The dates an act sets, in one chronological schedule: what EUR-Lex records (entry into force, the dates from which
 * the act or some provisions apply, a directive's transposition dates), each with the provisions it covers, and the
 * end of its validity (`noLonger`: the timeline's end_of_validity steps). Dates EUR-Lex gives as not recorded follow the
 * dated steps; an entry into force without a date comes first.
 */
export function KeyDates({
  app,
  today,
  instrument,
  stage,
  noLonger = [],
}: {
  app: ApplicationInfo;
  today: ISODate;
  instrument?: string | null;
  stage?: string;
  noLonger?: TimelineEvent[];
}) {
  const steps: ScheduleStep[] = [];
  // the glossary term is offered once, on its first step
  const termed = new Set<string>();
  const term = (id: string, text: string) => {
    if (termed.has(id)) return text;
    termed.add(id);
    return <Term id={id}>{text}</Term>;
  };
  const dated = (rank: number, what: (ahead: boolean) => React.ReactNode, items: DateItem[]) => {
    for (const it of items) steps.push({ date: it.date, note: it.note, rank, what: what(it.date > today) });
  };
  const plain = (ds: ISODate[]) => [...new Set(ds)].sort().map((date) => ({ date }));
  // an application date's exceptions in the directive's text follow its article (CSDDD, Art. 37(1): Article 16 later)
  const withArticles = (xs: TranspositionDateInfo[]) =>
    xs.map((x) => ({ date: x.date, note: [x.articles.join(', '), x.exceptions].filter(Boolean).join('. ') || undefined }));
  // the same wording as the timeline's steps, in the tense of the visitor's date
  const rulesApply = (ahead: boolean) => (ahead ? 'Rules start to apply' : 'Rules started to apply');
  const someApply = (ahead: boolean) => (ahead ? 'Some provisions start to apply' : 'Some provisions started to apply');
  if (app.entry_into_force)
    dated(0, (ahead) => term('entry-into-force', ahead ? 'Enters into force' : 'Entered into force'), plain([app.entry_into_force]));
  else if (app.entry_into_force_pending)
    steps.push({
      when: 'Not yet',
      rank: 0,
      what: term('entry-into-force', 'Entry into force'),
      note: `EUR-Lex records no date. ${app.entry_into_force_condition ?? 'The act enters into force once a condition it sets is met.'}`,
    });
  else if (app.effect_on_notification)
    steps.push({
      when: 'Not recorded',
      rank: 0,
      what: 'Takes effect',
      note: 'On notification to those to whom the decision is addressed, according to EUR-Lex, which does not record the date of notification.',
    });
  // EUR-Lex gives the date from which the act in general, or some provisions, apply as not recorded (ETIAS, Regulation
  // (EU) 2018/1240, Art. 96: "from the date determined by the Commission"): never shown as applying from entry into force
  const unrecorded = (partial: boolean) => app.application_unrecorded?.find((x) => x.partial === partial);
  const noGeneral = unrecorded(false);
  const noPartial = unrecorded(true);
  if (app.application_detail?.length) {
    const items = (xs: typeof app.application_detail) => xs.map((x) => ({ date: x.date, note: x.provisions ?? undefined }));
    dated(1, rulesApply, items(app.application_detail.filter((x) => !x.partial)));
    dated(2, someApply, items(app.application_detail.filter((x) => x.partial)));
  } else if (app.application_dates.length || app.partial_on_entry_into_force || noGeneral || noPartial) {
    const partialSet = new Set(app.partial_application_dates ?? []);
    const general = app.application_dates.filter((d) => !partialSet.has(d));
    const partial = app.application_dates.filter((d) => partialSet.has(d));
    // EUR-Lex marks the entry-into-force date too: some provisions apply from it
    const onEif = app.partial_on_entry_into_force && app.entry_into_force ? [{ date: app.entry_into_force, note: 'On entry into force' }] : [];
    dated(1, rulesApply, plain(general));
    if (!general.length && noGeneral)
      steps.push({ when: 'Not recorded', rank: 1, what: 'Rules apply from', note: `EUR-Lex gives no date${refersTo(noGeneral.articles)}.` });
    dated(2, someApply, [...onEif, ...plain(partial)]);
    if (noPartial)
      steps.push({
        when: 'Not recorded',
        rank: 2,
        what: 'Some provisions apply from',
        note: `EUR-Lex gives no date for some provisions${refersTo(noPartial.articles)}.`,
      });
    // EUR-Lex records the entry into force for some provisions and no date for the others
    if (onEif.length && !app.application_dates.length && !noGeneral)
      steps.push({ when: 'Not recorded', rank: 2, what: 'Other provisions apply from', note: 'EUR-Lex gives no date.' });
  }
  const tr = transpositionDates(app);
  const further = tr.filter((x) => x.kind === 'further_deadline');
  const applies = tr.filter((x) => x.kind === 'application');
  const other = tr.filter((x) => x.kind === 'other');
  dated(
    3,
    () => (
      <>
        National {term('transposition', 'transposition')} deadline
      </>
    ),
    withArticles(tr.filter((x) => x.kind === 'deadline')),
  );
  dated(4, () => 'Transposition deadline for specific provisions', withArticles(further));
  dated(5, () => 'Application date for national measures', withArticles(applies));
  dated(6, () => 'Other date recorded by EUR-Lex', withArticles(other));
  // "No longer in force" (from the day after the end of validity, or the repeal's date), as the status says
  for (const e of noLonger) steps.push({ date: e.date, rank: 7, what: e.title });
  if (!steps.length) return <p className="meta">No application dates are recorded for this act in EUR-Lex.</p>;
  // an entry into force without a date first, then the dated steps in time order, then the dates not recorded
  const place = (s: ScheduleStep) => (s.date ? 1 : s.rank === 0 ? 0 : 2);
  const schedule = [...steps].sort((a, b) => place(a) - place(b) || (a.date ?? '').localeCompare(b.date ?? '') || a.rank - b.rank);
  const ended = new Set(app.after_end_of_validity ?? []);
  return (
    <>
    <ol className="dz-sched">
      {schedule.map((s, i) => (
        <li key={i}>
          <span className="dz-sched__date">{s.date ? <DateWhen date={s.date} today={today} /> : <span className="dz-sched__none">{s.when}</span>}</span>
          <span className="dz-sched__what">
            {s.what}
            {s.note && <span className="dz-dates__prov">{s.note}</span>}
            {s.date && ended.has(s.date) && <span className="dz-dates__prov">A date after the act’s validity ended</span>}
          </span>
        </li>
      ))}
    </ol>
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
    {instrument === 'regulation' && stage !== 'no_longer_in_force' && (
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

// "applies directly" or, for an act implementing enhanced cooperation, "applies directly only in the Member States
// taking part …": never "in all EU countries" (pipeline/analysis/status.py, regulation_applies)
const APPLIES_DIRECTLY = /^The regulation (applies directly[^;]*); no national transposition is needed\.(.*)$/s;
const LATER_DATES = /^Later dates? from which \(parts of\) the act apply: (.+)\.$/;

/**
 * An in-force regulation's next step as the build writes it (pipeline/analysis/status.py), led by what is still to
 * come: "Provisions of the act start to apply on 2 December 2026 and 2 August 2028. As a regulation, …", or, once no
 * such date is ahead, that no step follows. `later` is true when it names dates still to come. Other texts unchanged.
 */
export function regulationNextStep(text: string): { text: string; later: boolean } {
  const m = APPLIES_DIRECTLY.exec(text);
  if (!m) return { text, later: false };
  const rest = m[2].trim();
  const directly = `As a regulation, it ${m[1]}; no national transposition is needed.`;
  if (!rest) return { text: `No further step in the procedure. ${directly}`, later: false };
  const dates = LATER_DATES.exec(rest)?.[1];
  return dates ? { text: `Provisions of the act start to apply on ${dates}. ${directly}`, later: true } : { text, later: false };
}

/**
 * The next procedural step when the records establish one; otherwise the next date fixed in law, if any.
 * Never invents a step. `whenId`: the id of the page's "When it applies", when it shows the dates still to come.
 */
export function NextStep({ d, today, whenId }: { d: DossierDetail; today: ISODate; whenId?: string }) {
  const ns = d.next_step;
  const sched = nextScheduled(d.timeline, today);
  if (splitParts(d).length > 0)
    return <p className="dz-fact__text">None on this file: each separate file listed above has its own next step.</p>;
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
  const next = regulationNextStep(asOfToday(ns.text, today));
  return (
    <>
      <p className="dz-fact__text">
        <ExplanationText text={next.text} acts={d.status.named_acts} /> <BasisNote basis={ns.basis} />
      </p>
      {next.later && whenId && (
        <p className="meta">
          See <a href={`#${whenId}`}>When it applies</a> for what applies from each date.
        </p>
      )}
      {ns.institution && <p className="meta">{institutionLabel(ns.institution)}</p>}
    </>
  );
}

/** The Commission's proposal among the file's documents (COM(2023)0753), when it has a link. */
export function commissionProposal(d: Pick<DossierDetail, 'documents'>) {
  return d.documents.find((doc) => doc.kind === 'proposal' && /^COM\(/i.test(doc.id) && safeUrl(doc.url));
}

/**
 * "What is it?" without an editorial summary: never the heading repeated. The official title when it differs from
 * the heading; then the official text that sets out what the file is about: the adopted act, else the Commission's
 * proposal.
 */
function NoSummary({ d }: { d: DossierDetail }) {
  const act = d.acts[0];
  const proposal = commissionProposal(d);
  const sameTitle = !!d.official_title && isSameTitle(d.title, d.official_title);
  const text = act ? (
    <>
      Its content is set out in <ExtLink href={act.eurlex_url || EURLEX_CELEX(act.celex)}>the adopted act on EUR-Lex</ExtLink>.
    </>
  ) : proposal ? (
    <>
      Its content is set out in <ExtLink href={proposal.url!}>the Commission proposal, {proposal.id}</ExtLink>.
    </>
  ) : null;
  if (d.official_title && !sameTitle)
    return (
      <>
        <p className="dz-nocurated">We have not written a plain-language summary for this file yet. Its official title is:</p>
        <p className="dz-what__official">{d.official_title}</p>
        {text && <p className="dz-nocurated dz-what__source">{text}</p>}
      </>
    );
  return (
    <p className="dz-nocurated">
      We have not written a plain-language summary for this file yet{sameTitle ? '; the heading above is its official title' : ''}.
      {text && <> {text}</>}
    </p>
  );
}

/** "In 15–30 seconds": what it is, why it matters, where it stands, what's next. The status itself heads the page. */
export function DossierSummaryPanel({ d, today }: { d: DossierDetail; today: ISODate }) {
  const ed = d.editorial;
  const latest = latestDone(d.timeline, today);
  // a status recorded when the data was built can state a date that has passed since (the label stays as recorded)
  const explanation = asOfToday(d.status.explanation, today);
  const adopted = ADOPTED_STAGES.has(d.stage);
  const parts = splitParts(d);
  const when = adopted && d.application ? 'when-it-applies' : undefined;
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
        {/* a split proposal's generated heading already says what it is: only its separate files are listed */}
        {(ed?.what || !parts.length || d.official_title) && (
          <div className="dz-block">
            <h3 className="dz-label">What is it?</h3>
            {ed?.what ? <p className="dz-what__text">{ed.what}</p> : <NoSummary d={d} />}
          </div>
        )}
        {parts.length > 0 && (
          <div className="dz-block">
            <h3 className="dz-label">This proposal was split into</h3>
            <SplitParts parts={parts} />
          </div>
        )}
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
            {parts.length > 0 ? (
              <p className="dz-fact__text">This file was split into separate procedures, listed above; each has its own status.</p>
            ) : (
              <p className="dz-fact__text">
                <ExplanationText text={explanation} acts={d.status.named_acts} /> <BasisNote basis={d.status.basis} />
              </p>
            )}
            {explanation !== d.status.explanation && (
              <p className="meta">Status as recorded at the last data refresh, before the date above had passed.</p>
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
          <dt className="dz-label">Latest recorded step</dt>
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
            <NextStep d={d} today={today} whenId={when} />
          </dd>
        </div>
      </dl>

      {when && d.application && (
        <div className="dz-block dz-when" id={when}>
          <h3 className="dz-label">When it applies</h3>
          <KeyDates
            app={d.application}
            today={today}
            instrument={d.instrument}
            stage={d.stage}
            noLonger={d.timeline.filter((e) => e.kind === 'end_of_validity')}
          />
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
