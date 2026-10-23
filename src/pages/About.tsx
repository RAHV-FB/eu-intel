import { Link } from 'react-router-dom';
import type { Meta, SourceStatusInfo } from '../types/data';
import { useData } from '../lib/data';
import { formatDateTime, formatNumber } from '../lib/format';
import { legislationScope, votesPeriod } from '../lib/scope';
import { ErrorState, ExtLink, Loading, PageHeader, Term, institutionLabel } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { useHashScroll } from '../features/guide/useHashScroll';
import { CLOSE_RELATIVE } from '../features/votes/labels';
import '../features/guide/guide.css';
import '../features/votes/common.css';

const STATUS_LABEL: Record<SourceStatusInfo['status'], string> = {
  ok: 'Retrieved',
  partial: 'Partly retrieved',
  failed: 'Retrieval failed',
  unavailable: 'Not available in this release',
};

const COUNT_LABEL: { key: keyof Meta['counts']; label: string }[] = [
  { key: 'dossiers', label: 'Legislative files (procedures)' },
  { key: 'legal_acts', label: 'Adopted legal acts' },
  { key: 'meps', label: 'MEPs (current and former)' },
  { key: 'meps_active', label: 'Current MEPs' },
  { key: 'ep_votes', label: 'Parliament votes' },
  { key: 'ep_votes_with_ballots', label: 'Parliament votes with each MEP’s recorded vote (whole texts, resolutions, motions and mandates)' },
  { key: 'council_votes', label: 'Council of the EU votes' },
  { key: 'national_measures', label: 'National transposition measures' },
  { key: 'infringements', label: 'Infringement cases' },
];

/**
 * Public record counts, used only when a build has no plain-language summary. Other keys in `records`
 * are per-run counters from the pipeline and are not shown.
 */
const RECORD_LABEL: Record<string, Record<string, string>> = {
  ep_people: { meps: 'MEPs', orgs: 'groups, parties and committees' },
  ep_procedures: { procedures: 'procedures', events: 'procedural steps' },
  ep_votes: { votes: 'plenary votes', ballots: 'votes with individual results' },
  eurlex: { acts: 'legal acts' },
  council: { votes: 'voting results', votes_with_positions: 'with Member State positions' },
  implementation: { measures: 'national measures', infringements: 'infringement cases' },
  train: { files: 'files' },
};

function recordsText(s: SourceStatusInfo): string | null {
  const labels = RECORD_LABEL[s.id] ?? {};
  const parts = Object.entries(labels)
    .filter(([k]) => typeof s.records?.[k] === 'number')
    .map(([k, label]) => `${formatNumber(s.records[k])} ${label}`);
  return parts.length ? parts.join(' · ') : null;
}

function SourceCard({ s }: { s: SourceStatusInfo }) {
  const summary = s.summary || recordsText(s);
  return (
    <article className="source-card" aria-labelledby={`src-${s.id}`}>
      <div className="source-card__head">
        <h3 id={`src-${s.id}`}>{s.name}</h3>
        <span className={`src-status src-status--${s.status}`}>{STATUS_LABEL[s.status] ?? s.status}</span>
      </div>
      <dl>
        <dt>Publisher</dt>
        <dd>{institutionLabel(s.institution)}</dd>
        <dt>Last successful retrieval</dt>
        <dd>{s.fetched_at ? formatDateTime(s.fetched_at) : 'Not retrieved'}</dd>
        {summary && (
          <>
            <dt>In this release</dt>
            <dd>{summary}</dd>
          </>
        )}
        <dt>Licence</dt>
        <dd>{s.licence}</dd>
        <dt>Source</dt>
        <dd>
          <ExtLink href={s.url}>Official documentation</ExtLink>
        </dd>
      </dl>
      {s.note && s.note !== summary && (
        <details className="source-card__log">
          <summary>Technical details of the latest retrieval</summary>
          <p>{s.note}</p>
          <p className="meta">
            The counts in this log are those of that retrieval. Records corrected since then from the same official
            answers can change them; the figures under “In this release” are the ones this site uses.
          </p>
        </details>
      )}
    </article>
  );
}

export default function About() {
  useDocumentTitle('About & methodology');
  const { data: meta, error, loading } = useData<Meta>('meta.json');
  useHashScroll(!loading);

  return (
    <div className="container page">
      <PageHeader
        eyebrow="About"
        title="About this project"
        lead="EU Legislative Intelligence is an independent, nonpartisan public website that explains what the European Union is doing — which laws are moving, who supported them, and how they reach each country — using only official EU records."
      />

      <div className="prose">
        <section aria-labelledby="what-h">
          <h2 id="what-h">What this is</h2>
          <p>
            The EU publishes a great deal of information, spread across many official websites and written mostly for specialists. This
            site brings together procedure records, Parliament and Council votes, adopted acts and national implementation data, joined by
            official identifiers, and explains them in plain language. Every fact links back to the official record it comes from.
          </p>
          <div className="not-same">
            <strong>Independent and not official.</strong> This is not an official website of the European Union or of any EU institution,
            and it is not endorsed by them. It takes no position on legislation, parties or countries: labels are neutral, and we do not rank
            parties, MEPs or Member States. Where official records are missing or unclear, we say so rather than fill the gap.
          </div>
          <p>
            New to the EU? Start with <Link to="/how-the-eu-works">How the EU works</Link>.
          </p>
        </section>

        <section id="sources" aria-labelledby="sources-h">
          <h2 id="sources-h">Data sources and licences</h2>
          <p>
            All data comes from official EU open-data services and registers. The status below is read from the current build, so it shows
            what this version of the site actually contains.
          </p>
          {loading && <Loading label="Loading source status…" />}
          {error && <ErrorState error={error} title="Source status could not be loaded" />}
          {meta && (
            <>
              <p className="meta">
                This version was built on {formatDateTime(meta.built_at)}
                {meta.snapshot_at && <>; the latest successful retrieval from a source was on {formatDateTime(meta.snapshot_at)}</>}.
              </p>
              <div className="sources">
                {meta.sources.map((s) => (
                  <SourceCard key={s.id} s={s} />
                ))}
              </div>
            </>
          )}
        </section>

        <section id="coverage" aria-labelledby="coverage-h">
          <h2 id="coverage-h">What’s covered</h2>
          {meta ? (
            <>
              {legislationScope(meta.scope) && (
                <p>
                  {legislationScope(meta.scope)}
                  {votesPeriod(meta.scope) && <> Parliament votes are covered from {votesPeriod(meta.scope)}.</>} Lists and
                  counts on this site refer to this dataset, not to all EU law.
                </p>
              )}
              {meta.coverage_notes.length > 0 && (
                <ul>
                  {meta.coverage_notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}
              <div className="table-wrap table-card">
                <table className="table">
                  <caption>Records in this version of the site</caption>
                  <thead>
                    <tr>
                      <th scope="col">Record type</th>
                      <th scope="col" className="num">
                        Count
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {COUNT_LABEL.map((c) => (
                      <tr key={c.key}>
                        <th scope="row" style={{ fontWeight: 400 }}>
                          {c.label}
                        </th>
                        <td className="num">{formatNumber(meta.counts[c.key])}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note" style={{ marginTop: 'var(--sp-3)' }}>
                A count of zero means the source was not available for this release, not that nothing happened.
              </p>
            </>
          ) : (
            !loading && <p className="meta">Coverage information is unavailable.</p>
          )}
        </section>

        <section id="selection" aria-labelledby="selection-h">
          <h2 id="selection-h">How featured files are selected</h2>
          <p>
            The homepage features a small number of major legislative files chosen by editorial judgement, aiming for a spread of topics
            and broad public relevance. Being featured is not a ranking and does not mean a file is more important than others.
          </p>
          <ul>
            <li>
              For featured and other curated files we add a short title and a plain-language description of what the law does and who it
              affects. These are written from the official sources listed with them and carry the date they were last reviewed.
            </li>
            <li>
              Everything else — status, dates, next steps, votes, implementation — is computed from official data, never written by hand.
            </li>
            <li>
              The homepage lists are rule-based: <em>Recently adopted</em> (formally adopted acts, newest first);{' '}
              <em>Under discussion</em> (files not yet adopted with a recorded procedural step in the last 120 days);{' '}
              <em>Close votes</em> (the most recent final Parliament votes on a whole text that were close, as defined under “Votes and
              margins” below); <em>Rejected</em> (final votes on a whole text that Parliament voted down,
              and motions to reject a proposal or the Council’s position that it adopted, with what happened to the file next; then files
              recorded as rejected — never amendments, rejected objections or motions of censure);{' '}
              <em>Stalled</em> (see below); <em>Coming up</em> (legally fixed dates in the next 12 months).
            </li>
          </ul>
        </section>

        <section id="methodology" aria-labelledby="method-h">
          <h2 id="method-h">Methodology</h2>

          <h3>Recorded, calculated, editorial, unavailable</h3>
          <p>
            We keep four kinds of statement apart: facts recorded by an official source; statistics we calculate from those records
            (marked “Derived from recorded events” where it matters); editorial selections and descriptions; and information that is not
            available, which we show as missing rather than guess.
          </p>

          <h3>Status of a legislative file</h3>
          <p>
            A file’s stage is worked out from the events recorded by Parliament’s Legislative Observatory and from the adopted act recorded
            in EUR-Lex. Labels are deliberately precise: for example, “Approved by Parliament” is not “passed” when the Council has not yet
            agreed.
          </p>

          <h3>Topics</h3>
          <p>
            A file’s topics come from the subject codes in Parliament’s procedure record (the Legislative Observatory’s subject
            classification), grouped into broad topics; for featured files our editors may add a topic. Files whose codes
            fall outside the ten topics (mostly regional and cohesion funds, the EU’s institutions, development cooperation,
            external relations and culture), and the few with no Parliament record of their own, have no topic
            {meta?.scope ? <> ({formatNumber(meta.scope.dossiers_without_topic)} files in this release)</> : null}. They are
            in the full list and in search, and the legislation explorer can list them under “No topic assigned”, but they do
            not appear on topic pages or in topic counts.
          </p>

          <h3>Stalled and blocked files</h3>
          <p>
            We call a file <strong>officially blocked</strong> only when Parliament’s Legislative Train Schedule labels it “blocked” (no
            progress for at least nine months, in the Train’s own definition). Otherwise we state only a fact: the number of days since the
            last recorded procedural step. Files still under discussion with no recorded step for a year or more appear in the homepage’s
            “Stalled” list, described that way — this is not an official assessment, and work can continue without a recorded step.
          </p>

          <h3>Votes and margins</h3>
          <ul>
            <li>Totals are Parliament’s official results. Individual votes come from roll-call records.</li>
            <li>
              A margin is shown only when the threshold that applied can be established: a majority of votes cast, a majority of all
              members, or two thirds of the votes cast. The margin is the number of votes in favour above or below that threshold:
              “Majority reached: 10 votes more than needed” means the text or motion voted on was adopted, not that a law was passed —
              a final vote can be Parliament’s opinion, or its position before the Council has agreed.
            </li>
            <li>
              In the vote explorer and the homepage’s <em>Close votes</em> list, a vote is marked <strong>close</strong> when the votes
              in favour were within {formatNumber(CLOSE_RELATIVE * 100)}% of the votes counted towards the threshold.
            </li>
            <li>
              <strong>Group majority</strong> is the most common position among a political group’s members with a recorded vote, using
              membership on the day of the vote; <strong>cohesion</strong> is the share of them who voted that way. If positions are tied,
              no majority is shown. These describe how members voted individually — a group has no vote of its own.
            </li>
            <li>
              Breakdowns by country group MEPs by the country they were elected in. They are <strong>not</strong> that country’s position,
              which is expressed by its government in the <Term id="council">Council of the EU</Term>.
            </li>
            <li>
              An MEP with no recorded vote did not vote or was absent: <strong>“not recorded” is not “abstained”</strong>. Vote corrections
              published after a vote are shown as notes and never change the result.
            </li>
          </ul>

          <h3>Council votes</h3>
          <p>
            Where Member States’ positions are published, we check them against the applicable rule: for a{' '}
            <Term id="qmv">qualified majority</Term>, the share of Member States and the share of the EU population (using the population
            figures the Council itself applies each year); for <Term id="unanimity">unanimity</Term>, whether any participating Member State
            voted against. If the figures needed are not verified, we do not show that part of the check.
          </p>

          <h3>Implementation</h3>
          <ul>
            <li>
              <strong>Measures notified</strong>: the number of national measures a Member State has notified for a directive, as listed by
              EUR-Lex. A notification does not show that transposition is complete or correct.
            </li>
            <li>
              <strong>No measures found in the available dataset</strong> is not proof of non-compliance; <strong>Deadline not yet reached</strong>{' '}
              and <strong>Data unavailable</strong> mean exactly that.
            </li>
            <li>
              <strong>Infringement cases</strong> come from the Commission’s register of infringement decisions: all open cases and all
              cases with a Commission decision since 1 January 2019 (cases closed before then are not included). Stages are shown as
              published. An open case is not a court ruling.
            </li>
            <li>
              Published indicators are shown with their period, definition and source. We never combine different measures into a single
              score or ranking.
            </li>
          </ul>

          <h3>Missing and changing records</h3>
          <p>
            Official databases are sometimes incomplete, late or inconsistent with each other. When a record is missing we say “not
            recorded” or “unavailable”; when two sources disagree we follow the official result and note the difference. Changes are
            detected by comparing successive snapshots of the sources and dated by the underlying event.
          </p>
        </section>

        <section id="limitations" aria-labelledby="limits-h">
          <h2 id="limits-h">Limitations</h2>
          <ul>
            <li>Coverage depends on what each official source makes available in machine-readable form; see the status of each source above.</li>
            <li>Plain-language summaries simplify. The legal texts on EUR-Lex are authoritative.</li>
            <li>
              Our membership and voting data covers the parliamentary terms listed under coverage; earlier periods are not fully included.
            </li>
            <li>The site is updated when its data is rebuilt; it is not a live feed.</li>
          </ul>
          <p>
            See also: <Link to="/privacy">Privacy</Link>.
          </p>
        </section>
      </div>
    </div>
  );
}
