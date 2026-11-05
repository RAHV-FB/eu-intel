/**
 * The Atom feeds on the real build (public/data/feeds): one per file, each well-formed (elements nested and closed, text
 * escaped) with the elements Atom requires (RFC 4287: a feed's id, title and updated; each entry's id, title, updated and
 * a link to its page), an id once per feed, and the same id for the same entry in every feed. Skipped when the data has
 * not been built. (tests/test_feeds.py parses the feeds of the test build with an XML parser.)
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { DossierSummary } from '../../types/data';

const DATA = new URL('../../../public/data/', import.meta.url);
const built = existsSync(new URL('feeds/dossiers/', DATA));
const read = (name: string) => readFileSync(new URL(name, DATA), 'utf8');

/** Problems of well-formedness: unbalanced or crossed elements, a bare "&" or "<" in text, a control character. */
function malformed(xml: string): string[] {
  const out: string[] = [];
  const body = xml.replace(/^<\?xml[^>]*\?>\s*/, '');
  const stack: string[] = [];
  for (const m of body.matchAll(/<(\/?)([A-Za-z][\w:.-]*)((?:\s+[\w:.-]+="[^"<]*")*)\s*(\/?)>/g)) {
    const [, close, name, , empty] = m;
    if (empty) continue;
    if (!close) stack.push(name);
    else if (stack.pop() !== name) out.push(`</${name}> closes another element`);
  }
  if (stack.length) out.push(`unclosed: ${stack.join(', ')}`);
  const text = body.replace(/<[^>]*>/g, '');
  if (/&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/.test(text)) out.push('a bare "&" in text');
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(xml)) out.push('a control character');
  if ((body.match(/</g) ?? []).length !== (body.match(/>/g) ?? []).length) out.push('a bare "<" or ">"');
  return out;
}

const tag = (xml: string, name: string) => [...xml.matchAll(new RegExp(`<${name}>([^<]*)</${name}>`, 'g'))].map((m) => m[1]);

describe.skipIf(!built)('the Atom feeds on the built data', () => {
  const index = built ? (JSON.parse(read('dossiers/index.json')) as DossierSummary[]) : [];
  const files = built ? readdirSync(new URL('feeds/dossiers/', DATA)).filter((f) => f.endsWith('.xml')) : [];

  it('has one feed per file, each well-formed Atom with its required elements', () => {
    expect(files.map((f) => f.replace(/\.xml$/, '')).sort()).toEqual(index.map((d) => d.id).sort());
    for (const f of files) {
      const xml = read(`feeds/dossiers/${f}`);
      expect(malformed(xml), f).toEqual([]);
      expect(xml.startsWith('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'), f).toBe(true);
      const head = xml.split('<entry>')[0];
      expect(tag(head, 'id'), f).toEqual([`tag:rahv-fb.github.io,2026:eu-intel/feeds/dossiers/${f}`]);
      expect(tag(head, 'title')[0], f).toBeTruthy();
      expect(tag(head, 'updated')[0], f).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
      expect(head, f).toMatch(/<author><name>[^<]+<\/name>/);
      const entries = xml.split('<entry>').slice(1);
      expect(entries.length, f).toBeLessThanOrEqual(10);
      const ids = entries.map((e) => tag(e, 'id')[0]);
      expect(new Set(ids).size, f).toBe(ids.length);
      for (const e of entries) {
        expect(tag(e, 'title')[0], f).toBeTruthy();
        expect(tag(e, 'updated')[0], f).toBeTruthy();
        expect(e, f).toMatch(/<link rel="alternate" type="text\/html" href="https:\/\/[^"]+"\/>/);
        // full titles: never the activity list's shortened file title
        expect(tag(e, 'title')[0], f).not.toMatch(/…: /);
      }
    }
  });

  it('gives an entry the same id and title in its file’s feed and in the site-wide feed', () => {
    const entries = (xml: string) => new Map(xml.split('<entry>').slice(1).map((e) => [tag(e, 'id')[0], tag(e, 'title')[0]]));
    const siteWide = entries(read('feeds/updates.xml'));
    let shared = 0;
    for (const f of files) {
      for (const [id, title] of entries(read(`feeds/dossiers/${f}`))) {
        if (!siteWide.has(id)) continue;
        shared++;
        // a status change is told with its step where both are listed: a file's feed lists steps of any date
        if (!id.includes(':stage:')) expect(title, id).toBe(siteWide.get(id));
      }
    }
    expect(shared).toBeGreaterThan(0);
    expect(malformed(read('feeds/updates.xml'))).toEqual([]);
  });
});
