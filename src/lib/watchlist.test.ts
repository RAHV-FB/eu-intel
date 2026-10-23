import { afterEach, describe, expect, it, vi } from 'vitest';
import { follow, storageAvailable, storageReadable } from './watchlist';

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
});
