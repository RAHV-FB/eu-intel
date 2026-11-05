import { describe, expect, it } from 'vitest';
import type { ActivityItem } from '../../types/data';
import {
  OTHER,
  byWeek,
  changesOf,
  countByKind,
  countLabel,
  formatDays,
  formatRange,
  headlineFile,
  kindKeys,
  latestChanges,
  matches,
  mondayOf,
  sundayOf,
} from './changes';

// TEST-ONLY items shaped like activity.json (2026/0078(COD) as recorded on 5 November 2026)
const EUR_LEX = { institution: 'EUR-Lex' as const, url: 'https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R2387' };
const EP = { institution: 'EP' as const, url: 'https://data.europarl.europa.eu/api/v2/events/2026-0078-PUB-2026-11-03' };
const item = (x: Partial<ActivityItem> & Pick<ActivityItem, 'id' | 'date' | 'kind' | 'title'>): ActivityItem => ({
  detected_at: '2026-11-05T09:26:44Z',
  dossier_id: '2026-0078',
  vote_id: null,
  source: EUR_LEX,
  ...x,
});
const STATUS = item({
  id: 'chg:2026-0078:stage:in_force:2026-11-04',
  date: '2026-11-04',
  kind: 'status_change',
  title: 'AGILE: status now “In force” (previously “Published, not yet in force”)',
  event: 'Status now “In force” (previously “Published, not yet in force”)',
  step_id: 'chg:2026-0078:ev:act-32026R2387-entry_into_force-2026-11-04',
});
const ENTRY = item({
  id: 'chg:2026-0078:ev:act-32026R2387-entry_into_force-2026-11-04',
  date: '2026-11-04',
  kind: 'publication',
  title: 'AGILE: Entered into force',
  event: 'Entered into force',
});
const PUB = item({
  id: 'chg:2026-0078:ev:2026-0078-PUB-2026-11-03',
  date: '2026-11-03',
  kind: 'publication',
  title: 'AGILE: Final act published in the Official Journal',
  event: 'Final act published in the Official Journal',
  source: EP,
});
const VOTE = item({
  id: 'vote:198300',
  date: '2026-10-21',
  kind: 'ep_vote',
  title: 'Parliament adopted: Objection pursuant to Rule 115(2) and (3): Genetically modified soybean MON 87769',
  detected_at: null,
  dossier_id: null,
  vote_id: '198300',
  source: { institution: 'EP', url: 'https://data.europarl.europa.eu/eli/dl/event/198300' },
});
const LONE = item({
  id: 'chg:2023-0421:stage:proposed:2023-12-14',
  date: '2023-12-14',
  kind: 'status_change',
  title: 'Protection of workers…: status now “Proposal under examination” (previously “Published in the Official Journal”)',
  event: 'Status now “Proposal under examination” (previously “Published in the Official Journal”)',
  dossier_id: '2023-0421',
  detected_at: '2026-11-02T13:51:00Z',
});

describe('changes as the What changed page tells them', () => {
  it('tells a status change with the step that gave the status, once, in the status change’s place', () => {
    const cs = changesOf([STATUS, ENTRY, PUB, VOTE]);
    expect(cs.map((c) => c.id)).toEqual([STATUS.id, PUB.id, VOTE.id]);
    const [merged] = cs;
    expect(merged).toMatchObject({
      event: 'Entered into force',
      status: { now: 'In force', was: 'Published, not yet in force' },
      kinds: ['publication', 'status_change'],
      dossierId: '2026-0078',
      week: '2026-11-02',
      fileTitle: 'AGILE',
    });
    expect(merged.sources.map((s) => s.url)).toEqual([EUR_LEX.url]); // the same record, once
    // a status change whose step is not listed says what it changed in its status line, not twice
    const [lone] = changesOf([LONE]);
    expect(lone).toMatchObject({ event: null, status: { now: 'Proposal under examination' }, kinds: ['status_change'] });
    // a vote on no file is read whole, and leads to its page
    expect(cs[2]).toMatchObject({ event: null, headline: VOTE.title, voteId: '198300', dossierId: null, fileTitle: null });
  });

  it('groups by the week of recording, or of the step’s date when recording did not track it', () => {
    expect(mondayOf('2026-11-05')).toBe('2026-11-02');
    expect(mondayOf('2026-11-02')).toBe('2026-11-02');
    expect(mondayOf('2026-11-08')).toBe('2026-11-02');
    expect(mondayOf('2027-01-01')).toBe('2026-12-28');
    expect(sundayOf('2026-12-28')).toBe('2027-01-03');
    const cs = changesOf([STATUS, ENTRY, PUB, VOTE, LONE]);
    // 2023/0421's change was recorded on 2 November 2026: news that week, whatever its date
    expect(cs.find((c) => c.id === LONE.id)?.week).toBe('2026-11-02');
    expect(cs.find((c) => c.id === VOTE.id)?.week).toBe('2026-10-19');
  });

  it('files each change under every topic of its file, and the rest under “other”', () => {
    const topics: Record<string, string[]> = { '2026-0078': ['security', 'economy'], '2023-0421': ['social'] };
    const topicsOf = (id: string | null) => (id ? (topics[id] ?? []) : []);
    const [week, older] = byWeek(changesOf([STATUS, ENTRY, PUB, VOTE, LONE]), topicsOf, ['economy', 'social', 'security']);
    expect(week.week).toBe('2026-11-02');
    expect(week.topics.map((t) => [t.slug, t.changes.length])).toEqual([
      ['economy', 2],
      ['social', 1],
      ['security', 2],
    ]);
    expect(week.changes).toHaveLength(3);
    expect(older.topics.map((t) => t.slug)).toEqual([OTHER]);
    expect(older.tracked).toBe(0);
    // filters: a topic, files of no topic, a kind (a merged change is a status change and a publication)
    const [merged] = changesOf([STATUS, ENTRY]);
    expect(kindKeys(merged)).toEqual(['status', 'publication']);
    expect(matches(merged, topicsOf, 'economy', 'status')).toBe(true);
    expect(matches(merged, topicsOf, 'social', null)).toBe(false);
    expect(matches(changesOf([VOTE])[0], topicsOf, OTHER, 'ep_vote')).toBe(true);
    expect(matches(merged, topicsOf, null, 'ep_vote')).toBe(false);
  });

  it('counts the changes of each kind, in words', () => {
    const counts = countByKind(changesOf([STATUS, ENTRY, PUB, VOTE]));
    expect(counts.map((c) => [c.key, c.n])).toEqual([
      ['status', 1],
      ['publication', 2],
      ['ep_vote', 1],
    ]);
    expect(countLabel('ep_vote', 1)).toBe('1 Parliament vote');
    expect(countLabel('publication', 2)).toBe('2 signatures, publications and entries into force');
    expect(countLabel('status', 1234)).toBe('1,234 status changes');
  });

  it('reads the file’s title from a headline that gives it', () => {
    expect(headlineFile(ENTRY)).toBe('AGILE');
    expect(headlineFile(STATUS)).toBe('AGILE'); // "status now …" in the headline, "Status now …" as the event
    expect(headlineFile(item({ id: 'chg:x:new', date: '2026-10-27', kind: 'new_dossier', title: 'New file: Climate law', event: 'New file' }))).toBe(
      'Climate law',
    );
    expect(headlineFile(VOTE)).toBeNull();
  });

  it('writes days and weeks briefly', () => {
    expect(formatDays(['2026-11-05'])).toBe('5 Nov 2026');
    expect(formatDays(['2026-11-05', '2026-11-02', '2026-11-05'])).toBe('2 and 5 Nov 2026');
    expect(formatDays(['2026-10-30', '2026-11-02', '2026-11-05'])).toBe('30 Oct, 2 and 5 Nov 2026');
    expect(formatDays(['2026-12-29', '2027-01-04'])).toBe('29 Dec 2026 and 4 Jan 2027');
    expect(formatRange('2026-11-02', '2026-11-08')).toBe('2–8 Nov 2026');
    expect(formatRange('2026-09-28', '2026-10-04')).toBe('28 Sep – 4 Oct 2026');
    expect(formatRange('2026-12-28', '2027-01-03')).toBe('28 Dec 2026 – 3 Jan 2027');
  });
});

describe('“This week in EU law” on the reader’s date', () => {
  const day = (d: string) => Date.parse(`${d}T12:00:00Z`);
  const items = [STATUS, ENTRY, PUB, VOTE, LONE];

  it('takes the week of recording up to the latest refresh, called “this week” while it is at most a week old', () => {
    const l = latestChanges(changesOf(items), day('2026-11-06'));
    expect(l.recordedAt).toBe('2026-11-05T09:26:44Z');
    expect(l.from).toBe('2026-10-30');
    expect(l.days).toEqual(['2026-11-02', '2026-11-05']);
    expect(l.changes.map((c) => c.id)).toEqual([STATUS.id, PUB.id, LONE.id]); // newest step first; no untracked vote
    expect(l.current).toBe(true);
    expect(latestChanges(changesOf(items), Date.parse('2026-11-12T09:00:00Z')).current).toBe(true);
    // a reader more than a week after the refresh: the same changes, no longer "this week"
    expect(latestChanges(changesOf(items), Date.parse('2026-11-12T10:00:00Z')).current).toBe(false);
    expect(latestChanges(changesOf(items), day('2026-11-19')).changes).toEqual(l.changes);
  });

  it('without recording, takes the steps of the latest 14 days and never calls them this week', () => {
    const untracked = items.map((i) => ({ ...i, detected_at: null }));
    const l = latestChanges(changesOf(untracked), day('2026-11-06'));
    expect(l.recordedAt).toBeNull();
    expect(l.from).toBe('2026-10-22');
    expect(l.changes.map((c) => c.id)).toEqual([STATUS.id, PUB.id]);
    expect(l.current).toBe(false);
    expect(latestChanges([], day('2026-11-06')).changes).toEqual([]);
  });
});
