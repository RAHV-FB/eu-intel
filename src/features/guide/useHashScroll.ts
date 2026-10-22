import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Scroll to the element named by the URL fragment (e.g. /how-the-eu-works#council) once the page has
 * rendered, and whenever the fragment changes through in-app links. Pass `ready` = false while data loads.
 */
export function useHashScroll(ready = true) {
  const { hash } = useLocation();
  useEffect(() => {
    if (!ready || !hash) return;
    const id = decodeURIComponent(hash.slice(1));
    // wait a frame so layout (and the site's scroll-to-top on navigation) has settled
    const t = window.setTimeout(() => {
      const el = document.getElementById(id);
      if (!el) return;
      el.scrollIntoView({ block: 'start' });
      const heading = el.querySelector<HTMLElement>('h2, h3');
      if (heading) {
        heading.setAttribute('tabindex', '-1');
        heading.focus({ preventScroll: true });
      }
    }, 30);
    return () => window.clearTimeout(t);
  }, [hash, ready]);
}
