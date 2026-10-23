import { useId, useState, type ReactNode } from 'react';
import { useMediaQuery } from './useMediaQuery';

/** Below this width list pages keep only their search box open (same breakpoint as the legislation explorer). */
export const PHONE_WIDTH = '(max-width: 39.99rem)';

/**
 * The filter controls after a list's search box. On wider screens they render in place, as direct items of the
 * surrounding `.filters` grid; on phones they sit behind a toggle button that says how many are set, so the first
 * results stay near the top of the screen. Put it inside the form, straight after the search field.
 */
export function CollapsibleFilters({ label, active, children }: { label: string; active: number; children: ReactNode }) {
  const narrow = useMediaQuery(PHONE_WIDTH);
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      {narrow && (
        <button type="button" className="btn filters__toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
          {open ? `Hide ${label.toLowerCase()}` : label}
          {active > 0 && <span className="filters__count"> ({active} active)</span>}
        </button>
      )}
      <div id={id} className="filters__rest" hidden={narrow && !open}>
        {children}
      </div>
    </>
  );
}
