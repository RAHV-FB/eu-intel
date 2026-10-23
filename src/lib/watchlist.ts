/**
 * "Follow this legislation": a browser-local watchlist.
 *
 * Privacy contract (also explained on /following and /privacy):
 * - Nothing is written until the visitor explicitly clicks "Follow" (pages only read the saved list, to show
 *   what is followed; storageReadable() checks for storage without writing).
 * - Only dossier ids, when each was followed and last viewed (timestamps), and what the visitor last saw (last
 *   recorded event date, stage, status label) are stored, in this browser's localStorage. Nothing is ever sent
 *   anywhere; there are no notifications.
 * - A shareable form (/following?ids=2021-0106,2022-0155) works without any storage.
 */
import { useSyncExternalStore } from 'react';
import type { DossierSummary, ISODate, LifecycleStage } from '../types/data';

const KEY = 'eu-intel.following.v1';
const MAX_ITEMS = 200;
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

export interface SeenState {
  last_event?: ISODate | null;
  stage?: LifecycleStage | null;
  status_label?: string | null;
}

export interface WatchEntry {
  id: string;
  added_at: string; // ISO timestamp
  seen_at: string; // ISO timestamp of the last time the visitor looked at this dossier
  seen: SeenState;
}

type Snapshot = Pick<DossierSummary, 'id' | 'last_event' | 'stage' | 'status_label'>;

export function isValidId(id: string): boolean {
  return ID_RE.test(id);
}

/** Parse "2021-0106,2022-0155" (commas or spaces) into unique, valid ids. */
export function parseIds(param: string | null | undefined): string[] {
  if (!param) return [];
  const out: string[] = [];
  for (const raw of param.split(/[\s,]+/)) {
    const id = raw.trim();
    if (id && isValidId(id) && !out.includes(id)) out.push(id);
    if (out.length >= MAX_ITEMS) break;
  }
  return out;
}

export function shareUrl(ids: string[]): string {
  const path = `${window.location.origin}${import.meta.env.BASE_URL}following`;
  return ids.length ? `${path}?ids=${ids.join(',')}` : path;
}

// ------------------------------------------------------------------ storage (defensive)

function storage(): Storage | null {
  try {
    const s = window.localStorage;
    return s ?? null;
  } catch {
    return null; // blocked by browser settings
  }
}

/** Whether this browser lets the page read localStorage, checked without writing (for checks on page load). A
 * write can still fail (e.g. no quota left): the writers below return false then. */
export function storageReadable(): boolean {
  const s = storage();
  if (!s) return false;
  try {
    s.getItem(KEY);
    return true;
  } catch {
    return false;
  }
}

/** Whether a write works: writes and removes a probe key, so only call it on a click. */
export function storageAvailable(): boolean {
  const s = storage();
  if (!s) return false;
  try {
    const probe = `${KEY}.probe`;
    s.setItem(probe, '1');
    s.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

function readRaw(): WatchEntry[] {
  const s = storage();
  if (!s) return [];
  try {
    const raw = s.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { v?: number; items?: unknown };
    if (!Array.isArray(parsed.items)) return [];
    return parsed.items
      .filter((e): e is WatchEntry => !!e && typeof e === 'object' && typeof (e as WatchEntry).id === 'string' && isValidId((e as WatchEntry).id))
      .map((e) => ({
        id: e.id,
        added_at: typeof e.added_at === 'string' ? e.added_at : '',
        seen_at: typeof e.seen_at === 'string' ? e.seen_at : '',
        seen: {
          last_event: typeof e.seen?.last_event === 'string' ? e.seen.last_event : null,
          stage: typeof e.seen?.stage === 'string' ? e.seen.stage : null,
          status_label: typeof e.seen?.status_label === 'string' ? e.seen.status_label : null,
        },
      }))
      .slice(0, MAX_ITEMS);
  } catch {
    return [];
  }
}

let cache: WatchEntry[] | null = null;
const listeners = new Set<() => void>();

function emit() {
  cache = null;
  listeners.forEach((l) => l());
}

function write(items: WatchEntry[]): boolean {
  const s = storage();
  if (!s) return false;
  try {
    if (items.length) s.setItem(KEY, JSON.stringify({ v: 1, items }));
    else s.removeItem(KEY);
    emit();
    return true;
  } catch {
    return false;
  }
}

function getSnapshot(): WatchEntry[] {
  cache ??= readRaw();
  return cache;
}

const EMPTY: WatchEntry[] = [];

function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY || e.key === null) emit();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener('storage', onStorage);
  };
}

/** Reactive list of followed dossiers (newest first). */
export function useWatchlist(): WatchEntry[] {
  return useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
}

export function getWatchlist(): WatchEntry[] {
  return getSnapshot();
}

function seenFrom(d: Snapshot): SeenState {
  return { last_event: d.last_event ?? null, stage: d.stage, status_label: d.status_label };
}

export function follow(d: Snapshot): boolean {
  const items = getSnapshot().filter((e) => e.id !== d.id);
  const now = new Date().toISOString();
  return write([{ id: d.id, added_at: now, seen_at: now, seen: seenFrom(d) }, ...items].slice(0, MAX_ITEMS));
}

/** Follow several dossiers at once (e.g. from a shared link); keeps existing entries untouched. */
export function followMany(ds: Snapshot[]): boolean {
  const existing = getSnapshot();
  const have = new Set(existing.map((e) => e.id));
  const now = new Date().toISOString();
  const added = ds.filter((d) => !have.has(d.id)).map((d) => ({ id: d.id, added_at: now, seen_at: now, seen: seenFrom(d) }));
  return write([...added, ...existing].slice(0, MAX_ITEMS));
}

export function unfollow(id: string): boolean {
  return write(getSnapshot().filter((e) => e.id !== id));
}

export function clearWatchlist(): boolean {
  return write([]);
}

/** Record that the visitor has now seen the current state of a followed dossier. No-op if not followed. */
export function markSeen(d: Snapshot): void {
  const items = getSnapshot();
  const i = items.findIndex((e) => e.id === d.id);
  if (i < 0) return;
  const prev = items[i];
  const next = seenFrom(d);
  if (prev.seen.last_event === next.last_event && prev.seen.stage === next.stage && prev.seen.status_label === next.status_label) return;
  const copy = items.slice();
  copy[i] = { ...prev, seen: next, seen_at: new Date().toISOString() };
  write(copy);
}

export interface ChangeInfo {
  changed: boolean;
  stageChanged: boolean;
  newEvent: boolean;
  previousLabel?: string | null;
}

/** Compare what the visitor last saw with current data. */
export function changeSince(entry: WatchEntry | undefined, current: Snapshot): ChangeInfo {
  if (!entry) return { changed: false, stageChanged: false, newEvent: false };
  const stageChanged = !!entry.seen.stage && (entry.seen.stage !== current.stage || entry.seen.status_label !== current.status_label);
  const newEvent = !!current.last_event && (!entry.seen.last_event || current.last_event > entry.seen.last_event);
  return { changed: stageChanged || newEvent, stageChanged, newEvent, previousLabel: entry.seen.status_label };
}
