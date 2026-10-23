import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { SearchDoc, SearchKind } from '../types/data';
import { loadSearch, type SearchEngine, type SearchHit } from '../lib/search';
import { formatDate, formatNumber } from '../lib/format';
import { kindLabel } from '../components/SearchBox';
import { EmptyState, ErrorState, Loading } from '../components/ui';
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

function ResultItem({ doc, showKind }: { doc: SearchDoc; showKind: boolean }) {
  const dateLabel = DATE_LABEL[doc.k];
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

function GroupSection({ g, hits, q }: { g: Group; hits: SearchHit[]; q: string }) {
  const [all, setAll] = useState(false);
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
          <ResultItem key={`${h.doc.k}:${h.doc.id}`} doc={h.doc} showKind={mixed} />
        ))}
      </ol>
      <div className="sr-group__foot">
        {hits.length > PER_GROUP && (
          <button type="button" className="lx-linkbtn" aria-expanded={all} aria-controls={listId} onClick={() => setAll((a) => !a)}>
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

export default function Search() {
  const [params, setParams] = useSearchParams();
  const q = (params.get('q') ?? '').slice(0, 200);
  const [input, setInput] = useState(q);
  useEffect(() => setInput(q), [q]);
  useDocumentTitle(q ? `Search: ${q}` : 'Search');

  const [engine, setEngine] = useState<SearchEngine | null>(null);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    loadSearch().then(setEngine, (e: Error) => setError(e));
  }, []);

  const { grouped, partialOnly, partialCount } = useMemo(() => {
    if (!engine || !q.trim()) return { grouped: [], partialOnly: false, partialCount: 0 };
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
    return { grouped: groups, partialOnly: hits.length > 0 && partialCount === hits.length, partialCount };
  }, [engine, q]);
  const total = grouped.reduce((n, x) => n + x.hits.length, 0);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const v = input.trim();
    setParams(v ? { q: v } : {});
  };
  const inputId = useId();

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
            className="input lx-input sr-form__input"
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search a law, topic, MEP, party or country…"
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

      {engine && q.trim() && total > 0 && (
        <>
          <p className="sr-summary" role="status">
            {formatNumber(total)} result{total === 1 ? '' : 's'}
            {total >= 1000 ? ' (showing the best 1,000)' : ''}
            {partialOnly && <> · no whole-word matches for “{q}”, so these contain words that start with it</>}
            {!partialOnly && partialCount > 0 && (
              <>
                {' '}
                · {formatNumber(partialCount)} of them match only another form of a word (a longer word built on it,
                or another ending) and are listed after the exact matches
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
            <GroupSection key={`${g.id}:${q}`} g={g} hits={hits} q={q} />
          ))}
          <VotesLink q={q.trim()} />
        </>
      )}

      {engine && q.trim() && total === 0 && (
        <EmptyState title={`No results for “${q}”`}>
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
