import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

/** A lazily loaded page script that failed to download (messages differ between browsers). */
function isCodeDownload(error: Error): boolean {
  return /dynamically imported module|importing a module script failed|loading chunk|module script/i.test(`${error.name} ${error.message}`);
}

/**
 * Catches render errors in a page so the header, navigation and footer stay usable.
 * `resetKey` (the route) clears the error when the visitor navigates elsewhere.
 */
export class ErrorBoundary extends Component<{ resetKey: string; children: ReactNode }, { error: Error | null; key: string }> {
  state = { error: null as Error | null, key: this.props.resetKey };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  static getDerivedStateFromProps(props: { resetKey: string }, state: { error: Error | null; key: string }) {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page could not be displayed', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="container page">
        <header className="page-header">
          <h1>This page could not be displayed</h1>
          <p className="lead">
            {isCodeDownload(this.state.error)
              ? 'Part of the website’s code could not be downloaded, for example because the connection was interrupted. Reloading the page usually fixes this.'
              : 'Something in the data for this page could not be shown. The rest of the site is not affected.'}
          </p>
        </header>
        <p>
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </p>
        <p>
          <Link to="/">Go to the homepage</Link> · <Link to="/legislation">Browse legislation</Link> ·{' '}
          <Link to="/about#sources">Data sources</Link>
        </p>
      </div>
    );
  }
}
