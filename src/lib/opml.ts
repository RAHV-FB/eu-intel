/**
 * OPML (2.0) for the files a reader follows: one outline per file, with its Atom feed (data/feeds/dossiers/<id>.xml) and
 * its page, so that a feed reader can subscribe to all of them at once. Made in the browser from the list it keeps; nothing
 * is sent anywhere. The download is a `data:` link (an <a download>), which the page's Content-Security-Policy does not
 * restrict: it governs what the page loads, not a file the reader saves.
 */
import type { ISODate } from '../types/data';

export interface OpmlFile {
  id: string;
  title?: string | null;
  ref?: string | null;
}

const XML_ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };
// characters XML 1.0 does not allow (a control character in a title would make the file unreadable)
const NOT_XML = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g;

export function xmlEscape(s: string): string {
  return s.replace(NOT_XML, '').replace(/[&<>"']/g, (c) => XML_ESCAPES[c]);
}

/** The address of a file's feed and of its page, under the site's address (`site`: origin and base path, with "/"). */
export function feedUrl(site: string, id: string): string {
  return `${site}data/feeds/dossiers/${encodeURIComponent(id)}.xml`;
}

export function pageUrl(site: string, id: string): string {
  return `${site}legislation/${encodeURIComponent(id)}/`;
}

/** RFC 822 date, as OPML's dateCreated wants it ("Thu, 05 Nov 2026 14:00:00 GMT"). */
const rfc822 = (d: Date) => d.toUTCString();

export function opml(files: OpmlFile[], site: string, now: Date, siteName = 'EU Legislative Intelligence'): string {
  const outline = (f: OpmlFile) => {
    const text = f.title ? `${f.title}${f.ref ? ` (${f.ref})` : ''}` : f.ref || f.id;
    return (
      `      <outline type="rss" text="${xmlEscape(text)}" title="${xmlEscape(text)}" ` +
      `xmlUrl="${xmlEscape(feedUrl(site, f.id))}" htmlUrl="${xmlEscape(pageUrl(site, f.id))}"/>`
    );
  };
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<opml version="2.0">',
    '  <head>',
    `    <title>${xmlEscape(`EU legislation I follow – ${siteName}`)}</title>`,
    `    <dateCreated>${rfc822(now)}</dateCreated>`,
    '  </head>',
    '  <body>',
    `    <outline text="${xmlEscape(siteName)}" title="${xmlEscape(siteName)}">`,
    ...files.map(outline),
    '    </outline>',
    '  </body>',
    '</opml>',
    '',
  ].join('\n');
}

/** A `data:` address of the OPML, for an <a download> link. */
export function opmlHref(xml: string): string {
  return `data:text/x-opml;charset=utf-8,${encodeURIComponent(xml)}`;
}

/** "eu-legislation-following-2026-11-05.opml" */
export function opmlFileName(today: ISODate): string {
  return `eu-legislation-following-${today}.opml`;
}
