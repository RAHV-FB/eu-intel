import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LifecycleStage } from '../types/data';
import { follow, getWatchlist, markSeen, storageAvailable, storageReadable, unfollow } from './watchlist';

/** A localStorage stand-in that records every call; `full` makes writes throw (e.g. no quota left). */
function fakeStorage(calls: string[], full = false): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    key: (i: number) => [...data.keys()][i] ?? null,
    getItem: (k: string) => {
      calls.push(`get ${k}`);
      return data.get(k) ?? null;
    },
    setItem: (k: string, v: string) => {
      calls.push(`set ${k}`);
      if (full) throw new DOMException('quota', 'QuotaExceededError');
      data.set(k, v);
    },
    removeItem: (k: string) => {
      calls.push(`remove ${k}`);
      data.delete(k);
    },
    clear: () => data.clear(),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('watchlist storage checks', () => {
  it('checks for storage on page load without writing anything', () => {
    // /following used to write and remove a probe key when it loaded, before any click
    const calls: string[] = [];
    vi.stubGlobal('window', { localStorage: fakeStorage(calls) });
    expect(storageReadable()).toBe(true);
    expect(calls.filter((c) => !c.startsWith('get '))).toEqual([]);
  });

  it('reports blocked storage, and a write that fails on a click', () => {
    vi.stubGlobal('window', {
      get localStorage(): Storage {
        throw new DOMException('denied', 'SecurityError');
      },
    });
    expect(storageReadable()).toBe(false);
    const calls: string[] = [];
    vi.stubGlobal('window', { localStorage: fakeStorage(calls, true) });
    expect(storageReadable()).toBe(true); // reading works ...
    expect(storageAvailable()).toBe(false); // ... writing does not: the click handlers see it
    expect(follow({ id: '2021-0106', last_event: '2024-07-12', stage: 'in_force', status_label: 'In force' })).toBe(false);
  });

  it('writes nothing when a file page opens until the file is followed; then records what was last seen there', () => {
    // the dossier page calls markSeen() when it loads (src/pages/Dossier.tsx)
    const calls: string[] = [];
    vi.stubGlobal('window', { localStorage: fakeStorage(calls) });
    const writes = () => calls.filter((c) => !c.startsWith('get '));
    const ai = { id: '2021-0106', last_event: '2024-07-12', stage: 'in_force' as const, status_label: 'In force' };
    unfollow('none'); // start from an empty list (this also resets the module's cached copy of it)
    calls.length = 0;
    markSeen(ai);
    expect(writes()).toEqual([]);
    expect(follow(ai)).toBe(true); // the "Follow" click
    calls.length = 0;
    markSeen(ai); // nothing new since
    expect(writes()).toEqual([]);
    markSeen({ ...ai, last_event: '2026-10-20' });
    expect(writes()).toEqual(['set eu-intel.following.v1']);
  });
});

describe('the list followed in several tabs of the browser', () => {
  const KEY = 'eu-intel.following.v1';
  type File = { id: string; last_event: string; stage: LifecycleStage; status_label: string };
  const ai: File = { id: '2021-0106', last_event: '2024-07-12', stage: 'in_force', status_label: 'In force' };
  const dsa: File = { id: '2020-0361', last_event: '2022-10-27', stage: 'in_force', status_label: 'In force' };
  const csam: File = { id: '2022-0155', last_event: '2026-10-01', stage: 'negotiations', status_label: 'In negotiations' };
  const entry = (d: File) => ({ id: d.id, added_at: '2026-11-05T10:00:00.000Z', seen_at: '2026-11-05T10:00:00.000Z', seen: { last_event: d.last_event, stage: d.stage, status_label: d.status_label } });
  const stored = (s: Storage) => (JSON.parse(s.getItem(KEY) ?? '{"items":[]}') as { items: { id: string }[] }).items.map((e) => e.id);

  /** The "storage" event listeners this tab has added. */
  let listeners: ((e: { key: string | null }) => void)[] = [];

  /** This tab, with a storage that another tab of the same site also writes (no list is on screen in this tab). */
  function thisTab(): Storage {
    const storage = fakeStorage([]);
    listeners = [];
    vi.stubGlobal('window', {
      localStorage: storage,
      addEventListener: (type: string, l: (e: { key: string | null }) => void) => type === 'storage' && listeners.push(l),
      removeEventListener: (_type: string, l: (e: { key: string | null }) => void) => (listeners = listeners.filter((x) => x !== l)),
    });
    unfollow('none'); // start from an empty list (this also resets the module's cached copy of it)
    return storage;
  }

  it('a file followed in another tab is kept when this tab follows, unfollows or views one', () => {
    const storage = thisTab();
    expect(follow(ai)).toBe(true);
    expect(getWatchlist().map((e) => e.id)).toEqual([ai.id]);
    // another tab follows CSAM: it writes the whole list, with this tab's AI Act
    storage.setItem(KEY, JSON.stringify({ v: 1, items: [entry(csam), entry(ai)] }));
    // this tab then follows the DSA: written from its earlier copy of the list, CSAM was lost
    expect(follow(dsa)).toBe(true);
    expect(stored(storage)).toEqual([dsa.id, csam.id, ai.id]);
    // another tab unfollows the AI Act; this tab then views CSAM's page, which records what it saw there
    storage.setItem(KEY, JSON.stringify({ v: 1, items: [entry(dsa), entry(csam)] }));
    markSeen({ ...csam, last_event: '2026-11-04' });
    expect(stored(storage)).toEqual([dsa.id, csam.id]);
    // and unfollows the DSA: the AI Act, unfollowed elsewhere, does not come back
    expect(unfollow(dsa.id)).toBe(true);
    expect(stored(storage)).toEqual([csam.id]);
  });

  it('the list this tab shows is the stored one once another tab has changed it', () => {
    const storage = thisTab();
    expect(follow(ai)).toBe(true);
    expect(getWatchlist().map((e) => e.id)).toEqual([ai.id]);
    storage.setItem(KEY, JSON.stringify({ v: 1, items: [entry(csam), entry(ai)] }));
    // the browser tells the other tabs of a change in storage (a "storage" event): the list read before is out of date
    for (const l of listeners) l({ key: KEY });
    expect(getWatchlist().map((e) => e.id)).toEqual([csam.id, ai.id]);
  });
});
