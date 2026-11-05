/**
 * The law in context, from EUR-Lex / Cellar (pipeline/sources/lawcontext.py): EUR-Lex's official summary of the file's
 * acts, the court cases on them, their current consolidated text and the advisory opinions on the file. Each part
 * renders nothing when the data has none. Official text is shown as text, labelled with its source and date.
 */
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { ConsolidatedTextInfo, CourtCaseInfo, CourtDecisionInfo, DossierDetail, ISODate, Meta, OfficialSummaryInfo } from '../../../types/data';
import { ExtLink, Term } from '../../../components/ui';
import { formatDate } from '../../../lib/format';
import { EURLEX_CELEX, dossierPath } from '../labels';

/** "Source: EUR-Lex (Cellar), retrieved 5 Nov 2026." from meta.json's entry for the source. */
function LawSource({ meta, what = 'Recorded by EUR-Lex' }: { meta?: Meta; what?: string }) {
  const at = meta?.sources.find((s) => s.id === 'lawcontext')?.fetched_at;
  return (
    <p className="meta dz-law__source">
      {what} (Publications Office, Cellar){at ? `, as retrieved ${formatDate(at)}` : ''}.
    </p>
  );
}

// ------------------------------------------------------------------------------------------- official summary

/** "Official summary (EUR-Lex, last updated 24 March 2026)": the summary's opening section as published, and a link. */
export function OfficialSummary({ s, others = [] }: { s: OfficialSummaryInfo; others?: OfficialSummaryInfo[] }) {
  return (
    <div className="dz-osum" id="official-summary">
      <h4 className="dz-osum__label">
        Official summary{' '}
        <span className="dz-osum__src">(EUR-Lex{s.date ? <>, last updated <time dateTime={s.date}>{formatDate(s.date, true)}</time></> : ''})</span>
      </h4>
      {s.aim.length > 0 ? (
        <blockquote className="dz-osum__quote" cite={s.url}>
          <AimText s={s} />
        </blockquote>
      ) : (
        <p>EUR-Lex publishes a summary of this act; its text could not be read for this release.</p>
      )}
      <p className="meta dz-osum__note">
        {s.aim.length > 0 && <>{s.aim_complete ? 'Its opening section' : 'The start of its opening section'}, quoted as published. </>}
        Written by the EU Publications Office for EUR-Lex, not by this site.{' '}
        <ExtLink href={s.url}>Read the full summary on EUR-Lex: “{s.title}”</ExtLink>
      </p>
      {s.predates && <Predates s={s} />}
      {others.length > 0 && (
        <p className="meta">
          EUR-Lex also summarises this file’s acts in{' '}
          {others.map((o, i) => (
            <span key={o.id}>
              {i > 0 && (i === others.length - 1 ? ' and ' : ', ')}
              <ExtLink href={o.url}>“{o.title}”</ExtLink>
              {o.date && <> (last updated {formatDate(o.date)})</>}
            </span>
          ))}
          .
        </p>
      )}
    </div>
  );
}

/** The quoted paragraphs as text, the summary's list items (consecutive) as one list. */
function AimText({ s }: { s: OfficialSummaryInfo }) {
  const items = new Set(s.aim_items ?? []);
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = (key: number) => {
    if (list.length)
      out.push(
        <ul key={`list-${key}`}>
          {list.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>,
      );
    list = [];
  };
  s.aim.forEach((p, i) => {
    if (items.has(i)) list.push(p);
    else {
      flush(i);
      out.push(<p key={i}>{p}</p>);
    }
  });
  flush(s.aim.length);
  return <>{out}</>;
}

/** The summary was last updated before the latest amending act our data knows was published. */
function Predates({ s }: { s: OfficialSummaryInfo }) {
  const p = s.predates!;
  return (
    <p className="meta dz-osum__predates">
      EUR-Lex last updated this summary{s.date ? ` on ${formatDate(s.date, true)}` : ''}, before{' '}
      <Link to={dossierPath(p.celex)}>{p.label}</Link>, which amends the act, was published on {formatDate(p.date, true)}: the
      summary may not reflect that change.
    </p>
  );
}

/** For a file with an editorial summary: a link to EUR-Lex's own, which it does not repeat. */
export function OfficialSummaryLink({ summaries }: { summaries: OfficialSummaryInfo[] }) {
  if (!summaries.length) return null;
  return (
    <p className="meta dz-osum__link">
      Official summary on EUR-Lex:{' '}
      {summaries.map((s, i) => (
        <span key={s.id}>
          {i > 0 && '; '}
          <ExtLink href={s.url}>“{s.title}”</ExtLink>
          {s.date && <> (last updated {formatDate(s.date)})</>}
        </span>
      ))}
      .
    </p>
  );
}

// ------------------------------------------------------------------------------------------------------ court

const KIND_LABEL: Record<CourtCaseInfo['kind'], string> = {
  preliminary_reference: 'request for a preliminary ruling',
  annulment: 'action for annulment (in whole or in part)',
  annulment_of_withdrawal: 'action against the withdrawal of this proposal',
};

/** What the badges at the head of the court section say, each only when a record states it. */
export function courtBadges(d: Pick<DossierDetail, 'acts' | 'court'>): string[] {
  const rulings = d.acts.flatMap((a) => a.court_rulings ?? []);
  const pending = d.court?.pending ?? [];
  return [
    ...(rulings.some((r) => r.effect === 'annulment') ? ['Annulled (in whole or in part)'] : []),
    ...(rulings.some((r) => r.effect === 'invalidity') ? ['Declared invalid (in whole or in part)'] : []),
    ...(pending.some((k) => k.kind === 'preliminary_reference') ? ['Questions pending before the Court'] : []),
    ...(pending.some((k) => k.kind !== 'preliminary_reference') ? ['Action for annulment pending'] : []),
  ];
}

/** Whether the court section has anything to show. */
export function hasCourt(d: Pick<DossierDetail, 'acts' | 'court'>): boolean {
  return courtBadges(d).length > 0 || (d.court?.interpreted_by.length ?? 0) > 0;
}

/** "C-660/26 ↗ — request for a preliminary ruling, lodged 16 Jun 2026": the case number links its notice in the OJ. */
function PendingCase({ k, d }: { k: CourtCaseInfo; d: DossierDetail }) {
  const actLabel = (c: string) => d.acts.find((a) => a.celex === c)?.title;
  return (
    <li>
      <ExtLink href={k.url}>
        <strong className="nowrap">{k.case}</strong>
      </ExtLink>{' '}
      — {KIND_LABEL[k.kind]}
      {k.kind === 'annulment_of_withdrawal' && k.applicants?.length ? <>, brought by the {k.applicants.join(' and the ')}</> : null}
      {k.lodged && (
        <>
          , lodged <time dateTime={k.lodged}>{formatDate(k.lodged)}</time>
        </>
      )}
      {k.court === 'General Court' && <span className="meta"> (General Court)</span>}
      {k.kind === 'annulment_of_withdrawal' && k.annulled && (
        <span className="as-block meta">
          It asks for the annulment, in whole or in part, of the Commission’s withdrawal notice (
          <ExtLink href={EURLEX_CELEX(k.annulled)}>
            <span className="mono">{k.annulled}</span>
          </ExtLink>
          ) and cites this file’s proposal.
        </span>
      )}
      {d.acts.length > 1 && k.acts.length > 0 && <span className="as-block meta">On {k.acts.map((c) => actLabel(c) ?? c).join('; ')}</span>}
    </li>
  );
}

/** A list shown up to `max` items, then all on request. */
function Capped<T>({ items, max, render }: { items: T[]; max: number; render: (x: T) => ReactNode }) {
  const [all, setAll] = useState(false);
  return (
    <>
      <ul className="dz-list dz-law__list">{(all ? items : items.slice(0, max)).map(render)}</ul>
      {items.length > max && (
        <button type="button" className="lx-linkbtn" aria-expanded={all} onClick={() => setAll((a) => !a)}>
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </>
  );
}

function Decision({ x }: { x: CourtDecisionInfo }) {
  return (
    <li>
      <ExtLink href={x.url}>
        <strong>{x.case}</strong>
      </ExtLink>{' '}
      — {x.kind === 'judgment' ? 'judgment' : 'order'}
      {x.date && (
        <>
          {' '}
          of <time dateTime={x.date}>{formatDate(x.date)}</time>
        </>
      )}
      {x.court === 'General Court' && <span className="meta"> (General Court)</span>}
    </li>
  );
}

const SHOWN_DECISIONS = 8;
const SHOWN_PENDING = 6;

/** "Court rulings on this law": what EUR-Lex records of the Court's case law on the file's acts. */
export function CourtSection({ d, meta }: { d: DossierDetail; meta?: Meta }) {
  if (!hasCourt(d)) return null;
  const badges = courtBadges(d);
  const rulings = d.acts.flatMap((a) => a.court_rulings ?? []);
  const pending = d.court?.pending ?? [];
  const decisions = d.court?.interpreted_by ?? [];
  const isLaw = d.acts.length > 0;
  return (
    <section className="dz-section" id="court" aria-labelledby="court-title">
      <h2 id="court-title">{isLaw ? 'Court rulings on this law' : 'Court cases on this proposal'}</h2>
      {badges.length > 0 && (
        <ul className="dz-badges" aria-label="What EUR-Lex records">
          {badges.map((b) => (
            <li key={b}>
              <span className={`badge ${b.startsWith('Annulled') || b.startsWith('Declared') ? 'badge--critical' : 'badge--alert'}`}>{b}</span>
            </li>
          ))}
        </ul>
      )}
      {rulings.length > 0 && (
        <div className="dz-sub">
          <h3>Annulled or declared invalid</h3>
          <ul className="dz-list">
            {rulings.map((r) => (
              <li key={r.celex}>
                <ExtLink href={r.url}>
                  <strong>{r.case_number ?? r.celex}</strong>
                </ExtLink>
                {r.date && <>, {formatDate(r.date)}</>} — {r.summary}
              </li>
            ))}
          </ul>
        </div>
      )}
      {pending.length > 0 && (
        <div className="dz-sub">
          <h3>Pending before the Court</h3>
          <p className="meta dz-law__intro">
            Cases whose file in EUR-Lex records no judgment, order or closure yet, newest first; each links to the notice of
            the case in the Official Journal. In a request for a preliminary ruling, a national court asks the{' '}
            <Term id="cjeu">Court of Justice of the European Union</Term> how an EU act is to be interpreted or whether it
            is valid.
          </p>
          <Capped items={pending} max={SHOWN_PENDING} render={(k) => <PendingCase key={k.celex} k={k} d={d} />} />
        </div>
      )}
      {decisions.length > 0 && (
        <div className="dz-sub">
          <h3>Judgments and orders interpreting it</h3>
          <p className="meta dz-law__intro">
            {decisions.length === 1 ? 'EUR-Lex records one decision' : `EUR-Lex records ${decisions.length} decisions`} of the
            Court of Justice of the European Union interpreting {d.acts.length > 1 ? 'these acts' : 'this act'}, newest first.
          </p>
          <Capped items={decisions} max={SHOWN_DECISIONS} render={(x) => <Decision key={x.celex} x={x} />} />
        </div>
      )}
      <LawSource meta={meta} />
    </section>
  );
}

// ------------------------------------------------------------------------------------------ consolidated text

/** The latest version dated on or before `today` (else the earliest), and a later one if any. */
export function currentVersion(c: ConsolidatedTextInfo, today: ISODate) {
  const past = c.versions.filter((v) => v.date <= today);
  const current = past.length ? past[past.length - 1] : c.versions[0];
  const later = c.versions.filter((v) => v.date > (current?.date ?? today));
  return { current, later: later[later.length - 1] };
}

/** "Current consolidated text": the act as amended, on EUR-Lex. */
export function ConsolidatedSection({ d, today, meta }: { d: DossierDetail; today: ISODate; meta?: Meta }) {
  const items = (d.consolidated ?? []).filter((c) => c.versions.length > 0);
  if (!items.length) return null;
  const ended = d.stage === 'no_longer_in_force';
  return (
    <section className="dz-section" id="consolidated" aria-labelledby="consolidated-title">
      <h2 id="consolidated-title">{ended ? 'Latest consolidated text' : 'Current consolidated text'}</h2>
      <p className="dz-intro">
        A consolidated version combines an act with its later amendments and corrections in one text. EUR-Lex states that
        it “is meant purely as a documentation tool and has no legal effect”: the authentic versions are those published
        in the Official Journal.
      </p>
      <ul className="dz-list dz-law__list">
        {items.map((c) => {
          const { current, later } = currentVersion(c, today);
          if (!current) return null;
          const future = current.date > today;
          return (
            <li key={c.act}>
              <ExtLink href={EURLEX_CELEX(current.celex)}>
                {c.act_label}, {future ? 'version applicable from' : 'as it stands from'} {formatDate(current.date, true)}
              </ExtLink>{' '}
              <span className="meta mono">{current.celex}</span>
              {later && (
                <span className="as-block meta">
                  EUR-Lex also publishes the version applicable from{' '}
                  <ExtLink href={EURLEX_CELEX(later.celex)}>{formatDate(later.date, true)}</ExtLink>.
                </span>
              )}
            </li>
          );
        })}
      </ul>
      <LawSource meta={meta} />
    </section>
  );
}

// --------------------------------------------------------------------------------------------------- opinions

const BODY: Record<'EESC' | 'CoR', string> = {
  EESC: 'European Economic and Social Committee',
  CoR: 'European Committee of the Regions',
};

/** "Advisory opinions": EESC and CoR opinions that EUR-Lex records on the file. */
export function OpinionsSection({ d, meta }: { d: DossierDetail; meta?: Meta }) {
  const items = d.advisory_opinions ?? [];
  if (!items.length) return null;
  return (
    <section className="dz-section" id="opinions" aria-labelledby="opinions-title">
      <h2 id="opinions-title">Advisory opinions</h2>
      <p className="dz-intro">
        The Parliament, the Council and the Commission are assisted by the European Economic and Social Committee and the
        European Committee of the Regions, “acting in an advisory capacity” (Article 13(4) of the Treaty on European
        Union).
      </p>
      <ul className="dz-list dz-law__list">
        {items.map((o) => (
          <li key={o.celex}>
            <ExtLink href={o.url}>
              {BODY[o.body]} — opinion{o.date ? ` of ${formatDate(o.date, true)}` : ''}
            </ExtLink>
            {o.title && <span className="as-block meta dz-law__title">{o.title}</span>}
          </li>
        ))}
      </ul>
      <LawSource meta={meta} />
    </section>
  );
}
