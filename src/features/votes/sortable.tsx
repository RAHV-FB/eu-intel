/**
 * Keyboard-friendly sortable tables: header cells contain a <button>, the <th> carries aria-sort.
 * Used by votes, people and countries features.
 */
import { useMemo, useState, type ReactNode } from 'react';
import { useParamState } from '../../lib/urlState';
import './common.css';

export type SortDir = 'asc' | 'desc';
export interface SortState<K extends string> {
  key: K;
  dir: SortDir;
}

type Accessor<T> = (row: T) => string | number | null | undefined;

/** Nulls always sort last, whatever the direction. */
export function compareValues(a: string | number | null | undefined, b: string | number | null | undefined, dir: SortDir): number {
  const an = a == null || (typeof a === 'number' && Number.isNaN(a));
  const bn = b == null || (typeof b === 'number' && Number.isNaN(b));
  if (an && bn) return 0;
  if (an) return 1;
  if (bn) return -1;
  const r = typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'en', { sensitivity: 'base' });
  return dir === 'asc' ? r : -r;
}

export function useSortable<T, K extends string>(
  rows: T[],
  accessors: Record<K, Accessor<T>>,
  initial: SortState<K>,
  /** default direction when a column is first selected */
  firstDir: Partial<Record<K, SortDir>> = {},
  /** keep the order in this query parameter ("name-desc"), so that Back returns to it; left out when it is `initial` */
  urlKey?: string,
) {
  const [local, setLocal] = useState<SortState<K>>(initial);
  const [params, patch] = useParamState();
  const fromUrl = urlKey ? /^(.+)-(asc|desc)$/.exec(params.get(urlKey) ?? '') : null;
  const sort: SortState<K> = !urlKey
    ? local
    : fromUrl && Object.prototype.hasOwnProperty.call(accessors, fromUrl[1])
      ? { key: fromUrl[1] as K, dir: fromUrl[2] as SortDir }
      : initial;
  const setSort = (s: SortState<K>) => {
    if (!urlKey) return setLocal(s);
    patch({ [urlKey]: s.key === initial.key && s.dir === initial.dir ? null : `${s.key}-${s.dir}` });
  };
  const sorted = useMemo(() => {
    const acc = accessors[sort.key];
    return [...rows].sort((a, b) => compareValues(acc(a), acc(b), sort.dir));
    // accessors are expected to be stable in meaning for a given key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort.key, sort.dir]);
  const toggle = (key: K) =>
    setSort(sort.key === key ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: firstDir[key] ?? 'asc' });
  return { sorted, sort, toggle, setSort };
}

/** <th> with an accessible sort button. */
export function SortTh<K extends string>({
  k,
  sort,
  onSort,
  children,
  num,
  className,
  scope = 'col',
}: {
  k: K;
  sort: SortState<K>;
  onSort: (k: K) => void;
  children: ReactNode;
  num?: boolean;
  className?: string;
  scope?: 'col' | 'colgroup';
}) {
  const active = sort.key === k;
  const ariaSort = active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none';
  return (
    <th scope={scope} aria-sort={ariaSort} className={[num ? 'num' : '', className ?? ''].join(' ').trim() || undefined}>
      <button type="button" className={`sort-btn${active ? ' is-active' : ''}`} onClick={() => onSort(k)}>
        <span>{children}</span>
        <span className="sort-btn__icon" aria-hidden="true">
          {active ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}
        </span>
      </button>
    </th>
  );
}
