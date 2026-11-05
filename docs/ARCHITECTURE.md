# Architecture

```
Official EU sources ──fetch──▶ data/snapshot/** (normalized, validated, committed)
                                     │
data/curated/*.yaml ─────────────────┤ build (offline, deterministic)
                                     ▼
                              public/data/** (compact static JSON, Atom feeds, calendars)
                                     │
                              React SPA (Vite) ──▶ GitHub Pages (static)
```

## Why this shape

- **No backend, no database, no keys.** Everything the browser needs is a static file; visitors never contact
  EU APIs (privacy, speed, robustness).
- **Fetch and build are separate.** `fetch` touches the network and may fail per source; `build` is offline and
  reproducible from the committed snapshot. A failed source keeps its previous validated files, so a transient
  outage never erases published data. `_manifest.json` records the last successful retrieval per source, and the
  site displays it.
- **The snapshot is committed.** Git history gives auditability and lets the build diff successive snapshots to
  record *verified* changes (activity feed) without inventing history.

## Pipeline (`pipeline/`)

| Module | Role |
| --- | --- |
| `http.py` | Single HTTP client: timeouts, retries with backoff, Retry-After, per-host throttle, disk cache, Cellar SPARQL helper |
| `snapshot.py` | Atomic, diff-friendly JSON writing (one record per line, sorted keys); manifest |
| `models/entities.py` | **Snapshot contract** (pydantic): Procedure, Event, LegalAct (with its TranspositionDate, ValidityNote and CourtRuling sub-records), ProcedureNotice, EpVote, EpBallots, Mep, Organization, Membership, CouncilVote, NationalMeasure, InfringementCase, CountryIndicator, ImplementationCoverage, DirectiveOptOut, TrainFile, PlannedStep, OfficialSummary, ActContext (with ConsolidatedVersion, CourtDecision and CourtCase), AdvisoryOpinion, ProcedureCase, SourceRef, and SourceStatus (`_manifest.json`). CheckedTransposition is a build-only annotation (`exclude=True`, set by `build.py` from curated YAML), not part of the snapshot |
| `models/countries.py` | Member State table and code normalization (EU "EL" → ISO "GR") |
| `sources/ep_people.py` | MEPs, groups, national parties, committees, dated memberships (EP Open Data API v2) |
| `sources/ep_procedures.py` | Procedures and their events/documents (EP Open Data API v2) |
| `sources/ep_votes.py` | Plenary decisions with roll-call ballots (EP Open Data API v2) |
| `sources/eurlex.py` | Legal acts: CELEX, ELI, dates, procedure links, amendments; Commission withdrawals and replacements of proposals → `procedure_notices.json` (Cellar SPARQL) |
| `sources/council.py` | Council voting results (see DATA_SOURCES.md for availability) |
| `sources/implementation.py` | National implementing measures (Cellar), infringements, country indicators: each Member State's overdue Single Market directives from the Single Market Scoreboard's transposition table (`indicators.json`; nothing is read from a table that fails its checks) |
| `sources/optouts.py` | Treaty opt-outs (Protocols No 21 and 22: Denmark, Ireland) that a directive's recitals record, and later opt-ins confirmed by Commission decisions → `optouts/directives.json` (EUR-Lex texts via Cellar) |
| `sources/lawcontext.py` | The law in context (Cellar): EUR-Lex's summaries of EU legislation (their opening section, read as plain text by content negotiation), judgments interpreting each act and cases pending on it, consolidated versions, EESC and CoR opinions on each file, actions against a proposal's withdrawal → `lawcontext/{acts,summaries,opinions,procedure_cases}.json` |
| `sources/legislative_train.py` | EP Legislative Train status of major files |
| `sources/agenda.py` | Steps the Council and Parliament have scheduled, as they publish them ahead: planned events in Cellar (`cdm:event_legal_projected`, with the meeting their Council agenda names) → `agenda/planned.json`; Parliament's plenary agenda (EP API foreseen activities) → `agenda/plenary.json`. Each run replaces both files |
| `analysis/status.py` | Lifecycle stage, next step, inactivity vs official "blocked" |
| `analysis/transposition.py` | Classifies each transposition date Cellar records as a deadline, an application date or another date; `data/curated/transposition.yaml` settles the cases its labels cannot |
| `analysis/ep_margin.py` | Vote margin relative to the legally applicable majority |
| `analysis/council_qmv.py` | Council QMV/unanimity arithmetic |
| `analysis/activity.py`, `feeds.py` | Snapshot diffing → verified activity; Atom feeds: all recent activity, one per topic, and one per file (`feeds/dossiers/<id>.xml`: its latest 10 entries of any date) |
| `analysis/tracker.py` | The implementation tracker: `transposition.json` (the directives of the site's files whose general transposition deadline falls in the last 3 years or the next 12 months, a month more at each end; each Member State's status as on the directive's page, its measures, latest notification and open infringement cases), and one Atom feed per Member State (`feeds/countries/<CC>.xml`, its newest 100 entries, each dated by its event: the national measures it notified for the site's directives, one entry per directive and notification date; the Commission's infringement decisions on it, one per case, stage and date; the transposition deadlines reached of the directives that bind it). Ids are `feeds.TAG_BASE` tag URIs |
| `analysis/changes.py` | How activity items read, for the What changed page and the feeds: what happened apart from the file's title (`event` in `activity.json`), the file's full title in a headline, and a status change paired with the item of the step that gave the status (`step_id`: the same file and day, the record it cites, else a step of a kind that dates the status). It never adds, drops or re-dates an item |
| `analysis/scheduled.py` | Planned steps joined to files by procedure reference, those dated after the build only: each file's `scheduled` and the home page's "Scheduled in the next 3 weeks" |
| `analysis/applies.py` | When new rules apply → `applies.json`: one row per act, date and kind (entry into force; application, in general or for some provisions; transposition deadline; national measures applying), from 31 days before the build on, as the file's timeline states the dates (EUR-Lex's, or those of `data/curated/act_dates.yaml` with the provisions each covers; `other` transposition dates and dates after an act's validity left out), with where: the Member States bound, those not bound with the reason the data give (recitals, the Council's voting result, the directive's own exemption), and those the data cannot tell (Denmark and Ireland without a record, a decision's addressees). Its feeds under `feeds/applies/` (`all`, `topics/<slug>`, `countries/<code>`): Atom of the next 90 days and iCalendar of every row, with entry ids, UIDs and timestamps that do not change from build to build |
| `analysis/ical.py` | iCalendar (RFC 5545): CRLF lines folded at 75 octets, TEXT escaping, whole-day events |
| `analysis/lawcontext.py` | A file's official summaries, court cases, consolidated texts and advisory opinions for its page, by the CELEX of its acts and its procedure reference (fields left out when there are none) |
| `build.py` | Joins everything by official identifiers → `public/data/**` per `src/types/data.ts`; `--strict` (`EU_INTEL_STRICT=1`) fails when it had to work around a problem |
| `freshness.py` | How old each source's data may get before the site and the Data health issue call it stale; the core sources behind `core_data_at`; when the Legislative Train's "blocked" stops being shown |
| `validate.py` | Schema + invariants (ballot totals, referential integrity, legal-type rules); on a build, the claims in `public/data` against the rules and the files' own records, and the contract (`contract.py`: the built JSON against `src/types/data.ts`). Errors fail; warnings are by design (not counted), integrity (fail unless `validate_baseline.json` accepts the finding) or backlog |

### Identifiers and linking

Records are joined **only through official identifiers**: procedure reference `YYYY/NNNN(TYPE)` (EP process id
`YYYY-NNNN`), CELEX, ELI, EP person/organization ids, EP voting ids, ISO country codes. A dossier can link to
several acts, many events and many votes. No link is ever inferred from title similarity; an ambiguous
relationship is left unlinked. Where the EP's final-act list and EUR-Lex give an act to different procedures, the EP's
wins only when something supports it (the procedure EUR-Lex names lists other final acts, or the claimant is a part
of a split procedure); otherwise the act stays on the procedure its own EUR-Lex record names.

### Provenance

Each record carries a `SourceRef` (institution, URL, identifier, retrieval time). The build forwards sources to
the UI; every institutional fact on a page has a reachable origin.

## Frontend (`src/`)

- React 19 + TypeScript + Vite; react-router `BrowserRouter` with the Pages base path.
- `scripts/prerender-routes.mjs` writes an `index.html` per known route (correct `<title>`, HTTP 200 on direct
  navigation; a file's page also links its Atom feed) plus `404.html` as SPA fallback — no server rewrites needed. The former topic addresses
  (`/topics/<slug>/`) get a static page that redirects to `/legislation/?topic=<slug>` without a script (`noindex`).
- **Link previews, search engines and readers without JavaScript** (`scripts/seo.mjs`, used by the prerender; Plan 3.1).
  Every page the prerender writes with `page()`, the home page and `404.html` carry Open Graph and Twitter tags: `og:title`
  and `og:description` are the page's own title and description, `og:type` `website`, `og:site_name`, `og:locale`
  `en_GB`, `twitter:card` `summary`, and, only with `SITE_URL` (their addresses are absolute), `og:url` (the canonical
  address) and `og:image`, the site's icon as a 512 × 512 PNG (`public/og-image.png`, 6 KB, with `og:image:alt`), which
  `scripts/render-og-image.mjs` renders from the icon in `index.html` with Chromium (shapes only, so the same Chromium
  gives the same file; run it again when the icon changes). A
  legislative file's page also carries, in its `<noscript>` block, the key facts its page states once loaded: title and
  names, status and its explanation, the next step, procedure and type, the dates of proposal, adoption and publication,
  the CELEX number and the official links, and "When it applies" (entry into force, application and transposition dates,
  labelled without a tense); in the page's words (status labels and next steps as the data gives them, wording as
  `Dossier.tsx` and `Summary.tsx` put it), as of the data's build date, ending with how current the data is. A browser
  that runs scripts never renders a `<noscript>` block, so a reader with JavaScript never sees them, not even before the
  app has loaded. A file with an act also describes it as schema.org `Legislation` in JSON-LD (its title, number, CELEX
  number, type, date, publication, legal force from the status the page gives, EUR-Lex page, ELI and the page's
  address); a `<script type="application/ld+json">` is a data block, never executed, so the CSP does not apply to it.
  `tests/e2e/seo.spec.ts` compares the facts with the loaded page for files of each kind. With `SITE_URL` the prerender
  writes `sitemap.xml`: every page written by `page()` (a new route is listed by being written there) and the home page,
  but `/following/` and `/search/`, which have nothing of their own to index, with `lastmod` where the data dates a
  change (a file's latest step or the latest change recorded on it, a vote's date); past 50,000 addresses or 50 MB it
  becomes the index of `sitemap-<n>.xml` files. `robots.txt` allows every crawler everything and names the sitemap
  (docs/DEPLOYMENT.md, "Search engines and link previews").
- **What changed** (`/legislation/changes`, `src/pages/Changes.tsx`, `src/features/changes/`) reads `activity.json`: the
  changes grouped by the week our data refresh first recorded them (`detected_at`; a step already in the records when
  recording began has none, and is grouped by its own date), and within a week by the topics of each file
  (`dossiers/index.json`), with filters by topic and kind of change (kept in the address) and each topic's Atom feed. A
  status change is told with the step that gave the status (`step_id`), as in the feeds. Each change links its file's
  page and the official records it cites. It is a view of Legislation, not one of the seven primary destinations
  (docs/PRODUCT.md): the home page, the explorer and the footer lead to it. The home page's **This week in EU law** shows
  the changes of the latest week of recording, with counts by kind; it is called "this week" only while the latest
  refresh is at most a week old on the reader's date.
- **When new rules apply** (`/legislation/applies`, `src/pages/Applies.tsx`, `src/features/applies/`) reads `applies.json`:
  the dates fixed in law from which rules start to apply, by month, in the next 30 or 90 days (the default), the next 12
  months, every date ahead or the last 30 days, by topic and Member State (kept in the address). Which window a date is
  in, and its tense, are judged on the reader's date by the rule of `src/lib/format.ts` (an entry into force or
  application has come on its day, a transposition deadline passes once its day is over; `stepTitle` gives the past
  tense). A Member State's view lists the acts that bind it and those the data cannot tell, each row saying where it
  applies and why a Member State is not bound or not known; "All 27 Member States" only when all are bound. Unlike the
  steps the Council and Parliament schedule (`ScheduledNext.tsx`), these dates are fixed in law. The page links the Atom
  feed and calendar of every date, of its topic and of its Member State, and announces its feed in `<head>`
  (prerendered too). The explorer, a file's "When it applies" and the home page's "Coming up" lead to it.
- List rows name each file's **latest recorded step** ("Latest step: Council adopted the act · 26 Oct 2026"): the
  explorer and search results from `last_step` (`dossiers/index.json`) and `e` (`search.json`), the home lists from
  `step`. A step dated in the law that passes after the build (`steps_ahead`, the next 60 days) becomes the latest step
  on the reader's date, as on the file's page (`src/features/legislation/latestStep.ts`, which uses its `latestDone`).
- The **stuck view** is the explorer's sort "Longest without a recorded step" (`?stage=active&sort=stuck`, the home
  "Stalled" list's link): files still being decided first, each saying for how long on the reader's date. A file's page
  says under its status that it is officially reported as blocked (only while the Legislative Train's copy is current:
  `blockedNow`) and how long it has had no recorded step.
- A search or a keyword in the explorer that finds nothing says what the site covers and what it does not (implementing
  and delegated acts, non-legislative procedures, laws before the dataset, national law), and links the same words on
  EUR-Lex's own search (`src/components/OutOfScope.tsx`; a plain link, the words URL-encoded).
- Each file's page links its Atom feed ("Follow in a feed reader") and announces it in `<head>` (`<link rel="alternate"
  id="page-feed">`, written into the prerendered page and kept to the page shown by `useFeedLink`). So does each country
  page, for its own feed (`feeds/countries/<CC>.xml`).
- **One address per directive**: `/legislation/<id>/#national` lands on the directive's table of the 27 Member States
  once the page has loaded (`useHashScroll`), on GitHub Pages too (the 301 to the trailing slash keeps the query and
  the fragment); `?country=FR` highlights that Member State's row. The section gives the address to copy ("Link to this
  table") with a Member State to highlight. A file with several directives has one table each, `#national-<CELEX>`.
- **Directives into national law** (`/legislation/transposition`, `src/pages/Transposition.tsx`,
  `src/features/transposition/`) reads `transposition.json`: the directives whose deadline falls in the last three years
  or the next twelve months on the reader's date, deadlines ahead (soonest first) and passed (latest first); each with its
  bound Member States counted by status, those not bound or exempted named apart, and its open non-communication cases;
  filters by topic, deadline passed or ahead, and Member State (that country's status on each directive, its open
  cases, its page, its feed and the Commission's count for it). Nothing is ranked, sorted by status or added up into a
  score. A view of Legislation, linked from the explorer and the country pages, not from home.
- **Time since a deadline** is told on the reader's date (`src/lib/deadline.ts`, as `freshness.ts` judges a source's
  age): "2 years ago", "in 4 months", "15 months after the deadline". A Member State's status is restated on that date
  (`statusOn`): no measures in the dataset reads "Deadline not yet reached" until the deadline's day is over, then "No
  measures found in the available dataset".
- The **Single Market Scoreboard**'s count of a Member State's overdue Single Market directives is shown on that
  country's page only (and in the tracker's view of that country), as the Commission's count with its period and
  source; the Countries table has no indicator columns, which would rank the Member States. The Following page
  downloads the feeds of the files followed as one OPML file, made in the browser (a `data:` link with `download`, which
  the Content-Security-Policy does not restrict; nothing is sent).
- `src/types/data.ts` is the **public data contract**. Pages lazy-load only the JSON they need:
  `home.json` for the homepage, `dossiers/index.json` for the explorer, `dossiers/<id>.json` per law, etc. The vote
  tables of the MEP, political group and national party pages read `votes/titles.json` (the votes of
  `votes/index.json`, in its order, with only the date, title, kind of vote, procedure reference, distinction, result
  and file they show), not the whole index, which only the votes list needs. A vote page's table by national party
  is added up in the browser (`src/features/votes/partyRows.ts`) from the ballots, which give each MEP's party record
  on the day, and the vote file's `no_vote`, with the party names of `people/parties.json`; the party pages' counts
  come from the same build step (`party_breakdown`), and a data test checks that the two agree.
- Search: `search.json` + an in-browser engine (`src/lib/search.ts`): accent/case folding, aliases, identifier
  matching, prefix, word-family ("fish" -> "fisheries", ranked below whole words) and bounded fuzzy matching
  (flagged `approximate` and ranked last; /search, the header suggestions, /legislation and /votes say so), static
  boosts. A query that is an identifier matches only through identifiers (a split part also typed without its
  procedure type, "2016/0224A") and names citing it; the start of an act's official title ("Regulation (EU) 2016/679
  of the European Parliament and of the Council of …") and its EUR-Lex or ELI address are its identifier. The list
  filters for names and parties (vote ballots, People) fold accents as the search does.
- Design tokens in `src/styles/tokens.css`; shared primitives in `src/components/ui.tsx`. Shared visual patterns
  are defined once in `src/styles/base.css` and `components.css`, and feature styles reuse them rather than restyle
  them: one section-title style, line length (`--measure`), two note boxes (`.callout`, `.callout--distinction`),
  status tags with icons drawn in CSS (`StatusIcon`), `.row-link` for a row's title or name, `.ref` for procedure
  references (monospace only for identifiers), metadata separated by dots that never open a line (`.dot-list`),
  and the loading, empty, error and not-found states.
- Strict CSP meta: `default-src 'self'`, and scripts and styles only from the site's own files, none inline
  (`scripts/check_privacy.mjs` fails a build with `'unsafe-inline'` or an inline style). React sets its `style` props
  through the CSSOM, which the policy does not restrict; only the dev server's page allows inline styles, which it
  injects (`vite.config.ts`). Styles a reader applies through the browser (a user style sheet, CSS an extension
  inserts) are not subject to the policy, but a bookmarklet that adds an inline `<style>` element is refused, so the
  e2e text-spacing check loads its style sheet as a file. No third-party fonts/scripts, no cookies. The optional
  watchlist writes nothing to `localStorage` before the visitor's first "Follow" click (pages check for storage by reading only).
  After that the list changes on clicks only, except that opening the page of a followed file records what the
  visitor last saw there (`markSeen`: its stage, status label and latest event, when one of them changed), as
  /privacy says ("when you last viewed it").
- Dates that the data states as still ahead (the home page's "Coming up", "Scheduled" timeline steps, next steps,
  status explanations) are compared with the visitor's date, since the data is rebuilt only weekly
  (`src/lib/format.ts`): a date that has passed is restated as the build would state it on that day (past tense,
  left out of a list of later dates, the step's past title, "Latest recorded step"), and a transposition
  deadline passes only once its day is over. The status label stays as built; when its explanation states a date
  that has passed since, the dossier page says the status is as recorded at the last data refresh.
  `format.test.ts` checks every built next step, status explanation and dated timeline step with the clock moved
  forward, and fails on a dated wording it does not know. A step the Council or Parliament has scheduled (a file's
  "Scheduled next", the home page's "Scheduled in the next 3 weeks") stays ahead on its day; after it, the file's page
  says it "was scheduled for …; not yet recorded as done" and the home page leaves it out (`ScheduledNext.tsx`).
- How fresh the data is is judged on the visitor's date too (`src/lib/freshness.ts`), from `meta.json`: home and the
  footer give the date to which procedures, votes and acts are current (`core_data_at`, the oldest core retrieval) and
  name the sources whose last successful retrieval is older than their `stale_after_days` (thresholds in
  `pipeline/freshness.py`, none in the app); About marks the same sources. Once the Legislative Train copy is older
  than its `labels_expire_after_days`, no file is shown as officially blocked (badges, list tags, the `?blocked=1`
  filter and sort, the home "Stalled" list), and the file's page says the classification is not shown and why.

## Operations

- `ci.yml` (pushes to `main`, pull requests, manual runs): lint, typecheck (app and e2e tests); Python tests, data
  build, vitest, site build and a Playwright e2e and accessibility job in three engines on the frozen test data
  (`tests/frozen-data.txt`; a manual run can skip e2e); the data gate on the commit's own data (validate, strict build,
  `validate --built`, the dated-wording check, site build, privacy check, size check). It does not run after a refresh.
- `pages.yml`: deploy to GitHub Pages once CI has passed on a push to `main`, when a refresh calls it with the commit
  it pushed, or on manual dispatch, after running the data gate again on the commit it deploys.
- `refresh.yml`: twice on Mondays, and on Fridays for the core sources and the planned dates (a scheduled run is skipped
  if every core source was retrieved in the last 20 hours): `fetch` (incremental, each record re-read at least every 8
  weeks; a full refresh in the first week of each month or by hand) → `validate` per source → the data gate, recording
  activity → commit snapshot and state → deploy that commit, if CI has passed on its code.
- `rebuild.yml`: daily, deploys `main` again, built with the day's date (no fetch, no commit), once CI has passed on its
  code and while no refresh runs.
- `watchdog.yml`: after each refresh, CI run on `main`, deploy and daily rebuild, and daily, opens, updates or closes the
  "Data health" issue (failed or stale sources, a failed refresh, deploy or rebuild, red CI on `main`, live data more
  than 8 days old, the repository past 750 MB, and anything it could not check).

## Future analytics (not implemented)

The architecture leaves room for a self-hosted, cookieless Umami instance later. Nothing is loaded today; adding
it requires a privacy/ePrivacy assessment and an update of the privacy notice and CSP.
