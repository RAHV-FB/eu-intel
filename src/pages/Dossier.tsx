import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { DossierDetail, Meta, Topic } from '../types/data';
import { NotFoundError, useData } from '../lib/data';
import { formatDate } from '../lib/format';
import { changeSince, getWatchlist, markSeen, type ChangeInfo } from '../lib/watchlist';
import { ErrorState, ExtLink, Loading, NotFound, Term } from '../components/ui';
import { ACTIVE_STAGES, EURLEX_CELEX, INSTRUMENT_LABEL, isSameTitle, useDocumentTitle } from '../features/legislation/labels';
import { todayISO } from '../features/legislation/explorer';
import { DossierSummaryPanel } from '../features/legislation/dossier/Summary';
import { WhereIsIt } from '../features/legislation/dossier/WhereIsIt';
import { Timeline } from '../features/legislation/dossier/Timeline';
import { CouncilVotes, ParliamentVotes } from '../features/legislation/dossier/Votes';
import { NationalApplication } from '../features/legislation/dossier/Application';
import { DossierDetails } from '../features/legislation/dossier/Details';
import { FollowButton } from '../features/watchlist/FollowButton';
import '../features/legislation/common.css';
import '../features/legislation/dossier/dossier.css';

export default function Dossier() {
  const { id = '' } = useParams();
  const valid = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(id);
  const { data: d, error, loading } = useData<DossierDetail>(valid ? `dossiers/${id}.json` : null);
  const { data: meta } = useData<Meta>('meta.json');
  const { data: topics } = useData<Topic[]>('topics.json');
  useDocumentTitle(d?.title ?? (error ? 'Legislative file not found' : 'Legislation'));

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

  if (!valid || error instanceof NotFoundError) return <NotFound what="legislative file" />;
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
  const topicLabel = (slug: string) => topics?.find((t) => t.slug === slug)?.label ?? slug;
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

      <header className="dz-head" id="summary">
        <h1 className="dz-title">{d.title}</h1>
        {!isSameTitle(d.title, d.official_title) && (
          <p className="dz-official">
            <span className="visually-hidden">Official title: </span>
            {d.official_title}
          </p>
        )}
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
                  {d.instrument && d.instrument !== 'other' && <> · {INSTRUMENT_LABEL[d.instrument]}</>}
                </dd>
              </div>
              <div>
                <dt>Proposed</dt>
                <dd>{d.started ? formatDate(d.started) : '—'}</dd>
              </div>
              <div>
                <dt>Latest recorded step</dt>
                <dd>{d.last_event ? formatDate(d.last_event) : '—'}</dd>
              </div>
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
              <li>
                <ExtLink href={d.oeil_url}>Procedure file (OEIL)</ExtLink>
              </li>
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
          <Timeline events={d.timeline} changes={d.changes ?? []} today={today} />
          <ParliamentVotes votes={d.ep_votes} />
          <CouncilVotes votes={d.council_votes} meta={meta} />
          <NationalApplication d={d} today={today} />
          <DossierDetails d={d} />
        </div>
      </div>
    </article>
  );
}
