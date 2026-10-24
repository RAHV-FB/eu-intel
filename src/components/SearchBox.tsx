import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import type { SearchKind } from '../types/data';
import { loadSearch, type SearchEngine, type SearchHit } from '../lib/search';
import { useFittingPlaceholder } from './useFittingPlaceholder';

const KIND_LABEL: Record<SearchKind, string> = {
  dossier: 'Legislation',
  act: 'Legal act',
  mep: 'MEP',
  group: 'Political group',
  party: 'National party',
  country: 'Country',
  topic: 'Topic',
  vote: 'Vote',
  page: 'Guide',
};

export function kindLabel(k: SearchKind): string {
  return KIND_LABEL[k];
}

/** How an approximate match matched (search.ts tiers 6-7): "Similar word: macro", or "All but one of the words". */
export function approximateNote(h: SearchHit): string | null {
  if (!h.approximate) return null;
  return h.similar?.length ? `Similar word: ${h.similar.slice(0, 2).join(', ')}` : 'All but one of the words';
}

/** Placeholders, longest first: the longest that fits the field is shown (useFittingPlaceholder). */
const PLACEHOLDERS = [
  'Search a law, topic, politician, party or country…',
  'Search a law, topic, MEP or country…',
  'Search a law, MEP or country…',
  'Search…',
];
/** The same for the large search fields (home page, search page). */
export const PAGE_PLACEHOLDERS = [
  'Search a law, topic, MEP, party or country…',
  'Search a law, topic, MEP or country…',
  'Search a law, MEP or country…',
  'A law, MEP or country…',
  'Search…',
];

/**
 * Global search field with keyboard-navigable suggestions (ARIA combobox pattern).
 * Enter without a highlighted suggestion opens the full results page (/search?q=…).
 */
export function SearchBox({
  compact,
  autoFocus,
  placeholder = PLACEHOLDERS,
  initial = '',
  label,
}: {
  compact?: boolean;
  autoFocus?: boolean;
  placeholder?: readonly string[];
  initial?: string;
  /** names the search landmark when the page has a second one (the header's) */
  label?: string;
}) {
  const [q, setQ] = useState(initial);
  const [engine, setEngine] = useState<SearchEngine | null>(null);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const navigate = useNavigate();
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const [shownPlaceholder, inputRef] = useFittingPlaceholder(placeholder);

  // Load the index lazily on first interaction.
  const ensureEngine = () => {
    if (!engine) loadSearch().then(setEngine, () => undefined);
  };

  useEffect(() => {
    if (!engine || q.trim().length < 2) {
      setHits([]);
      return;
    }
    // as-you-type: the last word may be unfinished ("artific"); whole-word matches still rank first
    setHits(engine.search(q, { limit: 8, typing: true }));
    setActive(-1);
  }, [q, engine]);

  const go = (url: string) => {
    setOpen(false);
    navigate(url);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (active >= 0 && hits[active]) return go(hits[active].doc.u);
    if (q.trim()) go(`/search?q=${encodeURIComponent(q.trim())}`);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, hits.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, -1));
    } else if (e.key === 'Escape') {
      // With suggestions open, Escape only closes them: the browser would also clear a search field.
      if (open && hits.length > 0) e.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  };

  const showList = open && hits.length > 0;

  // In the sticky header (and the phone search panel) the list fits in the screen below the field and scrolls there:
  // the page cannot scroll a suggestion into view, notably on short or zoomed screens. (Elsewhere the page scrolls.)
  useLayoutEffect(() => {
    const list = listRef.current;
    if (!showList || !list || !compact) return;
    const fit = () => {
      const bottom = window.visualViewport?.height ?? window.innerHeight;
      list.style.maxHeight = `${Math.max(96, bottom - list.getBoundingClientRect().top - 8)}px`;
    };
    fit();
    window.addEventListener('resize', fit);
    window.visualViewport?.addEventListener('resize', fit);
    return () => {
      window.removeEventListener('resize', fit);
      window.visualViewport?.removeEventListener('resize', fit);
    };
  }, [showList, compact]);
  // The highlighted suggestion is kept in view, so that keyboard users see what Enter opens; back in the field, or
  // with new suggestions, the list starts from the top.
  useLayoutEffect(() => {
    if (!showList) return;
    if (active >= 0) document.getElementById(`${listId}-opt-${active}`)?.scrollIntoView({ block: 'nearest' });
    else if (listRef.current) listRef.current.scrollTop = 0;
  }, [active, hits, listId, showList]);

  return (
    <form role="search" aria-label={label} className={`searchbox${compact ? ' searchbox--compact' : ''}`} onSubmit={onSubmit}>
      <label className="visually-hidden" htmlFor={`${listId}-input`}>
        Search legislation, people, parties and countries
      </label>
      <div className="searchbox__field">
        <svg className="searchbox__icon" viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
          <circle cx="8.5" cy="8.5" r="5.75" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <input
          ref={inputRef}
          id={`${listId}-input`}
          className="searchbox__input"
          type="search"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-opt-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          autoFocus={autoFocus}
          placeholder={shownPlaceholder}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            ensureEngine();
            setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
        />
        {!compact && (
          <button type="submit" className="btn btn--primary searchbox__submit">
            Search
          </button>
        )}
      </div>
      {showList && (
        <ul id={listId} role="listbox" className="searchbox__list" ref={listRef}>
          {hits.map((h, i) => (
            <li
              key={`${h.doc.k}:${h.doc.id}`}
              id={`${listId}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'is-active' : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                go(h.doc.u);
              }}
            >
              <span className="searchbox__kind">{KIND_LABEL[h.doc.k]}</span>
              <span className="searchbox__title">{h.doc.t}</span>
              {h.doc.s && <span className="searchbox__sub">{h.doc.s}</span>}
              {h.approximate && <span className="searchbox__sub searchbox__approx">{approximateNote(h)}</span>}
            </li>
          ))}
          <li
            role="option"
            aria-selected={false}
            className="searchbox__all"
            onMouseDown={(e) => {
              e.preventDefault();
              go(`/search?q=${encodeURIComponent(q.trim())}`);
            }}
          >
            See all results for “{q.trim()}”
          </li>
        </ul>
      )}
    </form>
  );
}
