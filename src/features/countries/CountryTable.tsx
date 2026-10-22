import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { CountryIndicatorValue, CountrySummary } from '../../types/data';
import { formatNumber } from '../../lib/format';
import { SortTh, useSortable } from '../votes/sortable';
import './countries.css';

export interface IndicatorColumn {
  id: string;
  label: string;
  unit: string;
  period: string;
  definition: string;
  source: CountryIndicatorValue['source'];
}

/** Indicator columns present in the data, in first-seen order. */
export function indicatorColumns(rows: CountrySummary[]): IndicatorColumn[] {
  const seen = new Map<string, IndicatorColumn>();
  for (const r of rows)
    for (const i of r.indicators)
      if (!seen.has(i.indicator))
        seen.set(i.indicator, { id: i.indicator, label: i.label, unit: i.unit, period: i.period, definition: i.definition, source: i.source });
  return [...seen.values()];
}

export function formatIndicator(value: number | null | undefined, unit: string): string {
  if (value == null) return '—';
  const n = value.toLocaleString('en-GB', { maximumFractionDigits: 1 });
  if (unit === '%') return `${n}%`;
  return unit ? `${n} ${unit}` : n;
}

export function CountryTable({
  rows,
  councilAvailable,
  infringementsAvailable,
}: {
  rows: CountrySummary[];
  councilAvailable: boolean;
  infringementsAvailable: boolean;
}) {
  const inds = useMemo(() => indicatorColumns(rows), [rows]);
  const accessors = useMemo(() => {
    const a: Record<string, (r: CountrySummary) => string | number | null | undefined> = {
      name: (r) => r.name,
      meps: (r) => r.meps_active,
      groups: (r) => Object.values(r.groups).filter((n) => n > 0).length,
      cfor: (r) => r.council_positions.for,
      cagainst: (r) => r.council_positions.against,
      cabstain: (r) => r.council_positions.abstain,
      cnp: (r) => r.council_positions.not_participating,
      infr: (r) => r.open_infringements ?? null,
    };
    for (const i of inds) a[`ind:${i.id}`] = (r) => r.indicators.find((x) => x.indicator === i.id)?.value ?? null;
    return a;
  }, [inds]);
  const { sorted, sort, toggle } = useSortable<CountrySummary, string>(rows, accessors, { key: 'name', dir: 'asc' }, {
    meps: 'desc',
    groups: 'desc',
    cfor: 'desc',
    cagainst: 'desc',
    cabstain: 'desc',
    cnp: 'desc',
    infr: 'desc',
  });
  const hasNp = rows.some((r) => r.council_positions.not_participating > 0);
  const councilCols = councilAvailable ? (hasNp ? 4 : 3) : 1;
  const implCols = inds.length + 1;

  return (
    <>
    <p className="note" style={{ marginBottom: 'var(--sp-2)' }}>
      Three separate kinds of information — representation in Parliament, participation in Council votes, and implementation of EU law.
      They are not combined into a score. Select a column heading to sort.<span className="scroll-hint"> Scroll sideways to see all columns.</span>
    </p>
    <div className="table-wrap table-card">
      <table className="table ctable">
        <caption className="visually-hidden">
          Countries compared: representation in Parliament, Council of the EU votes, and implementation of EU law. Select a column heading
          to sort.
        </caption>
        <colgroup>
          <col />
        </colgroup>
        <colgroup span={2} />
        <colgroup span={councilCols} />
        <colgroup span={implCols} />
        <thead>
          <tr>
            <th scope="col" rowSpan={2} aria-sort={sort.key === 'name' ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
              <button type="button" className={`sort-btn${sort.key === 'name' ? ' is-active' : ''}`} onClick={() => toggle('name')}>
                <span>Country</span>
                <span className="sort-btn__icon" aria-hidden="true">
                  {sort.key === 'name' ? (sort.dir === 'asc' ? '▲' : '▼') : '↕'}
                </span>
              </button>
            </th>
            <th scope="colgroup" colSpan={2} className="grp-start grp-rep">
              Representation in Parliament
            </th>
            <th scope="colgroup" colSpan={councilCols} className="grp-start grp-council">
              Council of the EU votes
            </th>
            <th scope="colgroup" colSpan={implCols} className="grp-start grp-impl">
              Implementation of EU law
            </th>
          </tr>
          <tr>
            <SortTh k="meps" sort={sort} onSort={toggle} num className="grp-start grp-rep">
              Current MEPs
            </SortTh>
            <SortTh k="groups" sort={sort} onSort={toggle} num className="grp-rep">
              Groups
            </SortTh>
            {councilAvailable ? (
              <>
                <SortTh k="cfor" sort={sort} onSort={toggle} num className="grp-start grp-council">
                  For
                </SortTh>
                <SortTh k="cagainst" sort={sort} onSort={toggle} num className="grp-council">
                  Against
                </SortTh>
                <SortTh k="cabstain" sort={sort} onSort={toggle} num className="grp-council">
                  Abstained
                </SortTh>
                {hasNp && (
                  <SortTh k="cnp" sort={sort} onSort={toggle} num className="grp-council">
                    Not part.
                  </SortTh>
                )}
              </>
            ) : (
              <th scope="col" className="grp-start grp-council">
                Positions
              </th>
            )}
            {inds.map((i, n) => (
              <SortTh key={i.id} k={`ind:${i.id}`} sort={sort} onSort={toggle} num className={`grp-impl${n === 0 ? ' grp-start' : ''}`}>
                {i.label} ({i.period})
              </SortTh>
            ))}
            <SortTh k="infr" sort={sort} onSort={toggle} num className={`grp-impl${inds.length === 0 ? ' grp-start' : ''}`}>
              Open infringement cases
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.code}>
              <th scope="row" style={{ fontWeight: 500 }}>
                <Link to={`/countries/${r.code}`}>{r.name}</Link>
              </th>
              <td className="num grp-start">{formatNumber(r.meps_active)}</td>
              <td className="num">{formatNumber(Object.values(r.groups).filter((n) => n > 0).length)}</td>
              {councilAvailable ? (
                <>
                  <td className="num grp-start">{formatNumber(r.council_positions.for)}</td>
                  <td className="num">{formatNumber(r.council_positions.against)}</td>
                  <td className="num">{formatNumber(r.council_positions.abstain)}</td>
                  {hasNp && <td className="num">{formatNumber(r.council_positions.not_participating)}</td>}
                </>
              ) : (
                <td className="grp-start unavail">Unavailable</td>
              )}
              {inds.map((i, n) => {
                const v = r.indicators.find((x) => x.indicator === i.id);
                return (
                  <td key={i.id} className={`num${n === 0 ? ' grp-start' : ''}`}>
                    {v ? formatIndicator(v.value, v.unit) : <span className="unavail">—</span>}
                  </td>
                );
              })}
              <td className={`num${inds.length === 0 ? ' grp-start' : ''}`}>
                {infringementsAvailable && r.open_infringements != null ? formatNumber(r.open_infringements) : <span className="unavail">Unavailable</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
