import { describe, expect, it } from 'vitest';
import { feedUrl, opml, opmlFileName, opmlHref, pageUrl, xmlEscape } from './opml';
import { eurlexSearchUrl, notCovered } from './scope';

const SITE = 'https://rahv-fb.github.io/eu-intel/';
const NOW = new Date('2026-11-05T14:00:00Z');

describe('the OPML of the files a reader follows', () => {
  const xml = opml(
    [
      { id: '2021-0106', title: 'Artificial Intelligence Act', ref: '2021/0106(COD)' },
      { id: '2016-0224A', title: 'Asylum <Procedure> & "Return" — it\u0007\'s', ref: '2016/0224A(COD)' },
      { id: '2099-0001' }, // not loaded: named by its id
    ],
    SITE,
    NOW,
  );

  it('lists each file’s Atom feed and page, under the site', () => {
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<opml version="2.0">')).toBe(true);
    expect(xml).toContain('<dateCreated>Thu, 05 Nov 2026 14:00:00 GMT</dateCreated>');
    const outlines = [...xml.matchAll(/<outline type="rss" text="([^"]*)" title="[^"]*" xmlUrl="([^"]*)" htmlUrl="([^"]*)"\/>/g)];
    expect(outlines.map((m) => [m[1], m[2], m[3]])).toEqual([
      [
        'Artificial Intelligence Act (2021/0106(COD))',
        'https://rahv-fb.github.io/eu-intel/data/feeds/dossiers/2021-0106.xml',
        'https://rahv-fb.github.io/eu-intel/legislation/2021-0106/',
      ],
      [
        'Asylum &lt;Procedure&gt; &amp; &quot;Return&quot; — it&apos;s (2016/0224A(COD))',
        'https://rahv-fb.github.io/eu-intel/data/feeds/dossiers/2016-0224A.xml',
        'https://rahv-fb.github.io/eu-intel/legislation/2016-0224A/',
      ],
      ['2099-0001', feedUrl(SITE, '2099-0001'), pageUrl(SITE, '2099-0001')],
    ]);
    // balanced elements: one opml, head, body, and the group outline around the files
    expect(xml.match(/<outline /g)).toHaveLength(4);
    expect(xml.match(/<\/outline>/g)).toHaveLength(1);
    expect(xml).not.toMatch(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/);
  });

  it('is offered as a data: link the browser saves, named by the day', () => {
    const href = opmlHref(xml);
    expect(href.startsWith('data:text/x-opml;charset=utf-8,')).toBe(true);
    expect(decodeURIComponent(href.slice(href.indexOf(',') + 1))).toBe(xml);
    expect(opmlFileName('2026-11-05')).toBe('eu-legislation-following-2026-11-05.opml');
    expect(xmlEscape(`a&b<c>"d"'e'`)).toBe('a&amp;b&lt;c&gt;&quot;d&quot;&apos;e&apos;');
  });
});

describe('a search that finds nothing', () => {
  it('links the same words on EUR-Lex, encoded', () => {
    expect(eurlexSearchUrl('glyphosate')).toBe('https://eur-lex.europa.eu/search.html?scope=EURLEX&text=glyphosate&lang=en&type=quick');
    expect(eurlexSearchUrl(' novel food & insects ')).toBe(
      'https://eur-lex.europa.eu/search.html?scope=EURLEX&text=novel%20food%20%26%20insects&lang=en&type=quick',
    );
    expect(new URL(eurlexSearchUrl('a#b?c=d')).searchParams.get('text')).toBe('a#b?c=d');
  });

  it('says what the data does not cover', () => {
    const lines = notCovered({ procedure_types: ['COD', 'CNS', 'APP'], procedures_from_year: 2014, acts_from: '2014-07-01', ep_roll_call_votes: 1, dossiers_without_topic: 1, other_type_dossiers: 12 });
    expect(lines[0]).toMatch(/^Implementing and delegated acts/);
    expect(lines.join(' ')).toContain('Laws adopted before 2014.');
    expect(lines.join(' ')).toContain('National law');
    expect(notCovered(undefined).join(' ')).not.toContain('before');
  });
});
