import { afterEach, describe, expect, it, vi } from 'vitest';
import { follow, markSeen, storageAvailable, storageReadable, unfollow } from './watchlist';

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
