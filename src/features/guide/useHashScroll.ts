import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** Input by which a visitor scrolls or moves on themselves: the page stops keeping the target in place. */
const INTENT = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const;

/**
 * Scroll to the element named by the URL fragment (e.g. /how-the-eu-works#council) once the page has
 * rendered, and whenever the fragment changes through in-app links. Pass `ready` = false while data loads.
 * For a short while afterwards the target is kept in place if the layout above it still moves (late text, a table
 * filled in), until the visitor scrolls.
 */
export function useHashScroll(ready = true) {
  const { hash } = useLocation();
  useEffect(() => {
    if (!ready || !hash) return;
    const id = decodeURIComponent(hash.slice(1));
    let frame = 0;
    const stop = () => {
      window.cancelAnimationFrame(frame);
      for (const e of INTENT) window.removeEventListener(e, stop);
    };
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
      const top = el.getBoundingClientRect().top;
      const until = performance.now() + 1000;
      for (const e of INTENT) window.addEventListener(e, stop, { passive: true });
      const keep = () => {
        if (Math.abs(el.getBoundingClientRect().top - top) > 1) el.scrollIntoView({ block: 'start' });
        if (performance.now() < until) frame = window.requestAnimationFrame(keep);
        else stop();
      };
      frame = window.requestAnimationFrame(keep);
    }, 30);
    return () => {
      window.clearTimeout(t);
      stop();
    };
  }, [hash, ready]);
}
