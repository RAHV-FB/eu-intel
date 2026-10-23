import { Suspense, useEffect, useRef, useState, type RefObject } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import type { Meta } from '../types/data';
import { useData } from '../lib/data';
import { formatDateTime } from '../lib/format';
import { ErrorBoundary } from './ErrorBoundary';
import { SearchBox } from './SearchBox';
import { Loading } from './ui';
import { useScrollableTables } from './scrollableTables';

export const NAV = [
  { to: '/', label: 'Discover', end: true },
  { to: '/legislation', label: 'Legislation' },
  { to: '/votes', label: 'Votes' },
  { to: '/people', label: 'People & Parties' },
  { to: '/countries', label: 'Countries' },
  { to: '/how-the-eu-works', label: 'How the EU Works' },
];

export const SITE_NAME = 'EU Legislative Intelligence';

/**
 * On every route change after the first page load: scroll to the top, move keyboard focus to the main
 * content (so the next Tab starts there, not at the top of the document) and announce the new page title
 * to screen-reader users once the page has set it.
 */
function useRouteFocus(announce: (text: string) => void) {
  const { pathname } = useLocation();
  const previous = useRef<string | null>(null);
  useEffect(() => {
    window.scrollTo(0, 0);
    // First load: leave focus where the browser put it. (Comparing paths also ignores effect re-runs.)
    const firstLoad = previous.current === null;
    const samePath = previous.current === pathname;
    previous.current = pathname;
    if (firstLoad || samePath) return;
    document.getElementById('main')?.focus({ preventScroll: true });
    // Pages set document.title after their data loads; announce it once it has settled (clearing the
    // region first so that a page with the same title as the previous one is still announced).
    announce('');
    let timer = window.setTimeout(() => announce(document.title), 700);
    const title = document.querySelector('title');
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => announce(document.title), 400);
    });
    if (title) observer.observe(title, { childList: true, characterData: true, subtree: true });
    const stop = window.setTimeout(() => observer.disconnect(), 5000);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(stop);
      observer.disconnect();
    };
  }, [pathname, announce]);
}

/**
 * Keep the focused element clear of the sticky header (WCAG 2.4.11). Browsers scroll a newly focused element
 * only just into the viewport, which leaves it under the header, notably when tabbing backwards.
 * (Done here rather than with `scroll-padding-top` on <html>, which would also add the header height to the
 * offsets that in-page anchors already set with scroll-margin-top.)
 */
function useFocusClearOfHeader(header: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const onFocusIn = (e: FocusEvent) => {
      const h = header.current;
      const el = e.target;
      if (!h || !(el instanceof HTMLElement) || h.contains(el) || el.id === 'main' || el.classList.contains('skip-link')) return;
      const r = el.getBoundingClientRect();
      const clear = h.getBoundingClientRect().bottom + 12; // room for the focus outline
      if (r.height > 0 && r.top < clear && r.bottom > 0) window.scrollBy(0, r.top - clear);
    };
    document.addEventListener('focusin', onFocusIn);
    return () => document.removeEventListener('focusin', onFocusIn);
  }, [header]);
}

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const { pathname } = useLocation();
  const headerRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const searchToggleRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    setMenuOpen(false);
    setSearchOpen(false);
  }, [pathname]);
  useRouteFocus(setAnnouncement);
  useFocusClearOfHeader(headerRef);
  useScrollableTables(mainRef);
  const isHome = pathname === '/';

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <p className="visually-hidden" aria-live="polite" aria-atomic="true" data-route-announcer="">
        {announcement}
      </p>
      <header className="site-header" ref={headerRef}>
        <div className="container site-header__inner">
          <Link to="/" className="brand" aria-label={`${SITE_NAME} — home`}>
            <span className="brand__mark" aria-hidden="true">
              <svg viewBox="0 0 32 32" width="28" height="28">
                <rect width="32" height="32" rx="6" fill="#003399" />
                <path d="M9 10h14M9 16h10M9 22h14" stroke="#FFCC00" strokeWidth="2.5" strokeLinecap="round" />
              </svg>
            </span>
            <span className="brand__name">
              EU Legislative <span>Intelligence</span>
            </span>
          </Link>
          {!isHome && (
            <>
              <div className="site-header__search">
                <SearchBox compact />
              </div>
              {/* Phones and narrow tablets: the search field above is hidden, so offer it behind a button. */}
              <button
                ref={searchToggleRef}
                type="button"
                className="search-toggle"
                aria-expanded={searchOpen}
                aria-controls="header-search"
                onClick={() => {
                  setSearchOpen((o) => !o);
                  setMenuOpen(false);
                }}
              >
                <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
                  {searchOpen ? (
                    <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  ) : (
                    <>
                      <circle cx="8.5" cy="8.5" r="5.75" fill="none" stroke="currentColor" strokeWidth="2" />
                      <path d="M13 13l4.5 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </>
                  )}
                </svg>
                <span className="visually-hidden">Search</span>
              </button>
            </>
          )}
          <button
            type="button"
            className="menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="primary-nav"
            onClick={() => {
              setMenuOpen((o) => !o);
              setSearchOpen(false);
            }}
          >
            <span aria-hidden="true">{menuOpen ? '✕' : '☰'}</span>
            <span className="visually-hidden">Menu</span>
          </button>
        </div>
        {!isHome && (
          <div
            id="header-search"
            className="header-search"
            hidden={!searchOpen}
            onKeyDown={(e) => {
              // The first Escape closes open suggestions (SearchBox), the next one closes the panel.
              if (e.key !== 'Escape' || (e.target as HTMLElement).getAttribute('aria-expanded') === 'true') return;
              setSearchOpen(false);
              searchToggleRef.current?.focus();
            }}
          >
            <div className="container">{searchOpen && <SearchBox compact autoFocus />}</div>
          </div>
        )}
        <nav id="primary-nav" className={`primary-nav${menuOpen ? ' is-open' : ''}`} aria-label="Primary">
          <div className="container">
            <ul>
              {NAV.map((n) => (
                <li key={n.to}>
                  <NavLink to={n.to} end={n.end}>
                    {n.label}
                  </NavLink>
                </li>
              ))}
              <li className="primary-nav__search">
                <NavLink to="/search">Search</NavLink>
              </li>
            </ul>
          </div>
        </nav>
      </header>
      <main id="main" tabIndex={-1} ref={mainRef}>
        <ErrorBoundary resetKey={pathname}>
          <Suspense fallback={<div className="container page"><Loading /></div>}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>
      <Footer />
    </>
  );
}

function Footer() {
  const { data: meta } = useData<Meta>('meta.json');
  return (
    <footer className="site-footer">
      <div className="container site-footer__inner">
        <div className="site-footer__about">
          <strong>{SITE_NAME}</strong>
          <p>
            An independent, nonpartisan project. <strong>Not an official website of the European Union</strong> or of
            any EU institution, and not endorsed by them. All legislative data comes from official EU open-data sources;
            see <Link to="/about#sources">data sources</Link>.
          </p>
          {meta && (
            <p className="meta">
              Data last refreshed: {formatDateTime(meta.snapshot_at ?? meta.built_at)} ·{' '}
              <Link to="/about#coverage">What’s covered</Link>
            </p>
          )}
        </div>
        <nav aria-label="Footer" className="site-footer__links">
          <ul>
            <li>
              <Link to="/about">About & methodology</Link>
            </li>
            <li>
              <Link to="/about#sources">Data sources & licences</Link>
            </li>
            <li>
              <Link to="/following">Followed legislation</Link>
            </li>
            <li>
              <Link to="/privacy">Privacy</Link>
            </li>
            <li>
              <a href={`${import.meta.env.BASE_URL}data/feeds/updates.xml`}>Atom feed</a>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
