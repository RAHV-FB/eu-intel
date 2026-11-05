import { Link } from 'react-router-dom';
import type { CountrySummary, Meta } from '../types/data';
import { useData } from '../lib/data';
import { formatDate, formatNumber } from '../lib/format';
import { EmptyState, ErrorState, ExtLink, Loading, PageHeader, Term } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { CountryTable } from '../features/countries/CountryTable';

export default function Countries() {
  useDocumentTitle('Countries');
  const { data, error, loading } = useData<CountrySummary[]>('countries/index.json');
  const meta = useData<Meta>('meta.json');

  const rows = data ?? [];
  const councilAvailable = rows.some((r) => r.council_positions.for + r.council_positions.against + r.council_positions.abstain > 0);
  const infringementsAvailable = rows.some((r) => r.open_infringements != null);
  // the Single Market Scoreboard's count of overdue directives: on each country's page only, never side by side
  const scoreboard = rows.some((r) => r.indicators.length > 0);
  const councilSource = meta.data?.sources.find((s) => s.id === 'council');
  // the Council votes counted: each row adds up every vote with that country's recorded position, so all rows give the
  // same total when every vote lists all the Member States; the dates are those of the first and last vote listed
  const councilTotals = new Set(rows.map((r) => Object.values(r.council_positions).reduce((a, b) => a + b, 0)));
  const councilTotal = councilTotals.size === 1 ? [...councilTotals][0] : null;
  const councilFrom = meta.data?.scope?.council_votes_from;
  const councilTo = meta.data?.scope?.council_votes_to;
  const councilPeriod = councilFrom && councilTo ? `${councilFrom.slice(0, 4)}–${councilTo.slice(0, 4)}` : null;
  const notTakingPart = rows.some((r) => r.council_positions.not_participating > 0);

  return (
    <div className="container page">
      <PageHeader
        eyebrow="Member States"
        title="Countries"
        lead="How each Member State is represented in Parliament, how its government voted in the Council of the EU, and what published records show about implementing EU law. Each kind of information is kept separate."
      />

      {loading && <Loading label="Loading countries…" />}
      {error && <ErrorState error={error} title="The country list could not be loaded" />}
      {data && data.length === 0 && <EmptyState title="No country data available in this build" />}

      {data && data.length > 0 && (
        <>
          <CountryTable
            rows={rows}
            councilAvailable={councilAvailable}
            infringementsAvailable={infringementsAvailable}
            councilPeriod={councilPeriod}
          />

          <div className="grid grid--3 section" style={{ marginTop: 'var(--sp-6)' }}>
            <div>
              <h2 style={{ fontSize: 'var(--fs-md)' }}>Representation in Parliament</h2>
              <p className="note">
                Current MEPs elected in each country and the number of <Term id="political-group">political groups</Term> they sit in
                (non-attached MEPs belong to no group and are not counted as one). MEPs
                vote individually, not as national delegations. The number of seats per country is fixed by a European Council decision.
              </p>
            </div>
            <div>
              <h2 style={{ fontSize: 'var(--fs-md)' }}>Council of the EU votes</h2>
              {councilAvailable ? (
                <p className="note">
                  How each government voted, from the Council’s published voting results
                  {councilTotal ? <>: {formatNumber(councilTotal)} votes with each country’s position recorded</> : null}
                  {councilFrom && councilTo ? (
                    <>
                      , between {formatDate(councilFrom, true)} and {formatDate(councilTo, true)}
                    </>
                  ) : null}
                  .{' '}
                  {notTakingPart && (
                    <>
                      “Did not take part”: for example under Denmark’s or Ireland’s opt-outs, or in enhanced cooperation that a country
                      has not joined.{' '}
                    </>
                  )}
                  Under <Term id="qmv">qualified majority</Term> one country cannot normally block a decision on its own.
                </p>
              ) : (
                <p className="note">
                  <strong>Council vote data unavailable.</strong>{' '}
                  {councilSource?.note ?? 'Member State voting results were not available from an accessible official source in this release.'}{' '}
                  {councilSource?.url && <ExtLink href={councilSource.url}>Council voting results</ExtLink>}
                </p>
              )}
            </div>
            <div>
              <h2 style={{ fontSize: 'var(--fs-md)' }}>Implementation of EU law</h2>
              <p className="note">
                {infringementsAvailable ? (
                  <>
                    Open <Term id="infringement">infringement cases</Term> are formal procedures opened by the Commission; an open case is not
                    a court ruling. Countries differ in how many directives apply to them and when cases are opened, so counts are not a
                    ranking.
                  </>
                ) : (
                  <>Infringement data is unavailable in this release.</>
                )}{' '}
                {scoreboard &&
                  'Each country’s page gives the Commission’s count of its overdue Single Market directives, from the Single Market Scoreboard; the counts are not listed side by side here.'}{' '}
                <Link to="/legislation/transposition">Directives into national law</Link>: each directive due in the last
                three years or the next twelve months, with every Member State’s status.
              </p>
            </div>
          </div>

          <p className="note section">
            Figures come from official sources listed on the <Link to="/about#sources">About page</Link>. There is no overall score: these
            measures describe different things and should not be added up.
          </p>
        </>
      )}
    </div>
  );
}
