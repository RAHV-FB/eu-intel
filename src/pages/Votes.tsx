import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { EpVoteSummary, Topic, VoteKind, VoteOutcome } from '../types/data';
import { useData } from '../lib/data';
import { formatNumber, plural } from '../lib/format';
import { loadSearch, type SearchEngine } from '../lib/search';
import { clearAllParams, shownParam, useParamState, useParamText } from '../lib/urlState';
import { Disclosure, EmptyState, ErrorState, Loading, PageHeader, Term } from '../components/ui';
import { CollapsibleFilters } from '../components/CollapsibleFilters';
import { useFittingPlaceholder } from '../components/useFittingPlaceholder';
import { useDocumentTitle } from '../features/legislation/labels';
import { CloseVoteMethod, VoteKindGuide, VoteListItem } from '../features/votes/components';
import { KIND_LABEL, OUTCOME_LABEL, isClose } from '../features/votes/labels';
import { matchVoteDetails, voteHaystacksOnce } from '../features/votes/keyword';

const PAGE = 50;
// longest first: the longest that fits the field is shown, so that phones keep the reference-format example
const Q_PLACEHOLDERS = ['e.g. artificial intelligence, 2021/0106(COD)', 'e.g. AI Act, 2021/0106(COD)', 'e.g. 2021/0106(COD)'];
const SHOW_RESET = ['show']; // a new search starts from the first page
const KIND_ORDER: VoteKind[] = ['final', 'mandate', 'resolution', 'motion', 'amendment', 'split_or_separate', 'procedural', 'other'];
const OUTCOME_ORDER: VoteOutcome[] = ['adopted', 'rejected', 'lapsed', 'unknown'];
type SortKey = 'newest' | 'oldest' | 'margin';

function countBy<T>(rows: T[], key: (r: T) => string | null | undefined): Map<string, number> {
  const m = new Map<string, number>();
  for (const r of rows) {
    const k = key(r);
    if (k) m.set(k, (m.get(k) ?? 0) + 1);
  }
  return m;
}

export default function Votes() {
  useDocumentTitle('Parliament votes');
  const { data, error, loading } = useData<EpVoteSummary[]>('votes/index.json');
  const topicsState = useData<Topic[]>('topics.json');
  const [params, patch] = useParamState();
  // rows shown: kept in the address like the filters, so that Back from a vote returns to the same list
  const shown = shownParam(params, 'show', PAGE);

  const qBox = useParamText('q', SHOW_RESET);
  const q = qBox.value;
  const [qPlaceholder, qRef] = useFittingPlaceholder(Q_PLACEHOLDERS);
  const year = params.get('year') ?? '';
  const kind = params.get('kind') ?? '';
  const outcome = params.get('outcome') ?? '';
  const topic = params.get('topic') ?? '';
  const dossier = params.get('dossier') ?? '';
  const close = params.get('close') === '1';
  const sort = (params.get('sort') as SortKey) || 'newest';

  const set = (key: string, value: string) => patch({ [key]: value, show: null }); // a new filter starts from the first page
  const setShown = (n: number) => patch({ show: String(n) });
  // this list's address, with the search as typed: a vote page's "All votes" link returns to it
  const listUrl = useMemo(() => {
    const p = new URLSearchParams(params);
    if (q) p.set('q', q);
    else p.delete('q');
    const s = p.toString();
    return s ? `/votes?${s}` : '/votes';
  }, [params, q]);

  const votes = useMemo(() => data ?? [], [data]);
  const opts = useMemo(() => {
    const years = [...new Set(votes.map((v) => v.date.slice(0, 4)))].sort().reverse();
    const kinds = countBy(votes, (v) => v.kind);
    const outcomes = countBy(votes, (v) => v.outcome);
    const topics = new Map<string, number>();
    for (const v of votes) for (const t of v.topics) topics.set(t, (topics.get(t) ?? 0) + 1);
    const linked = votes.filter((v) => v.dossier_id).length;
    const withMargin = votes.filter((v) => v.margin).length;
    const derived = votes.filter((v) => v.outcome_basis === 'derived').length;
    const noTopic = votes.filter((v) => !v.topics.length).length;
    return { years, kinds, outcomes, topics, linked, withMargin, derived, noTopic };
  }, [votes]);

  const topicLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of topicsState.data ?? []) m.set(t.slug, t.label);
    return (slug: string) => m.get(slug) ?? slug;
  }, [topicsState.data]);

  // keyword search: whole words in the vote titles and references, or the search index's matches on the
  // linked legislative file (its common names); the index is loaded only once there is a query
  const [engine, setEngine] = useState<SearchEngine | null>(null);
  const hasQuery = !!q.trim();
  useEffect(() => {
    if (hasQuery && !engine) loadSearch().then(setEngine, () => undefined);
  }, [hasQuery, engine]);
  const haystacks = useMemo(() => (hasQuery ? voteHaystacksOnce(votes) : new Map<string, Set<string>>()), [votes, hasQuery]);
  const keywordMatch = useMemo(() => matchVoteDetails(votes, haystacks, q, engine), [votes, haystacks, q, engine]);
  const keywordHits = keywordMatch?.ids ?? null;

  // each filter, so that a filter's options can count the votes matching all the other filters
  const tests = useMemo(
    () => ({
      year: (v: EpVoteSummary) => !year || v.date.startsWith(year),
      kind: (v: EpVoteSummary) => !kind || v.kind === kind,
      outcome: (v: EpVoteSummary) => !outcome || v.outcome === outcome,
      topic: (v: EpVoteSummary) => !topic || v.topics.includes(topic),
      dossier: (v: EpVoteSummary) => (dossier === 'linked' ? !!v.dossier_id : dossier === 'unlinked' ? !v.dossier_id : true),
      close: (v: EpVoteSummary) => !close || isClose(v),
      keyword: (v: EpVoteSummary) => !keywordHits || keywordHits.has(v.id),
    }),
    [year, kind, outcome, topic, dossier, close, keywordHits],
  );
  const facets = useMemo(() => {
    const others = (skip: keyof typeof tests) => {
      const ts = Object.entries(tests).filter(([k]) => k !== skip).map(([, t]) => t);
      return votes.filter((v) => ts.every((t) => t(v)));
    };
    const topics = new Map<string, number>();
    for (const v of others('topic')) for (const t of v.topics) topics.set(t, (topics.get(t) ?? 0) + 1);
    const byDossier = others('dossier');
    const linked = byDossier.filter((v) => v.dossier_id).length;
    return {
      kinds: countBy(others('kind'), (v) => v.kind),
      outcomes: countBy(others('outcome'), (v) => v.outcome),
      topics,
      linked,
      unlinked: byDossier.length - linked,
      closeCount: others('close').filter(isClose).length,
    };
  }, [votes, tests]);

  const filtered = useMemo(() => {
    const ts = Object.values(tests);
    const rows = votes.filter((v) => ts.every((t) => t(v)));
    const byDate = (a: EpVoteSummary, b: EpVoteSummary) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id);
    if (sort === 'oldest') rows.sort((a, b) => -byDate(a, b));
    else if (sort === 'margin')
      rows.sort((a, b) => {
        if (a.margin && b.margin) return Math.abs(a.margin.relative) - Math.abs(b.margin.relative) || byDate(a, b);
        if (a.margin) return -1;
        if (b.margin) return 1;
        return byDate(a, b);
      });
    else rows.sort(byDate);
    return rows;
  }, [votes, tests, sort]);

  const active = [q, year, kind, outcome, topic, dossier, close ? '1' : ''].some(Boolean);
  // what the phone toggle reports: everything behind it that differs from the default, including the order
  const activeFilters = [year, kind, outcome, topic, dossier, close ? '1' : '', sort !== 'newest' ? sort : ''].filter(Boolean).length;

  return (
    <div className="container page">
      <PageHeader
        eyebrow="European Parliament"
        title="Votes in Parliament"
        lead={
          <>
            How the European Parliament voted in plenary: roll-call votes on whole texts (laws and Parliament’s other
            decisions), resolutions, motions and committees’ decisions to open negotiations, and every final or
            negotiating-mandate vote on a legislative file we track. Votes on amendments and on parts of a text are not
            listed. Each vote links to the official record.
          </>
        }
      />

      <div className="explainers">
        <Disclosure summary="What kinds of votes are listed here?">
          <VoteKindGuide />
        </Disclosure>
        <Disclosure summary="How we identify close votes">
          <CloseVoteMethod />
        </Disclosure>
      </div>

      {loading && <Loading label="Loading votes…" />}
      {error && <ErrorState error={error} title="The vote list could not be loaded" />}

      {data && data.length === 0 && (
        <EmptyState title="No Parliament votes are available yet">
          Vote data has not been published in this build. See <Link to="/about#coverage">coverage</Link> for the current status of each
          source.
        </EmptyState>
      )}

      {data && data.length > 0 && (
        <>
          <form className="filters filters--wide-first" role="search" aria-label="Filter votes" onSubmit={(e) => e.preventDefault()}>
            <div className="field">
              <label htmlFor="vf-q">Search vote titles or procedure references</label>
              <input
                id="vf-q"
                ref={qRef}
                className="input"
                type="search"
                value={q}
                placeholder={qPlaceholder}
                onChange={(e) => qBox.set(e.target.value)}
                onBlur={qBox.flush}
              />
            </div>
            <CollapsibleFilters label="Filters and sorting" active={activeFilters}>
              <div className="field">
                <label htmlFor="vf-year">Year</label>
                <select id="vf-year" className="select" value={year} onChange={(e) => set('year', e.target.value)}>
                  <option value="">All years</option>
                  {opts.years.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="vf-kind">Kind of vote</label>
                <select id="vf-kind" className="select" value={kind} onChange={(e) => set('kind', e.target.value)}>
                  <option value="">All kinds</option>
                  {KIND_ORDER.filter((k) => opts.kinds.has(k)).map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABEL[k]} ({formatNumber(facets.kinds.get(k) ?? 0)})
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="vf-outcome">Outcome</label>
                <select
                  id="vf-outcome"
                  className="select"
                  value={outcome}
                  onChange={(e) => set('outcome', e.target.value)}
                  aria-describedby="vf-outcome-d"
                >
                  <option value="">Any outcome</option>
                  {OUTCOME_ORDER.filter((o) => opts.outcomes.has(o)).map((o) => (
                    <option key={o} value={o}>
                      {OUTCOME_LABEL[o]} ({formatNumber(facets.outcomes.get(o) ?? 0)})
                    </option>
                  ))}
                </select>
                <span className="meta" id="vf-outcome-d">
                  Outcomes come from Parliament’s open data or the official minutes of the sitting
                  {opts.derived > 0 && <>; {formatNumber(opts.derived)} are calculated from the recorded counts</>}.
                </span>
              </div>
              {opts.topics.size > 0 && (
                <div className="field">
                  <label htmlFor="vf-topic">Topic</label>
                  <select
                    id="vf-topic"
                    className="select"
                    value={topic}
                    onChange={(e) => set('topic', e.target.value)}
                    aria-describedby={opts.noTopic > 0 ? 'vf-topic-d' : undefined}
                  >
                    <option value="">All topics</option>
                    {[...opts.topics.keys()]
                      .sort((a, b) => topicLabel(a).localeCompare(topicLabel(b)))
                      .map((t) => (
                        <option key={t} value={t}>
                          {topicLabel(t)} ({formatNumber(facets.topics.get(t) ?? 0)})
                        </option>
                      ))}
                  </select>
                  {opts.noTopic > 0 && (
                    <span className="meta" id="vf-topic-d">
                      Topics come from a vote’s linked legislative file, so {formatNumber(opts.noTopic)} votes are in no topic.
                    </span>
                  )}
                </div>
              )}
              {opts.linked > 0 && opts.linked < votes.length && (
                <div className="field">
                  <label htmlFor="vf-dossier">Legislative file</label>
                  <select id="vf-dossier" className="select" value={dossier} onChange={(e) => set('dossier', e.target.value)}>
                    <option value="">Linked or not</option>
                    <option value="linked">Linked to a file ({formatNumber(facets.linked)})</option>
                    <option value="unlinked">Not linked ({formatNumber(facets.unlinked)})</option>
                  </select>
                </div>
              )}
              <div className="field">
                <label htmlFor="vf-sort">Sort by</label>
                <select id="vf-sort" className="select" value={sort} onChange={(e) => set('sort', e.target.value === 'newest' ? '' : e.target.value)}>
                  <option value="newest">Newest first</option>
                  <option value="oldest">Oldest first</option>
                  {opts.withMargin > 0 && <option value="margin">Closest margin first</option>}
                </select>
              </div>
              {opts.withMargin > 0 && (
                <div className="field field--check">
                  <input id="vf-close" type="checkbox" checked={close} onChange={(e) => set('close', e.target.checked ? '1' : '')} />
                  <label htmlFor="vf-close">Close votes only ({formatNumber(facets.closeCount)})</label>
                </div>
              )}
            </CollapsibleFilters>
          </form>

          {/* the votes' titles are h3: this heading puts them under the page's h1 in the outline */}
          <h2 className="visually-hidden">Results</h2>
          <div className="results-bar">
            <p className="results-bar__count" aria-live="polite">
              {filtered.length === votes.length ? plural(votes.length, 'vote') : `${formatNumber(filtered.length)} of ${plural(votes.length, 'vote')}`}
              {keywordMatch?.partial && filtered.length > 0 && (
                <>
                  {' '}
                  · no whole-word matches for “{q.trim()}”, so{' '}
                  {keywordMatch.wordStart
                    ? 'these have words in their titles, or in the names of their files, that start with it'
                    : 'these match only another form of a word (a longer word built on it, or another ending)'}
                </>
              )}
              {keywordMatch?.approximate && filtered.length > 0 && (
                <>
                  {' '}
                  · no votes match “{q.trim()}”, so these are votes on files that match it only approximately (
                  {keywordMatch.similar ? <>a similar word: {keywordMatch.similar.map((w) => `“${w}”`).join(', ')}</> : 'all but one of the words'})
                </>
              )}
            </p>
            {active && (
              <button type="button" className="linkish" onClick={() => patch(clearAllParams())}>
                Clear all filters
              </button>
            )}
          </div>

          {filtered.length === 0 ? (
            <EmptyState title="No votes match these filters">Try removing a filter or searching for a different word.</EmptyState>
          ) : (
            <>
              <ul className="vote-list">
                {filtered.slice(0, shown).map((v) => (
                  <VoteListItem key={v.id} v={v} listUrl={listUrl} />
                ))}
              </ul>
              {filtered.length > shown && (
                <div className="more">
                  <button type="button" className="btn" onClick={() => setShown(shown + PAGE)}>
                    Show {formatNumber(Math.min(PAGE, filtered.length - shown))} more
                  </button>
                  <span className="meta">
                    Showing {formatNumber(shown)} of {formatNumber(filtered.length)}
                  </span>
                </div>
              )}
            </>
          )}

          <p className="note" style={{ marginTop: 'var(--sp-5)' }}>
            Figures are the official totals recorded by Parliament. Where Parliament held a <Term id="roll-call">roll-call vote</Term>,
            the vote page also shows how each MEP, political group and country’s MEPs voted.
          </p>
        </>
      )}
    </div>
  );
}
