import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { DossierSummary, LegalInstrument, Meta, Topic } from '../types/data';
import { useData, DATA_BASE } from '../lib/data';
import { formatNumber } from '../lib/format';
import { legislationScope } from '../lib/scope';
import { loadSearch, type SearchEngine } from '../lib/search';
import { useWatchlist } from '../lib/watchlist';
import { EmptyState, ErrorState, Loading, PageHeader } from '../components/ui';
import { useMediaQuery } from '../components/useMediaQuery';
import {
  INSTRUMENT_LABEL,
  STAGE_GROUPS,
  STAGE_LABEL,
  STAGE_ORDER,
  dossierYear,
  stageFilterLabel,
  useDocumentTitle,
} from '../features/legislation/labels';
import {
  PAGE_SIZE,
  SORT_LABEL,
  applyFilters,
  buildHaystacks,
  countBy,
  keywordScores,
  makePredicates,
  NO_TOPIC,
  readState,
  sortRows,
  todayISO,
  type ExplorerState,
  type SortKey,
} from '../features/legislation/explorer';
import { DossierRow } from '../features/legislation/DossierRow';
import '../features/legislation/common.css';
import '../features/legislation/legislation.css';

const INSTRUMENTS: LegalInstrument[] = ['regulation', 'directive', 'decision', 'recommendation', 'other'];
const NO_TOPIC_LABEL = 'No topic assigned';

export default function Legislation() {
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => readState(params), [params]);
  const index = useData<DossierSummary[]>('dossiers/index.json');
  const topicsData = useData<Topic[]>('topics.json');
  const meta = useData<Meta>('meta.json');
  const topics = topicsData.data ?? [];
  const topicLabel = (slug: string) => (slug === NO_TOPIC ? NO_TOPIC_LABEL : (topics.find((t) => t.slug === slug)?.label ?? slug));
  const watch = useWatchlist();
  const followed = useMemo(() => new Set(watch.map((w) => w.id)), [watch]);
  const today = todayISO();

  const noTopic = state.topic === NO_TOPIC;
  const currentTopic = state.topic ? topics.find((t) => t.slug === state.topic) : undefined;
  useDocumentTitle(currentTopic ? `${currentTopic.label} – Legislation` : noTopic ? `${NO_TOPIC_LABEL} – Legislation` : 'Legislation');

  // Phones: only the keyword box stays open, so the first results are near the top of the screen.
  const narrow = useMediaQuery('(max-width: 39.99rem)');
  const [filtersOpen, setFiltersOpen] = useState(false);

  // ---- URL updates
  const update = (patch: Partial<Record<keyof ExplorerState, string | null>>, opts: { keepShow?: boolean; replace?: boolean } = {}) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === '') next.delete(k);
      else next.set(k, v);
    }
    if (!opts.keepShow && !('show' in patch)) next.delete('show');
    setParams(next, { replace: opts.replace ?? false });
  };

  // ---- keyword input: local state, debounced into the URL
  const [qInput, setQInput] = useState(state.q);
  const lastWritten = useRef(state.q);
  useEffect(() => {
    if (state.q !== lastWritten.current) {
      lastWritten.current = state.q;
      setQInput(state.q);
    }
  }, [state.q]);
  useEffect(() => {
    if (qInput === lastWritten.current) return;
    const t = setTimeout(() => {
      lastWritten.current = qInput;
      const next = new URLSearchParams(params);
      if (qInput.trim()) next.set('q', qInput);
      else next.delete('q');
      // switching between "has a query" and "no query" changes the natural default sort
      if (next.get('sort') === 'relevance' && !qInput.trim()) next.delete('sort');
      next.delete('show');
      setParams(next, { replace: true });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qInput]);

  // ---- search engine for ranking (loaded only when there is a query)
  const [engine, setEngine] = useState<SearchEngine | null>(null);
  const hasQuery = !!state.q.trim();
  useEffect(() => {
    if (hasQuery && !engine) loadSearch().then(setEngine, () => undefined);
  }, [hasQuery, engine]);

  const rows = index.data ?? [];
  const haystacks = useMemo(() => buildHaystacks(rows), [rows]);

  const { matched, scores } = useMemo(() => {
    if (!hasQuery) return { matched: rows, scores: new Map<string, number>() };
    const keyword = keywordScores(rows, haystacks, engine, state.q);
    return { matched: rows.filter((d) => keyword.has(d.id)), scores: keyword };
  }, [rows, haystacks, engine, state.q, hasQuery]);

  const preds = useMemo(() => makePredicates(state), [state]);
  const filtered = useMemo(() => applyFilters(matched, preds), [matched, preds]);
  const sorted = useMemo(() => sortRows(filtered, state.sort, scores, today), [filtered, state.sort, scores, today]);

  // ---- facet counts (each facet counted with all *other* filters applied)
  const facets = useMemo(() => {
    const topic = countBy(applyFilters(matched, preds, 'topic'), (d) => (d.topics.length ? d.topics : NO_TOPIC));
    const stageRows = applyFilters(matched, preds, 'stage');
    const stage = countBy(stageRows, (d) => d.stage);
    const type = countBy(applyFilters(matched, preds, 'type'), (d) => d.type);
    const instrument = countBy(applyFilters(matched, preds, 'instrument'), (d) => d.instrument ?? null);
    const year = countBy(applyFilters(matched, preds, 'year'), (d) => dossierYear(d));
    const blocked = applyFilters(matched, preds, 'blocked').filter((d) => d.officially_blocked).length;
    const groups: Record<string, number> = {};
    for (const [g, def] of Object.entries(STAGE_GROUPS)) groups[g] = def.stages.reduce((n, s) => n + (stage.get(s) ?? 0), 0);
    return { topic, stage, groups, type, instrument, year, blocked };
  }, [matched, preds]);

  const typeLabels = useMemo(() => {
    const m = new Map<string, string>();
    for (const d of rows) if (!m.has(d.type)) m.set(d.type, d.type_label || d.type);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);
  const years = useMemo(() => [...new Set(rows.map(dossierYear).filter((y): y is number => !!y))].sort((a, b) => b - a), [rows]);
  const hasAdopted = rows.some((d) => d.adopted);
  const hasNextDates = rows.some((d) => d.next_date);
  const anyBlocked = rows.some((d) => d.officially_blocked);

  const advancedActive = !!(state.type || state.instrument || state.year || state.blocked);
  const anyFilter = !!(state.topic || state.stage || advancedActive || hasQuery);
  const activeFilters = [state.topic, state.stage, state.type, state.instrument, state.year, state.blocked || null].filter(Boolean).length;
  const scopeText = legislationScope(meta.data?.scope, true);
  const visible = sorted.slice(0, state.show);

  // "Show more": move keyboard focus to the first newly revealed result.
  const listRef = useRef<HTMLOListElement>(null);
  const focusFrom = useRef<number | null>(null);
  useEffect(() => {
    const i = focusFrom.current;
    if (i == null) return;
    focusFrom.current = null;
    listRef.current?.querySelectorAll<HTMLAnchorElement>('.drow__title a')[i]?.focus();
  }, [visible.length]);

  const ids = useId();
  const [copied, setCopied] = useState(false);
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  };

  const chips: { key: string; label: string; clear: () => void }[] = [];
  if (hasQuery) chips.push({ key: 'q', label: `“${state.q.trim()}”`, clear: () => { setQInput(''); update({ q: null, sort: state.sort === 'relevance' ? null : state.sort }); } });
  if (state.topic) chips.push({ key: 'topic', label: `Topic: ${topicLabel(state.topic)}`, clear: () => update({ topic: null }) });
  if (state.stage) chips.push({ key: 'stage', label: `Status: ${stageFilterLabel(state.stage)}`, clear: () => update({ stage: null }) });
  if (state.type) chips.push({ key: 'type', label: `Procedure: ${typeLabels.find(([t]) => t === state.type)?.[1] ?? state.type}`, clear: () => update({ type: null }) });
  if (state.instrument) chips.push({ key: 'instrument', label: `Act: ${INSTRUMENT_LABEL[state.instrument] ?? state.instrument}`, clear: () => update({ instrument: null }) });
  if (state.year) chips.push({ key: 'year', label: `Proposed in ${state.year}`, clear: () => update({ year: null }) });
  if (state.blocked) chips.push({ key: 'blocked', label: 'Officially blocked', clear: () => update({ blocked: null }) });

  const clearAll = () => {
    setQInput('');
    lastWritten.current = '';
    setParams(new URLSearchParams(), { replace: false });
  };

  return (
    <div className="container page lx">
      <PageHeader
        eyebrow={currentTopic || noTopic ? 'Topic' : 'Legislation'}
        title={currentTopic ? currentTopic.label : noTopic ? 'Files without a topic' : 'Legislation'}
        lead={
          noTopic
            ? 'Legislative files that none of the ten topics covers. Most have Parliament subject codes outside them (regional and cohesion funds, the EU’s institutions, development cooperation, external relations, culture); a few have no Parliament record of their own (split procedures, laws known only from EUR-Lex).'
            : currentTopic?.description ||
              'Search and filter EU legislative files — from Commission proposals to laws in force. Status and dates come from the European Parliament’s Legislative Observatory and EUR-Lex.'
        }
      >
        {(scopeText || currentTopic) && (
          <p className="meta lx-scope">
            {currentTopic && (
              <>
                Topics follow Parliament’s subject codes, so files whose codes fall outside the ten topics are not listed here (
                <Link to={`/legislation?topic=${NO_TOPIC}`}>files without a topic</Link>).{' '}
              </>
            )}
            {scopeText} <Link to="/about#coverage">What’s covered</Link>
          </p>
        )}
      </PageHeader>

      <form className="lx-filters" role="search" aria-label="Filter legislation" onSubmit={(e) => e.preventDefault()}>
        <div className="lx-field lx-filters__q">
          <label htmlFor={`${ids}-q`}>Keyword, title or reference</label>
          <input
            id={`${ids}-q`}
            className="input lx-input"
            type="search"
            value={qInput}
            placeholder="e.g. artificial intelligence, 2021/0106(COD), 32024R1689"
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setQInput(e.target.value)}
          />
        </div>
        {narrow && (
          <button
            type="button"
            className="btn lx-filters__toggle"
            aria-expanded={filtersOpen}
            aria-controls={`${ids}-rest`}
            onClick={() => setFiltersOpen((o) => !o)}
          >
            {filtersOpen ? 'Hide filters and sorting' : 'Filters and sorting'}
            {activeFilters > 0 && <span className="lx-more__count"> ({activeFilters} active)</span>}
          </button>
        )}
        <div id={`${ids}-rest`} className="lx-filters__rest" hidden={narrow && !filtersOpen}>
          <div className="lx-field">
            <label htmlFor={`${ids}-topic`}>Topic</label>
            <select id={`${ids}-topic`} className="select lx-select" value={state.topic ?? ''} onChange={(e) => update({ topic: e.target.value || null })}>
              <option value="">All topics</option>
              {topics.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.label} ({formatNumber(facets.topic.get(t.slug) ?? 0)})
                </option>
              ))}
              {(rows.some((d) => !d.topics.length) || noTopic) && (
                <option value={NO_TOPIC}>
                  {NO_TOPIC_LABEL} ({formatNumber(facets.topic.get(NO_TOPIC) ?? 0)})
                </option>
              )}
            </select>
          </div>
          <div className="lx-field">
            <label htmlFor={`${ids}-stage`}>Status</label>
            <select id={`${ids}-stage`} className="select lx-select" value={state.stage ?? ''} onChange={(e) => update({ stage: e.target.value || null })}>
              <option value="">Any status</option>
              <optgroup label="Broad status">
                {Object.entries(STAGE_GROUPS).map(([k, g]) => (
                  <option key={k} value={k}>
                    {g.label} ({formatNumber(facets.groups[k] ?? 0)})
                  </option>
                ))}
              </optgroup>
              <optgroup label="Exact stage">
                {STAGE_ORDER.filter((s) => (facets.stage.get(s) ?? 0) > 0 || state.stage === s).map((s) => (
                  <option key={s} value={s}>
                    {STAGE_LABEL[s]} ({formatNumber(facets.stage.get(s) ?? 0)})
                  </option>
                ))}
              </optgroup>
            </select>
          </div>
          <div className="lx-field">
            <label htmlFor={`${ids}-sort`}>Sort by</label>
            <select
              id={`${ids}-sort`}
              className="select lx-select"
              value={state.sort}
              onChange={(e) => update({ sort: e.target.value }, { keepShow: false })}
            >
              {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => {
                if (k === 'relevance' && !hasQuery) return null;
                if (k === 'deadline' && !hasNextDates) return null;
                if (k === 'blocked' && !anyBlocked) return null;
                return (
                  <option key={k} value={k}>
                    {SORT_LABEL[k]}
                    {k === 'adopted' && !hasAdopted ? ' (by latest step)' : ''}
                  </option>
                );
              })}
            </select>
          </div>
  
          <details className="lx-more" open={advancedActive || undefined}>
            <summary>
              More filters
              {advancedActive && <span className="lx-more__count"> ({[state.type, state.instrument, state.year, state.blocked || null].filter(Boolean).length} active)</span>}
            </summary>
            <div className="lx-more__body">
              <div className="lx-field">
                <label htmlFor={`${ids}-type`}>Procedure type</label>
                <select id={`${ids}-type`} className="select lx-select" value={state.type ?? ''} onChange={(e) => update({ type: e.target.value || null })}>
                  <option value="">Any procedure</option>
                  {typeLabels.map(([t, label]) => (
                    <option key={t} value={t}>
                      {label} ({formatNumber(facets.type.get(t) ?? 0)})
                    </option>
                  ))}
                </select>
              </div>
              <div className="lx-field">
                <label htmlFor={`${ids}-instrument`}>Type of act</label>
                <select
                  id={`${ids}-instrument`}
                  className="select lx-select"
                  value={state.instrument ?? ''}
                  onChange={(e) => update({ instrument: e.target.value || null })}
                >
                  <option value="">Any type of act</option>
                  {INSTRUMENTS.map((i) => (
                    <option key={i} value={i}>
                      {INSTRUMENT_LABEL[i]} ({formatNumber(facets.instrument.get(i) ?? 0)})
                    </option>
                  ))}
                </select>
              </div>
              <div className="lx-field">
                <label htmlFor={`${ids}-year`}>Year proposed</label>
                <select id={`${ids}-year`} className="select lx-select" value={state.year ?? ''} onChange={(e) => update({ year: e.target.value || null })}>
                  <option value="">Any year</option>
                  {years.map((y) => (
                    <option key={y} value={y}>
                      {y} ({formatNumber(facets.year.get(y) ?? 0)})
                    </option>
                  ))}
                </select>
              </div>
              <div className="lx-field lx-field--check">
                <span className="lx-field__label" id={`${ids}-blocked-l`}>
                  Official monitoring
                </span>
                {anyBlocked || state.blocked ? (
                  <>
                    <label className="lx-check">
                      <input
                        type="checkbox"
                        checked={state.blocked}
                        onChange={(e) => update({ blocked: e.target.checked ? '1' : null })}
                        aria-describedby={`${ids}-blocked-d`}
                      />
                      Only files officially reported as blocked ({formatNumber(facets.blocked)})
                    </label>
                    <span className="meta" id={`${ids}-blocked-d`}>
                      As recorded by the European Parliament’s Legislative Train Schedule.
                    </span>
                  </>
                ) : (
                  <span className="meta">
                    No file is officially reported as blocked in the current data (source: the European Parliament’s Legislative
                    Train Schedule).
                  </span>
                )}
              </div>
            </div>
          </details>
        </div>
      </form>

      {index.loading && <Loading label="Loading legislative files…" />}
      {index.error && <ErrorState error={index.error} title="The list of legislative files could not be loaded" />}

      {index.data && (
        <>
          <div className="lx-results-head">
            <p className="lx-count" role="status" aria-live="polite" aria-atomic="true">
              <strong>{formatNumber(sorted.length)}</strong> {sorted.length === 1 ? 'file' : 'files'}
              {anyFilter ? <> match{sorted.length === 1 ? 'es' : ''}</> : <> in our dataset</>}
              {sorted.length > 0 && <span className="meta"> · sorted by {SORT_LABEL[state.sort].toLowerCase()}</span>}
            </p>
            <div className="lx-results-tools">
              {state.topic && !noTopic && (
                <a className="lx-linkbtn" href={`${DATA_BASE}feeds/${encodeURIComponent(state.topic)}.xml`}>
                  Atom feed for this topic
                </a>
              )}
              {anyFilter && (
                <button type="button" className="lx-linkbtn" onClick={copyLink}>
                  {copied ? 'Link copied' : 'Copy link to this view'}
                </button>
              )}
            </div>
          </div>

          {chips.length > 0 && (
            <ul className="lx-chips lx-active" aria-label="Active filters">
              {chips.map((c) => (
                <li key={c.key}>
                  <button type="button" className="lx-chip lx-chip--filter" onClick={c.clear}>
                    {c.label}
                    <span className="lx-chip__x" aria-hidden="true">
                      ×
                    </span>
                    <span className="visually-hidden">(remove filter)</span>
                  </button>
                </li>
              ))}
              {chips.length > 1 && (
                <li>
                  <button type="button" className="lx-linkbtn" onClick={clearAll}>
                    Clear all
                  </button>
                </li>
              )}
            </ul>
          )}

          {state.sort === 'adopted' && !hasAdopted && (
            <p className="meta lx-sortnote">
              Adoption dates are not yet in the summary data, so adopted files are ordered by their latest recorded step.
            </p>
          )}

          {sorted.length === 0 ? (
            <EmptyState title={rows.length === 0 ? 'No legislative files are available yet' : 'No files match these filters'}>
              {rows.length === 0 ? (
                <p>The data build has not produced any legislative files. See <Link to="/about#coverage">what’s covered</Link>.</p>
              ) : (
                <>
                  <p>
                    Try fewer words, a procedure reference such as <span className="mono">2021/0106(COD)</span>, or remove a
                    filter.
                  </p>
                  {anyFilter && (
                    <button type="button" className="btn" onClick={clearAll}>
                      Clear all filters
                    </button>
                  )}
                </>
              )}
            </EmptyState>
          ) : (
            <>
              <ol className="drows" aria-label="Legislative files" ref={listRef}>
                {visible.map((d) => (
                  <DossierRow key={d.id} d={d} sort={state.sort} today={today} topicLabel={topicLabel} following={followed.has(d.id)} />
                ))}
              </ol>
              {sorted.length > visible.length && (
                <div className="lx-more-results">
                  <p className="meta">
                    Showing {formatNumber(visible.length)} of {formatNumber(sorted.length)}
                  </p>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      focusFrom.current = visible.length;
                      update({ show: String(state.show + PAGE_SIZE * 2) }, { keepShow: true, replace: true });
                    }}
                  >
                    Show {formatNumber(Math.min(PAGE_SIZE * 2, sorted.length - visible.length))} more
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
