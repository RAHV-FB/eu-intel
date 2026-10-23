import { useLayoutEffect, useState } from 'react';

/**
 * The first of `texts` (longest first) that fits in the input, measured in the input's own font, and again when the
 * input is resized: on a phone a long placeholder is cut off at the field's edge, which loses its end (where the
 * examples of reference formats are). The last text is used when none fits. Returns the text and the input's ref.
 */
export function useFittingPlaceholder(texts: readonly string[]): [string, (el: HTMLInputElement | null) => void] {
  const [input, setInput] = useState<HTMLInputElement | null>(null);
  const [index, setIndex] = useState(0);
  const key = texts.join('\n');
  useLayoutEffect(() => {
    const ctx = input && texts.length > 1 && typeof ResizeObserver !== 'undefined' ? document.createElement('canvas').getContext('2d') : null;
    if (!input || !ctx) return;
    const fit = () => {
      const cs = getComputedStyle(input);
      const room = input.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      if (room <= 0) return; // not displayed
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const i = texts.findIndex((t) => ctx.measureText(t).width <= room);
      setIndex(i < 0 ? texts.length - 1 : i);
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(input);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, key]);
  return [texts[Math.min(index, texts.length - 1)] ?? '', setInput];
}
