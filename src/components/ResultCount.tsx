import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';

/** How long a count must stay the same before it is read out: longer than a pause between keys while typing. */
const SETTLE_MS = 800;

/**
 * A list's result count. It is shown at once, and screen readers are told it once it has settled, in the list's one
 * status region: not for every key typed in a search box, and not while `pending` (a search index still loading, while
 * the count shown is not yet the full one). The count the list opens with is not read out (the region starts with it).
 */
export function ResultCount({
  className,
  style,
  pending = false,
  children,
}: {
  className: string;
  style?: CSSProperties;
  pending?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [said, setSaid] = useState<string | null>(null);
  const due = useRef<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  // after every render (each key typed is one): the text shown, as it reads; a new count waits until the renders stop
  useLayoutEffect(() => {
    const text = ref.current?.textContent ?? '';
    if (pending) {
      window.clearTimeout(timer.current);
      due.current = null;
      return;
    }
    if (said === null) {
      setSaid(text);
      return;
    }
    if (due.current === null && text === said) return;
    due.current = text;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      due.current = null;
      setSaid(text);
    }, SETTLE_MS);
  });
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <>
      <p className={className} style={style} ref={ref}>
        {children}
      </p>
      {said !== null && (
        <p className="visually-hidden" role="status" aria-atomic="true">
          {said}
        </p>
      )}
    </>
  );
}
