import { useCallback, useId, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { ActivityItem, DossierSummary } from '../types/data';
import { DATA_BASE, useData } from '../lib/data';
import { formatDate, formatNumber } from '../lib/format';
import { shownParam, useParamState } from '../lib/urlState';
import { EmptyState, ErrorState, Loading, LookupNotice, PageHeader } from '../components/ui';
import { useDocumentTitle, useTopics } from '../features/legislation/labels';
import { ChangeItem } from '../features/changes/ChangeItem';
import {
  CHANGE_KINDS,
  OTHER,
  byWeek,
  changesOf,
  countLabel,
  formatDays,
  formatRange,
  kindKeys,
  matches,
  sundayOf,
  type Change,
  type WeekGroup,
} from '../features/changes/changes';
import '../features/legislation/common.css';
import '../features/legislation/legislation.css';
import '../features/changes/changes.css';

/** Weeks shown at first, and added by "Show earlier weeks" (the address keeps how many: `?weeks=`). */
const WEEKS = 4;
const OTHER_LABEL = 'Other files, and votes on other texts';

const feedHref = (slug: string | null) => `${DATA_BASE}feeds/${slug ? `${encodeURIComponent(slug)}.xml` : 'updates.xml'}`;

/** What a week's changes are: recorded that week (by which refreshes), or steps dated that week whose appearance in the
 * records was not tracked. */
function weekNote(w: WeekGroup): string {
  const recorded = [...new Set(w.changes.flatMap((c) => (c.detectedAt ? [c.detectedAt.slice(0, 10)] : [])))].sort();
  const untracked = w.changes.length - w.tracked;
  const parts: string[] = [];
  if (w.tracked)
    parts.push(
      `${untracked ? `${formatNumber(w.tracked)} ` : ''}recorded by our data refresh${recorded.length > 1 ? 'es' : ''} of ${formatDays(recorded)}`,
    );
  if (untracked)
    parts.push(
      `${w.tracked ? `${formatNumber(untracked)} ` : ''}dated this week, already in the official records when we began recording changes (when they appeared there was not tracked)`,
    );
  const s = parts.join('; ');
  return s[0].toUpperCase() + s.slice(1) + '.';
}

export default function Changes() {
  const [params, patch] = useParamState();
  const topic = params.get('topic') || null;
  const kind = params.get('kind') && CHANGE_KINDS[params.get('kind')!] ? params.get('kind') : null;
  const weeksShown = shownParam(params, 'weeks', WEEKS, 200);
  const activity = useData<ActivityItem[]>('activity.json');
  const index = useData<DossierSummary[]>('dossiers/index.json');
  const topicsData = useTopics();
  const topics = topicsData.topics;
  const ids = useId();

  const all = useMemo(() => changesOf(activity.data ?? []), [activity.data]);
  const files = useMemo(() => new Map((index.data ?? []).map((d) => [d.id, d])), [index.data]);
  // the topics of a change's file, from the file list; without it (not loaded) no change is put under a topic
  const topicsOf = useCallback((id: string | null) => (id ? (files.get(id)?.topics ?? []) : []), [files]);
  const order = useMemo(() => topics.map((t) => t.slug), [topics]);
  const topicLabel = (slug: string) => (slug === OTHER ? OTHER_LABEL : (topics.find((t) => t.slug === slug)?.label ?? slug));
  const currentTopic = topic ? topicLabel(topic) : null;
  const heading = currentTopic && topic !== OTHER ? `What changed: ${currentTopic}` : 'What changed';
  useDocumentTitle(`${heading} – Legislation`);

  const selected = useMemo(() => all.filter((c) => matches(c, topicsOf, topic, kind)), [all, topicsOf, topic, kind]);
  const weeks = useMemo(() => byWeek(selected, topicsOf, order), [selected, topicsOf, order]);
  const shown = weeks.slice(0, weeksShown);
  // facet counts: each filter counted with the other one applied
  const topicCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of all.filter((x) => matches(x, topicsOf, null, kind))) {
      const ts = topicsOf(c.dossierId).filter((t) => order.includes(t));
      for (const t of ts.length ? ts : [OTHER]) m.set(t, (m.get(t) ?? 0) + 1);
    }
    return m;
  }, [all, topicsOf, kind, order]);
  const kindCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of all.filter((x) => matches(x, topicsOf, topic, null))) for (const k of kindKeys(c)) m.set(k, (m.get(k) ?? 0) + 1);
    return m;
  }, [all, topicsOf, topic]);
  const firstRecorded = useMemo(
    () => all.reduce<string | null>((m, c) => (c.detectedAt && (!m || c.detectedAt < m) ? c.detectedAt : m), null),
    [all],
  );

  const set = (p: Record<string, string | null>) => patch({ ...p, weeks: null });
  const loading = activity.loading || (index.loading && !index.data);
  const fileTitle = (c: Change) => (c.dossierId ? (files.get(c.dossierId)?.title ?? null) : null);

  return (
    <div className="container page chg">
      <nav className="chg-crumbs" aria-label="Breadcrumb">
        <ol>
          <li>
            <Link to="/legislation">Legislation</Link>
          </li>
          <li aria-current="page">What changed</li>
        </ol>
      </nav>
      <PageHeader
        eyebrow="Legislation"
        title={heading}
        lead="Steps, votes and status changes on EU legislative files, by the week our data refresh first recorded them. Each one links its file and the official record it comes from."
      >
        <p className="meta chg__scope">
          {firstRecorded ? (
            <>
              Changes are recorded when the data is refreshed (twice a week), since {formatDate(firstRecorded)}. Steps already in
              the records before then are listed by their own date.
            </>
          ) : (
            <>Steps are listed by their own date: when they appeared in the official records is not tracked.</>
          )}{' '}
          A status change is listed with the step that gave the file its status. <Link to="/about#coverage">What’s covered</Link>
        </p>
        <p className="chg__feeds">
          Follow in a feed reader: <a href={feedHref(null)}>all changes (Atom)</a>
          {topic && topic !== OTHER && (
            <>
              {' '}
              · <a href={feedHref(topic)}>{currentTopic} (Atom)</a>
            </>
          )}
          {' '}
          · each file’s own feed is on its page
        </p>
      </PageHeader>

      <form className="lx-filters chg__filters" aria-label="Filter the changes" onSubmit={(e) => e.preventDefault()}>
        <div className="lx-field">
          <label htmlFor={`${ids}-topic`}>Topic</label>
          <select id={`${ids}-topic`} className="select lx-select" value={topic ?? ''} onChange={(e) => set({ topic: e.target.value || null })}>
            <option value="">All topics</option>
            {topics.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.label} ({formatNumber(topicCounts.get(t.slug) ?? 0)})
              </option>
            ))}
            <option value={OTHER}>
              {OTHER_LABEL} ({formatNumber(topicCounts.get(OTHER) ?? 0)})
            </option>
          </select>
        </div>
        <div className="lx-field">
          <label htmlFor={`${ids}-kind`}>Kind of change</label>
          <select id={`${ids}-kind`} className="select lx-select" value={kind ?? ''} onChange={(e) => set({ kind: e.target.value || null })}>
            <option value="">All kinds</option>
            {Object.entries(CHANGE_KINDS)
              .filter(([k]) => (kindCounts.get(k) ?? 0) > 0 || kind === k)
              .map(([k, def]) => (
                <option key={k} value={k}>
                  {def.label} ({formatNumber(kindCounts.get(k) ?? 0)})
                </option>
              ))}
          </select>
        </div>
      </form>

      {loading && <Loading label="Loading the recorded changes…" />}
      {activity.error && <ErrorState error={activity.error} title="The recorded changes could not be loaded" />}
      <LookupNotice failed={topicsData.failed} what="Topic names" />
      {index.error && (
        <div className="state state--error state--note" role="alert">
          The list of legislative files could not be loaded, so changes are not grouped by topic. Reload the page to try again.
        </div>
      )}

      {activity.data && !loading && (
        <>
          <p className="chg__count" role="status">
            <strong>{formatNumber(selected.length)}</strong> {selected.length === 1 ? 'change' : 'changes'}
            {weeks.length > 0 && (
              <>
                {' '}
                in {formatNumber(weeks.length)} {weeks.length === 1 ? 'week' : 'weeks'}
              </>
            )}
            {(topic || kind) && (
              <>
                {' '}
                ·{' '}
                <button type="button" className="lx-linkbtn" onClick={() => set({ topic: null, kind: null })}>
                  Show all changes
                </button>
              </>
            )}
          </p>

          {selected.length === 0 ? (
            <EmptyState title="No changes recorded for these filters">
              <p>Try another topic or kind of change. Changes are recorded when the data is refreshed, twice a week.</p>
            </EmptyState>
          ) : (
            shown.map((w) => (
              <section key={w.week} className="chg-week" aria-labelledby={`${ids}-w-${w.week}`}>
                <h2 id={`${ids}-w-${w.week}`} className="section-title chg-week__title">
                  Week of {formatDate(w.week, true)}{' '}
                  <span className="chg-week__range">({formatRange(w.week, sundayOf(w.week))})</span>
                </h2>
                <p className="meta chg-week__note">
                  {kind || topic
                    ? `${formatNumber(w.changes.length)} ${w.changes.length === 1 ? 'change matches' : 'changes match'} the filters. `
                    : `${countSummary(w.changes)}. `}
                  {weekNote(w)}
                </p>
                {/* one topic: its changes in one list; otherwise under each topic of their file */}
                {topic || index.error ? (
                  <ol className="ch-list">
                    {w.changes.map((c) => (
                      <ChangeItem key={c.id} c={c} fileTitle={fileTitle(c)} />
                    ))}
                  </ol>
                ) : (
                  w.topics.map((t) => (
                    // named by its week as well as its topic: each topic recurs from week to week
                    <section key={t.slug} className="chg-topic" aria-labelledby={`${ids}-w-${w.week}-${t.slug} ${ids}-w-${w.week}`}>
                      <h3 id={`${ids}-w-${w.week}-${t.slug}`} className="chg-topic__title">
                        {topicLabel(t.slug)} <span className="chg-topic__n">{formatNumber(t.changes.length)}</span>
                      </h3>
                      <p className="chg-topic__links">
                        {t.slug !== OTHER && (
                          <>
                            <Link to={`/legislation/changes?topic=${encodeURIComponent(t.slug)}`}>Only this topic</Link> ·{' '}
                            <a href={feedHref(t.slug)}>Atom feed</a>
                          </>
                        )}
                      </p>
                      <ol className="ch-list">
                        {t.changes.map((c) => (
                          <ChangeItem key={c.id} c={c} fileTitle={fileTitle(c)} />
                        ))}
                      </ol>
                    </section>
                  ))
                )}
              </section>
            ))
          )}
          {weeks.length > shown.length && (
            <div className="lx-more-results">
              <p className="meta">
                Showing {formatNumber(shown.length)} of {formatNumber(weeks.length)} weeks
              </p>
              <button type="button" className="btn" onClick={() => patch({ weeks: String(weeksShown + WEEKS) })}>
                Show {Math.min(WEEKS, weeks.length - shown.length) === 1 ? 'the earliest week' : `${formatNumber(Math.min(WEEKS, weeks.length - shown.length))} earlier weeks`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** "37 changes: 6 status changes, 20 procedural steps, …" (a change counts once for each of its kinds). */
function countSummary(cs: Change[]): string {
  const counts = Object.keys(CHANGE_KINDS)
    .map((k) => [k, cs.filter((c) => kindKeys(c).includes(k)).length] as const)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => countLabel(k, n));
  return `${formatNumber(cs.length)} ${cs.length === 1 ? 'change' : 'changes'}${counts.length > 1 ? `: ${counts.join(', ')}` : ''}`;
}
