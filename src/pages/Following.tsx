import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { DossierDetail } from '../types/data';
import { loadData } from '../lib/data';
import { asOfToday, formatDate, formatDateTime, formatNumber } from '../lib/format';
import {
  changeSince,
  clearWatchlist,
  follow,
  followMany,
  markSeen,
  parseIds,
  shareUrl,
  storageReadable,
  unfollow,
  useWatchlist,
  type WatchEntry,
} from '../lib/watchlist';
import { EmptyState, Loading, PageHeader, StatusBadge } from '../components/ui';
import { dossierPath, institutionSuffix, isMissing, useDocumentTitle } from '../features/legislation/labels';
import { latestDone } from '../features/legislation/dossier/Summary';
import { todayISO } from '../features/legislation/explorer';
import '../features/legislation/common.css';
import '../features/watchlist/watchlist.css';

type Loaded = { state: 'ok'; d: DossierDetail } | { state: 'missing' } | { state: 'error' };

/** Load dossier details for the given ids (each file is small and cached by loadData). */
function useDossiers(ids: string[]): Record<string, Loaded> {
  const [map, setMap] = useState<Record<string, Loaded>>({});
  const key = ids.join(',');
  useEffect(() => {
    let alive = true;
    for (const id of ids) {
      loadData<DossierDetail>(`dossiers/${id}.json`).then(
        (d) => alive && setMap((m) => ({ ...m, [id]: { state: 'ok', d } })),
        (e) => alive && setMap((m) => ({ ...m, [id]: isMissing(e) ? { state: 'missing' } : { state: 'error' } })),
      );
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return map;
}

/** The element that receives focus for an item (its title), after an action removed the control that had it. */
const itemTitle = (id: string) => document.querySelector<HTMLElement>(`[data-follow-title="${CSS.escape(id)}"]`);

function Item({
  id,
  loaded,
  entry,
  shared,
  followingIds,
  today,
  onRemove,
  onSeen,
  onFollow,
}: {
  id: string;
  loaded: Loaded | undefined;
  entry: WatchEntry | undefined;
  shared: boolean;
  followingIds: Set<string>;
  today: string;
  onRemove: (id: string, title: string) => void;
  onSeen: (d: DossierDetail) => void;
  onFollow: (d: DossierDetail) => void;
}) {
  if (!loaded)
    return (
      <li className="following__item">
        <p className="meta">Loading {id}…</p>
      </li>
    );
  if (loaded.state !== 'ok')
    return (
      <li className="following__item">
        <div>
          <p className="following__title">
            <span className="mono" tabIndex={-1} data-follow-title={id}>
              {id}
            </span>
          </p>
          <p className="following__latest">
            {loaded.state === 'missing'
              ? 'This file is no longer in our dataset (or the id is wrong).'
              : 'This file could not be loaded right now.'}
          </p>
        </div>
        {!shared && followingIds.has(id) && (
          <div className="following__item-actions">
            <button type="button" className="btn lx-btn-quiet" onClick={() => onRemove(id, id)} aria-label={`Remove ${id}`}>
              Remove
            </button>
          </div>
        )}
      </li>
    );

  const d = loaded.d;
  const change = !shared ? changeSince(entry, d) : null;
  const latest = latestDone(d.timeline ?? [], today);
  const isFollowed = followingIds.has(id);

  return (
    <li className="following__item">
      <div>
        <h3 className="following__title">
          <Link to={dossierPath(d.id)} data-follow-title={d.id}>
            {d.title}
          </Link>
        </h3>
        <div className="following__status">
          <StatusBadge stage={d.stage} label={d.status_label} blocked={d.officially_blocked} />
          {change?.changed && (
            <span className="lx-changed">
              Changed since you last looked
              {change.stageChanged && change.previousLabel ? ` (was “${change.previousLabel}”)` : ''}
            </span>
          )}
          <span className="meta mono">{d.ref}</span>
        </div>
        <p className="following__latest">
          {latest ? (
            <>
              Latest: <time dateTime={latest.date}>{formatDate(latest.date)}</time> — {latest.title}
              {institutionSuffix(latest.title, latest.institution) && (
                <span className="meta"> ({institutionSuffix(latest.title, latest.institution)})</span>
              )}
            </>
          ) : (
            'No dated step recorded.'
          )}
        </p>
        {d.next_step?.text && <p className="following__latest">Next: {asOfToday(d.next_step.text, today)}</p>}
        {!shared && entry?.seen_at && (
          <p className="following__latest meta">You last looked {formatDateTime(entry.seen_at)}</p>
        )}
      </div>
      <div className="following__item-actions">
        {!shared && change?.changed && (
          <button type="button" className="btn" onClick={() => onSeen(d)}>
            Mark as seen
          </button>
        )}
        {isFollowed ? (
          <button type="button" className="btn lx-btn-quiet" onClick={() => onRemove(d.id, d.title)} aria-label={`Unfollow ${d.title}`}>
            Unfollow
          </button>
        ) : (
          <button type="button" className="btn" onClick={() => onFollow(d)} aria-label={`Follow ${d.title} in this browser`}>
            Follow
          </button>
        )}
      </div>
    </li>
  );
}

export default function Following() {
  const [params] = useSearchParams();
  const shared = params.has('ids');
  const sharedIds = useMemo(() => parseIds(params.get('ids')), [params]);
  const watch = useWatchlist();
  const followingIds = useMemo(() => new Set(watch.map((w) => w.id)), [watch]);
  const ids = shared ? sharedIds : watch.map((w) => w.id);
  const loaded = useDossiers(ids);
  const today = todayISO();
  // checked without writing: nothing is stored before a click; a write that fails then shows the same notice
  const readable = useMemo(() => storageReadable(), []);
  const [writeFailed, setWriteFailed] = useState(false);
  const canStore = readable && !writeFailed;
  const onSaved = (ok: boolean) => setWriteFailed(!ok);
  useDocumentTitle(shared ? 'Shared list of legislation' : 'Followed legislation');

  const [confirmClear, setConfirmClear] = useState(false);
  const [copied, setCopied] = useState(false);
  const shareId = useId();
  const link = shareUrl(ids);

  // Actions that remove the control that has keyboard focus (Unfollow, Clear all, Mark as seen…) move focus to
  // the next sensible place once the page has re-rendered, and a status message says what happened.
  const [announcement, setAnnouncement] = useState('');
  const focusNext = useRef<(() => HTMLElement | null) | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  const afterRender = (target: () => HTMLElement | null, message?: string) => {
    focusNext.current = target;
    setFocusTick((t) => t + 1);
    if (message) setAnnouncement(message);
  };
  useEffect(() => {
    const target = focusNext.current;
    focusNext.current = null;
    target?.()?.focus();
  }, [focusTick]);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const emptyRef = useRef<HTMLDivElement>(null);
  const clearRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const ownListRef = useRef<HTMLAnchorElement>(null);

  const entries = new Map(watch.map((w) => [w.id, w]));
  const changedIds = shared
    ? []
    : ids.filter((id) => {
        const l = loaded[id];
        return l?.state === 'ok' && changeSince(entries.get(id), l.d).changed;
      });
  // Changed first; otherwise keep the stored order (most recently followed first).
  const ordered = shared ? ids : [...changedIds, ...ids.filter((id) => !changedIds.includes(id))];
  const notYetFollowed = sharedIds.filter((id) => !followingIds.has(id) && loaded[id]?.state === 'ok');

  const remove = (id: string, title: string) => {
    onSaved(unfollow(id));
    // a shared list keeps the file, whose button becomes "Follow" and keeps focus: only the browser's list changed
    if (shared) {
      setAnnouncement(`You no longer follow ${title} in this browser.`);
      return;
    }
    const i = ordered.indexOf(id);
    const next = ordered[i + 1] ?? ordered[i - 1];
    afterRender(() => (next ? itemTitle(next) : emptyRef.current ?? headingRef.current), `Removed ${title} from the list.`);
  };
  const followOne = (d: DossierDetail) => {
    const ok = follow(d);
    onSaved(ok);
    if (ok) setAnnouncement(`Now following ${d.title} in this browser.`);
  };
  const seen = (d: DossierDetail) => {
    markSeen(d);
    afterRender(() => itemTitle(d.id), `Marked ${d.title} as seen.`);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      (document.getElementById(shareId) as HTMLInputElement | null)?.select();
    }
  };

  return (
    <div className="container page">
      <PageHeader
        eyebrow="Following"
        title={shared ? 'Shared list of legislation' : 'Legislation you follow'}
        lead={
          shared
            ? 'Someone shared this list of EU legislative files with you. It shows their current status from official records.'
            : 'Keep an eye on a few files: see their current status, the latest recorded step, and what changed since you last looked.'
        }
      />

      <div className="following__privacy" id="about-storage">
        <p>
          <strong>What is stored, and where.</strong> When you click “Follow”, this site saves in this browser’s local storage
          the identifier of each file you follow (for example <span className="mono">2021-0106</span>), when you followed it
          and when you last viewed it, and the status you last saw. It is never sent to us or anyone else: this site has no
          server, accounts, cookies or analytics. See the <Link to="/privacy">privacy notice</Link>.
        </p>
        <p>
          <strong>No notifications.</strong> Come back to this page to see what changed. Clearing your browser data, or “Clear
          all” below, removes the list. To use it on another device, copy the share link.
        </p>
        {!canStore && (
          <p role={writeFailed ? 'alert' : undefined}>
            <strong>Your browser is blocking local storage</strong>, so a list cannot be saved here. Share links still work.
          </p>
        )}
      </div>
      {/* stays mounted when the list empties, so that the result of the last action is still announced */}
      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>

      {shared && (
        <div className="following__shared-note" style={{ marginTop: 'var(--sp-5)' }}>
          <p>
            {sharedIds.length
              ? `This shared list has ${plural(sharedIds.length)}. It is not saved in your browser unless you choose to follow them.`
              : 'This shared link does not contain any valid file identifiers.'}
          </p>
          <div className="following__actions">
            {canStore && notYetFollowed.length > 0 && (
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => {
                  const ds = notYetFollowed.map((id) => loaded[id]).flatMap((l) => (l?.state === 'ok' ? [l.d] : []));
                  onSaved(followMany(ds));
                  afterRender(() => ownListRef.current, `Now following ${plural(ds.length)} in this browser.`);
                }}
              >
                {notYetFollowed.length === 1 ? 'Follow this file' : `Follow these ${notYetFollowed.length} files`} in this browser
              </button>
            )}
            <Link to="/following" className="btn" ref={ownListRef}>
              View my own list{watch.length ? ` (${watch.length})` : ''}
            </Link>
          </div>
        </div>
      )}

      {ids.length === 0 ? (
        !shared && (
          <div style={{ marginTop: 'var(--sp-6)' }} ref={emptyRef} tabIndex={-1}>
            <EmptyState title="You are not following any legislation yet">
              <p>
                Open any file and choose <strong>Follow this legislation</strong>. Start from the{' '}
                <Link to="/legislation">legislation explorer</Link> or the <Link to="/">selected major legislation</Link>.
              </p>
            </EmptyState>
          </div>
        )
      ) : (
        <>
          <div className="following__bar">
            <h2 ref={headingRef} tabIndex={-1}>
              {plural(ids.length)}
              {changedIds.length > 0 && <span className="meta"> · {formatNumber(changedIds.length)} changed since you last looked</span>}
            </h2>
            {!shared && (
              <div className="following__actions">
                {changedIds.length > 1 && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      changedIds.forEach((id) => {
                        const l = loaded[id];
                        if (l?.state === 'ok') markSeen(l.d);
                      });
                      afterRender(() => headingRef.current, `Marked ${plural(changedIds.length)} as seen.`);
                    }}
                  >
                    Mark all as seen
                  </button>
                )}
                {confirmClear ? (
                  <>
                    <button
                      type="button"
                      className="btn lx-btn-danger"
                      onClick={() => {
                        const n = ids.length;
                        onSaved(clearWatchlist());
                        setConfirmClear(false);
                        afterRender(() => emptyRef.current, `Removed all ${plural(n)} from the list.`);
                      }}
                    >
                      Yes, remove all {ids.length}
                    </button>
                    <button
                      type="button"
                      className="btn lx-btn-quiet"
                      ref={cancelRef}
                      onClick={() => {
                        setConfirmClear(false);
                        afterRender(() => clearRef.current);
                      }}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn lx-btn-danger"
                    ref={clearRef}
                    onClick={() => {
                      setConfirmClear(true);
                      afterRender(() => cancelRef.current); // the safe choice
                    }}
                  >
                    Clear all
                  </button>
                )}
              </div>
            )}
          </div>

          {ids.some((id) => !loaded[id]) && Object.keys(loaded).length === 0 && <Loading label="Loading current status…" />}

          <ul className="following__list">
            {ordered.map((id) => (
              <Item
                key={id}
                id={id}
                loaded={loaded[id]}
                entry={entries.get(id)}
                shared={shared}
                followingIds={followingIds}
                today={today}
                onRemove={remove}
                onSeen={seen}
                onFollow={followOne}
              />
            ))}
          </ul>

          <div className="following__share">
            <label htmlFor={shareId} className="lx-field__label">
              {shared ? 'Link to this shared list' : 'Share or bookmark this list'}
            </label>
            <div className="following__share-row">
              <input id={shareId} className="input lx-input" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
              <button type="button" className="btn" onClick={copy}>
                {copied ? 'Copied' : 'Copy link'}
              </button>
            </div>
            <p className="meta" role="status">
              {copied
                ? 'Link copied to your clipboard.'
                : 'Anyone with this link sees the same files with their current status. The link contains only the file identifiers.'}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function plural(n: number) {
  return `${formatNumber(n)} legislative file${n === 1 ? '' : 's'}`;
}
