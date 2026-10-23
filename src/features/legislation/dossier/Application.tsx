import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { DossierDetail, DossierImplementation, ISODate, LegalInstrument, TranspositionStatus } from '../../../types/data';
import { ExtLink, SourceLink, Term } from '../../../components/ui';
import { countryName, formatDate, formatNumber, safeUrl } from '../../../lib/format';
import { ACTIVE_STAGES, ADOPTED_STAGES, TRANSPOSITION_LABEL } from '../labels';
import { transpositionDates } from './Summary';

const STATUS_ORDER: TranspositionStatus[] = [
  'measures_notified',
  'none_found',
  'deadline_not_reached',
  'no_deadline',
  'not_participating',
  'unavailable',
];

const NIM_URL = (celex: string) => `https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:${encodeURIComponent(celex)}`;

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
      <ul className="tp-summary" aria-label="Summary by status">
        {STATUS_ORDER.filter((s) => counts.get(s)).map((s) => (
          <li key={s}>
            <button
              type="button"
              className={`tp-summary__btn${filter === s ? ' is-active' : ''}`}
              aria-pressed={filter === s}
              onClick={() => setFilter((f) => (f === s ? 'all' : s))}
            >
              <b className="num">{counts.get(s)}</b> <StatusMark s={s} />
            </button>
          </li>
        ))}
      </ul>
      <div className="table-wrap">
        <table className="table tp-table">
          <caption className="visually-hidden">National measures notified for {impl.celex}, by Member State</caption>
          <thead>
            <tr>
              <th scope="col">Member State</th>
              <th scope="col">Status in the dataset</th>
              <th scope="col" className="num">
                Measures notified
              </th>
              <th scope="col">Latest notification</th>
              <th scope="col">
                <Term id="infringement">Infringement cases</Term>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.country}>
                <th scope="row">
                  <Link to={`/countries/${encodeURIComponent(c.country)}`}>{countryName(c.country)}</Link>
                </th>
                <td>
                  <StatusMark s={c.status} />
                  {c.infringements.some((i) => i.status === 'open' && i.non_communication) && (
                    <span className="tp-case meta">Commission case open for incomplete notification</span>
                  )}
                </td>
                <td className="num">{formatNumber(c.measures)}</td>
                <td>{c.latest_notification ? formatDate(c.latest_notification) : <span className="meta">—</span>}</td>
                <td>
                  {c.infringements.length === 0 ? (
                    <span className="meta">None in the dataset</span>
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
      {impl.countries.some((c) => (c.country === 'DK' || c.country === 'IE') && c.status === 'none_found') && (
        <p className="meta tp-optout">
          Denmark and Ireland do not take part in some justice and home affairs measures (Protocols 21 and 22 to
          the Treaties). Where no Council voting record shows whether they took part in adopting this act, “no
          measures found” may simply mean that it does not bind them.
        </p>
      )}
      {impl.countries.some((c) => c.status === 'no_deadline') && (
        <p className="meta tp-optout">
          “No transposition deadline recorded” means EUR-Lex gives no transposition deadline for this directive (for
          example, a codification that brings earlier directives together), so this dataset cannot say whether new
          national measures were due.
        </p>
      )}
      {impl.countries.some((c) => c.status === 'not_participating') && (
        <p className="meta tp-optout">
          “Not bound” means that the directive itself (in its recitals) or the Council’s official voting result records
          the country as not taking part in its adoption, under its opt-out from this area of EU law (Protocols 21 and 22
          to the Treaties).
        </p>
      )}
    </>
  );
}

/** How the law reaches each Member State: transposition for directives; direct application for regulations. */
export function NationalApplication({ d, today }: { d: DossierDetail; today: ISODate }) {
  const instrument: LegalInstrument | null = d.instrument ?? d.acts[0]?.act_type ?? null;
  const adopted = ADOPTED_STAGES.has(d.stage);
  const impl = d.implementation;
  const celex = impl?.celex ?? d.acts.find((a) => a.act_type === 'directive')?.celex ?? d.celex[0];
  const tr = transpositionDates(d.application);
  const general: ISODate | null = impl?.deadline ?? tr.find((x) => x.kind === 'deadline')?.date ?? null;
  const further = tr.filter((x) => x.kind === 'further_deadline');
  const applies = tr.filter((x) => x.kind === 'application');
  const dateList = (xs: { date: ISODate; articles: string[] }[]) =>
    xs.map((x, i) => (
      <span key={x.date}>
        {i > 0 && ', '}
        <time dateTime={x.date}>{formatDate(x.date, true)}</time>
        {x.articles.length > 0 && <span className="meta"> ({x.articles.join(', ')})</span>}
        {x.date > today && <span className="dz-upcoming">upcoming</span>}
      </span>
    ));

  let body: React.ReactNode;
  if (!adopted) {
    body = ACTIVE_STAGES.has(d.stage) ? (
      <p className="dz-none">
        This file is not law yet, so nothing applies in the Member States. Once adopted,{' '}
        {instrument === 'directive' ? (
          <>
            as a <Term id="directive">directive</Term> it would have to be turned into national law by a deadline.
          </>
        ) : instrument === 'regulation' ? (
          <>
            as a <Term id="regulation">regulation</Term> it would apply directly in every Member State.
          </>
        ) : (
          <>its legal form determines how it applies nationally.</>
        )}
      </p>
    ) : (
      <p className="dz-none">This file did not become law, so nothing applies in the Member States.</p>
    );
  } else if (instrument === 'directive') {
    body = (
      <>
        <p>
          A <Term id="directive">directive</Term> sets goals that each Member State must reach through its own national law.
          Governments notify the Commission of the measures they adopt (<Term id="transposition">transposition</Term>).
        </p>
        {general && (
          <p className="dz-deadline">
            Transposition deadline:{' '}
            <strong>
              <time dateTime={general}>{formatDate(general, true)}</time>
            </strong>
            {general > today && <span className="dz-upcoming">upcoming</span>}
          </p>
        )}
        {further.length > 0 && <p className="meta">Further deadline{further.length > 1 ? 's' : ''} for specific provisions: {dateList(further)}</p>}
        {applies.length > 0 && (
          <p className="meta">
            Application date{applies.length > 1 ? 's' : ''} for the national measures: {dateList(applies)}
          </p>
        )}
        {impl && impl.countries.length > 0 ? (
          <>
            <ImplementationTable impl={impl} />
            <p className="dz-caveat">
              “Measures notified” means that at least one national measure was notified to the Commission; it does{' '}
              <strong>not</strong> show that transposition is complete or correct, and the Commission may still have a case
              open. “No measures found in the available dataset” is <strong>not</strong> proof that a country has failed to act: the
              dataset can be incomplete, and existing national law may already meet the directive’s requirements. Whether a country has
              breached EU law is for the Commission to pursue and, ultimately, for the Court of Justice to decide. {impl.note}
            </p>
            <p className="meta">
              <ExtLink href={impl.nim_url}>National transposition measures on EUR-Lex</ExtLink> · <SourceLink source={impl.source} />
            </p>
          </>
        ) : (
          <p className="dz-none">
            <strong>{TRANSPOSITION_LABEL.unavailable}.</strong> National implementation data for this directive is not in our
            dataset.
            {celex && safeUrl(NIM_URL(celex)) && (
              <>
                {' '}
                You can check the <ExtLink href={NIM_URL(celex)}>national transposition measures on EUR-Lex</ExtLink>.
              </>
            )}
          </p>
        )}
      </>
    );
  } else if (instrument === 'regulation') {
    body = (
      <>
        <p className="dz-lede">
          <strong>Applies directly; no national transposition needed.</strong> A <Term id="regulation">regulation</Term> is
          binding in its entirety in every Member State from the dates it sets
          {d.application ? (
            <>
              {' '}
              (see <a href="#summary">When it applies</a> above)
            </>
          ) : null}
          .
        </p>
      </>
    );
  } else if (instrument === 'decision') {
    body = (
      <>
        <p className="dz-lede">
          A decision is binding on those it is addressed to; it does not need national transposition
          {d.application ? (
            <>
              {' '}
              (see <a href="#summary">When it applies</a> above)
            </>
          ) : null}
          .
        </p>
      </>
    );
  } else {
    body = (
      <>
        <p className="dz-none">
          Our sources do not record how this act applies in the Member States.
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
