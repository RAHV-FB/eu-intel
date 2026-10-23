import { useEffect, type RefObject } from 'react';

/**
 * Makes every `.table-wrap` inside `root` usable when its table is wider than the screen:
 *  - the wrapper becomes a named, keyboard-focusable region (arrow keys scroll it);
 *  - `data-overflow` turns on the edge shadows and the "scroll sideways" hint (see base.css);
 *  - `data-sticky` keeps a row-header first column in view while scrolling.
 * Tables that fit are left untouched. Runs on any page, so feature components need no changes.
 */
const MANAGED = 'data-scroll-managed';

/** The heading that introduces an element: the nearest h2–h4 before it in document order. */
function headingBefore(el: HTMLElement): string {
  for (let node: Element | null = el; node && node.tagName !== 'MAIN'; node = node.parentElement) {
    for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
      if (/^H[2-4]$/.test(sib.tagName)) return sib.textContent ?? '';
      const inner = sib.querySelectorAll('h2, h3, h4');
      if (inner.length) return inner[inner.length - 1].textContent ?? '';
    }
  }
  return '';
}

function regionName(wrap: HTMLElement): string {
  const text = wrap.querySelector('caption')?.textContent || headingBefore(wrap);
  const name = text
    .replace(/\s*Select a column heading to sort\.?/i, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[.,;:]$/, '');
  return `${name || 'Table'} (scrolls sideways)`;
}

function hasOwnHint(wrap: HTMLElement): boolean {
  return !!wrap.previousElementSibling?.querySelector('.scroll-hint');
}

function update(wrap: HTMLElement) {
  const over = wrap.scrollWidth > wrap.clientWidth + 1;
  if (over) {
    if (!wrap.hasAttribute('tabindex')) {
      wrap.setAttribute('tabindex', '0');
      wrap.setAttribute(MANAGED, '');
    }
    if (wrap.hasAttribute(MANAGED)) {
      wrap.setAttribute('role', 'region');
      wrap.setAttribute('aria-label', regionName(wrap));
    }
    wrap.setAttribute('data-overflow', '');
    if (!hasOwnHint(wrap)) wrap.setAttribute('data-hint', '');
    // Keep the first column in view only when it holds row headers and is not too wide to share the screen.
    const first = wrap.querySelector<HTMLElement>('tbody tr > :first-child');
    const sticky = !!first && first.tagName === 'TH' && first.getAttribute('scope') === 'row' && first.offsetWidth <= wrap.clientWidth * 0.45;
    wrap.toggleAttribute('data-sticky', sticky);
  } else {
    wrap.removeAttribute('data-overflow');
    wrap.removeAttribute('data-hint');
    wrap.removeAttribute('data-sticky');
    if (wrap.hasAttribute(MANAGED)) {
      wrap.removeAttribute('tabindex');
      wrap.removeAttribute('role');
      wrap.removeAttribute('aria-label');
      wrap.removeAttribute(MANAGED);
    }
  }
}

export function useScrollableTables(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const seen = new Set<HTMLElement>();
    const resize = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = (e.target as HTMLElement).closest<HTMLElement>('.table-wrap');
        if (w) update(w);
      }
    });
    let frame = 0;
    const scan = () => {
      frame = 0;
      for (const w of seen) {
        if (!w.isConnected) {
          resize.unobserve(w);
          seen.delete(w);
        }
      }
      el.querySelectorAll<HTMLElement>('.table-wrap').forEach((w) => {
        if (!seen.has(w)) {
          seen.add(w);
          resize.observe(w);
          const table = w.querySelector('table');
          if (table) resize.observe(table);
        }
        update(w);
      });
    };
    // Tables change size when rows are added, sorted or revealed; re-check after DOM changes (once per frame).
    const mutations = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(scan);
    });
    mutations.observe(el, { childList: true, subtree: true });
    scan();
    return () => {
      if (frame) cancelAnimationFrame(frame);
      mutations.disconnect();
      resize.disconnect();
    };
  }, [root]);
}
