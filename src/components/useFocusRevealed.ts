import { useEffect, useRef } from 'react';

/**
 * "Show more" under a list: once the new rows are rendered, keyboard focus moves to the first of them (to its first
 * link, or to the element `target` selects in it), so that the focus stays in view, the next Tab goes on through the
 * new rows, and focus is not lost when the button goes away with the last rows. `count` is the number of rows shown;
 * `ref` goes on the element whose children are the rows (a list, or a table body), and the button calls `reveal()`
 * before it shows more.
 */
export function useFocusRevealed<T extends HTMLElement>(count: number, target = 'a[href]') {
  const ref = useRef<T>(null);
  const from = useRef<number | null>(null);
  useEffect(() => {
    const i = from.current;
    if (i == null) return;
    from.current = null;
    const row = ref.current?.children[i];
    if (!(row instanceof HTMLElement)) return;
    const el = row.matches(target) ? row : row.querySelector<HTMLElement>(target);
    if (el) el.focus();
    else {
      // a row without a link: the row itself
      row.tabIndex = -1;
      row.focus();
    }
  }, [count, target]);
  return {
    ref,
    reveal: () => {
      from.current = count;
    },
  };
}
