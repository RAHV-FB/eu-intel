import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { DossierDetail, DossierImplementation, ISODate, LegalInstrument, TranspositionStatus } from '../../../types/data';
import { ExtLink, SourceLink, Term } from '../../../components/ui';
import { StackLabel } from '../../../components/StackedTable';
import { countryName, formatDate, formatNumber, safeUrl } from '../../../lib/format';
import { ACTIVE_STAGES, ADOPTED_STAGES, TRANSPOSITION_LABEL } from '../labels';
import { SplitNote, splitParts } from './Split';
import { transpositionDates } from './Summary';

const STATUS_ORDER: TranspositionStatus[] = [
  'measures_notified',
  'none_found',
  'deadline_not_reached',
  'no_deadline',
  'not_participating',
  'not_required',
  'unavailable',
];

const NIM_URL = (celex: string) => `https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:${encodeURIComponent(celex)}`;

/** Whether a country's latest notified measure predates the directive (EUR-Lex links measures notified earlier). */
function earlierNotified(d: DossierDetail, impl: DossierImplementation): boolean {
  const date = d.acts.find((a) => a.celex === impl.celex)?.date_document;
  return !!date && impl.countries.some((c) => !!c.latest_notification && c.latest_notification < date);
}

/** "Cyprus and Malta", "Denmark, Ireland and Malta". */
function namesList(codes: string[]): string {
  const names = codes.map(countryName);
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : (names[0] ?? '');
}

function StatusMark({ s }: { s: TranspositionStatus }) {
  return <span className={`tp tp--${s}`}>{TRANSPOSITION_LABEL[s]}</span>;
}

function ImplementationTable({ impl }: { impl: DossierImplementation }) {
  const [filter, setFilter] = useState<TranspositionStatus | 'all'>('all');
  const counts = new Map<TranspositionStatus, number>();
  for (const c of impl.countries) counts.set(c.status, (counts.get(c.status) ?? 0) + 1);
  const rows = impl.countries
    .filter((c) => filter === 'all' || c.status === filter)
    .slice()
    .sort((a, b) => countryName(a.country).localeCompare(countryName(b.country)));

  return (
    <>
      {/* each count is of Member States, not of measures (the table's "Measures notified" column counts those) */}
      <ul className="tp-summary" aria-label="Member States by status">
        {STATUS_ORDER.filter((s) => counts.get(s)).map((s) => (
          <li key={s}>
            <button
              type="button"
              className={`tp-summary__btn${filter === s ? ' is-active' : ''}`}
              aria-pressed={filter === s}
              onClick={() => setFilter((f) => (f === s ? 'all' : s))}
            >
              <span>
                <b className="num">{counts.get(s)}</b> {counts.get(s) === 1 ? 'Member State' : 'Member States'}:
              </span>{' '}
              <StatusMark s={s} />
            </button>
          </li>
        ))}
      </ul>
      <div className="table-wrap">
        {/* Explicit roles: on phones the rows are laid out as cards (table--stack), not as table cells. */}
        <table className="table tp-table table--stack" role="table">
          <caption className="visually-hidden">National measures notified for {impl.celex}, by Member State</caption>
          <thead role="rowgroup">
            <tr role="row">
              <th scope="col" role="columnheader">Member State</th>
              <th scope="col" role="columnheader">Status in the dataset</th>
              <th scope="col" role="columnheader" className="num">
                Measures notified
              </th>
              <th scope="col" role="columnheader">Latest notification</th>
              <th scope="col" role="columnheader">Infringement cases</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {rows.map((c) => (
              <tr key={c.country} role="row">
                <th scope="row" role="rowheader" className="stack-title">
                  <Link to={`/countries/${encodeURIComponent(c.country)}`}>{countryName(c.country)}</Link>
                </th>
                <td role="cell">
                  <StackLabel>Status</StackLabel>
                  <span>
                    <StatusMark s={c.status} />
                    {c.opted_in && (
                      <span className="tp-case meta">
                        Took part after adoption (
                        <ExtLink href={`https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:${c.opted_in}`}>
                          Commission decision
                        </ExtLink>
                        )
                      </span>
                    )}
                    {/* Denmark and a directive building upon the Schengen acquis (Protocol No 22, Art. 4) */}
                    {c.status_note && (
                      <span className="tp-case meta">
                        {c.status_note}
                        {c.status_note_url && (
                          <>
                            {' '}
                            <ExtLink href={c.status_note_url}>Notification</ExtLink>
                          </>
                        )}
                      </span>
                    )}
                    {c.infringements.some((i) => i.status === 'open' && i.non_communication) && (
                      <span className="tp-case meta">Commission case open for non-communication of transposition measures</span>
                    )}
                  </span>
                </td>
                <td role="cell" className="num">
                  <StackLabel>Measures</StackLabel>
                  {formatNumber(c.measures)}
                </td>
                <td role="cell">
                  <StackLabel>Last notified</StackLabel>
                  {c.latest_notification ? formatDate(c.latest_notification) : <span className="meta">—</span>}
                </td>
                <td role="cell">
                  <StackLabel>Cases</StackLabel>
                  {c.infringements.length === 0 ? (
                    <span className="meta">
                      None in the dataset
                      {impl.infringements_from && ` (cases closed before ${impl.infringements_from.slice(0, 4)} not included)`}
                    </span>
                  ) : (
                    <ul className="tp-inf">
                      {c.infringements.map((inf) => (
                        <li key={inf.id}>
                          <ExtLink href={inf.source.url}>{inf.id}</ExtLink>{' '}
                          <span className="meta">
                            {inf.status === 'open' ? 'open' : inf.status === 'closed' ? 'closed' : 'status unknown'}
                            {inf.latest_stage ? ` · ${inf.latest_stage}` : ''}
                            {inf.latest_decision_date ? ` · ${formatDate(inf.latest_decision_date)}` : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {impl.countries.some(
        (c) => c.status === 'none_found' && (impl.participation_unknown ?? []).includes(c.country),
      ) && (
        <p className="meta tp-optout">
          Denmark and Ireland do not take part in some justice and home affairs measures (Protocols 21 and 22 to
          the Treaties). Neither the directive’s recitals nor a Council voting record in our data show whether they
          took part in adopting this act, so “no measures found” may simply mean that it does not bind them.
        </p>
      )}
      {impl.countries.some((c) => c.status === 'no_deadline') && (
        <p className="meta tp-optout">
          “No transposition deadline recorded” means EUR-Lex gives no transposition deadline for this directive (for
          example, a codification that brings earlier directives together), so this dataset cannot say whether new
          national measures were due.
        </p>
      )}
      {impl.exemption && (
        <p className="meta tp-optout">
          {impl.exemption.countries?.length
            ? '“Not required by the directive” follows the directive’s own text'
            : 'The directive provides a derogation from transposition'}{' '}
          ({impl.exemption.provision}): “{impl.exemption.quote}”
          {!impl.exemption.countries?.length &&
            (impl.exemption.named?.length
              ? ` It exempts ${namesList(impl.exemption.named)} from the provisions it lists only, not from the rest of the directive, so their rows are not marked.`
              : ' It names no country, so “No measures found” may reflect it.')}
        </p>
      )}
      {impl.countries.some((c) => c.status === 'not_participating') && (
        <p className="meta tp-optout">
          “Not bound” means that the directive itself (in its recitals) or the Council’s official voting result records
          the country as not taking part in its adoption, under its opt-out from this area of EU law (Protocols 21 and 22
          to the Treaties).
          {impl.countries.some((c) => c.status === 'not_participating' && c.status_note) &&
            ' For a measure building upon the Schengen acquis, Denmark decides whether to implement it in its national law (Protocol No 22, Article 4); its row says so.'}
        </p>
      )}
    </>
  );
}

/** A directive's national measures: the table, what its statuses mean, and the EUR-Lex links. */
function NationalTable({ d, impl, celex }: { d: DossierDetail; impl: DossierImplementation | null | undefined; celex?: string }) {
  const nim = impl?.celex ?? celex;
  return impl && impl.countries.length > 0 ? (
    <>
      <ImplementationTable impl={impl} />
      <p className="dz-caveat">
        “Measures notified” means that at least one national measure was notified to the Commission; it does{' '}
        <strong>not</strong> show that transposition is complete or correct, and the Commission may still have a case
        open. “No measures found in the available dataset” is <strong>not</strong> proof that a country has failed to act: the
        dataset can be incomplete, existing national law may already meet the directive’s requirements, and some directives
        exempt certain Member States from transposing them or are not addressed to all of them. Whether a country has
        breached EU law is for the Commission to pursue (<Term id="infringement">infringement cases</Term>) and,
        ultimately, for the Court of Justice to decide. {impl.note}
        {earlierNotified(d, impl) &&
          ' Some notification dates are earlier than the directive: EUR-Lex can list, for a new directive, national measures notified for an earlier act.'}
      </p>
      <p className="meta">
        <ExtLink href={impl.nim_url}>National transposition measures on EUR-Lex</ExtLink> · <SourceLink source={impl.source} />
      </p>
    </>
  ) : (
    <p className="dz-none">
      <strong>{TRANSPOSITION_LABEL.unavailable}.</strong> National implementation data for this directive is not in our
      dataset.
      {nim && safeUrl(NIM_URL(nim)) && (
        <>
          {' '}
          You can check the <ExtLink href={NIM_URL(nim)}>national transposition measures on EUR-Lex</ExtLink>.
        </>
      )}
    </p>
  );
}

/** How the law reaches each Member State: transposition for directives; direct application for regulations. */
export function NationalApplication({ d, today }: { d: DossierDetail; today: ISODate }) {
  const typed: LegalInstrument | null = d.instrument ?? d.acts[0]?.act_type ?? null;
  const adopted = ADOPTED_STAGES.has(d.stage);
  // an adopted file is described by the type of a linked act, not by the type proposed (OEIL), which the adopted act's
  // can differ from (COM(2023) 596, a proposed decision, became Directive (EU) 2024/1306)
  const instrument = adopted && !d.acts.some((a) => a.act_type === typed) ? null : typed;
  const impl = d.implementation;
  // one table per directive of the file (2013/0400(CNS) adopted two)
  const tables = [impl, ...(d.implementation_more ?? [])].filter((t): t is DossierImplementation => !!t);
  const celex = impl?.celex ?? d.acts.find((a) => a.act_type === 'directive')?.celex ?? d.celex[0];
  const tr = transpositionDates(d.application);
  const general: ISODate | null = impl?.deadline ?? tr.find((x) => x.kind === 'deadline')?.date ?? null;
  const further = tr.filter((x) => x.kind === 'further_deadline');
  const applies = tr.filter((x) => x.kind === 'application');
  const other = tr.filter((x) => x.kind === 'other');
  // dates EUR-Lex records for after the act's validity ended (e.g. a deadline after a repeal)
  const ended = new Set(d.application?.after_end_of_validity ?? []);
  const endedNote = (x: ISODate) => ended.has(x) && <span className="meta"> (a date after the directive’s validity ended)</span>;
  const dateList = (xs: { date: ISODate; articles: string[]; exceptions?: string | null }[]) =>
    xs.map((x, i) => (
      <span key={x.date}>
        {i > 0 && ', '}
        <time dateTime={x.date}>{formatDate(x.date, true)}</time>
        {x.articles.length > 0 && <span className="meta"> ({x.articles.join(', ')})</span>}
        {x.date > today && <span className="dz-upcoming">upcoming</span>}
        {endedNote(x.date)}
        {/* what the directive's text provides beside this application date (CSDDD, Art. 37(1): Article 16 later) */}
        {x.exceptions && <span className="meta">. {x.exceptions}</span>}
      </span>
    ));

  // no act and no pending step can be stated (a stale file, one reported adopted without a linked act, a stage
  // the records do not determine): never "not law yet"
  // (split proposals and Parliament's reports have their own sentence below)
  const ownSentence = splitParts(d).length > 0 || d.related.some((r) => r.relation === 'Report on');
  const noActRecorded =
    !ownSentence && ((ACTIVE_STAGES.has(d.stage) && d.next_step.basis === 'unknown') || d.stage === 'unknown');
  let body: React.ReactNode;
  if (!adopted && noActRecorded) {
    body = (
      <p className="dz-none">
        No final act is linked to this file in our sources, so this page cannot show how it applies in the Member
        States.
      </p>
    );
  } else if (!adopted) {
    body = ACTIVE_STAGES.has(d.stage) ? (
      <p className="dz-none">
        This file is not law yet, so nothing applies in the Member States.{' '}
        {/* the type proposed, which can change before adoption (COM(2018) 277, a proposed regulation, became
            Directive (EU) 2021/1187) */}
        {instrument === 'directive' ? (
          <>
            It was proposed as a <Term id="directive">directive</Term>: if adopted in that form, it would have to be
            turned into national law by a deadline.
          </>
        ) : instrument === 'regulation' ? (
          <>
            It was proposed as a <Term id="regulation">regulation</Term>: if adopted in that form, it would apply
            directly, without national transposition.
          </>
        ) : (
          <>Once adopted, its legal form determines how it applies nationally.</>
        )}
      </p>
    ) : splitParts(d).length > 0 ? (
      <SplitNote>each separate file shows how its own act applies</SplitNote>
    ) : d.related.some((r) => r.relation === 'Report on') ? (
      <p className="dz-none">This is a resolution of Parliament, not a legislative act, so nothing applies in the Member States.</p>
    ) : (
      <p className="dz-none">This file has not become law, so nothing applies in the Member States.</p>
    );
  } else if (instrument === 'directive') {
    body = (
      <>
        <p>
          A <Term id="directive">directive</Term> sets goals that each Member State must reach through its own national law.
          Governments notify the Commission of the measures they adopt (<Term id="transposition">transposition</Term>).
        </p>
        {general && tables.length <= 1 && (
          <p className="dz-deadline">
            Transposition deadline:{' '}
            <strong>
              <time dateTime={general}>{formatDate(general, true)}</time>
            </strong>
            {general > today && <span className="dz-upcoming">upcoming</span>}
            {endedNote(general)}
          </p>
        )}
        {tables.length <= 1 && further.length > 0 && <p className="meta">Deadline{further.length > 1 ? 's' : ''} for specific provisions: {dateList(further)}</p>}
        {tables.length <= 1 && applies.length > 0 && (
          <p className="meta">
            Application date{applies.length > 1 ? 's' : ''} for the national measures: {dateList(applies)}
          </p>
        )}
        {tables.length <= 1 && other.length > 0 && <p className="meta">Other date{other.length > 1 ? 's' : ''} recorded by EUR-Lex: {dateList(other)}</p>}
        {tables.length > 1 ? (
          tables.map((t) => (
            <div key={t.celex} className="dz-sub" id={`national-${t.celex}`}>
              <h3>{t.act ?? t.celex}</h3>
              {t.deadline && (
                <p className="dz-deadline">
                  Transposition deadline:{' '}
                  <strong>
                    <time dateTime={t.deadline}>{formatDate(t.deadline, true)}</time>
                  </strong>
                  {t.deadline > today && <span className="dz-upcoming">upcoming</span>}
                </p>
              )}
              <NationalTable d={d} impl={t} />
            </div>
          ))
        ) : (
          <NationalTable d={d} impl={impl} celex={celex} />
        )}
      </>
    );
  } else if (instrument === 'regulation') {
    // which Member States it binds is in its text: one implementing enhanced cooperation binds only those taking part
    // (Art. 20(4) TEU), and Treaty opt-outs are in its recitals (Protocols 21 and 22); the Council's latest recorded
    // vote with positions names who did not take part (Regulation (EU) 2026/2280: Denmark and Ireland)
    const act = d.acts.find((a) => a.act_type === 'regulation');
    const enhanced = !!act && /\bimplementing enhanced cooperation\b/i.test(act.title);
    const cv = [...d.council_votes].sort((a, b) => b.date.localeCompare(a.date)).find((v) => Object.keys(v.positions).length > 0);
    const absent = cv ? Object.keys(cv.positions).filter((c) => cv.positions[c] === 'not_participating').sort() : [];
    // a Member State can take part after adoption: the recitals then no longer say whom it binds (AMMR, Regulation
    // (EU) 2024/1351, recital 91: Ireland "is not bound by it"; Commission Decision (EU) 2024/2088, Article 1: "The
    // participation of Ireland in Regulation (EU) 2024/1351 is confirmed", citing Protocol No 21, Article 4)
    const optedIn = d.acts.filter((a) => a.act_type === 'regulation').flatMap((a) => a.opted_in ?? []);
    const later = optedIn.map((o) => (
      <span key={o.decision}>
        {' '}
        {countryName(o.country)} opted in after its adoption: <ExtLink href={o.url}>{o.label}</ExtLink>
        {o.date && <> of {formatDate(o.date, true)}</>} confirms its participation in the regulation (Protocol No 21,
        Article 4).
      </span>
    ));
    const noLater = absent.includes('IE') && !optedIn.some((o) => o.country === 'IE');
    body = (
      <>
        <p className="dz-lede">
          <strong>Applies directly; no national transposition needed.</strong> A <Term id="regulation">regulation</Term> is
          binding in its entirety and directly applicable in the Member States it binds, from the dates it sets
          {d.application ? (
            <>
              {' '}
              (see <a href="#summary">When it applies</a> above)
            </>
          ) : null}
          .
          {enhanced && ' This one implements enhanced cooperation, so it binds only the Member States taking part in it (Article 20(4) TEU).'}
        </p>
        {cv && absent.length > 0 ? (
          <p className="meta">
            The Council’s vote of {formatDate(cv.date)} records {namesList(absent)} as not taking part. The regulation’s{' '}
            {act ? <ExtLink href={act.eurlex_url}>text</ExtLink> : 'text'} (its recitals) says which Member States were not
            bound by it when it was adopted.
            {later}
            {noLater && ' Our data record no Commission decision confirming that Ireland has taken part since.'}
          </p>
        ) : (
          later.length > 0 && <p className="meta">{later}</p>
        )}
      </>
    );
  } else if (instrument === 'decision') {
    const app = d.application;
    const seeAbove = app ? (
      <>
        {' '}
        (see <a href="#summary">When it applies</a> above)
      </>
    ) : null;
    body = app?.entry_into_force_pending ? (
      // e.g. an amendment of the Electoral Act: the condition (approval by every Member State) is the point
      <p className="dz-lede">
        {app.entry_into_force_condition ?? 'It enters into force only once a condition set in the decision is met.'} EUR-Lex
        records no date of entry into force yet{seeAbove}.
      </p>
    ) : app?.effect_on_notification ? (
      <p className="dz-lede">
        This decision is addressed to specific recipients and is binding only on them (Article 288 TFEU). EUR-Lex gives its
        date of effect as the date of notification to them. It does not need national transposition{seeAbove}.
      </p>
    ) : (
      // Article 288 TFEU; whether this decision names addressees is not in our data
      <p className="dz-lede">
        A decision is binding in its entirety; one that specifies those to whom it is addressed is binding only on them
        (Article 288 TFEU). It does not need national transposition{seeAbove}.
      </p>
    );
  } else {
    body = (
      <>
        <p className="dz-none">
          {typed && typed !== 'other' && !d.acts.length
            ? 'No adopted act is linked to this file in our sources yet, so this page cannot show how it applies in the ' +
              `Member States. It was proposed as a ${typed}; the adopted act’s type can differ from the one proposed.`
            : 'Our sources do not record how this act applies in the Member States.'}
          {d.application ? ' The dates recorded by EUR-Lex are shown under “When it applies” above.' : ''}
        </p>
      </>
    );
  }

  return (
    <section className="dz-section" id="national" aria-labelledby="national-title">
      <h2 id="national-title">How it applies in the Member States</h2>
      {body}
    </section>
  );
}
