import { Link } from 'react-router-dom';
import type { CountrySummary, Meta } from '../types/data';
import { useData } from '../lib/data';
import { formatDate } from '../lib/format';
import { EmptyState, ErrorState, ExtLink, Loading, PageHeader, Term } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { CountryTable, indicatorColumns } from '../features/countries/CountryTable';

export default function Countries() {
  useDocumentTitle('Countries');
  const { data, error, loading } = useData<CountrySummary[]>('countries/index.json');
  const meta = useData<Meta>('meta.json');

  const rows = data ?? [];
  const councilAvailable = rows.some((r) => r.council_positions.for + r.council_positions.against + r.council_positions.abstain > 0);
  const infringementsAvailable = rows.some((r) => r.open_infringements != null);
  const inds = indicatorColumns(rows);
  const councilSource = meta.data?.sources.find((s) => s.id === 'council');

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
          <CountryTable rows={rows} councilAvailable={councilAvailable} infringementsAvailable={infringementsAvailable} />

          <div className="grid grid--3 section" style={{ marginTop: 'var(--sp-6)' }}>
            <div>
              <h2 style={{ fontSize: 'var(--fs-md)' }}>Representation in Parliament</h2>
              <p className="note">
                Current MEPs elected in each country and the number of <Term id="political-group">political groups</Term> they sit in. MEPs
                vote individually, not as national delegations. The number of seats per country is fixed by a European Council decision.
              </p>
            </div>
            <div>
              <h2 style={{ fontSize: 'var(--fs-md)' }}>Council of the EU votes</h2>
              {councilAvailable ? (
                <p className="note">
                  How each government’s minister voted on the Council votes in our dataset. Under{' '}
                  <Term id="qmv">qualified majority</Term> one country cannot normally block a decision on its own.
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
                {inds.length === 0 && 'No published implementation indicators are available in this release.'}
              </p>
            </div>
          </div>

          {inds.length > 0 && (
            <section className="section" aria-labelledby="ind-h">
              <h2 id="ind-h">About the indicators</h2>
              <dl className="stack">
                {inds.map((i) => (
                  <div key={i.id}>
                    <dt>
                      <strong>{i.label}</strong> <span className="meta">({i.period})</span>
                    </dt>
                    <dd style={{ margin: 0 }} className="note">
                      {i.definition}{' '}
                      {i.source && (
                        <ExtLink href={i.source.url}>{i.source.label || 'Source'}</ExtLink>
                      )}
                      {i.source?.published && <> · published {formatDate(i.source.published)}</>}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          )}

          <p className="note section">
            Figures come from official sources listed on the <Link to="/about#sources">About page</Link>. There is no overall score: these
            measures describe different things and should not be added up.
          </p>
        </>
      )}
    </div>
  );
}
