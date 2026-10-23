/**
 * Helpers for tables that become stacked cards on phones (class `table--stack`, styles in components.css).
 * Below 40rem each row shows its title cell first, clamped to three lines, then every other cell as a line
 * labelled by a <StackLabel>. The column headings stay in the markup for screen readers.
 */
import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

/** Visible label for a cell on phones. Hidden from screen readers, which announce the column heading instead. */
export function StackLabel({ children }: { children: ReactNode }) {
  return (
    <span className="stack-label" aria-hidden="true">
      {children}
    </span>
  );
}

// One observer for every title on the page: a table can have hundreds of rows.
const checks = new Map<Element, () => void>();
let observer: ResizeObserver | null = null;

function watch(el: Element, check: () => void): () => void {
  if (typeof ResizeObserver === 'undefined') return () => {};
  observer ??= new ResizeObserver((entries) => {
    for (const e of entries) checks.get(e.target)?.();
  });
  checks.set(el, check);
  observer.observe(el);
  return () => {
    checks.delete(el);
    observer?.unobserve(el);
  };
}

/**
 * The title in a row's title cell: a link when `to` is given. On phones it is clamped to three lines, and a
 * "Show full title" button appears only while the clamp actually hides part of it. The clamp is visual only:
 * screen readers always get the whole title.
 */
export function RowTitle({ to, children }: { to?: string | null; children: ReactNode }) {
  const id = useId();
  const ref = useRef<HTMLElement | null>(null);
  const [clamped, setClamped] = useState(false);
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setClamped(el.scrollHeight > el.clientHeight + 1);
    check();
    return watch(el, check);
  }, []);

  const className = `row-title${open ? ' is-open' : ''}`;
  return (
    <>
      {to ? (
        <Link ref={(el) => void (ref.current = el)} id={id} className={className} to={to}>
          {children}
        </Link>
      ) : (
        <span ref={(el) => void (ref.current = el)} id={id} className={className}>
          {children}
        </span>
      )}
      {(clamped || open) && (
        <button type="button" className="row-title__toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
          {open ? 'Show less' : 'Show full title'}
        </button>
      )}
    </>
  );
}
