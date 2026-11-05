/**
 * The implementation tracker on the real build (public/data/transposition.json, public/data/feeds/countries): the same
 * statuses as each Member State's own page, the window with its margin, and one well-formed Atom feed per Member State
 * whose entries are dated by their events, never after the build. Skipped when the data has not been built.
 * (tests/test_tracker.py parses the feeds of the test build with an XML parser.)
 */
import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CountryDetail, Meta, TranspositionTracker } from '../../types/data';
import { addMonths } from '../../lib/deadline';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('transposition.json', DATA));
const read = (name: string) => readFileSync(new URL(name, DATA), 'utf8');
const MEMBER_STATES = ['AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK'];
const TAG = 'tag:rahv-fb.github.io,2026:eu-intel';

/** Unbalanced or crossed elements, a bare "&" in text, a control character. */
function malformed(xml: string): string[] {
  const out: string[] = [];
  const stack: string[] = [];
  for (const m of xml.replace(/^<\?xml[^>]*\?>\s*/, '').matchAll(/<(\/?)([A-Za-z][\w:.-]*)((?:\s+[\w:.-]+="[^"<]*")*)\s*(\/?)>/g)) {
    const [, close, name, , empty] = m;
    if (empty) continue;
    if (!close) stack.push(name);
    else if (stack.pop() !== name) out.push(`</${name}> closes another element`);
  }
  if (stack.length) out.push(`unclosed: ${stack.join(', ')}`);
  if (/&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/.test(xml.replace(/<[^>]*>/g, ''))) out.push('a bare "&" in text');
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(xml)) out.push('a control character');
  return out;
}

const tags = (xml: string, name: string) => [...xml.matchAll(new RegExp(`<${name}>([^<]*)</${name}>`, 'g'))].map((m) => m[1]);

describe.skipIf(!built)('the implementation tracker on the built data', () => {
  const t = built ? (JSON.parse(read('transposition.json')) as TranspositionTracker) : null;
  const meta = built ? (JSON.parse(read('meta.json')) as Meta) : null;

  it('lists the directives of the window, with its month of margin at each end, by deadline', () => {
    const today = t!.built_on;
    const from = new Date(Date.parse(`${addMonths(today, -12 * t!.window.years_back)}T00:00:00Z`) - 31 * 86_400_000).toISOString().slice(0, 10);
    const to = new Date(Date.parse(`${addMonths(today, t!.window.months_ahead)}T00:00:00Z`) + 31 * 86_400_000).toISOString().slice(0, 10);
    expect(t!.directives.length).toBeGreaterThan(0);
    for (const d of t!.directives) {
      expect(d.deadline >= from && d.deadline <= to, `${d.celex} ${d.deadline}`).toBe(true);
      expect(d.countries.map((c) => c.country)).toEqual(MEMBER_STATES);
    }
    const order = t!.directives.map((d) => `${d.deadline} ${d.celex}`);
    expect(order).toEqual([...order].sort());
  });

  it('gives each Member State the status, measures and title its own page gives', () => {
    for (const code of MEMBER_STATES) {
      const page = JSON.parse(read(`countries/${code}.json`)) as CountryDetail;
      const rows = new Map(page.transposition.map((r) => [r.celex, r]));
      for (const d of t!.directives) {
        const row = rows.get(d.celex);
        const c = d.countries.find((x) => x.country === code)!;
        expect(row, `${code} ${d.celex}`).toBeDefined();
        expect([c.status, c.measures], `${code} ${d.celex}`).toEqual([row!.status, row!.measures]);
        expect([d.title, d.deadline, d.dossier_id], d.celex).toEqual([row!.title, row!.deadline, row!.dossier_id]);
      }
    }
  });

  it('lists only open cases, each with the register’s link', () => {
    for (const d of t!.directives)
      for (const c of d.countries)
        for (const k of c.cases ?? []) expect(k.url, `${d.celex} ${c.country} ${k.id}`).toMatch(/^https:\/\/ec\.europa\.eu\/implementing-eu-law\//);
  });

  it('has one well-formed Atom feed per Member State, its newest 100 entries at most, dated by their events', () => {
    const builtOn = meta!.built_at.slice(0, 10);
    for (const code of MEMBER_STATES) {
      const xml = read(`feeds/countries/${code}.xml`);
      expect(malformed(xml), code).toEqual([]);
      expect(xml).toContain('<feed xmlns="http://www.w3.org/2005/Atom">');
      const ids = tags(xml, 'id');
      expect(ids[0]).toBe(`${TAG}/feeds/countries/${code}.xml`);
      const entries = ids.slice(1);
      expect(entries.length, code).toBeGreaterThan(0);
      expect(entries.length, code).toBeLessThanOrEqual(100);
      expect(new Set(entries).size, code).toBe(entries.length);
      for (const id of entries) expect(id).toMatch(new RegExp(`^${TAG}/countries/${code}/(measures|infringements|deadlines)/`));
      const updated = tags(xml, 'updated');
      const own = updated.slice(1);
      expect(own, code).toEqual([...own].sort().reverse()); // newest first
      expect(updated[0], code).toBe(own[0]); // the feed is as new as its newest entry
      for (const u of own) expect(u.slice(0, 10) <= builtOn, `${code} ${u}`).toBe(true);
    }
  });
});
