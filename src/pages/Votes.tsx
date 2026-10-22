import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { EpVoteSummary, Topic, VoteKind, VoteOutcome } from '../types/data';
import { useData } from '../lib/data';
import { formatNumber, plural } from '../lib/format';
import { Disclosure, EmptyState, ErrorState, Loading, PageHeader, Term } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { CloseVoteMethod, VoteKindGuide, VoteListItem } from '../features/votes/components';
import { KIND_LABEL, OUTCOME_LABEL, isClose } from '../features/votes/labels';

const PAGE = 50;
const KIND_ORDER: VoteKind[] = ['final', 'resolution', 'motion', 'amendment', 'split_or_separate', 'procedural', 'other'];
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
  const [params, setParams] = useSearchParams();
  const [shown, setShown] = useState(PAGE);

  const q = params.get('q') ?? '';
  const year = params.get('year') ?? '';
  const kind = params.get('kind') ?? '';
  const outcome = params.get('outcome') ?? '';
  const topic = params.get('topic') ?? '';
  const dossier = params.get('dossier') ?? '';
  const close = params.get('close') === '1';
  const sort = (params.get('sort') as SortKey) || 'newest';

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  // reset paging whenever the filters change
  const filterKey = params.toString();
  useEffect(() => setShown(PAGE), [filterKey]);

  const votes = useMemo(() => data ?? [], [data]);
  const opts = useMemo(() => {
    const years = [...new Set(votes.map((v) => v.date.slice(0, 4)))].sort().reverse();
    const kinds = countBy(votes, (v) => v.kind);
    const outcomes = countBy(votes, (v) => v.outcome);
    const topics = new Map<string, number>();
    for (const v of votes) for (const t of v.topics) topics.set(t, (topics.get(t) ?? 0) + 1);
    const linked = votes.filter((v) => v.dossier_id).length;
    const withMargin = votes.filter((v) => v.margin).length;
    const closeCount = votes.filter(isClose).length;
    return { years, kinds, outcomes, topics, linked, withMargin, closeCount };
  }, [votes]);

  const topicLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of topicsState.data ?? []) m.set(t.slug, t.label);
    return (slug: string) => m.get(slug) ?? slug;
  }, [topicsState.data]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = votes.filter((v) => {
      if (year && !v.date.startsWith(year)) return false;
      if (kind && v.kind !== kind) return false;
      if (outcome && v.outcome !== outcome) return false;
      if (topic && !v.topics.includes(topic)) return false;
      if (dossier === 'linked' && !v.dossier_id) return false;
      if (dossier === 'unlinked' && v.dossier_id) return false;
      if (close && !isClose(v)) return false;
      if (needle) {
        const hay = `${v.display_title} ${v.title} ${v.dossier_ref ?? ''} ${v.id}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
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
  }, [votes, q, year, kind, outcome, topic, dossier, close, sort]);

  const active = [q, year, kind, outcome, topic, dossier, close ? '1' : ''].some(Boolean);

  return (
    <div className="container page">
      <PageHeader
        eyebrow="European Parliament"
        title="Votes in Parliament"
        lead={
          <>
            How the European Parliament voted in plenary: final votes on laws, resolutions and motions, and every recorded vote linked
            to a legislative file we track. Each vote links to the official record.
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
                className="input"
                type="search"
                value={q}
                placeholder="e.g. artificial intelligence, 2021/0106(COD)"
                onChange={(e) => set('q', e.target.value)}
              />
            </div>
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
                    {KIND_LABEL[k]} ({formatNumber(opts.kinds.get(k))})
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="vf-outcome">Outcome</label>
              <select id="vf-outcome" className="select" value={outcome} onChange={(e) => set('outcome', e.target.value)}>
                <option value="">Any outcome</option>
                {OUTCOME_ORDER.filter((o) => opts.outcomes.has(o)).map((o) => (
                  <option key={o} value={o}>
                    {OUTCOME_LABEL[o]} ({formatNumber(opts.outcomes.get(o))})
                  </option>
                ))}
              </select>
            </div>
            {opts.topics.size > 0 && (
              <div className="field">
                <label htmlFor="vf-topic">Topic</label>
                <select id="vf-topic" className="select" value={topic} onChange={(e) => set('topic', e.target.value)}>
                  <option value="">All topics</option>
                  {[...opts.topics.keys()]
                    .sort((a, b) => topicLabel(a).localeCompare(topicLabel(b)))
                    .map((t) => (
                      <option key={t} value={t}>
                        {topicLabel(t)} ({formatNumber(opts.topics.get(t))})
                      </option>
                    ))}
                </select>
              </div>
            )}
            {opts.linked > 0 && opts.linked < votes.length && (
              <div className="field">
                <label htmlFor="vf-dossier">Legislative file</label>
                <select id="vf-dossier" className="select" value={dossier} onChange={(e) => set('dossier', e.target.value)}>
                  <option value="">Linked or not</option>
                  <option value="linked">Linked to a file ({formatNumber(opts.linked)})</option>
                  <option value="unlinked">Not linked ({formatNumber(votes.length - opts.linked)})</option>
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
                <label htmlFor="vf-close">Close votes only ({formatNumber(opts.closeCount)})</label>
              </div>
            )}
          </form>

          <div className="results-bar">
            <p className="results-bar__count" aria-live="polite">
              {filtered.length === votes.length ? plural(votes.length, 'vote') : `${formatNumber(filtered.length)} of ${plural(votes.length, 'vote')}`}
            </p>
            {active && (
              <button type="button" className="linkish" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
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
                  <VoteListItem key={v.id} v={v} />
                ))}
              </ul>
              {filtered.length > shown && (
                <div className="more">
                  <button type="button" className="btn" onClick={() => setShown((n) => n + PAGE)}>
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
