/**
 * When new rules apply on the real build (public/data/applies.json and feeds/applies/): every row on a file of the
 * dataset, with an act of that file and the file's topics; each Member State once in each row's `where`, and "All 27
 * Member States" only when all 27 are bound; a title the page can put in the past tense; and for everything, each
 * topic and each Member State an Atom feed of the next 90 days and a calendar of every row (CRLF, lines of at most 75
 * octets, one event per row, one UID each). Skipped when the data has not been built.
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { AppliesData, DossierSummary, Meta, Topic } from '../../types/data';
import { stepTitle } from '../../lib/format';
import { concerns, whereLead } from './applies';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('applies.json', DATA));
const read = (name: string) => readFileSync(new URL(name, DATA), 'utf8');
const json = <T,>(name: string) => JSON.parse(read(name)) as T;

const MEMBER_STATES = ['AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK'];
const plus = (d: string, n: number) => new Date(Date.parse(`${d}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);

describe.skipIf(!built)('when new rules apply, on the built data', () => {
  const data = built ? json<AppliesData>('applies.json') : { from: '', rows: [] };
  const index = built ? new Map(json<DossierSummary[]>('dossiers/index.json').map((d) => [d.id, d])) : new Map();
  const today = built ? json<Meta>('meta.json').built_at.slice(0, 10) : '';

  it('lists rows on the files of the dataset, by date from 31 days before the build', () => {
    expect(data.rows.length).toBeGreaterThan(0);
    expect(data.from).toBe(plus(today, -31));
    expect(new Set(data.rows.map((r) => r.id)).size).toBe(data.rows.length);
    expect(data.rows.map((r) => r.date)).toEqual(data.rows.map((r) => r.date).sort());
    for (const r of data.rows) {
      const d = index.get(r.dossier_id);
      expect(d, r.id).toBeTruthy();
      expect(d!.celex, r.id).toContain(r.act.celex);
      expect(r.topics, r.id).toEqual(d!.topics);
      expect(r.date >= data.from, r.id).toBe(true);
    }
  });

  it('lists each Member State once in every row’s where, and says “all” only when all 27 are bound', () => {
    for (const r of data.rows) {
      const w = r.where;
      expect([...w.bound, ...w.unknown, ...w.not_bound.map((x) => x.country)].sort(), r.id).toEqual(MEMBER_STATES);
      expect(whereLead(w).startsWith('All 27'), r.id).toBe(w.bound.length === 27);
      for (const x of w.not_bound) expect(x.reason, r.id).toMatch(/\.$/);
    }
  });

  it('gives every row a title the page can put in the past tense', () => {
    for (const r of data.rows) {
      const past = stepTitle(r.title, true);
      if (r.kind === 'national_application') expect(past, r.id).toBe(r.title);
      else expect(past, r.id).not.toBe(r.title);
      expect(stepTitle(past, false), r.id).toBe(r.title);
    }
  });

  it('has an Atom feed of the next 90 days and a calendar of every row for everything, each topic and each Member State', () => {
    const topics = json<Topic[]>('topics.json');
    const scopes = [
      { key: 'all', rows: data.rows },
      ...topics.map((t) => ({ key: `topics/${t.slug}`, rows: data.rows.filter((r) => r.topics.includes(t.slug)) })),
      ...MEMBER_STATES.map((c) => ({ key: `countries/${c}`, rows: data.rows.filter((r) => concerns(r, c)) })),
    ];
    for (const { key, rows } of scopes) {
      const atom = read(`feeds/applies/${key}.xml`);
      expect(atom.startsWith('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'), key).toBe(true);
      const ids = [...atom.matchAll(/<id>tag:rahv-fb\.github\.io,2026:eu-intel\/applies\/([^<]+)<\/id>/g)].map((m) => m[1]);
      const due = rows.filter((r) => r.date >= today && r.date <= plus(today, 90)).map((r) => r.id);
      expect(ids, key).toEqual(due);
      const cal = read(`feeds/applies/${key}.ics`);
      expect(cal.startsWith('BEGIN:VCALENDAR\r\n') && cal.endsWith('END:VCALENDAR\r\n'), key).toBe(true);
      expect(cal.replace(/\r\n/g, '').includes('\n'), key).toBe(false);
      for (const line of cal.split('\r\n')) expect(new TextEncoder().encode(line).length, key).toBeLessThanOrEqual(75);
      const unfolded = cal.replace(/\r\n /g, '');
      const uids = unfolded.split('\r\n').filter((l) => l.startsWith('UID:'));
      expect(uids.length, key).toBe(rows.length);
      expect(new Set(uids).size, key).toBe(uids.length);
    }
  });
});
