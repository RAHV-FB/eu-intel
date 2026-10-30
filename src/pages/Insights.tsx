import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { CountrySummary, DossierSummary, EpVoteSummary, Meta } from '../types/data';
import { useData } from '../lib/data';
import { formatDateTime, formatNumber } from '../lib/format';
import { ErrorState, Loading } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { councilPatterns, legislativePatterns, parliamentPatterns } from '../features/insights/analysis';
import '../features/insights/insights.css';

const percentage = (part: number, total: number) => total ? `${(100 * part / total).toFixed(1)}%` : '—';
const barWidth = (part: number, max: number) => `${max ? (100 * part / max) : 0}%`;

/** Every visualization is also labelled in text; no unsupported country-performance or causation claims. */
export default function Insights() {
  useDocumentTitle('Data insights');
  const dossiers = useData<DossierSummary[]>('dossiers/index.json');
  const votes = useData<EpVoteSummary[]>('votes/index.json');
  const countries = useData<CountrySummary[]>('countries/index.json');
  const meta = useData<Meta>('meta.json');
  const legislative = useMemo(() => legislativePatterns(dossiers.data ?? []), [dossiers.data]);
  const parliament = useMemo(() => parliamentPatterns(votes.data ?? []), [votes.data]);
  const council = useMemo(() => councilPatterns(countries.data ?? []), [countries.data]);
  const waiting = dossiers.loading || votes.loading || countries.loading || meta.loading;
  const failed = dossiers.error || votes.error || countries.error || meta.error;
  const ready = !!dossiers.data && !!votes.data && !!countries.data && !!meta.data;
  const recordedDecisions = parliament.withMargin;
  const councilMax = Math.max(1, ...council.map((c) => c.dissent));

  return (
    <div className="insights">
      <section className="insights-hero">
        <div className="container insights-hero__inner">
          <div>
            <p className="insights-overline">Explore the evidence / European Union</p>
            <h1>Patterns behind the <em>legislative record.</em></h1>
            <p className="insights-hero__lead">Track how recorded proposals progress, examine Parliament's final votes and see when national governments register opposition in the Council. Every number comes from the published records in this site's snapshot.</p>
            <div className="insights-hero__actions">
              <a href="#legislation">Legislative pipeline ↓</a>
              <a href="#parliament">Voting patterns ↓</a>
              <a href="#council">Council positions ↓</a>
            </div>
          </div>
          <div className="insights-hero__stamp" aria-label="Independent analysis">
            <span>EU</span>
            <strong>DATA / INTELLIGENCE</strong>
            <small>Official sources, independent presentation</small>
          </div>
        </div>
      </section>

      <div className="container insights-body">
        {waiting && <Loading label="Reading the legislative, Parliament and Council datasets…" />}
        {failed && <ErrorState error={failed} title="The analysis could not be loaded completely" />}
        {ready && (
          <>
            <p className="insights-fresh">Snapshot built {formatDateTime(meta.data!.built_at)}. These are counts from the site's tracked records, not totals for all EU activity. <Link to="/about#methodology">Sources and limits</Link>.</p>
            <div className="insights-metrics" aria-label="Dataset coverage">
              <div><strong>{formatNumber(legislative.total)}</strong><span>Legislative files</span></div>
              <div><strong>{formatNumber(parliament.total)}</strong><span>Selected Parliament votes</span></div>
              <div><strong>{formatNumber(meta.data!.counts.council_votes)}</strong><span>Published Council voting results</span></div>
              <div><strong>{formatNumber(meta.data!.counts.national_measures)}</strong><span>National measures listed</span></div>
            </div>

            <section className="insights-section" id="legislation" aria-labelledby="insights-leg-heading">
              <div className="insights-section__intro">
                <p className="insights-overline">01 / Legislative lifecycle</p>
                <h2 id="insights-leg-heading">Where tracked files stand</h2>
                <p>Each legislative file is counted once, in its latest determinable stage. Publication, entry into force and application are different legal events; a withdrawn proposal is not a rejected law.</p>
                <Link to="/legislation">Browse and filter every legislative file</Link>
              </div>
              <div className="insights-panel">
                <h3>Stage distribution</h3>
                <p className="insights-panel__sub">Number of tracked files, not a measure of legislative success</p>
                <div className="insights-bars">
                  {legislative.stages.map((s) => (
                    <div className="insights-bar-row" key={s.id}>
                      <div className="insights-bar-row__label"><span>{s.label}</span><strong>{formatNumber(s.count)}</strong></div>
                      <div className="insights-track" role="img" aria-label={`${s.label}: ${s.count} files, ${percentage(s.count, legislative.total)} of tracked files`}>
                        <div className={`insights-fill insights-fill--${s.id}`} style={{ width: barWidth(s.count, legislative.stages[0]?.count || 1) }} />
                      </div>
                    </div>
                  ))}
                </div>
                <p className="insights-panel__footnote">Stages are based on official procedural and legal-act records. “Not determinable” is retained rather than assigned an assumed result.</p>
              </div>
            </section>

            <section className="insights-section insights-section--timeline" aria-labelledby="insights-time-heading">
              <div className="insights-section__intro">
                <p className="insights-overline">02 / Activity over time</p>
                <h2 id="insights-time-heading">Proposals and adoptions by year</h2>
                <p>Recorded proposal starts and legal adoptions within the tracked files, counted separately by calendar year. A file introduced in one year can be adopted years later.</p>
                <p className="insights-caveat">The coverage is not exhaustive and is not a cohort conversion chart. Earlier years and the current year may be incomplete; do not infer adoption probabilities from these two series.</p>
              </div>
              <div className="insights-panel">
                <div className="insights-legend"><span><i className="insights-key insights-key--proposals" />Proposals recorded</span><span><i className="insights-key insights-key--adoptions" />Adoptions recorded</span></div>
                {legislative.timeline.length ? (
                  <div className="insights-timeline" role="group" aria-label="Proposals and adoptions by year">
                    {legislative.timeline.map((year) => (
                      <div className="insights-timeline__row" key={year.year}>
                        <strong>{year.year}</strong>
                        <div className="insights-timeline__pair">
                          <div className="insights-timeline__track"><span className="insights-fill insights-fill--proposals" style={{ width: barWidth(year.introduced, legislative.maxTimeline) }} /></div>
                          <div className="insights-timeline__track"><span className="insights-fill insights-fill--adoptions" style={{ width: barWidth(year.adopted, legislative.maxTimeline) }} /></div>
                        </div>
                        <span className="insights-timeline__numbers" aria-label={`${year.introduced} proposals, ${year.adopted} adoptions`}>{formatNumber(year.introduced)} / {formatNumber(year.adopted)}</span>
                      </div>
                    ))}
                  </div>
                ) : <p>No dated proposal or adoption records in this snapshot.</p>}
                <p className="insights-panel__footnote">The first number in each row is proposals; the second is adoptions. Only files for which the corresponding date is recorded contribute to that series.</p>
              </div>
            </section>

            <section className="insights-section" id="parliament" aria-labelledby="insights-parl-heading">
              <div className="insights-section__intro">
                <p className="insights-overline">03 / European Parliament</p>
                <h2 id="insights-parl-heading">Votes on complete texts</h2>
                <p>“Final” votes in this dataset concern a complete text, which may be a legislative position, consent, budget decision or another type of Parliament decision. They do not all create EU law.</p>
                <Link to="/votes?kind=final">Inspect the final votes and their underlying ballots</Link>
              </div>
              <div className="insights-panel">
                <div className="insights-stat-grid">
                  <div><strong>{formatNumber(parliament.final)}</strong><span>Final-text votes selected</span></div>
                  <div><strong>{formatNumber(parliament.withOutcome)}</strong><span>With an established adopted/rejected outcome</span></div>
                  <div><strong>{formatNumber(parliament.withMargin)}</strong><span>With an established decision margin</span></div>
                  <div><strong>{formatNumber(parliament.close)}</strong><span>Close under the site's margin criterion</span></div>
                </div>
                <h3>How many were close?</h3>
                <div className="insights-proportion" role="img" aria-label={`${parliament.close} close decisions out of ${recordedDecisions} final-text votes with known margins`}>
                  <span style={{ width: barWidth(parliament.close, recordedDecisions) }} />
                </div>
                <p className="insights-proportion__caption"><strong>{percentage(parliament.close, recordedDecisions)}</strong> of final-text votes with an established margin meet the site's <Link to="/votes?close=1">close-vote criterion</Link>.</p>
                <p className="insights-panel__footnote">The denominator excludes votes with no determinable margin. Votes without recorded outcomes are not treated as defeats. A close vote is not evidence of political controversy or a particular policy's merit.</p>
              </div>
            </section>

            <section className="insights-section" id="council" aria-labelledby="insights-council-heading">
              <div className="insights-section__intro">
                <p className="insights-overline">04 / Council of the EU</p>
                <h2 id="insights-council-heading">Positions recorded by government</h2>
                <p>For each Member State, a recorded vote against or abstention is counted separately from a vote in favour. Absence or non-participation is never recoded as opposition.</p>
                <p>These are published Council voting results, not a claim about a government's overall position on EU integration.</p>
                <Link to="/countries">Explore all Member States and their Council records</Link>
              </div>
              <div className="insights-panel">
                <h3>Recorded votes against and abstentions</h3>
                <p className="insights-panel__sub">Countries ordered by number of recorded opposing or abstaining positions. Counts are not comparable compliance or influence scores.</p>
                <div className="insights-council-list">
                  {council.map((c) => (
                    <div className="insights-council-row" key={c.code}>
                      <Link to={`/countries/${c.code}`} className="insights-council-row__name">{c.name}</Link>
                      <div className="insights-council-row__bar" role="img" aria-label={`${c.name}: ${c.against} votes against and ${c.abstained} abstentions, out of ${c.recorded} recorded positions`}>
                        <span style={{ width: barWidth(c.dissent, councilMax) }} />
                      </div>
                      <div className="insights-council-row__numbers"><strong>{formatNumber(c.dissent)}</strong><small>of {formatNumber(c.recorded)}</small></div>
                    </div>
                  ))}
                </div>
                {!council.length && <p>No Council positions are available in this snapshot.</p>}
                <p className="insights-panel__footnote">The numerator combines votes against and abstentions; the denominator is positions actually recorded for that country (excluding non-participation). See each country page for dates, decisions and underlying Council documents. Countries did not necessarily participate in the same set of votes.</p>
              </div>
            </section>

            <section className="insights-bottom" aria-labelledby="insights-method-heading">
              <p className="insights-overline">05 / How to read this</p>
              <h2 id="insights-method-heading">What these charts can—and cannot—tell us</h2>
              <div className="insights-bottom__grid">
                <div><h3>Traceable</h3><p>Each result is calculated directly from the same records you can open in the legislation, votes and countries sections. Counts change when the verified data snapshot changes.</p></div>
                <div><h3>Not a causal study</h3><p>Raw frequencies do not establish why a law passed, how an MEP was influenced or whether a government is effective. The site reports recorded events, without inferring motive.</p></div>
                <div><h3>Coverage is bounded</h3><p>The tracked procedure types, vote categories, publication period and available Council documents are limited. Missing information stays missing, not zero.</p></div>
              </div>
              <Link to="/about">Read the full methodology, corrections and coverage limitations</Link>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
