import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import type { Meta } from '../types/data';
import { useData } from '../lib/data';
import { formatDateTime } from '../lib/format';
import { SearchBox } from './SearchBox';

export const NAV = [
  { to: '/', label: 'Discover', end: true },
  { to: '/legislation', label: 'Legislation' },
  { to: '/votes', label: 'Votes' },
  { to: '/people', label: 'People & Parties' },
  { to: '/countries', label: 'Countries' },
  { to: '/how-the-eu-works', label: 'How the EU Works' },
];

export const SITE_NAME = 'EU Legislative Intelligence';

function ScrollAndFocus() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
    // Move focus to main content on route change for screen-reader users (not on first load).
    const main = document.getElementById('main');
    if (main && document.activeElement && document.activeElement !== document.body) main.focus({ preventScroll: true });
  }, [pathname]);
  return null;
}

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setMenuOpen(false), [pathname]);
  const isHome = pathname === '/';

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <ScrollAndFocus />
      <header className="site-header">
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
            <div className="site-header__search">
              <SearchBox compact />
            </div>
          )}
          <button
            type="button"
            className="menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="primary-nav"
            onClick={() => setMenuOpen((o) => !o)}
          >
            <span aria-hidden="true">{menuOpen ? '✕' : '☰'}</span>
            <span className="visually-hidden">Menu</span>
          </button>
        </div>
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
            </ul>
          </div>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
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
