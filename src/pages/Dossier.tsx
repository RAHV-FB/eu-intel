import { useEffect, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import type { DossierDetail, DossierSummary, Meta } from '../types/data';
import { useData } from '../lib/data';
import { formatDate } from '../lib/format';
import { changeSince, getWatchlist, markSeen, type ChangeInfo } from '../lib/watchlist';
import { ErrorState, ExtLink, Loading, LookupNotice, NotFound, PageHeader, Term } from '../components/ui';
import { ACTIVE_STAGES, EURLEX_CELEX, INSTRUMENT_LABEL, dossierPath, isMissing, isSameTitle, useDocumentTitle, useTopics } from '../features/legislation/labels';
import { todayISO } from '../features/legislation/explorer';
import { DossierSummaryPanel } from '../features/legislation/dossier/Summary';
import { WhereIsIt } from '../features/legislation/dossier/WhereIsIt';
import { Timeline } from '../features/legislation/dossier/Timeline';
import { splitParts } from '../features/legislation/dossier/Split';
import { CouncilVotes, ParliamentVotes } from '../features/legislation/dossier/Votes';
import { NationalApplication } from '../features/legislation/dossier/Application';
import { DossierDetails } from '../features/legislation/dossier/Details';
import { FollowButton } from '../features/watchlist/FollowButton';
import { useHashScroll } from '../features/guide/useHashScroll';
import '../features/legislation/common.css';
import '../features/legislation/dossier/dossier.css';

/** Procedure ids as published: "2021-0106", or a split part such as "2016-0282A". */
const DOSSIER_ID = /^\d{4}-\d{4}[A-Z]{0,2}$/;
/** A CELEX number, e.g. "32017R1550": a legal act, which may have no legislative file in this dataset. */
const CELEX_ID = /^[0-9][0-9]{4}[A-Z]{1,2}[0-9]{4}(\(\d{2}\))?$/;

/** "Directive (EU) 2022/2555 · also known as NIS 2 Directive · part of the Pact on Migration and Asylum" */
function KnownAs({ k }: { k: NonNullable<DossierDetail['known_as']> }) {
  const parts: string[] = [...k.acts];
  if (k.names.length > 0) parts.push(`${parts.length ? 'also' : 'Also'} known as ${k.names.join(', ')}`);
  if (k.part_of?.length) parts.push(`${parts.length ? 'part' : 'Part'} of the ${k.part_of[0]}`);
  return <p className="dz-known">{parts.join(' · ')}</p>;
}

export default function Dossier() {
  const { id = '' } = useParams();
  if (CELEX_ID.test(id)) return <ActByCelex celex={id} />;
  return <DossierPage id={id} />;
}

function DossierPage({ id }: { id: string }) {
  const valid = DOSSIER_ID.test(id);
  const { data: raw, error, loading } = useData<DossierDetail>(valid ? `dossiers/${id}.json` : null);
  // A file without the basic parts of a dossier (e.g. a list file) is treated as not found rather than rendered.
  const d = raw && raw.id === id && Array.isArray(raw.timeline) ? raw : undefined;
  const malformed = !!raw && !d;
  const { data: meta } = useData<Meta>('meta.json');
  const { topics, failed: topicsFailed } = useTopics();
  const notFound = !valid || malformed || isMissing(error);
  useDocumentTitle(d?.title ?? (notFound ? 'Legislative file not found' : 'Legislation'), d?.ref);

  // "Changed since you last looked" for followed files; then record that the visitor has now seen it.
  const [change, setChange] = useState<ChangeInfo | null>(null);
  useEffect(() => {
    setChange(null);
    if (!d) return;
    const entry = getWatchlist().find((e) => e.id === d.id);
    if (!entry) return;
    const c = changeSince(entry, d);
    if (c.changed) setChange(c);
    markSeen(d);
  }, [d]);
  // a link to a section (/legislation/2021-0106#timeline) lands on it once the file has loaded
  useHashScroll(!loading && !!d);

  if (notFound) return <NotFound what="legislative file" />;
  if (error)
    return (
      <div className="container page">
        <ErrorState error={error} title="This legislative file could not be loaded" />
      </div>
    );
  if (loading || !d)
    return (
      <div className="container page">
        <Loading label="Loading legislative file…" />
      </div>
    );

  const today = todayISO();
  const active = ACTIVE_STAGES.has(d.stage);
  const topicLabel = (slug: string) => topics.find((t) => t.slug === slug)?.label ?? slug;
  const primaryAct = d.acts[0];

  const nav = [
    { id: 'summary', label: 'Summary' },
    ...(active ? [{ id: 'where', label: 'Where it is now' }] : []),
    { id: 'timeline', label: 'Timeline' },
    { id: 'ep-votes', label: 'Parliament votes' },
    { id: 'council-votes', label: 'Council votes' },
    { id: 'national', label: 'In the Member States' },
    { id: 'details', label: 'Details & sources' },
  ];

  return (
    <article className="container page dz">
      <nav className="dz-crumbs" aria-label="Breadcrumb">
        <ol>
          <li>
            <Link to="/legislation">Legislation</Link>
          </li>
          {d.topics[0] && (
            <li>
              <Link to={`/legislation?topic=${encodeURIComponent(d.topics[0])}`}>{topicLabel(d.topics[0])}</Link>
            </li>
          )}
          <li aria-current="page" className="mono">
            {d.ref}
          </li>
        </ol>
      </nav>
      <LookupNotice failed={topicsFailed && d.topics.length > 0} what="Topic names" />

      <header className="dz-head" id="summary">
        <h1 className={`dz-title${d.title.length > 110 ? ' dz-title--long' : ''}`}>{d.title}</h1>
        {d.known_as && <KnownAs k={d.known_as} />}
        {/* Without an editorial summary, "What is it?" below already shows the official title in full. */}
        {d.editorial && d.official_title && !isSameTitle(d.title, d.official_title) && <OfficialTitle text={d.official_title} />}
        {change && (
          <p className="dz-changed" role="status">
            <span className="lx-changed">Updated since you last looked</span>{' '}
            {change.stageChanged && change.previousLabel ? (
              <>
                Status changed from “{change.previousLabel}” to “{d.status_label}”.
              </>
            ) : (
              <>A new step was recorded{d.last_event ? ` on ${formatDate(d.last_event)}` : ''}.</>
            )}
          </p>
        )}
      </header>

      <div className="dz-layout">
        <div className="dz-main-top">
          <DossierSummaryPanel d={d} today={today} />
        </div>

        <aside className="dz-aside" aria-label="Key facts">
          <div className="dz-aside__card">
            <FollowButton dossier={d} />
            <dl className="dz-keyfacts">
              <div>
                <dt>
                  <Term id="procedure-reference">Procedure</Term>
                </dt>
                <dd className="mono">{d.ref}</dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd>
                  {d.type === 'COD' ? <Term id="olp">{d.type_label}</Term> : d.type_label}
                  {d.instrument && d.instrument !== 'other' && (
                    <>
                      {' · '}
                      {INSTRUMENT_LABEL[d.instrument]}
                      {!d.acts.some((a) => a.act_type === d.instrument) && ' (as proposed)'}
                    </>
                  )}
                </dd>
              </div>
              {d.started && (
                <div>
                  <dt>Proposed</dt>
                  <dd>{formatDate(d.started)}</dd>
                </div>
              )}
              {d.adopted && (
                <div>
                  <dt>Adopted</dt>
                  <dd>{formatDate(d.adopted)}</dd>
                </div>
              )}
              {d.published && (
                <div>
                  <dt>Published in the Official Journal</dt>
                  <dd>{formatDate(d.published)}</dd>
                </div>
              )}
              {d.last_event && (
                <div>
                  <dt>Latest recorded step</dt>
                  <dd>{formatDate(d.last_event)}</dd>
                </div>
              )}
              {primaryAct && (
                <div>
                  <dt>
                    <Term id="celex">CELEX</Term>
                  </dt>
                  <dd>
                    <ExtLink href={primaryAct.eurlex_url || EURLEX_CELEX(primaryAct.celex)}>
                      <span className="mono">{primaryAct.celex}</span>
                    </ExtLink>
                  </dd>
                </div>
              )}
              {d.topics.length > 0 && (
                <div>
                  <dt>Topics</dt>
                  <dd>
                    <ul className="dz-topics">
                      {d.topics.map((t) => (
                        <li key={t}>
                          <Link className="tag" to={`/legislation?topic=${encodeURIComponent(t)}`}>
                            {topicLabel(t)}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </dd>
                </div>
              )}
            </dl>
            <ul className="dz-official-links">
              {d.oeil_url && (
                <li>
                  <ExtLink href={d.oeil_url}>Procedure file (OEIL)</ExtLink>
                </li>
              )}
              {primaryAct && (
                <li>
                  <ExtLink href={primaryAct.eurlex_url || EURLEX_CELEX(primaryAct.celex)}>Legal text (EUR-Lex)</ExtLink>
                </li>
              )}
            </ul>
          </div>
          <nav className="dz-toc" aria-label="On this page">
            <p className="dz-toc__title">On this page</p>
            <ul>
              {nav.map((n) => (
                <li key={n.id}>
                  <a href={`#${n.id}`}>{n.label}</a>
                </li>
              ))}
            </ul>
          </nav>
        </aside>

        <div className="dz-main">
          {active && <WhereIsIt d={d} today={today} />}
          <Timeline events={d.timeline} changes={d.changes ?? []} today={today} eurlexOnly={d.eurlex_only} oeilUrl={d.oeil_url} />
          <ParliamentVotes votes={d.ep_votes} oeilUrl={d.oeil_url} split={splitParts(d)} approval={d.ep_approval_without_vote} />
          <CouncilVotes votes={d.council_votes} meta={meta} split={splitParts(d)} timeline={d.timeline} adopted={d.adopted} />
          <NationalApplication d={d} today={today} />
          <DossierDetails d={d} />
        </div>
      </div>
    </article>
  );
}

/**
 * /legislation/<CELEX>: links to related acts use the act's CELEX number. Open the legislative file that adopted
 * the act when it is in the dataset; otherwise say so and link to the act on EUR-Lex.
 */
function ActByCelex({ celex }: { celex: string }) {
  const index = useData<DossierSummary[]>('dossiers/index.json');
  const owner = index.data?.find((d) => d.celex.includes(celex));
  useDocumentTitle(owner ? 'Legislation' : `Legal act ${celex}`);
  if (owner) return <Navigate to={dossierPath(owner.id)} replace />;
  if (index.loading)
    return (
      <div className="container page">
        <Loading label="Loading legislative files…" />
      </div>
    );
  return (
    <div className="container page">
      <PageHeader
        eyebrow="Legal act"
        title={<>Legal act <span className="mono">{celex}</span></>}
        lead="This act is not one of the legislative files covered by this site. It may have been adopted under a procedure the site does not cover, such as a delegated or implementing act. Its official text and details are on EUR-Lex."
      />
      <p>
        <ExtLink href={EURLEX_CELEX(celex)}>Open act {celex} on EUR-Lex</ExtLink>
      </p>
      <p>
        <Link to="/legislation">Browse legislation</Link> · <Link to="/about#coverage">What’s covered</Link>
      </p>
    </div>
  );
}

/** Official titles can run to several hundred characters: show the first lines, expandable on request. */
function OfficialTitle({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 180;
  return (
    <div className="dz-official-wrap">
      <p className={`dz-official${long && !open ? ' is-clamped' : ''}`} id="official-title">
        <span className="dz-official__label">Official title: </span>
        {text}
      </p>
      {long && (
        <button type="button" className="lx-linkbtn" aria-expanded={open} aria-controls="official-title" onClick={() => setOpen((o) => !o)}>
          {open ? 'Show less' : 'Show full official title'}
        </button>
      )}
    </div>
  );
}
