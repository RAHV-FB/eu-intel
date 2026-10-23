/**
 * In-page state (filters, sort order, how many rows are shown) kept in the address's query string, so that the
 * browser's Back button returns to the same list and a filtered view can be bookmarked or shared. Updates
 * replace the current history entry: typing in a filter or showing more rows does not add Back steps.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/** Parameters to set; null, undefined or '' removes one (defaults are left out of the address). */
export type ParamPatch = Record<string, string | null | undefined>;

export function useParamState(): [URLSearchParams, (patch: ParamPatch) => void] {
  const { search } = useLocation();
  const navigate = useNavigate();
  // React Router renders a new address in a transition, after the event that changed it. Until it has, the
  // parameters this hook wrote are read from the browser's address, which navigate() has already changed: a select
  // or checkbox would otherwise show its old value in between, so that a box just ticked unticks itself and a
  // second arrow key in a list starts again from the old option.
  const written = useRef<{ path: string; keys: Set<string> } | null>(null);
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const current = new URLSearchParams(search);
  const w = written.current;
  if (w && w.path === window.location.pathname) {
    const actual = new URLSearchParams(window.location.search);
    for (const k of w.keys) {
      const v = actual.get(k);
      if (v == null) current.delete(k);
      else current.set(k, v);
    }
  }
  const key = current.toString();
  const params = useMemo(() => new URLSearchParams(key), [key]);
  const patch = useCallback(
    (p: ParamPatch) => {
      // the current address rather than the last render's, so that two tables on one page never undo each other
      const next = new URLSearchParams(window.location.search);
      for (const [k, v] of Object.entries(p)) {
        if (v == null || v === '') next.delete(k);
        else next.set(k, v);
      }
      const path = window.location.pathname;
      const keys = written.current?.path === path ? written.current.keys : new Set<string>();
      for (const k of Object.keys(p)) keys.add(k);
      written.current = { path, keys };
      const q = next.toString();
      navigate({ search: q ? `?${q}` : '', hash: window.location.hash }, { replace: true, preventScrollReset: true });
      rerender();
    },
    [navigate],
  );
  return [params, patch];
}

/**
 * A text box whose text is kept in the address (parameter `key`). The box keeps its own text while it is typed in
 * and writes it to the address after a pause in typing, and when it loses focus: a box that read its text back
 * from the address would move the caret to the end and drop keys typed before the address had changed, and the
 * browser limits how often a page may change its address. The text is read from the address again when that
 * changes otherwise (Back, Forward, "Clear all filters"). Each write also removes the `reset` parameters (the rows
 * shown: a new search starts from the first page).
 */
export function useParamText(key: string, reset: readonly string[] = [], delay = 300) {
  const [params, patch] = useParamState();
  const inAddress = params.get(key) ?? '';
  const [text, setText] = useState(inAddress);
  const written = useRef(inAddress);
  const timer = useRef<number | undefined>(undefined);
  const write = (v: string) => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    if (v === written.current) return;
    written.current = v;
    patch({ [key]: v, ...Object.fromEntries(reset.map((k) => [k, null])) });
  };
  useEffect(() => {
    if (inAddress === written.current) return; // what this box wrote
    window.clearTimeout(timer.current);
    timer.current = undefined;
    written.current = inAddress;
    setText(inAddress);
  }, [inAddress]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return {
    value: text,
    set: (v: string) => {
      setText(v);
      window.clearTimeout(timer.current);
      const path = window.location.pathname;
      timer.current = window.setTimeout(() => {
        if (window.location.pathname === path) write(v);
        else timer.current = undefined; // another page has opened meanwhile: not into its address
      }, delay);
    },
    /** Write now (the box lost focus, e.g. to a link in the results). */
    flush: () => {
      if (timer.current !== undefined) write(text);
    },
  };
}

/** A patch that removes every parameter of the current address ("Clear all filters"), then sets `keep`. */
export function clearAllParams(keep: ParamPatch = {}): ParamPatch {
  return { ...Object.fromEntries([...new URLSearchParams(window.location.search).keys()].map((k) => [k, null])), ...keep };
}

/** Rows to show: the parameter when it is a whole number above the first page, else the first page. */
export function shownParam(params: URLSearchParams, key: string, page: number, max = 10000): number {
  const n = Number(params.get(key));
  return Number.isInteger(n) && n > page ? Math.min(n, max) : page;
}
