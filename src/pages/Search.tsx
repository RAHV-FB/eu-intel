import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { Meta, SearchKind } from '../types/data';
import { isIdentifier, loadSearch, similarWords, type SearchEngine, type SearchHit } from '../lib/search';
import { useData } from '../lib/data';
import { legislationScope } from '../lib/scope';
import { formatDate, formatNumber } from '../lib/format';
import { useParamState } from '../lib/urlState';
import { PAGE_PLACEHOLDERS, approximateNote, kindLabel } from '../components/SearchBox';
import { EmptyState, ErrorState, Loading } from '../components/ui';
import { useFittingPlaceholder } from '../components/useFittingPlaceholder';
import { useDocumentTitle } from '../features/legislation/labels';
import '../features/legislation/common.css';
import '../features/legislation/search.css';

interface Group {
  id: string;
  label: string;
  kinds: SearchKind[];
  more?: (q: string) => { to: string; label: string };
}

// The search index covers legislation, people, groups, parties, countries, topics and guides. Parliament votes
// are searched on /votes (linked from the results), where vote titles and the linked files' names are matched.
const GROUPS: Group[] = [
  {
    id: 'legislation',
    label: 'Legislation',
    kinds: ['dossier', 'act'],
    more: (q) => ({ to: `/legislation?q=${encodeURIComponent(q)}`, label: 'Filter these results in the legislation explorer' }),
  },
  { id: 'people', label: 'People', kinds: ['mep'] },
  { id: 'groups', label: 'Groups & parties', kinds: ['group', 'party'] },
  { id: 'countries', label: 'Countries', kinds: ['country'] },
  { id: 'topics', label: 'Topics', kinds: ['topic'] },
  { id: 'guides', label: 'Guides', kinds: ['page'] },
];

const SUGGESTIONS = ['AI Act', 'GDPR', 'Migration', 'Spain', 'EPP', 'Agriculture', 'Digital markets', 'Climate'];
const PER_GROUP = 8;

/** What the date on a result means (search.json `d`: the latest recorded procedural step of a file). */
const DATE_LABEL: Partial<Record<SearchKind, string>> = { dossier: 'Latest recorded step', act: 'Latest recorded step' };

function ResultItem({ hit, showKind }: { hit: SearchHit; showKind: boolean }) {
  const { doc } = hit;
  const dateLabel = DATE_LABEL[doc.k];
  const note = approximateNote(hit);
  return (
    <li className="sr-item">
      <Link to={doc.u} className="sr-item__title">
        {doc.t}
      </Link>
      <span className="sr-item__meta">
        {showKind && <span className="sr-item__kind">{kindLabel(doc.k)}</span>}
        {doc.s && <span>{doc.s}</span>}
        {doc.d && (
          <span>
            {dateLabel && <>{dateLabel} </>}
            <time dateTime={doc.d}>{formatDate(doc.d)}</time>
          </span>
        )}
        {note && <span className="sr-item__approx">{note}</span>}
      </span>
    </li>
  );
}

function VotesLink({ q }: { q: string }) {
  return (
    <p className="sr-votes">
      Looking for a vote? <Link to={`/votes?q=${encodeURIComponent(q)}`}>Search Parliament votes for “{q}”</Link>
    </p>
  );
}

function GroupSection({ g, hits, q, all, onToggle }: { g: Group; hits: SearchHit[]; q: string; all: boolean; onToggle: () => void }) {
  const listId = useId();
  const shown = all ? hits : hits.slice(0, PER_GROUP);
  const mixed = new Set(hits.map((h) => h.doc.k)).size > 1;
  const more = g.more?.(q);
  return (
    <section className="sr-group" id={`r-${g.id}`} aria-labelledby={`r-${g.id}-h`}>
      <h2 id={`r-${g.id}-h`} className="sr-group__title">
        {g.label} <span className="sr-group__count">{formatNumber(hits.length)}</span>
      </h2>
      <ol className="sr-list" id={listId}>
        {shown.map((h) => (
          <ResultItem key={`${h.doc.k}:${h.doc.id}`} hit={h} showKind={mixed} />
        ))}
      </ol>
      <div className="sr-group__foot">
        {hits.length > PER_GROUP && (
          <button type="button" className="lx-linkbtn" aria-expanded={all} aria-controls={listId} onClick={onToggle}>
            {all ? 'Show fewer' : `Show all ${formatNumber(hits.length)} ${g.label.toLowerCase()} results`}
          </button>
        )}
        {more && (
          <Link to={more.to} className="sr-group__more">
            {more.label} →
          </Link>
        )}
      </div>
    </section>
  );
}

/** The search engine once loaded, so that a page opened again (Back from a result) renders its results at once and
 * the browser can restore the reader's place in them. */
let loadedEngine: SearchEngine | null = null;

export default function Search() {
  const [, setParams] = useSearchParams();
  // the groups opened with "Show all" (all=legislation,people) are kept in the address, so that Back from a result
  // returns to the same list; a new search starts with them closed
  const [params, patch] = useParamState();
  const q = (params.get('q') ?? '').slice(0, 200);
  const opened = new Set((params.get('all') ?? '').split(',').filter(Boolean));
  const toggleAll = (id: string) => {
    const next = new Set(new URLSearchParams(window.location.search).get('all')?.split(',').filter(Boolean));
    if (next.has(id)) next.delete(id);
    else next.add(id);
    patch({ all: [...next].join(',') });
  };
  const [input, setInput] = useState(q);
  useEffect(() => setInput(q), [q]);
  useDocumentTitle(q ? `Search: ${q}` : 'Search');

  const [engine, setEngine] = useState<SearchEngine | null>(loadedEngine);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    loadSearch().then(
      (e) => {
        loadedEngine = e;
        setEngine(e);
      },
      (e: Error) => setError(e),
    );
  }, []);
  const meta = useData<Meta>('meta.json');

  const { grouped, partialCount, startCount, approx } = useMemo(() => {
    if (!engine || !q.trim()) return { grouped: [], partialCount: 0, startCount: 0, approx: [] };
    let hits: SearchHit[] = [];
    try {
      hits = engine.search(q, { limit: 1000 });
    } catch {
      hits = [];
    }
    // sections in the order of their best match ("EPP" shows the group first, "Hungary" the country)
    const rank = (k: SearchKind[]) => hits.findIndex((h) => k.includes(h.doc.k));
    const groups = GROUPS.map((g) => ({ g, hits: hits.filter((h) => g.kinds.includes(h.doc.k)) }))
      .filter((x) => x.hits.length > 0)
      .sort((a, b) => rank(a.g.kinds) - rank(b.g.kinds));
    const partialCount = hits.filter((h) => h.partial).length;
    const startCount = hits.filter((h) => h.wordStart).length;
    return { grouped: groups, partialCount, startCount, approx: hits.filter((h) => h.approximate) };
  }, [engine, q]);
  const total = grouped.reduce((n, x) => n + x.hits.length, 0);
  // matches on whole words (exact, or singular/plural) rank first, then other forms of a word, then approximate ones
  const wholeCount = total - partialCount - approx.length;
  const similar = similarWords(approx.map((h) => h.similar))
    .map((w) => `“${w}”`)
    .join(', ');
  const ofThem = (n: number) => `${formatNumber(n)} of them ${n === 1 ? 'matches' : 'match'}`;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const v = input.trim();
    setParams(v ? { q: v } : {});
  };
  const inputId = useId();
  const [placeholder, inputRef] = useFittingPlaceholder(PAGE_PLACEHOLDERS);

  return (
    <div className="container page sr">
      <header className="page-header">
        <div className="eyebrow">Search</div>
        <h1>{q ? <>Results for “{q}”</> : 'Search'}</h1>
        <form className="sr-form" role="search" onSubmit={onSubmit}>
          <label htmlFor={inputId} className="visually-hidden">
            Search legislation, people, parties and countries
          </label>
          <input
            id={inputId}
            ref={inputRef}
            className="input lx-input sr-form__input"
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={placeholder}
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit" className="btn btn--primary">
            Search
          </button>
        </form>
      </header>

      {error && <ErrorState error={error} title="The search index could not be loaded" />}
      {!error && !engine && q && <Loading label="Searching…" />}

      {/* one status region for every query, whatever its result count, so that each new search is announced (a
          region added together with its text, or removed, is not); the summary below says more */}
      {!error && q.trim() && (
        <p className="visually-hidden" role="status">
          {engine &&
            (total > 0
              ? `${formatNumber(total)} result${total === 1 ? '' : 's'} for “${q}”` +
                (approx.length === total ? ', none exact' : wholeCount === 0 && partialCount > 0 ? ', none on whole words' : '')
              : `No results for “${q}”`)}
        </p>
      )}

      {engine && q.trim() && total > 0 && (
        <>
          <p className="sr-summary">
            {formatNumber(total)} result{total === 1 ? '' : 's'}
            {total >= 1000 ? ' (showing the best 1,000)' : ''}
            {partialCount > 0 && wholeCount === 0 && startCount === partialCount && (
              <>
                {' '}
                · no whole-word matches for “{q}”, so{' '}
                {partialCount === total
                  ? 'these contain'
                  : `${formatNumber(partialCount)} of them ${partialCount === 1 ? 'contains' : 'contain'}`}{' '}
                words that start with it
              </>
            )}
            {partialCount > 0 && wholeCount === 0 && startCount < partialCount && (
              <>
                {' '}
                · no whole-word matches for “{q}”, so {partialCount === total ? 'these match' : ofThem(partialCount)} only
                another form of a word (a longer word built on it, or another ending)
              </>
            )}
            {partialCount > 0 && wholeCount > 0 && (
              <>
                {' '}
                · {ofThem(partialCount)} only another form of a word (a longer word built on it, or another ending) and{' '}
                {partialCount === 1 ? 'is' : 'are'} listed after the exact matches
              </>
            )}
            {approx.length > 0 && approx.length === total && (
              <>
                {' '}
                · no exact matches for “{q}”, so these{' '}
                {similar ? <>contain a similar word instead: {similar}</> : 'match all but one of the words'}
              </>
            )}
            {approx.length > 0 && approx.length < total && (
              <>
                {' '}
                · {ofThem(approx.length)} only approximately (
                {similar ? <>a similar word: {similar}</> : 'all but one of the words'}) and {approx.length === 1 ? 'is' : 'are'}{' '}
                listed last
              </>
            )}
          </p>
          <nav className="sr-jump" aria-label="Result groups">
            <ul className="lx-chips">
              {grouped.map(({ g, hits }) => (
                <li key={g.id}>
                  <a href={`#r-${g.id}`} className="lx-chip">
                    {g.label} <span className="sr-jump__n">{formatNumber(hits.length)}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          {grouped.map(({ g, hits }) => (
            <GroupSection key={`${g.id}:${q}`} g={g} hits={hits} q={q} all={opened.has(g.id)} onToggle={() => toggleAll(g.id)} />
          ))}
          <VotesLink q={q.trim()} />
        </>
      )}

      {engine && q.trim() && total === 0 && (
        <EmptyState title={`No results for “${q}”`}>
          {isIdentifier(q) && (
            <p>
              No file in our data has this reference or number. {legislationScope(meta.data?.scope, true)}
            </p>
          )}
          <p>
            Check the spelling, try a shorter or more general word, or search an official reference such as{' '}
            <span className="mono">2021/0106(COD)</span> or a CELEX number such as <span className="mono">32016R0679</span>.
          </p>
          <Suggestions />
          <p>
            Or <Link to="/legislation">browse all legislation by topic and status</Link>.
          </p>
          <VotesLink q={q.trim()} />
        </EmptyState>
      )}

      {!q.trim() && (
        <div className="sr-start">
          <p>
            Search across EU legislation, MEPs, political groups, national parties and countries. To find a Parliament vote, use
            the <Link to="/votes">vote search</Link>.
          </p>
          <Suggestions />
        </div>
      )}
    </div>
  );
}

function Suggestions() {
  return (
    <div className="sr-suggest">
      <span className="meta">Try:</span>
      <ul className="lx-chips">
        {SUGGESTIONS.map((s) => (
          <li key={s}>
            <Link className="lx-chip" to={`/search?q=${encodeURIComponent(s)}`}>
              {s}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
