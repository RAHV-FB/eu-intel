import { useEffect } from 'react';

/** The id of the page's own feed link in <head> (scripts/prerender-routes.mjs writes it into each file's page). */
export const FEED_LINK_ID = 'page-feed';

/**
 * Announces the page's own Atom feed to the browser and feed readers: a `<link rel="alternate"
 * type="application/atom+xml">` in <head>, as the prerendered page of a file has it, kept to the page shown while the
 * site is browsed (removed when the reader leaves the page). The site-wide feed's link stays in every page.
 */
export function useFeedLink(href: string | null, title: string) {
  useEffect(() => {
    if (!href) return;
    let link = document.getElementById(FEED_LINK_ID) as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement('link');
      link.id = FEED_LINK_ID;
      link.rel = 'alternate';
      link.type = 'application/atom+xml';
      document.head.appendChild(link);
    }
    link.href = href;
    link.title = title;
    return () => link?.remove();
  }, [href, title]);
}
