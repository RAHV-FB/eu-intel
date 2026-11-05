import { describe, expect, it } from 'vitest';
import type { Meta, SourceStatusInfo } from '../types/data';
import {
  ageInDays,
  asRetrieved,
  asShownNow,
  blockedNow,
  classifications,
  expiredReason,
  freshness,
  isStale,
  staleNote,
} from './freshness';

// The sources as the refresh of 2 November 2026 left them (data/snapshot/_manifest.json): every core source retrieved
// that day, the Legislative Train's copy from 22 October (its weekly retrievals have failed since). The thresholds
// are the data's (pipeline/freshness.py); a reader's clock is injected as `now`.
const src = (id: string, fetched_at: string | null, stale_after_days: number, extra: Partial<SourceStatusInfo> = {}) =>
  ({ id, name: `Source ${id}`, institution: 'EP', url: '', licence: '', status: 'ok', records: {}, fetched_at, stale_after_days, ...extra }) as SourceStatusInfo;

const META = {
  built_at: '2026-11-02T14:00:00Z',
  snapshot_at: '2026-11-02T13:51:20Z',
  core_data_at: '2026-11-02T13:39:55Z',
  counts: {} as Meta['counts'],
  coverage_notes: [],
  sources: [
    src('ep_procedures', '2026-11-02T13:39:55Z', 9, { core: true, short_name: "Parliament's procedure files" }),
    src('ep_votes', '2026-11-02T13:40:49Z', 9, { core: true, short_name: 'Parliament votes' }),
    src('implementation', '2026-11-02T13:50:49Z', 35, { status: 'partial' }),
    src('train', '2026-10-22T17:53:03Z', 35, {
      status: 'failed',
      attempted_at: '2026-11-02T13:51:20Z',
      short_name: 'Legislative Train',
      labels_expire_after_days: 42,
    }),
  ],
} satisfies Meta;

const at = (iso: string) => new Date(iso);

describe('sources not up to date on the reader’s date', () => {
  it('counts the age from the last successful retrieval, with a fraction, as the pipeline does', () => {
    expect(ageInDays('2026-11-02T12:00:00Z', at('2026-11-05T00:00:00Z'))).toBe(2.5);
    expect(ageInDays(null, at('2026-11-05T00:00:00Z'))).toBeNull();
    expect(ageInDays('not a date', at('2026-11-05T00:00:00Z'))).toBeNull();
  });

  it('says nothing is stale on the day the data was built, nor while every threshold holds', () => {
    for (const now of ['2026-11-02T14:00:00Z', '2026-11-05T09:00:00Z', '2026-11-11T13:39:55Z']) {
      const f = freshness(META, at(now));
      expect(f.stale, now).toEqual([]);
      expect(staleNote(f)).toBe('');
      expect(f.coreAt).toBe('2026-11-02T13:39:55Z'); // the oldest core retrieval, never the newest of any source
    }
  });

  it('flags a failing source once its last success is older than its own threshold, though attempted since', () => {
    // 22 Oct 17:53 + 35 days = 26 Nov 17:53: the Train failed on 2 Nov but is still within its threshold before that
    const train = META.sources[3];
    expect(isStale(train, at('2026-11-26T17:53:03Z'))).toBe(false);
    expect(isStale(train, at('2026-11-26T17:54:00Z'))).toBe(true);
    // the weekly core sources (9 days) go first; the Train's threshold comes from the data, not from this module
    const f = freshness(META, at('2026-11-12T00:00:00Z'));
    expect(f.stale.map((s) => s.id)).toEqual(['ep_procedures', 'ep_votes']);
    expect(f.coreStale).toBe(true);
    const later = freshness(META, at('2026-11-27T00:00:00Z'));
    expect(later.stale.map((s) => s.id)).toEqual(['ep_procedures', 'ep_votes', 'train']);
    const changed = { ...META, sources: META.sources.map((s) => (s.id === 'train' ? { ...s, stale_after_days: 10 } : s)) };
    expect(freshness(changed, at('2026-11-02T00:00:00Z')).stale.map((s) => s.id)).toEqual(['train']);
  });

  it('writes one short note naming each stale source and its last retrieval', () => {
    const onlyTrain = { ...META, sources: META.sources.filter((s) => !s.core) };
    const f = freshness(onlyTrain, at('2026-11-27T00:00:00Z'));
    expect(f.coreStale).toBe(false);
    expect(staleNote(f)).toBe('Not up to date: Legislative Train (last retrieved 22 Oct 2026)');
    // the sources last retrieved on the same day are named together
    expect(staleNote(freshness(META, at('2026-11-27T00:00:00Z')))).toBe(
      "Not up to date: Parliament's procedure files and Parliament votes (last retrieved 2 Nov 2026); Legislative Train " +
        '(last retrieved 22 Oct 2026)',
    );
    const three = { ...META, sources: [...META.sources, src('council', '2026-11-02T13:42:55Z', 9, { short_name: 'Council votes' })] };
    expect(staleNote(freshness(three, at('2026-11-12T00:00:00Z')))).toBe(
      "Not up to date: Parliament's procedure files, Parliament votes and Council votes (last retrieved 2 Nov 2026)",
    );
  });

  it('treats a source never retrieved as stale, and does not judge one without a threshold', () => {
    const never = src('council', null, 9, { status: 'unavailable', core: true, short_name: 'Council votes' });
    expect(isStale(never, at('2026-11-02T14:00:00Z'))).toBe(true);
    expect(staleNote(freshness({ ...META, sources: [never] }, at('2026-11-02T14:00:00Z')))).toBe(
      'Not up to date: Council votes (never retrieved)',
    );
    const unjudged = { ...META.sources[3], stale_after_days: undefined };
    expect(isStale(unjudged, at('2030-01-01T00:00:00Z'))).toBe(false);
    expect(freshness({ ...META, core_data_at: undefined }, at('2026-11-03T00:00:00Z')).coreAt).toBeNull();
  });
});

describe('the Legislative Train’s “blocked” classification on the reader’s date', () => {
  it('is current until its copy is older than the limit the data sets (42 days), then no longer shown', () => {
    // 22 Oct 17:53:03 + 42 days = 3 Dec 17:53:03
    const before = classifications(META, at('2026-12-03T17:53:03Z'))!;
    expect(before.current).toBe(true);
    expect(before.retrievedAt).toBe('2026-10-22T17:53:03Z');
    expect(before.expireAfterDays).toBe(42);
    const after = classifications(META, at('2026-12-03T17:53:04Z'))!;
    expect(after.current).toBe(false);
    expect(asRetrieved(before)).toBe('Legislative Train, as retrieved 22 Oct 2026');
    expect(asRetrieved(before, true)).toBe('Legislative Train, as retrieved 22 October 2026');
    expect(expiredReason(after)).toBe('our latest copy of the Legislative Train was retrieved on 22 Oct 2026, more than 42 days ago');
  });

  it('shows nothing as current while meta.json is not loaded, or when the Train was never retrieved', () => {
    expect(classifications(undefined, at('2026-11-05T00:00:00Z'))).toBeNull();
    expect(blockedNow(true, null)).toBe(false);
    const never = { ...META, sources: [src('train', null, 35, { labels_expire_after_days: 42, short_name: 'Legislative Train' })] };
    const c = classifications(never, at('2026-11-05T00:00:00Z'))!;
    expect(c.current).toBe(false);
    expect(expiredReason(c)).toBe('our copy of the Legislative Train has never been retrieved');
  });

  it('drops the flag from every row once expired, so that lists, filters and counts agree', () => {
    const rows = [
      { id: 'a', officially_blocked: true },
      { id: 'b', officially_blocked: false },
    ];
    const current = classifications(META, at('2026-11-05T00:00:00Z'));
    const expired = classifications(META, at('2026-12-10T00:00:00Z'));
    expect(asShownNow(rows, !!current?.current)).toBe(rows);
    expect(asShownNow(rows, !!expired?.current)).toEqual([
      { id: 'a', officially_blocked: false },
      { id: 'b', officially_blocked: false },
    ]);
    expect(rows[0].officially_blocked).toBe(true); // the loaded data is not changed
    expect(asShownNow(rows, false).some((d) => d.officially_blocked)).toBe(false);
    expect([blockedNow(true, current), blockedNow(true, expired), blockedNow(false, current)]).toEqual([true, false, false]);
  });
});
