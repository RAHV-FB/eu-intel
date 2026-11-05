import { useId, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { AppliesData } from '../types/data';
import { useData } from '../lib/data';
import { COUNTRY_NAMES, countryName, formatNumber } from '../lib/format';
import { useParamState } from '../lib/urlState';
import { EmptyState, ErrorState, Loading, LookupNotice, PageHeader } from '../components/ui';
import { useFeedLink } from '../components/useFeedLink';
import { useDocumentTitle, useTopics } from '../features/legislation/labels';
import { todayISO } from '../features/legislation/explorer';
import { AppliesItem } from '../features/applies/AppliesItem';
import { WINDOWS, byMonth, concerns, feedPath, inWindow, monthLabel, windowKey } from '../features/applies/applies';
import '../features/legislation/common.css';
import '../features/legislation/legislation.css';
import '../features/changes/changes.css';
import '../features/applies/applies.css';

/** The Member States (not the United Kingdom, which COUNTRY_NAMES also names for older records), by name. */
const MEMBER_STATES = Object.keys(COUNTRY_NAMES)
  .filter((c) => c !== 'GB')
  .sort((a, b) => countryName(a).localeCompare(countryName(b)));

/** The subscription links of one selection: its Atom feed (the next 90 days) and its calendar (every date). */
function Subscribe({ label, topic, country }: { label: string; topic?: string | null; country?: string | null }) {
  return (
    <>
      {label}: <a href={feedPath({ topic, country }, 'xml')}>Atom feed</a>,{' '}
      <a href={feedPath({ topic, country }, 'ics')}>calendar (.ics)</a>
    </>
  );
}

export default function Applies() {
  const [params, patch] = useParamState();
  const when = windowKey(params.get('when'));
  const topicParam = params.get('topic') || null;
  const countryParam = (params.get('country') || '').toUpperCase() || null;
  const country = countryParam && MEMBER_STATES.includes(countryParam) ? countryParam : null;
  const data = useData<AppliesData>('applies.json');
  const topicsData = useTopics();
  const topics = topicsData.topics;
  const topic = topicParam && (topics.some((t) => t.slug === topicParam) || !topics.length) ? topicParam : null;
  const ids = useId();
  // the dates are compared with the reader's date: the data is rebuilt weekly and read for a week or more after
  const today = todayISO();

  const topicLabel = (slug: string) => topics.find((t) => t.slug === slug)?.label ?? slug;
  const currentTopic = topic ? topicLabel(topic) : null;
  const heading = `When new rules apply${currentTopic ? `: ${currentTopic}` : ''}${country ? ` in ${countryName(country)}` : ''}`;
  useDocumentTitle(`${heading} – Legislation`);
  // the page's own feed, as its prerendered page announces the one of every date
  const feedScope = country ? countryName(country) : currentTopic;
  useFeedLink(feedPath({ topic: country ? null : topic, country }, 'xml'), `When new rules apply${feedScope ? `: ${feedScope}` : ''} (Atom)`);

  const rows = useMemo(() => data.data?.rows ?? [], [data.data]);
  const matchesTopic = (r: (typeof rows)[number], t: string | null) => !t || r.topics.includes(t);
  const matchesCountry = (r: (typeof rows)[number], c: string | null) => !c || concerns(r, c);
  const selected = rows.filter((r) => inWindow(r, when, today) && matchesTopic(r, topic) && matchesCountry(r, country));
  const groups = byMonth(selected, when === 'past');
  const files = new Set(selected.map((r) => r.dossier_id)).size;
  // each filter counted with the other two applied
  const windowCounts = new Map(WINDOWS.map((w) => [w.key, rows.filter((r) => inWindow(r, w.key, today) && matchesTopic(r, topic) && matchesCountry(r, country)).length]));
  const inWin = rows.filter((r) => inWindow(r, when, today));
  const topicCounts = new Map(topics.map((t) => [t.slug, inWin.filter((r) => matchesTopic(r, t.slug) && matchesCountry(r, country)).length]));
  const countryCounts = new Map(MEMBER_STATES.map((c) => [c, inWin.filter((r) => matchesTopic(r, topic) && matchesCountry(r, c)).length]));
  const phrase = WINDOWS.find((w) => w.key === when)!.phrase;

  const set = (p: Record<string, string | null>) => patch(p);
  const filtered = !!(topic || country || when !== '90');

  return (
    <div className="container page chg ap-page">
      <nav className="chg-crumbs" aria-label="Breadcrumb">
        <ol>
          <li>
            <Link to="/legislation">Legislation</Link>
          </li>
          <li aria-current="page">When new rules apply</li>
        </ol>
      </nav>
      <PageHeader
        eyebrow="Legislation"
        title={heading}
        lead="Dates set in EU law from which rules start to apply: entry into force, the application of an act or some of its provisions, deadlines to transpose a directive, and the dates national measures apply from."
      >
        <p className="meta chg__scope">
          The dates are fixed in the acts, or in the acts amending them, as EUR-Lex records them or as we checked them
          against the act’s text: unlike the steps the Council and Parliament schedule, a date changes only if a later act
          changes it. <Link to="/about#applies">How this list is made</Link>
        </p>
        <p className="chg__feeds">
          <Subscribe label="Subscribe to every date" />
          {topic && (
            <>
              ; <Subscribe label={`to ${currentTopic}`} topic={topic} />
            </>
          )}
          {country && (
            <>
              ; <Subscribe label={`to the dates in ${countryName(country)}`} country={country} />
            </>
          )}
        </p>
      </PageHeader>

      <form className="lx-filters ap__filters" aria-label="Filter the dates" onSubmit={(e) => e.preventDefault()}>
        <div className="lx-field">
          <label htmlFor={`${ids}-when`}>When</label>
          <select id={`${ids}-when`} className="select lx-select" value={when} onChange={(e) => set({ when: e.target.value === '90' ? null : e.target.value })}>
            {WINDOWS.map((w) => (
              <option key={w.key} value={w.key}>
                {w.label} ({formatNumber(windowCounts.get(w.key) ?? 0)})
              </option>
            ))}
          </select>
        </div>
        <div className="lx-field">
          <label htmlFor={`${ids}-topic`}>Topic</label>
          <select id={`${ids}-topic`} className="select lx-select" value={topic ?? ''} onChange={(e) => set({ topic: e.target.value || null })}>
            <option value="">All topics</option>
            {topics.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.label} ({formatNumber(topicCounts.get(t.slug) ?? 0)})
              </option>
            ))}
          </select>
        </div>
        <div className="lx-field">
          <label htmlFor={`${ids}-country`}>Member State</label>
          <select id={`${ids}-country`} className="select lx-select" value={country ?? ''} onChange={(e) => set({ country: e.target.value || null })}>
            <option value="">All Member States</option>
            {MEMBER_STATES.map((c) => (
              <option key={c} value={c}>
                {countryName(c)} ({formatNumber(countryCounts.get(c) ?? 0)})
              </option>
            ))}
          </select>
        </div>
      </form>

      {data.loading && <Loading label="Loading the dates…" />}
      {data.error && <ErrorState error={data.error} title="The dates could not be loaded" />}
      <LookupNotice failed={topicsData.failed} what="Topic names" />

      {data.data && (
        <>
          <p className="chg__count" role="status">
            <strong>{formatNumber(selected.length)}</strong> {selected.length === 1 ? 'date' : 'dates'} {phrase}
            {files > 0 && (
              <>
                , on {formatNumber(files)} {files === 1 ? 'file' : 'files'}
              </>
            )}
            {filtered && (
              <>
                {' '}
                ·{' '}
                <button type="button" className="lx-linkbtn" onClick={() => set({ when: null, topic: null, country: null })}>
                  Next 90 days, every topic and Member State
                </button>
              </>
            )}
          </p>
          {country && (
            <p className="meta ap__country-note">
              Dates of the acts that bind {countryName(country)}, and of those for which our data do not say whether they do
              (each says so under “Where”).
            </p>
          )}
          {selected.length === 0 ? (
            <EmptyState title={`No dates ${phrase} for these filters`}>
              <p>Try a longer period, another topic or another Member State.</p>
            </EmptyState>
          ) : (
            groups.map((g) => (
              <section key={g.month} className="chg-week" aria-labelledby={`${ids}-m-${g.month}`}>
                <h2 id={`${ids}-m-${g.month}`} className="section-title chg-week__title">
                  {monthLabel(g.month)}{' '}
                  <span className="chg-week__range">
                    ({formatNumber(g.rows.length)} {g.rows.length === 1 ? 'date' : 'dates'})
                  </span>
                </h2>
                <ol className="ch-list">
                  {g.rows.map((r) => (
                    <AppliesItem key={r.id} r={r} today={today} topicLabel={topicLabel} />
                  ))}
                </ol>
              </section>
            ))
          )}
          <section className="ap-sub" aria-labelledby={`${ids}-sub`}>
            <h2 id={`${ids}-sub`} className="ap-sub__title">
              Feeds and calendars
            </h2>
            <p className="meta ap-sub__note">
              An Atom feed lists the dates of the next 90 days, so a feed reader shows each date as it comes within 90 days. A
              calendar lists every date ahead, and those of the last month. To keep a calendar up to date, add its address to
              your calendar app as a subscription; opening the file only imports the dates as they are today. There is a feed
              and a calendar for every date, for each topic and for each Member State
              {topic && country ? ', not for a topic and a Member State together' : ''}.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
