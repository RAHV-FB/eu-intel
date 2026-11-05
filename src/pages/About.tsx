import { Link } from 'react-router-dom';
import type { CountrySummary, DataPackage, Meta, SourceStatusInfo } from '../types/data';
import { DATA_BASE, useData } from '../lib/data';
import { formatDate, formatDateTime, formatNumber, plural } from '../lib/format';
import { classifications, isStale } from '../lib/freshness';
import { legislationScope, votesPeriod } from '../lib/scope';
import { ErrorState, ExtLink, Loading, PageHeader, Term, institutionLabel } from '../components/ui';
import { useDocumentTitle } from '../features/legislation/labels';
import { useHashScroll } from '../features/guide/useHashScroll';
import { CLOSE_RELATIVE } from '../features/votes/labels';
import '../features/guide/guide.css';
import '../features/votes/common.css';

/** The project's public source code: the editorial policy and the corrections (`data/curated`) are kept there. */
const REPOSITORY = 'https://github.com/RAHV-FB/eu-intel';

const STATUS_LABEL: Record<SourceStatusInfo['status'], string> = {
  ok: 'Retrieved',
  partial: 'Partly retrieved',
  failed: 'Retrieval failed',
  unavailable: 'Not available in this release',
};

const COUNT_LABEL: { key: keyof Meta['counts']; label: string }[] = [
  { key: 'dossiers', label: 'Legislative files' },
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
  agenda: { planned: 'planned events (EUR-Lex)', plenary: 'plenary agenda items' },
};

function recordsText(s: SourceStatusInfo): string | null {
  const labels = RECORD_LABEL[s.id] ?? {};
  const parts = Object.entries(labels)
    .filter(([k]) => typeof s.records?.[k] === 'number')
    .map(([k, label]) => `${formatNumber(s.records[k])} ${label}`);
  return parts.length ? parts.join(' · ') : null;
}

/** One source: its latest attempt (the status), its last successful retrieval and whether that is up to date on the
 * reader's date (`now`), by the threshold the data gives it, as the home page and the footer judge it. */
function SourceCard({ s, now }: { s: SourceStatusInfo; now: number }) {
  const summary = s.summary || recordsText(s);
  const stale = isStale(s, now);
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
        <dd>
          {s.fetched_at ? formatDateTime(s.fetched_at) : 'Not retrieved'}
          {stale && <strong className="source-card__stale"> · Not up to date</strong>}
        </dd>
        {s.status === 'failed' && s.attempted_at && s.attempted_at !== s.fetched_at && (
          <>
            <dt>Latest attempt</dt>
            <dd>{formatDateTime(s.attempted_at)} (failed)</dd>
          </>
        )}
        {s.stale_after_days != null && (
          <>
            <dt>Up to date for</dt>
            <dd>
              {plural(s.stale_after_days, 'day')} after a successful retrieval
              {s.labels_expire_after_days != null && (
                <>; its classifications are no longer shown after {plural(s.labels_expire_after_days, 'day')}</>
              )}
            </dd>
          </>
        )}
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
  const now = Date.now(); // the reader's clock: the data is rebuilt weekly but read for a week or more
  const train = classifications(meta, now);
  const countries = useData<CountrySummary[]>('countries/index.json');
  const hasIndicators = !!countries.data?.some((c) => c.indicators.length > 0);
  // the open dataset of this version: its tables, from its descriptor (pipeline/analysis/opendata.py)
  const openData = useData<DataPackage>('open/datapackage.json');
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
            A few links lead to independent, non-official websites, such as each roll-call vote’s page on HowTheyVote.eu; they are labelled
            as such, and we take no data from those sites.
          </p>
          <p id="contact">
            <strong>Maintainer and corrections.</strong> The site is maintained by RAHV-FB, the GitHub account that owns the project’s{' '}
            <ExtLink href={REPOSITORY} official={false}>public repository</ExtLink>, where its code, data and editorial policy are kept. To
            report an error or a missing record, or to ask a question, open an issue in the{' '}
            <ExtLink href={`${REPOSITORY}/issues`} official={false}>repository’s issue tracker</ExtLink> (this needs a GitHub account, and
            issues are public).
          </p>
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
                {meta.core_data_at && (
                  <>
                    ; procedures, votes and acts are current to {formatDateTime(meta.core_data_at)}, the oldest last retrieval of
                    their sources
                  </>
                )}
                {meta.snapshot_at && <>; the latest successful retrieval from a source was on {formatDateTime(meta.snapshot_at)}</>}. A
                source is marked “Not up to date” once its last successful retrieval is older, on today’s date, than the period
                given for it.
              </p>
              <div className="sources">
                {meta.sources.map((s) => (
                  <SourceCard key={s.id} s={s} now={now} />
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
                A count of zero means the source was not available for this release, not that nothing happened. “Legislative files”
                counts every file in the legislation explorer: the procedures recorded by Parliament and the files without a
                Parliament procedure record of their own that the notes above describe.
              </p>
            </>
          ) : (
            !loading && <p className="meta">Coverage information is unavailable.</p>
          )}
        </section>

        <section id="reuse" aria-labelledby="reuse-h">
          <h2 id="reuse-h">Reuse the data</h2>
          <p>
            <strong>Open dataset.</strong> The data of this site is published as CSV tables with a schema: legislative files,
            adopted acts, Parliament and Council votes, the transposition of directives with the national measures notified,
            infringement cases, and a crosswalk of the official identifiers that join them. Its{' '}
            <a href={`${DATA_BASE}open/README.md`}>README</a> and{' '}
            <a href={`${DATA_BASE}open/datapackage.json`}>datapackage.json</a> (a Frictionless Data Package) give each
            column’s type and meaning. In each week the data changes, it is also released as a zip tagged data-YYYY-MM-DD
            among the repository’s <ExtLink href={`${REPOSITORY}/releases`} official={false}>releases</ExtLink>; cite a
            release by its tag, as the repository’s{' '}
            <ExtLink href={`${REPOSITORY}/blob/main/CITATION.cff`} official={false}>citation file</ExtLink> says.
          </p>
          {openData.data ? (
            <div className="table-wrap table-card">
              <table className="table">
                <caption>
                  The open dataset in this version: statuses as of {formatDate(openData.data.as_of)}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">File</th>
                    <th scope="col">Contents</th>
                    <th scope="col" className="num">
                      Rows
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {openData.data.resources.map((r) => (
                    <tr key={r.name}>
                      <th scope="row" style={{ fontWeight: 400 }}>
                        <a href={`${DATA_BASE}open/${r.path}`} className="mono">
                          {r.path}
                        </a>
                      </th>
                      <td>{r.title}</td>
                      <td className="num">{formatNumber(r.rows)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            openData.error && <p className="meta">The list of the dataset’s tables could not be loaded; its README lists them.</p>
          )}
          <p>
            <strong>The site’s JSON files.</strong> Each page reads static JSON files under{' '}
            <span className="mono">data/</span>, shaped for the pages: they can change with the site, and their current form
            is in <ExtLink href={`${REPOSITORY}/blob/main/src/types/data.ts`} official={false}>src/types/data.ts</ExtLink>.
            The open dataset is the stable form, with its columns documented in each release.
          </p>
          <ul>
            <li>
              <a href={`${DATA_BASE}meta.json`} className="mono">meta.json</a>: the sources, their last retrieval and reuse terms,
              the record counts and the coverage;
            </li>
            <li>
              <span className="mono">dossiers/index.json</span>, <span className="mono">dossiers/&lt;id&gt;.json</span>: the
              legislative files, each with its steps, acts, votes and transposition;
            </li>
            <li>
              <span className="mono">votes/index.json</span>, <span className="mono">votes/&lt;id&gt;.json</span>: the
              Parliament votes listed, each with every MEP’s recorded vote;
            </li>
            <li>
              <span className="mono">council/index.json</span>: Council votes, with each Member State’s position;
            </li>
            <li>
              <span className="mono">people/</span>, <span className="mono">countries/</span>: MEPs, political groups and
              national parties; for each Member State its MEPs, Council positions, transposition and infringement cases;
            </li>
            <li>
              <span className="mono">activity.json</span>: the steps recorded between weekly updates.
            </li>
          </ul>
          <p>
            <strong>Feeds.</strong> An <a href={`${DATA_BASE}feeds/updates.xml`}>Atom feed of all recorded steps</a>, and one for
            each topic, linked from its list of files. Their entries keep their ids if the site moves.
          </p>
          <p>
            <strong>CSV downloads.</strong> The tables of a vote page and the list of legislative files have a “Download CSV”
            button: the file is made in your browser from what the page shows, and nothing is sent.
          </p>
          <p>
            <strong>Licence.</strong> The dataset as compiled here (the selection, the structure, the derived fields and the
            checked corrections) is offered under{' '}
            <ExtLink href="https://creativecommons.org/licenses/by/4.0/" official={false}>CC BY 4.0</ExtLink>: credit
            “EU Legislative Intelligence (RAHV-FB)” with a link to this site. The official records in it keep their
            publishers’ terms, which also require acknowledging the source: see{' '}
            <a href="#sources">Data sources and licences</a>.
          </p>
        </section>

        <section id="selection" aria-labelledby="selection-h">
          <h2 id="selection-h">How featured files are selected</h2>
          <p>
            The homepage features five or six major legislative files, chosen by our editors. Each meets at least two of these criteria:
          </p>
          <ul>
            <li>it is part of a major package, or a named priority in the Commission’s work programme or Parliament’s Legislative Train;</li>
            <li>
              it has drawn significant institutional attention, for example a plenary vote with a recorded division or repeated
              negotiations between the institutions;
            </li>
            <li>people or companies must do, or may do, something concrete because of it;</li>
            <li>
              the institutions’ positions differ on the record, Member States’ statements were published by the Council, or a recorded
              vote was close or divided;
            </li>
            <li>it has reached an important milestone: recently adopted or published, a provisional agreement, or the start of negotiations;</li>
            <li>
              it has an officially recognised delay: a postponement adopted as law, or a “blocked” label on Parliament’s Legislative Train
              Schedule.
            </li>
          </ul>
          <p>
            Together the featured files include at least one adopted act and at least one pending proposal, with no more than two on the
            same topic. The selection is reviewed at least every three months and when the data show a material change. Being featured is
            not a ranking and does not mean a file is more important than others. The rules are in the{' '}
            <ExtLink href={`${REPOSITORY}/blob/main/docs/EDITORIAL.md`} official={false}>editorial policy</ExtLink>.
          </p>
          <ul>
            <li>
              For the homepage files and other curated files we add a short title and a plain-language description of what the law does and
              who it affects. These are written from the official sources listed with them and carry the date they were last reviewed. The
              other curated files meet at least one of the criteria.
            </li>
            <li>
              Everything else — status, dates, next steps, votes, implementation — is computed from official data. The one exception is a
              small set of corrections checked by hand against official texts, described under{' '}
              <a href="#corrections">Corrections checked against official texts</a>.
            </li>
            <li>
              The homepage lists are rule-based: <em>Recently adopted</em> (formally adopted acts, newest first);{' '}
              <em>Under discussion</em> (files not yet adopted with a recorded procedural step in the last 120 days);{' '}
              <em>Close votes</em> (the most recent final Parliament votes on a whole text that were close, as defined under “Votes and
              margins” below, except decisions on discharge for the EU budget); <em>Rejected</em> (final votes on a whole text that
              Parliament voted down, and motions to reject a proposal or the Council’s position that it adopted, with what happened to the
              file next; then files recorded as rejected — never amendments, rejected objections or motions of censure, or decisions on
              discharge for the EU budget);{' '}
              <em>Stalled</em> (see below); <em>Scheduled in the next 3 weeks</em> (steps the Council and Parliament have
              scheduled on a file, as they publish them: planned events recorded in EUR-Lex and Parliament’s plenary agenda;
              planned dates can change, and a step is left out once its day is over); <em>Coming up</em> (legally fixed dates
              in the next 12 months).
            </li>
          </ul>
        </section>

        <section id="methodology" aria-labelledby="method-h">
          <h2 id="method-h">Methodology</h2>

          <h3>Recorded, calculated, editorial, unavailable</h3>
          <p>
            We keep four kinds of statement apart: facts recorded by an official source; statements we derive from those records, such as
            a file’s stage and next step (marked “Derived from recorded events”), an outcome calculated from recorded vote counts (marked
            as such) and vote margins; editorial selections and descriptions; and information that is not available, which we show as
            missing rather than guess.
          </p>

          <div id="corrections">
            <h3>Corrections checked against official texts</h3>
            <p>
              Apart from the editorial texts, everything is computed from the retrieved official records. The exception is a small set of
              corrections, made only where an official text shows that a record is wrong or incomplete. Each one cites the provision of
              that text and lists the texts checked, and applies only in this site’s build: the retrieved data is kept unchanged.
            </p>
            <ul>
              <li>
                <strong>Dates of entry into force and application</strong>, where EUR-Lex’s record differs from the text of the act or of
                the act that amended it, and, for some acts, which provisions apply from each date, as the act’s text says. The file’s
                page says “Dates checked against the act’s text” and links the texts.
              </li>
              <li>
                <strong>The day the Council adopted an act</strong>, where the date in our sources differs from the one in the act’s own
                citation (“decision of the Council of …”). The timeline step or the Council vote quotes the citation and says which date
                the source records.
              </li>
              <li>
                <strong>Transposition dates of a directive</strong>: which of the dates EUR-Lex records is the general deadline, and, for a
                few directives, an exemption of some Member States that the directive’s own text provides.
              </li>
              <li>
                <strong>Council votes</strong>: where a voting-result document prints “qualified majority” but the act’s legal basis
                requires unanimity, the vote is shown under unanimity, with a note and the texts checked; and an adoption by written
                procedure that no voting-result document records is entered from the Council’s own communication on the outcome.
              </li>
              <li>
                A few further entries of the same kind, such as a link between two acts, or between an act and a procedure, that EUR-Lex
                records wrongly, Denmark’s decision (notified to the Council) on a directive that builds on the Schengen acquis, and the
                status of a file whose act the official records do not link to it.
              </li>
            </ul>
            <p>
              The corrections are listed in full in the{' '}
              <ExtLink href={`${REPOSITORY}/tree/main/data/curated`} official={false}>
                <span className="mono">data/curated</span> folder
              </ExtLink>{' '}
              of the project’s public repository, one file per kind, each entry with the provision it relies on.
            </p>
          </div>

          <h3>Status of a legislative file</h3>
          <p>
            A file’s stage is worked out from the events recorded by Parliament’s Legislative Observatory and from the adopted act recorded
            in EUR-Lex. Labels are deliberately precise: for example, “Approved by Parliament” is not “passed” when the Council has not yet
            agreed. <Link to="/how-the-eu-works#status-labels">The guide explains each label</Link> and whether the act is adopted or in
            force.
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
            last recorded procedural step. The Train’s labels are shown with the date of our copy of the Train
            {train?.retrievedAt ? <> (currently {formatDate(train.retrievedAt)})</> : null}, and only while that copy is at most{' '}
            {train?.expireAfterDays != null ? plural(train.expireAfterDays, 'day') : 'six weeks'} old on the day you read the page;
            after that, no file is shown as officially blocked until a newer copy is retrieved
            {train && !train.current ? <>, which is the case today</> : null}. The homepage’s “Stalled” list shows officially blocked
            files first (the Train’s most recent classifications, longest without a recorded step first, saying how many of them it
            shows), then files in the ordinary legislative procedure, where both Parliament and the Council must still act, with no
            recorded step for a year or more, described that way — this is not an official assessment, and work can continue without a
            recorded step.
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
              in favour were within {formatNumber(CLOSE_RELATIVE * 100)}% of the votes counted towards the threshold. The homepage list
              leaves out decisions on discharge for the EU budget: whether such a decision grants discharge depends on the proposal voted
              on, not on its being adopted or rejected.
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
              Breakdowns by national party use the party record Parliament’s membership data gives each MEP on the day of the vote, and
              are listed by country and party name. “Did not vote” counts a party’s MEPs in office that day, by those records, with no
              recorded vote; it is not given for days on which the records do not establish who was in office.
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
              <strong>Time since a deadline</strong> (“2 years after the deadline”, “in 4 months”) is counted on your date, not the
              date the data was built; a transposition deadline passes once its day is over, and a country without measures in the
              dataset reads “Deadline not yet reached” until then.
            </li>
            <li>
              <Link to="/legislation/transposition">Directives into national law</Link> lists the directives whose general
              transposition deadline falls in the last three years or the next twelve months, with each Member State’s status as
              the directive’s own page gives it. Member States a directive does not bind (opt-outs, exemptions in its text) are
              named apart, never counted. A directive’s table can be linked with one Member State’s row highlighted
              (<span className="mono">?country=FR</span>).
            </li>
            <li>
              Each country page links an <strong>Atom feed</strong> of the national measures the country notified for the directives
              on this site (one entry per directive and notification date), the Commission’s infringement decisions on it (each case’s
              latest decision, as the register publishes it, so a new decision is a new entry) and the transposition deadlines of the
              directives that bind it. Each entry is dated by the event it reports; a feed keeps its latest 100 entries.
            </li>
            <li>
              The <strong>Single Market Scoreboard</strong>’s count of each Member State’s overdue Single Market directives is read
              from the Commission’s table of the directives each Member State has not fully notified
              {hasIndicators
                ? ', and shown on that country’s page alone, with its period, definition and source.'
                : '. No data refresh has retrieved it yet, so none is shown.'}{' '}
              The Scoreboard’s other indicators are published only in embedded Power BI reports and are not read. We never combine
              different measures into a single score or ranking, and never set Member States’ figures side by side.
            </li>
          </ul>

          <h3 id="applies">When new rules apply</h3>
          <p>
            <Link to="/legislation/applies">When new rules apply</Link> lists the dates fixed in law from which an adopted act enters
            into force or applies (in general, or only some of its provisions), a directive’s transposition deadlines, and the dates from
            which the national measures transposing it apply: the dates each file’s page gives, as EUR-Lex records them or as we checked
            them against the act’s text, with the provisions each covers (see <a href="#corrections">Corrections</a>). A transposition
            date whose role EUR-Lex’s data do not establish, and a date after the end of an act’s validity, are left out. Which dates
            are ahead is judged on the day you read the page.
          </p>
          <p>
            Where: a regulation binds every Member State, and a directive each Member State to which it is addressed, except a Member
            State that the act’s recitals or the Council’s voting result record as not taking part in its adoption (Denmark and Ireland,
            under Protocols No 21 and 22 to the Treaties), unless a Commission decision confirms that it took part later, and one that a
            directive’s own text does not require to transpose it. Where no record in our data says whether Denmark or Ireland took part,
            the page says so. A decision binds those to whom it is addressed, which our data do not record.
          </p>
          <p>
            For every date, each topic and each Member State there is an Atom feed of the next 90 days and a calendar (iCalendar) of
            every date ahead. An entry keeps its identifier and its date from one data refresh to the next.
          </p>

          <h3>Official summaries, court cases and opinions</h3>
          <p>
            Where we have not written a summary of a law, its page quotes the opening section of EUR-Lex’s summary of the act
            (“Summaries of EU legislation”, written by the EU Publications Office), unchanged, labelled with the date EUR-Lex last
            updated it and linked to the full summary; pages with our own summary link it. Summaries EUR-Lex marks as obsolete are
            not shown, and a page says when a summary was last updated before the latest amending act we know of was published.
            The page also lists what EUR-Lex records on the law’s court cases (judgments and orders interpreting it, and cases
            whose file records no judgment, order or closure yet), its consolidated text, and the opinions of the European
            Economic and Social Committee and the European Committee of the Regions on the file. EUR-Lex links a case to its file
            for cases brought from 2024 and some of 2023, so earlier cases are never shown as pending.
          </p>

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
            <li>
              Procedures, votes, adopted acts and planned dates are refreshed twice a week (Mondays and Fridays), the other sources
              weekly; a refresh can be late or skipped. The homepage and the footer give the date to which procedures, votes and acts
              are current, and name any source that is not up to date. The site is not a live feed.
            </li>
          </ul>
          <p>
            See also: <Link to="/privacy">Privacy</Link>.
          </p>
        </section>
      </div>
    </div>
  );
}
