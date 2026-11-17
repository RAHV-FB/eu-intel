import { useId, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { CountrySummary, ISODate, TrackedCountry, TrackedDirective, TranspositionTracker } from '../types/data';
import { DATA_BASE, useData } from '../lib/data';
import { afterDeadline, fromToday } from '../lib/deadline';
import { COUNTRY_NAMES, countryName, formatDate, formatNumber, plural } from '../lib/format';
import { useParamState } from '../lib/urlState';
import { EmptyState, ErrorState, ExtLink, Loading, LookupNotice, PageHeader, SourceLink, Term } from '../components/ui';
import { RowTitle, StackLabel } from '../components/StackedTable';
import { dossierPath, useDocumentTitle, useTopics } from '../features/legislation/labels';
import { todayISO } from '../features/legislation/explorer';
import { TranspositionStatusLabel } from '../features/countries/Implementation';
import { formatIndicator } from '../features/countries/CountryTable';
import {
  builtTooLongAgo,
  directivesOn,
  matches,
  openNonCommunication,
  split,
  statusCounts,
  windowOn,
  type When,
} from '../features/transposition/tracker';
import '../features/legislation/common.css';
import '../features/legislation/legislation.css';
import '../features/transposition/transposition.css';

/** The 27 Member States, by name (the United Kingdom has no row). */
const MEMBER_STATES = Object.keys(COUNTRY_NAMES)
  .filter((c) => c !== 'GB')
  .sort((a, b) => countryName(a).localeCompare(countryName(b)));

const WHEN_LABEL: Record<When, string> = { ahead: 'Deadline ahead', passed: 'Deadline passed' };

/** "Denmark", "Cyprus and Malta", "Denmark, Ireland and Malta" */
function names(codes: string[]): string {
  const ns = codes.map(countryName).sort((a, b) => a.localeCompare(b));
  return ns.length > 1 ? `${ns.slice(0, -1).join(', ')} and ${ns[ns.length - 1]}` : (ns[0] ?? '');
}

/** The directive's table on its file's page, with the Member State's row highlighted. */
const tablePath = (d: TrackedDirective, country: string | null) =>
  d.dossier_id ? `${dossierPath(d.dossier_id)}${country ? `?country=${country}` : ''}#national` : null;

const feedHref = (code: string) => `${DATA_BASE}feeds/countries/${encodeURIComponent(code)}.xml`;

export default function Transposition() {
  const [params, patch] = useParamState();
  const tracker = useData<TranspositionTracker>('transposition.json');
  const countries = useData<CountrySummary[]>('countries/index.json');
  const topicsData = useTopics();
  const ids = useId();
  const today = todayISO(); // the reader's date: the window, the deadlines and the statuses are judged on it
  const topic = params.get('topic') || null;
  const when = (['ahead', 'passed'] as const).find((w) => w === params.get('when')) ?? null;
  const code = (params.get('country') ?? '').toUpperCase();
  const country = MEMBER_STATES.includes(code) ? code : null;
  useDocumentTitle(country ? `Directives into national law: ${countryName(country)} – Legislation` : 'Directives into national law – Legislation');

  const all = useMemo(() => (tracker.data ? directivesOn(tracker.data, today) : []), [tracker.data, today]);
  const shown = useMemo(() => all.filter((d) => matches(d, { topic, when }, today)), [all, topic, when, today]);
  const { ahead, passed } = useMemo(() => split(shown, today), [shown, today]);
  // each filter's options count the directives the other filter leaves
  const topicCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of all.filter((x) => matches(x, { topic: null, when }, today))) for (const t of d.topics) m.set(t, (m.get(t) ?? 0) + 1);
    return m;
  }, [all, when, today]);
  const whenCounts = useMemo(() => {
    const ds = all.filter((x) => matches(x, { topic, when: null }, today));
    return { ahead: ds.filter((d) => matches(d, { topic: null, when: 'ahead' }, today)).length, passed: ds.filter((d) => matches(d, { topic: null, when: 'passed' }, today)).length };
  }, [all, topic, today]);
  const range = tracker.data ? windowOn(tracker.data, today) : null;
  const indicator = country ? countries.data?.find((c) => c.code === country)?.indicators[0] : undefined;
  const scoreboard = !!countries.data?.some((c) => c.indicators.length > 0);
  const topicLabel = (slug: string) => topicsData.topics.find((t) => t.slug === slug)?.label ?? slug;

  return (
    <div className="container page tt">
      <nav className="tt-crumbs" aria-label="Breadcrumb">
        <ol>
          <li>
            <Link to="/legislation">Legislation</Link>
          </li>
          <li aria-current="page">Directives into national law</li>
        </ol>
      </nav>
      <PageHeader
        eyebrow="Legislation"
        title={country ? `Directives into national law: ${countryName(country)}` : 'Directives into national law'}
        lead="A directive must be written into each Member State’s own law by a deadline. For each directive due in the last three years or the next twelve months: what each Member State has notified to the Commission, and the Commission’s open cases for not notifying measures."
      >
        <p className="meta tt-scope">
          {range ? (
            <>
              The directives adopted in the legislative files on this site whose general{' '}
              <Term id="transposition">transposition</Term> deadline falls between {formatDate(range.from, true)} and{' '}
              {formatDate(range.to, true)}, three years before today and twelve months after.
            </>
          ) : (
            <>
              The directives adopted in the legislative files on this site whose general{' '}
              <Term id="transposition">transposition</Term> deadline falls in the last three years or the next twelve months.
            </>
          )}{' '}
          Each links the table of all 27 Member States on its file’s page. <Link to="/about#coverage">What’s covered</Link>
        </p>
        <p className="meta tt-scope">
          “Measures notified” means a Member State notified at least one national measure; it does not show that
          transposition is complete or correct. “No measures found in the available dataset” is not proof that a country
          has failed to act. Whether a country has breached EU law is for the Commission to pursue and, ultimately, for
          the Court of Justice to decide. Member States are not ranked or scored here.
        </p>
      </PageHeader>

      <form className="lx-filters tt-filters" aria-label="Filter the directives" onSubmit={(e) => e.preventDefault()}>
        <div className="lx-field">
          <label htmlFor={`${ids}-country`}>Member State</label>
          <select
            id={`${ids}-country`}
            className="select lx-select"
            value={country ?? ''}
            onChange={(e) => patch({ country: e.target.value || null })}
          >
            <option value="">All 27, by status</option>
            {MEMBER_STATES.map((c) => (
              <option key={c} value={c}>
                {countryName(c)}
              </option>
            ))}
          </select>
        </div>
        <div className="lx-field">
          <label htmlFor={`${ids}-topic`}>Topic</label>
          <select id={`${ids}-topic`} className="select lx-select" value={topic ?? ''} onChange={(e) => patch({ topic: e.target.value || null })}>
            <option value="">All topics</option>
            {topicsData.topics
              .filter((t) => (topicCounts.get(t.slug) ?? 0) > 0 || t.slug === topic)
              .map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.label} ({formatNumber(topicCounts.get(t.slug) ?? 0)})
                </option>
              ))}
          </select>
        </div>
        <div className="lx-field">
          <label htmlFor={`${ids}-when`}>Deadline</label>
          <select id={`${ids}-when`} className="select lx-select" value={when ?? ''} onChange={(e) => patch({ when: e.target.value || null })}>
            <option value="">Passed or ahead</option>
            <option value="passed">Passed ({formatNumber(whenCounts.passed)})</option>
            <option value="ahead">Ahead ({formatNumber(whenCounts.ahead)})</option>
          </select>
        </div>
      </form>

      {country && (
        <div className="tt-country">
          <p>
            {countryName(country)}’s status on each directive, as on the directive’s own page.{' '}
            <Link to={`/countries/${country}`}>{countryName(country)}’s country page</Link> ·{' '}
            <a href={feedHref(country)} type="application/atom+xml">
              Follow {countryName(country)} in a feed reader (Atom)
            </a>
          </p>
          {indicator && (
            // the Commission's own count for this Member State, never beside another's
            <p className="meta">
              The Commission’s count of {countryName(country)}’s overdue Single Market directives:{' '}
              <strong>{formatIndicator(indicator.value, indicator.unit)}</strong> ({indicator.period}). It covers Single
              Market directives only. <SourceLink source={indicator.source} />
            </p>
          )}
        </div>
      )}
      {!country && scoreboard && (
        <p className="meta tt-note">
          The Commission’s own count of each Member State’s overdue Single Market directives (Single Market Scoreboard) is
          on that country’s page, and here once a Member State is chosen.
        </p>
      )}

      {tracker.loading && <Loading label="Loading the directives…" />}
      {tracker.error && <ErrorState error={tracker.error} title="The directives could not be loaded" />}
      <LookupNotice failed={topicsData.failed} what="Topic names" />

      {tracker.data && (
        <>
          <p className="tt-count" role="status">
            <strong>{formatNumber(shown.length)}</strong> {shown.length === 1 ? 'directive' : 'directives'}
            {(topic || when) && (
              <>
                {' '}
                ({[topic && topicLabel(topic), when && WHEN_LABEL[when].toLowerCase()].filter(Boolean).join(', ')}) ·{' '}
                <button type="button" className="lx-linkbtn" onClick={() => patch({ topic: null, when: null })}>
                  Show all directives
                </button>
              </>
            )}
          </p>
          {builtTooLongAgo(tracker.data, today) && (
            <p className="meta tt-note">
              This list was built on {formatDate(tracker.data.built_on, true)}: a directive whose deadline falls more than
              thirteen months after that date is not in it.
            </p>
          )}
          {shown.length === 0 ? (
            <EmptyState title="No directive matches these filters">
              <p>Try another topic, or both passed and future deadlines.</p>
            </EmptyState>
          ) : (
            <>
              {ahead.length > 0 && (
                <section className="tt-section" aria-labelledby={`${ids}-ahead`}>
                  <h2 id={`${ids}-ahead`} className="section-title">
                    Deadline ahead <span className="tt-section__n">{formatNumber(ahead.length)}</span>
                  </h2>
                  <p className="meta">The soonest first. Measures can be notified before the deadline.</p>
                  <DirectiveTable rows={ahead} country={country} today={today} caption="Directives whose transposition deadline is ahead, the soonest first" />
                </section>
              )}
              {passed.length > 0 && (
                <section className="tt-section" aria-labelledby={`${ids}-passed`}>
                  <h2 id={`${ids}-passed`} className="section-title">
                    Deadline passed <span className="tt-section__n">{formatNumber(passed.length)}</span>
                  </h2>
                  <p className="meta">The latest first.</p>
                  <DirectiveTable rows={passed} country={country} today={today} caption="Directives whose transposition deadline has passed, the latest first" />
                </section>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

function DirectiveTable({ rows, country, today, caption }: { rows: TrackedDirective[]; country: string | null; today: ISODate; caption: string }) {
  return (
    <div className="table-wrap table-card">
      {/* Explicit roles: on phones the rows are laid out as cards (table--stack), not as table cells. */}
      <table className="table table--stack tt-table" role="table">
        <caption className="visually-hidden">
          {caption}
          {country ? `, with ${countryName(country)}’s status` : ', with the Member States by status'}
        </caption>
        <thead role="rowgroup">
          <tr role="row">
            <th scope="col" role="columnheader">
              Directive
            </th>
            <th scope="col" role="columnheader">
              Deadline
            </th>
            {country ? (
              <>
                <th scope="col" role="columnheader">
                  {countryName(country)}’s status in the dataset
                </th>
                <th scope="col" role="columnheader">
                  Open infringement cases
                </th>
              </>
            ) : (
              <>
                <th scope="col" role="columnheader">
                  Member States by status
                </th>
                <th scope="col" role="columnheader" className="num">
                  Open non-communication cases
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody role="rowgroup">
          {rows.map((d) => (
            <tr key={d.celex} role="row">
              <td role="cell" className="stack-title tt-dir">
                <RowTitle to={tablePath(d, country)}>{d.title}</RowTitle>
                <span className="meta as-block">
                  {d.act ?? d.celex}
                  {d.names.length > 0 && ` (${d.names.join(', ')})`}
                </span>
              </td>
              <td role="cell" className="tt-deadline">
                <StackLabel>Deadline</StackLabel>
                <span>
                  <time dateTime={d.deadline}>{formatDate(d.deadline)}</time>
                  <span className="meta as-block">{fromToday(d.deadline, today)}</span>
                  {d.first_deadline && (
                    <span className="meta as-block">
                      Some provisions by <time dateTime={d.first_deadline}>{formatDate(d.first_deadline)}</time>
                    </span>
                  )}
                </span>
              </td>
              {country ? <CountryCells d={d} c={d.countries.find((x) => x.country === country)} today={today} /> : <OverviewCells d={d} />}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A directive's Member States by status: the bound ones counted, the others named apart. */
function OverviewCells({ d }: { d: TrackedDirective }) {
  const counts = statusCounts(d);
  const open = openNonCommunication(d);
  return (
    <>
      <td role="cell" className="tt-status">
        <StackLabel>Member States</StackLabel>
        {counts.covered ? (
          <ul className="tt-counts">
            {/* the number of Member States, then their status: the column's heading says what is counted, and a screen
                reader hears it with each number */}
            {counts.bound.map(([s, n]) => (
              <li key={s} className="tt-counts__row">
                <span className="tt-counts__n">
                  {formatNumber(n)}
                  <span className="visually-hidden"> {n === 1 ? 'Member State' : 'Member States'}:</span>
                </span>{' '}
                <TranspositionStatusLabel status={s} />
              </li>
            ))}
            {counts.notBound.length > 0 && <li className="meta">Not bound (did not take part in adoption): {names(counts.notBound)}</li>}
            {counts.exempt.length > 0 && <li className="meta">Not required by the directive: {names(counts.exempt)}</li>}
            {counts.unknown.length > 0 && <li className="meta">Not recorded whether it binds {names(counts.unknown)}</li>}
          </ul>
        ) : (
          <span className="meta">National measures for this directive are not in this release’s data</span>
        )}
      </td>
      <td role="cell" className="num">
        <StackLabel>Open non-communication cases</StackLabel>
        {formatNumber(open)}
      </td>
    </>
  );
}

/** One Member State's row of the directive's table: its status on the reader's date and its open cases. */
function CountryCells({ d, c, today }: { d: TrackedDirective; c: TrackedCountry | undefined; today: ISODate }) {
  if (!c)
    return (
      <>
        <td role="cell">
          <span className="meta">Not in the data</span>
        </td>
        <td role="cell" />
      </>
    );
  const since = c.status === 'none_found' ? afterDeadline(d.first_deadline ?? d.deadline, today) : null;
  return (
    <>
      <td role="cell">
        <StackLabel>Status</StackLabel>
        <span>
          <TranspositionStatusLabel status={c.status} />
          {c.status === 'measures_notified' && (
            <span className="meta as-block">
              {plural(c.measures, 'measure')}
              {c.latest_notification && (
                <>
                  , {c.measures > 1 ? 'the latest notified' : 'notified'} {formatDate(c.latest_notification)}
                </>
              )}
            </span>
          )}
          {since && <span className="meta as-block">{since}</span>}
          {c.participation_unknown && (
            <span className="meta as-block">Our sources do not record whether the directive binds {countryName(c.country)}.</span>
          )}
        </span>
      </td>
      <td role="cell">
        <StackLabel>Open cases</StackLabel>
        {c.cases?.length ? (
          <ul className="tt-cases">
            {c.cases.map((k) => (
              <li key={k.id}>
                <ExtLink href={k.url}>{k.id}</ExtLink>{' '}
                <span className="meta">
                  {k.stage ?? 'stage not recorded'}
                  {k.date && <> · {formatDate(k.date)}</>}
                  {k.non_communication && <> · not notifying measures</>}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="meta">None open in the dataset</span>
        )}
      </td>
    </>
  );
}
