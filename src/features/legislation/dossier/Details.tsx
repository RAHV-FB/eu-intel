import { useState } from 'react';
import { Link } from 'react-router-dom';
import { splitParts } from './Split';
import type { DossierDetail, LegalActSummary } from '../../../types/data';
import { Disclosure, ExtLink, Term, institutionLabel } from '../../../components/ui';
import { countryName, formatDate, formatDateTime, safeUrl } from '../../../lib/format';
import { EURLEX_CELEX, INSTRUMENT_LABEL, dossierPath } from '../labels';
import { rapporteurRoleLabel } from '../../people/labels';

/**
 * What SourceRef.published is for each source: Cellar's last modification of its record (not the Official Journal
 * date, shown with the act), the Legislative Train page's update, a Council register document's date.
 */
const SOURCE_DATE_LABEL: Record<string, string> = {
  'EUR-Lex': 'record updated',
  LegislativeTrain: 'page updated',
  Council: 'document dated',
};

/** Committee roles on a file (CommitteeRole.role in the snapshot). */
const COMMITTEE_ROLE_LABEL: Record<string, string> = {
  responsible: 'committee responsible',
  joint: 'joint committee responsible',
  opinion: 'committee for opinion',
  other: 'other role',
};

function CelexList({ items, max = 8 }: { items: string[]; max?: number }) {
  const [all, setAll] = useState(false);
  if (!items.length) return null;
  const shown = all ? items : items.slice(0, max);
  return (
    <>
      <ul className="dz-inline">
        {shown.map((c) => (
          <li key={c}>
            <ExtLink href={EURLEX_CELEX(c)}>
              <span className="mono">{c}</span>
            </ExtLink>
          </li>
        ))}
      </ul>
      {items.length > max && (
        <button type="button" className="lx-linkbtn" onClick={() => setAll((a) => !a)}>
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </>
  );
}

function ActBlock({ a }: { a: LegalActSummary }) {
  const relations: [string, string[]][] = [
    ['Amends', a.amends],
    ['Amended by', a.amended_by],
    ['Repeals', a.repeals],
    ['Repealed by', a.repealed_by],
    // EUR-Lex's classification of the link: the repealing act's text need not use the word (Decision (EU) 2024/867,
    // Art. 6: Decision (EU) 2020/1531 "remains applicable to the extent referred to in Article 5(2)")
    ['Partly repeals (EUR-Lex)', a.partly_repeals ?? []],
    ['Partly repealed by (EUR-Lex)', a.partly_repealed_by ?? []],
  ];
  return (
    <div className="dz-act">
      <p className="dz-act__title">
        <ExtLink href={a.eurlex_url}>{a.title}</ExtLink>
      </p>
      <dl className="dz-kv">
        <div>
          <dt>Type</dt>
          <dd>{INSTRUMENT_LABEL[a.act_type] ?? a.act_type}</dd>
        </div>
        <div>
          <dt>
            <Term id="celex">CELEX</Term>
          </dt>
          <dd className="mono">{a.celex}</dd>
        </div>
        {a.eli && (
          <div>
            <dt>ELI</dt>
            <dd>
              {safeUrl(a.eli) ? (
                <ExtLink href={a.eli}>
                  <span className="mono dz-break">{a.eli}</span>
                </ExtLink>
              ) : (
                <span className="mono dz-break">{a.eli}</span>
              )}
            </dd>
          </div>
        )}
        {a.date_document && (
          <div>
            <dt>Date of the act</dt>
            <dd>{formatDate(a.date_document)}</dd>
          </div>
        )}
        {a.date_publication && (
          <div>
            <dt>Published in the Official Journal</dt>
            <dd>{formatDate(a.date_publication)}</dd>
          </div>
        )}
        {a.entry_into_force && (
          <div>
            <dt>Entry into force</dt>
            <dd>{formatDate(a.entry_into_force)}</dd>
          </div>
        )}
        {a.in_force != null && (
          <div>
            <dt>Currently in force (EUR-Lex)</dt>
            <dd>{a.in_force ? 'Yes' : 'No'}</dd>
          </div>
        )}
        {a.end_of_validity && (
          <div>
            <dt>End of validity</dt>
            <dd>{formatDate(a.end_of_validity)}</dd>
          </div>
        )}
      </dl>
      {relations.some(([, v]) => v.length) && (
        <dl className="dz-kv dz-kv--rel">
          {relations
            .filter(([, v]) => v.length)
            .map(([label, v]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  <CelexList items={v} />
                </dd>
              </div>
            ))}
        </dl>
      )}
    </div>
  );
}

/** An interim report (…R) or a report accompanying a consent (…M) on a main procedure (pipeline/build.py PARLIAMENT_REPORT_RE). */
const PARLIAMENT_REPORT = /^\d{4}-\d{4}[RM]$/;

/** Everything a researcher needs: identifiers, actors, related acts, documents and sources. Collapsed by default. */
export function DossierDetails({ d }: { d: DossierDetail }) {
  const comRefs = d.documents.filter((doc) => /^COM\(/i.test(doc.id) || doc.kind === 'COM');
  return (
    <section className="dz-section" id="details" aria-labelledby="details-title">
      <h2 id="details-title">Details, identifiers and sources</h2>
      <Disclosure summary="Show official identifiers, people involved, related acts, documents and sources">
        <dl className="dz-kv dz-kv--wide">
          <div>
            <dt>Official title</dt>
            <dd>
              {d.official_title ?? (
                <span className="meta">
                  Not recorded{splitParts(d).length > 0 ? ': this is the file the proposal was split from (see the separate files below)' : ''}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt>
              <Term id="procedure-reference">Procedure reference</Term>
            </dt>
            <dd>
              <span className="mono">{d.ref}</span>
              {d.oeil_url && (
                <>
                  {' '}
                  · <ExtLink href={d.oeil_url}>Legislative Observatory (OEIL)</ExtLink>
                </>
              )}
            </dd>
          </div>
          <div>
            <dt>Procedure type</dt>
            <dd>
              {d.type === 'COD' ? <Term id="olp">{d.type_label}</Term> : d.type_label} <span className="mono meta">({d.type})</span>
            </dd>
          </div>
          {d.instrument && (
            <div>
              <dt>Type of act</dt>
              <dd>
                {INSTRUMENT_LABEL[d.instrument]}
                {/* no linked act of this type: the type of act proposed (OEIL "Legislative instrument") */}
                {!d.acts.some((a) => a.act_type === d.instrument) && <span className="meta"> (as proposed)</span>}
              </dd>
            </div>
          )}
          <div>
            <dt>
              <Term id="celex">CELEX number{d.celex.length === 1 ? '' : 's'}</Term>
            </dt>
            <dd>
              {d.celex.length ? (
                <CelexList items={d.celex} />
              ) : splitParts(d).length > 0 ? (
                <span className="meta">None on this file: each separate file lists its own act</span>
              ) : PARLIAMENT_REPORT.test(d.id) ? (
                <span className="meta">None: Parliament’s report is a resolution of Parliament, not a legislative act</span>
              ) : (
                <span className="meta">None recorded (no adopted act yet, or not linked)</span>
              )}
            </dd>
          </div>
          {comRefs.length > 0 && (
            <div>
              <dt>Commission proposal</dt>
              <dd>
                <ul className="dz-inline">
                  {comRefs.map((c) => (
                    <li key={c.id}>
                      {safeUrl(c.url) ? (
                        <ExtLink href={c.url}>
                          <span className="mono">{c.id}</span>
                        </ExtLink>
                      ) : (
                        <span className="mono">{c.id}</span>
                      )}
                      {c.date && <span className="meta"> ({formatDate(c.date)})</span>}
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
          <div>
            <dt>Proposed{d.started_from_parts && ' (as recorded for its parts)'}</dt>
            <dd>{d.started ? formatDate(d.started, true) : <span className="meta">Not recorded</span>}</dd>
          </div>
          <div>
            <dt>Latest recorded step</dt>
            <dd>{d.last_event ? formatDate(d.last_event, true) : <span className="meta">Not recorded</span>}</dd>
          </div>
        </dl>

        {d.committees.length > 0 && (
          <div className="dz-sub">
            <h3>Parliament committees</h3>
            <ul className="dz-list">
              {d.committees.map((c) => (
                <li key={`${c.code}-${c.role}-${c.former ? 'former' : ''}`}>
                  <span className="mono">{c.code}</span>
                  {c.name && <> — {c.name}</>}{' '}
                  <span className="meta">
                    ({c.former ? 'former ' : ''}
                    {COMMITTEE_ROLE_LABEL[c.role] ?? c.role})
                  </span>
                </li>
              ))}
            </ul>
            {d.committees.some((c) => c.former) && (
              <p className="meta">
                “Former” means that the Legislative Observatory lists the committee only under a “Former …” heading for this file, in the
                current parliamentary term or an earlier one.
              </p>
            )}
          </div>
        )}

        {d.rapporteurs.length > 0 && (
          <div className="dz-sub">
            <h3>Rapporteurs and shadow rapporteurs</h3>
            <p className="meta">
              From Parliament’s open data and, where available, the key players of its Legislative Observatory file. Each MEP is shown with the
              political group they belonged to in that role, where the records establish it. “Former” means that the Legislative Observatory
              lists the MEP only under a “Former …” heading for this file, in the current parliamentary term or an earlier one; where it
              does not list the MEP, it means that Parliament’s open data records the appointment in an earlier term.
              {d.rapporteurs.some((r) => !r.has_page) && ' A name without a link has no MEP page on this site, which covers the parliamentary terms since 2019.'}
            </p>
            <ul className="dz-list">
              {d.rapporteurs.map((r, i) => (
                <li key={`${r.mep_id ?? r.name}-${i}`}>
                  {/* MEPs of earlier terms have no page here: their name is not a link, as groups before 2019 */}
                  {r.mep_id && r.has_page ? <Link to={`/people/meps/${encodeURIComponent(r.mep_id)}`}>{r.name}</Link> : r.name}
                  <span className="meta">
                    {' '}
                    — {rapporteurRoleLabel(r.role, r.committee, r.former)}
                    {r.group_code ? ` · ${r.group_code}` : ''}
                    {r.country ? ` · ${countryName(r.country)}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {d.acts.length > 0 && (
          <div className="dz-sub">
            <h3>Adopted legal act{d.acts.length > 1 ? 's' : ''} (EUR-Lex)</h3>
            {d.acts.map((a) => (
              <ActBlock key={a.celex} a={a} />
            ))}
          </div>
        )}

        {d.related.length > 0 && (
          <div className="dz-sub">
            <h3>Related acts and files</h3>
            <p className="meta">Only relations established in official records are listed.</p>
            <ul className="dz-list">
              {d.related.map((r) => (
                <li key={`${r.id}-${r.relation}`}>
                  <span className="meta">{r.relation}: </span>
                  {/^\d{4}-\d{4}/.test(r.id) ? (
                    <>
                      <Link to={dossierPath(r.id)}>
                        {r.ref && (
                          <>
                            <span className="mono">{r.ref}</span> –{' '}
                          </>
                        )}
                        {r.title}
                      </Link>
                      {r.status_label && <span className="meta"> ({r.status_label})</span>}
                    </>
                  ) : (
                    <ExtLink href={EURLEX_CELEX(r.id)}>{r.title}</ExtLink>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {d.documents.length > 0 && (
          <div className="dz-sub">
            <h3>Key documents</h3>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Document</th>
                    <th scope="col" className="hide-narrow">
                      Reference
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {d.documents.map((doc) => (
                    <tr key={doc.id}>
                      <td className="nowrap">{doc.date ? formatDate(doc.date) : '—'}</td>
                      <td>
                        {safeUrl(doc.url) ? <ExtLink href={doc.url}>{doc.label || doc.kind || doc.id}</ExtLink> : doc.label || doc.kind || doc.id}
                        {/* phones: the reference column is hidden and shown here */}
                        <span className="only-narrow meta mono">{doc.id}</span>
                      </td>
                      <td className="mono hide-narrow">{doc.id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="dz-sub">
          <h3>Sources</h3>
          <ul className="dz-list dz-sources">
            {d.sources
              .filter((s, i, all) => all.findIndex((o) => o.url === s.url && o.identifier === s.identifier && o.label === s.label) === i)
              .map((s, i) => (
              <li key={`${s.url}-${i}`}>
                <ExtLink href={s.url}>{s.label || institutionLabel(s.institution)}</ExtLink>
                <span className="meta">
                  {' '}
                  — {institutionLabel(s.institution)}
                  {s.identifier ? ` · ${s.identifier}` : ''}
                  {s.published ? ` · ${SOURCE_DATE_LABEL[s.institution] ?? 'dated'} ${formatDate(s.published)}` : ''}
                  {s.retrieved_at ? ` · retrieved ${formatDateTime(s.retrieved_at)}` : ''}
                </span>
              </li>
            ))}
            {d.sources.length === 0 && <li className="meta">No source records attached.</li>}
          </ul>
        </div>
      </Disclosure>
    </section>
  );
}
