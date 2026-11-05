import { Fragment, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { EpVoteDetail, PartySummary } from '../../types/data';
import { countryName, formatNumber } from '../../lib/format';
import { shownParam, useParamState } from '../../lib/urlState';
import { ResultCount } from '../../components/ResultCount';
import { useFocusRevealed } from '../../components/useFocusRevealed';
import { recordPeriod } from '../people/labels';
import { orderPartyRows, partyRows, type PartyRow } from './partyRows';
import { compareValues } from './sortable';
import './votes.css';

const PAGE = 40;

/** "For 0 · Against 19 · Abstained 0 · Did not vote 4": a party's counts on one line (on phones, where the columns are
 * hidden), each figure kept with its label. Did not vote is "not known" when null. */
export function PartyCounts({ counts, className }: { counts: [number, number, number, number | null]; className?: string }) {
  const items = [['For', counts[0]], ['Against', counts[1]], ['Abstained', counts[2]], ['Did not vote', counts[3]]] as const;
  return (
    <span className={className ? `party-counts ${className}` : 'party-counts'}>
      {items.map(([label, n], i) => (
        <Fragment key={label}>
          {i > 0 && ' · '}
          <span className="party-counts__item">
            {label} <b>{n != null ? formatNumber(n) : 'not known'}</b>
          </span>
        </Fragment>
      ))}
    </span>
  );
}

/**
 * How MEPs voted by national party: one row per party record, listed by country and then by party name. The country
 * chosen here is the one the list of individual MEPs is filtered by (`bl-country`), so the two stay in step.
 * `parties` names the records (people/parties.json); null when that file could not be loaded.
 */
export function PartyBreakdown({
  v,
  parties,
  groupCodes,
}: {
  v: Pick<EpVoteDetail, 'ballots' | 'no_vote' | 'parties_outside_period'>;
  parties: Map<string, PartySummary> | null;
  groupCodes: Map<string, string>;
}) {
  const [params, patch] = useParamState();
  const country = params.get('bl-country') ?? '';
  const shown = shownParam(params, 'np-show', PAGE);
  const all = useMemo(() => partyRows(v.ballots, v.no_vote), [v.ballots, v.no_vote]);
  const countries = useMemo(
    () => [...new Set(all.map((r) => r.country).filter((c): c is string => !!c))].sort((a, b) => compareValues(countryName(a), countryName(b), 'asc')),
    [all],
  );
  const rows = useMemo(
    () => orderPartyRows(country ? all.filter((r) => r.country === country) : all, (id) => parties?.get(id)?.label ?? null),
    [all, country, parties],
  );
  const outside = useMemo(() => new Map((v.parties_outside_period ?? []).map((x) => [x.party, x])), [v.parties_outside_period]);
  const visible = rows.slice(0, shown);
  // "Show all" moves keyboard focus to the first party it shows
  const more = useFocusRevealed<HTMLTableSectionElement>(visible.length);
  const known = Array.isArray(v.no_vote);
  const named = rows.filter((r) => r.party !== null).length;
  const groupsText = (r: PartyRow) =>
    r.groups
      .map((g) => groupCodes.get(g) ?? g)
      .sort((a, b) => compareValues(a, b, 'asc'))
      .join(', ');

  const name = (r: PartyRow) => {
    if (!r.party) return <span>No national party recorded</span>;
    const p = parties?.get(r.party);
    // a record missing from people/parties.json is one whose name Parliament's data does not give (the build leaves
    // those out of the list); when the list itself could not be loaded, the record is named by its identifier
    const label = p?.label ?? (parties ? 'Party name not recorded' : `National party ${r.party}`);
    return (
      <>
        <Link to={`/people/parties/${encodeURIComponent(r.party)}`}>{label}</Link>
        {/* the code, unless the name already gives it ("Partit dels Socialistes de Catalunya (PSC-PSOE)") */}
        {p?.code && p.code !== p.label && !p.label.includes(`(${p.code})`) && <span className="meta"> ({p.code})</span>}
      </>
    );
  };

  return (
    <div>
      {!parties && (
        <div className="state state--error state--note" role="alert">
          The names of the national parties could not be loaded, so each is shown by its identifier in Parliament’s data; reload the
          page to try again.
        </div>
      )}
      <form className="filters" aria-label="Filter national parties" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="np-country">MEPs from</label>
          <select
            id="np-country"
            className="select"
            value={country}
            aria-describedby="np-country-note"
            onChange={(e) => patch({ 'bl-country': e.target.value, 'bl-show': null, 'np-show': null })}
          >
            <option value="">All countries</option>
            {countries.map((c) => (
              <option key={c} value={c}>
                {countryName(c)}
              </option>
            ))}
          </select>
          <span id="np-country-note" className="meta">
            Also filters the list of individual MEPs below.
          </span>
        </div>
      </form>
      <ResultCount className="party-tally">
        {country
          ? `MEPs from ${countryName(country)}: ${formatNumber(named)} national ${named === 1 ? 'party' : 'parties'}`
          : `${formatNumber(named)} national parties from ${formatNumber(countries.length)} countries`}
        {rows.length > named ? ', and MEPs with no national party recorded' : ''}
      </ResultCount>
      {!known && (
        <p className="note mb-3">
          “Did not vote” is not given for this vote: Parliament’s membership records do not give the Members in office on this day, so
          we cannot tell who sat without voting. Only parties with a recorded vote are listed.
        </p>
      )}
      {rows.length > 0 && (
        <div className="table-wrap table-card">
          <table className="table table--breakdown table--parties">
            <caption className="visually-hidden">
              How MEPs voted, by the national party Parliament’s data lists them under on the day of the vote; listed by country, then by
              party name.
            </caption>
            <thead>
              <tr>
                <th scope="col">Party</th>
                <th scope="col" className="hide-narrow">
                  Country
                </th>
                <th scope="col" className="hide-narrow">
                  Group
                </th>
                <th scope="col" className="num hide-narrow">
                  For
                </th>
                <th scope="col" className="num hide-narrow">
                  Against
                </th>
                <th scope="col" className="num hide-narrow">
                  Abstained
                </th>
                <th scope="col" className="num hide-narrow">
                  Did not vote
                </th>
              </tr>
            </thead>
            <tbody ref={more.ref}>
              {visible.map((r) => {
                const out = r.party ? outside.get(r.party) : undefined;
                const n = r.for + r.against + r.abstain + (r.didNotVote ?? 0);
                const groups = groupsText(r);
                return (
                  <tr key={`${r.party ?? ''}|${r.country ?? ''}`}>
                    <th scope="row" className="wrap-anywhere">
                      {name(r)}
                      {out && (
                        <span className="meta as-block">
                          Parliament’s membership data lists {n === 1 ? 'this MEP' : 'these MEPs'} in this party record outside its period (
                          {recordPeriod(out.start, out.end)}).
                        </span>
                      )}
                      {/* phones: the other columns are hidden and shown here, so that a party's name is never cut short */}
                      <span className="only-narrow meta">
                        {[r.country ? countryName(r.country) : null, groups || null].filter(Boolean).join(' · ')}
                      </span>
                      <PartyCounts counts={[r.for, r.against, r.abstain, r.didNotVote]} className="only-narrow" />
                    </th>
                    <td className="hide-narrow">{r.country ? countryName(r.country) : <span className="muted">—</span>}</td>
                    <td className="hide-narrow">{groups || <span className="muted">—</span>}</td>
                    <td className="num hide-narrow">{formatNumber(r.for)}</td>
                    <td className="num hide-narrow">{formatNumber(r.against)}</td>
                    <td className="num hide-narrow">{formatNumber(r.abstain)}</td>
                    <td className="num hide-narrow">{r.didNotVote != null ? formatNumber(r.didNotVote) : <span className="muted">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > shown && (
        <div className="more">
          <button
            type="button"
            className="btn"
            onClick={() => {
              more.reveal();
              patch({ 'np-show': String(rows.length) });
            }}
          >
            Show all parties
          </button>
          <span className="meta">
            Showing {formatNumber(shown)} of {formatNumber(rows.length)}; choose a country to see only its parties.
          </span>
        </div>
      )}
    </div>
  );
}
