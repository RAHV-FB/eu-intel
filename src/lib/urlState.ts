/**
 * In-page state (filters, sort order, how many rows are shown) kept in the address's query string, so that the
 * browser's Back button returns to the same list and a filtered view can be bookmarked or shared. Updates
 * replace the current history entry: typing in a filter or showing more rows does not add Back steps.
 */
import { useCallback, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/** Parameters to set; null, undefined or '' removes one (defaults are left out of the address). */
export type ParamPatch = Record<string, string | null | undefined>;

export function useParamState(): [URLSearchParams, (patch: ParamPatch) => void] {
  const { search } = useLocation();
  const navigate = useNavigate();
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const patch = useCallback(
    (p: ParamPatch) => {
      // the current address rather than the last render's, so that two tables on one page never undo each other
      const next = new URLSearchParams(window.location.search);
      for (const [k, v] of Object.entries(p)) {
        if (v == null || v === '') next.delete(k);
        else next.set(k, v);
      }
      const q = next.toString();
      navigate({ search: q ? `?${q}` : '', hash: window.location.hash }, { replace: true, preventScrollReset: true });
    },
    [navigate],
  );
  return [params, patch];
}

/** Rows to show: the parameter when it is a whole number above the first page, else the first page. */
export function shownParam(params: URLSearchParams, key: string, page: number, max = 10000): number {
  const n = Number(params.get(key));
  return Number.isInteger(n) && n > page ? Math.min(n, max) : page;
}
