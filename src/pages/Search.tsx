import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { CountryDetail, Meta, SearchKind } from '../types/data';
import {
  actTypes,
  dossierScores,
  isIdentifier,
  isMepQuery,
  loadSearch,
  normalize,
  queryParts,
  similarWords,
  words,
  type QueryPart,
  type SearchEngine,
  type SearchHit,
} from '../lib/search';
import { useData } from '../lib/data';
import { matchDirectives, queryNumber } from '../features/countries/directiveSearch';
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
// the most results a group lists when opened (its count is every match; the legislation explorer filters them all)
const MAX_LISTED = 1000;

/** What the date on a result means (search.json `d`: the latest recorded procedural step of a file). */
const DATE_LABEL: Partial<Record<SearchKind, string>> = { dossier: 'Latest recorded step', act: 'Latest recorded step' };

/** "Regulation", "Regulation and directive": the types of a file's acts, which the search matches too. */
function typeLabel(types: string[]): string | null {
  const s = types.join(', ').replace(/, ([^,]+)$/, ' and $1');
  return s ? s[0].toUpperCase() + s.slice(1) : null;
}

function ResultItem({ hit, showKind }: { hit: SearchHit; showKind: boolean }) {
  const { doc } = hit;
  const dateLabel = DATE_LABEL[doc.k];
  const note = approximateNote(hit);
  const types = typeLabel(actTypes(doc));
  return (
    <li className="sr-item">
      <Link to={doc.u} className="sr-item__title">
        {doc.t}
      </Link>
      <span className="sr-item__meta">
        {showKind && <span className="sr-item__kind">{kindLabel(doc.k)}</span>}
        {doc.s && <span>{doc.s}</span>}
        {types && <span>{types}</span>}
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

/** Where a query for MEPs ("Spanish MEPs", "EPP MEPs", "former MEPs") is answered: the MEP directory, filtered by
 * the country or group the query names (a party's page lists its MEPs). */
function mepLink(q: string, hits: SearchHit[]): { to: string; label: string } | null {
  const h = hits.find((x) => x.meps);
  if (!h && !isMepQuery(q)) return null;
  if (h?.doc.k === 'country') return { to: `/people?country=${h.doc.id}`, label: `See the current MEPs from ${h.doc.t}` };
  if (h?.doc.k === 'group') {
    const former = (h.doc.s ?? '').startsWith('Former');
    // "the Renew Europe Group", but "The Left group in the European Parliament - GUE/NGL", as the group writes it
    const group = /^the\s/i.test(h.doc.t) ? h.doc.t : `the ${h.doc.t}`;
    return former
      ? { to: `/people?group=${h.doc.id}&status=all`, label: `See the MEPs of ${group} (a group of an earlier term)` }
      : { to: `/people?group=${h.doc.id}`, label: `See the current MEPs of ${group}` };
  }
  if (h?.doc.k === 'party') return { to: h.doc.u, label: `See the MEPs of ${h.doc.t}` };
  if (words(q).includes('former')) return { to: '/people?status=former', label: 'See former MEPs in the MEP directory' };
  return { to: '/people', label: 'Find MEPs by name, country, political group or party in the MEP directory' };
}

function MepLink({ link }: { link: { to: string; label: string } }) {
  return (
    <p className="sr-summary">
      Looking for MEPs? <Link to={link.to}>{link.label}</Link>
    </p>
  );
}

/** The part of a query that names a country ("Ireland" in "NIS2 Ireland"), and the file another part finds. */
function countryAndFile(parts: QueryPart[]): { country: SearchHit; file: SearchHit; text: string } | null {
  const names = (h: SearchHit) => [h.doc.t, ...(h.doc.a ?? '').split('|')].map(normalize);
  const at = parts.findIndex((p) => p.hits[0]?.doc.k === 'country' && names(p.hits[0]).includes(normalize(p.text)));
  const file = parts.find((p, k) => k !== at && p.hits[0]?.doc.k === 'dossier' && !p.hits[0].approximate);
  return at >= 0 && file ? { country: parts[at].hits[0], file: file.hits[0], text: file.text } : null;
}

function PartSection({ part }: { part: QueryPart }) {
  const id = useId();
  return (
    <section className="sr-group" aria-labelledby={id}>
      <h2 id={id} className="sr-group__title">
        “{part.text}”
      </h2>
      <ol className="sr-list">
        {part.hits.map((h) => (
          <ResultItem key={`${h.doc.k}:${h.doc.id}`} hit={h} showKind />
        ))}
      </ol>
      <div className="sr-group__foot">
        <Link to={`/search?q=${encodeURIComponent(part.text)}`} className="sr-group__more">
          All results for “{part.text}” →
        </Link>
      </div>
    </section>
  );
}

function GroupSection({ g, hits, q, all, onToggle }: { g: Group; hits: SearchHit[]; q: string; all: boolean; onToggle: () => void }) {
  const listId = useId();
  const shown = hits.slice(0, all ? MAX_LISTED : PER_GROUP);
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
            {all
              ? 'Show fewer'
              : hits.length > MAX_LISTED
                ? `Show the best ${formatNumber(MAX_LISTED)} of ${formatNumber(hits.length)} ${g.label.toLowerCase()} results`
                : `Show all ${formatNumber(hits.length)} ${g.label.toLowerCase()} results`}
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

  const { grouped, partialCount, startCount, approx, mep } = useMemo(() => {
    if (!engine || !q.trim()) return { grouped: [], partialCount: 0, startCount: 0, approx: [], mep: null };
    let hits: SearchHit[] = [];
    try {
      // every match, so that the counts are the true totals and agree with the legislation explorer's
      hits = engine.search(q, { limit: Infinity });
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
    return { grouped: groups, partialCount, startCount, approx: hits.filter((h) => h.approximate), mep: mepLink(q, hits) };
  }, [engine, q]);
  const total = grouped.reduce((n, x) => n + x.hits.length, 0);
  // nothing matches all the words ("NIS2 Ireland"): what each part of the query finds on its own; not for MEPs,
  // whom the MEP directory lists ("former MEPs" is not the "former Yugoslav Republic")
  const parts = useMemo(
    () => (engine && q.trim() && total === 0 && !mep ? queryParts(engine, q) : null),
    [engine, q, total, mep],
  );
  const found = parts?.filter((p) => p.hits.length) ?? [];
  const unknown = parts?.filter((p) => !p.hits.length) ?? [];
  const noneForAll = `No results for “${q}”: nothing matches all of its words.`;
  const eachPart = `${found.length === parts?.length ? 'Each part' : 'Part of it'} finds results on its own`;
  // a file next to a country ("NIS2 Ireland"): the directive in that country's implementation table
  const pair = useMemo(() => (parts && parts.every((p) => p.hits.length) ? countryAndFile(parts) : null), [parts]);
  const country = useData<CountryDetail>(pair ? `countries/${pair.country.doc.id}.json` : null);
  const transposed = useMemo(() => {
    const ofCountry = pair && country.data?.code === pair.country.doc.id ? country.data.transposition : [];
    const row = ofCountry.find((r) => r.dossier_id === pair?.file.doc.id);
    if (!engine || !pair || !row) return null;
    // the country page's directive search, with the words typed if they find the row, else with the act's number
    const opts = queryNumber(pair.text) ? { identifiers: true } : { wholeWords: true };
    const files = new Set(dossierScores(engine, pair.text, opts).keys());
    const typed = matchDirectives([row], pair.text, files).rows.length > 0;
    const trq = typed ? pair.text : (row.act ?? row.celex);
    return { row, to: `/countries/${pair.country.doc.id}?tr-q=${encodeURIComponent(trq)}#implementation` };
  }, [engine, pair, country.data]);
  // matches on whole words (exact, or singular/plural) rank first, then other forms of a word, then approximate ones
  const wholeCount = total - partialCount - approx.length;
  const similar = similarWords(approx.map((h) => h.similar))
    .map((w) => `“${w}”`)
    .join(', ');
  const ofThem = (n: number) => `${formatNumber(n)} of them ${n === 1 ? 'matches' : 'match'}`;

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const v = input.trim();
    // nothing to search: back to the field, where the reader types (the examples are below it)
    if (!v && !q) e.currentTarget.querySelector('input')?.focus();
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
              : found.length > 0
                ? `${noneForAll} ${eachPart}`
                : `No results for “${q}”`)}
        </p>
      )}

      {engine && q.trim() && total > 0 && (
        <>
          <p className="sr-summary">
            {formatNumber(total)} result{total === 1 ? '' : 's'}
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
          {/* links to the groups of results, when there is more than one (the heading of a single group follows) */}
          {grouped.length > 1 && (
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
          )}
          {mep && <MepLink link={mep} />}
          {grouped.map(({ g, hits }) => (
            <GroupSection key={`${g.id}:${q}`} g={g} hits={hits} q={q} all={opened.has(g.id)} onToggle={() => toggleAll(g.id)} />
          ))}
          <VotesLink q={q.trim()} />
        </>
      )}

      {engine && q.trim() && total === 0 && found.length > 0 && (
        <>
          {/* announced by the status region above */}
          <p className="sr-summary">
            {noneForAll} {eachPart}:
          </p>
          {transposed && (
            <p className="sr-summary">
              <Link to={transposed.to}>
                {transposed.row.act ?? transposed.row.title} in {pair?.country.doc.t}’s implementation table
              </Link>{' '}
              (national measures as EUR-Lex records them)
            </p>
          )}
          {found.map((p) => (
            <PartSection key={`${p.text}:${q}`} part={p} />
          ))}
          {unknown.length > 0 && (
            <p className="sr-votes">
              {unknown.map((p) => `“${p.text}”`).join(', ')} {unknown.length === 1 ? 'is' : 'are'} not in our index as typed:
              check the spelling, or try a shorter or more general word.
            </p>
          )}
          <VotesLink q={q.trim()} />
        </>
      )}

      {engine && q.trim() && total === 0 && found.length === 0 && (
        <EmptyState title={`No results for “${q}”`}>
          {isIdentifier(q) && (
            <p>
              No file in our data has this reference or number. {legislationScope(meta.data?.scope, true)}
            </p>
          )}
          {mep ? (
            <>
              <p>No legislative file, guide or name in our data matches it.</p>
              <p>
                Looking for MEPs? <Link to={mep.to}>{mep.label}</Link>.
              </p>
            </>
          ) : (
            <p>
              Check the spelling, try a shorter or more general word, or search an official reference such as{' '}
              <span className="mono">2021/0106(COD)</span> or a CELEX number such as <span className="mono">32016R0679</span>.
            </p>
          )}
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
