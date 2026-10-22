import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { DossierSummary } from '../../types/data';
import { follow, storageAvailable, unfollow, useWatchlist } from '../../lib/watchlist';
import './watchlist.css';

type Snap = Pick<DossierSummary, 'id' | 'last_event' | 'stage' | 'status_label'>;

/**
 * Toggle button for the browser-local watchlist. Writes to localStorage only when clicked.
 */
export function FollowButton({ dossier, showHint = true }: { dossier: Snap; showHint?: boolean }) {
  const list = useWatchlist();
  const following = list.some((e) => e.id === dossier.id);
  const [error, setError] = useState<string | null>(null);

  const toggle = () => {
    setError(null);
    if (!storageAvailable()) {
      setError('Your browser is blocking local storage, so this list cannot be saved here. You can still bookmark a share link from the Following page.');
      return;
    }
    const ok = following ? unfollow(dossier.id) : follow(dossier);
    if (!ok) setError('Could not save in this browser.');
  };

  return (
    <div className="follow">
      <button type="button" className={`btn follow__btn${following ? ' is-following' : ''}`} aria-pressed={following} onClick={toggle}>
        <span aria-hidden="true" className="follow__icon">
          {following ? '★' : '☆'}
        </span>
        {following ? 'Following' : 'Follow this legislation'}
      </button>
      {showHint && (
        <p className="follow__hint meta">
          {following ? (
            <>
              Saved in this browser only. <Link to="/following">See everything you follow</Link>.
            </>
          ) : (
            <>Saved only in this browser. No account, nothing sent anywhere.</>
          )}
        </p>
      )}
      {error && (
        <p className="follow__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
