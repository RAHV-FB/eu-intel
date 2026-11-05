# Architecture

```
Official EU sources ──fetch──▶ data/snapshot/** (normalized, validated, committed)
                                     │
data/curated/*.yaml ─────────────────┤ build (offline, deterministic)
                                     ▼
                              public/data/** (compact static JSON, Atom feeds)
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
| `models/entities.py` | **Snapshot contract** (pydantic): Procedure, Event, LegalAct (with its TranspositionDate, ValidityNote and CourtRuling sub-records), ProcedureNotice, EpVote, EpBallots, Mep, Organization, Membership, CouncilVote, NationalMeasure, InfringementCase, CountryIndicator, ImplementationCoverage, DirectiveOptOut, TrainFile, SourceRef, and SourceStatus (`_manifest.json`). CheckedTransposition is a build-only annotation (`exclude=True`, set by `build.py` from curated YAML), not part of the snapshot |
| `models/countries.py` | Member State table and code normalization (EU "EL" → ISO "GR") |
| `sources/ep_people.py` | MEPs, groups, national parties, committees, dated memberships (EP Open Data API v2) |
| `sources/ep_procedures.py` | Procedures and their events/documents (EP Open Data API v2) |
| `sources/ep_votes.py` | Plenary decisions with roll-call ballots (EP Open Data API v2) |
| `sources/eurlex.py` | Legal acts: CELEX, ELI, dates, procedure links, amendments; Commission withdrawals and replacements of proposals → `procedure_notices.json` (Cellar SPARQL) |
| `sources/council.py` | Council voting results (see DATA_SOURCES.md for availability) |
| `sources/implementation.py` | National implementing measures (Cellar), infringements, country indicators |
| `sources/optouts.py` | Treaty opt-outs (Protocols No 21 and 22: Denmark, Ireland) that a directive's recitals record, and later opt-ins confirmed by Commission decisions → `optouts/directives.json` (EUR-Lex texts via Cellar) |
| `sources/legislative_train.py` | EP Legislative Train status of major files |
| `analysis/status.py` | Lifecycle stage, next step, inactivity vs official "blocked" |
| `analysis/transposition.py` | Classifies each transposition date Cellar records as a deadline, an application date or another date; `data/curated/transposition.yaml` settles the cases its labels cannot |
| `analysis/ep_margin.py` | Vote margin relative to the legally applicable majority |
| `analysis/council_qmv.py` | Council QMV/unanimity arithmetic |
| `analysis/activity.py`, `feeds.py` | Snapshot diffing → verified activity; Atom feeds: all recent activity, one per topic, and one per file (`feeds/dossiers/<id>.xml`: its latest 10 entries of any date) |
| `analysis/changes.py` | How activity items read, for the What changed page and the feeds: what happened apart from the file's title (`event` in `activity.json`), the file's full title in a headline, and a status change paired with the item of the step that gave the status (`step_id`: the same file and day, the record it cites, else a step of a kind that dates the status). It never adds, drops or re-dates an item |
| `build.py` | Joins everything by official identifiers → `public/data/**` per `src/types/data.ts`; `--strict` (`EU_INTEL_STRICT=1`) fails when it had to work around a problem |
| `freshness.py` | How old each source's data may get before the site and the Data health issue call it stale; the core sources behind `core_data_at`; when the Legislative Train's "blocked" stops being shown |
| `validate.py` | Schema + invariants (ballot totals, referential integrity, legal-type rules); on a build, the claims in `public/data` against the rules and the files' own records, and the contract (`contract.py`: the built JSON against `src/types/data.ts`). Errors fail; warnings are by design (not counted), integrity (fail above `validate_baseline.json`) or backlog |

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
- **What changed** (`/legislation/changes`, `src/pages/Changes.tsx`, `src/features/changes/`) reads `activity.json`: the
  changes grouped by the week our data refresh first recorded them (`detected_at`; a step already in the records when
  recording began has none, and is grouped by its own date), and within a week by the topics of each file
  (`dossiers/index.json`), with filters by topic and kind of change (kept in the address) and each topic's Atom feed. A
  status change is told with the step that gave the status (`step_id`), as in the feeds. Each change links its file's
  page and the official records it cites. It is a view of Legislation, not one of the seven primary destinations
  (docs/PRODUCT.md): the home page, the explorer and the footer lead to it. The home page's **This week in EU law** shows
  the changes of the latest week of recording, with counts by kind; it is called "this week" only while the latest
  refresh is at most a week old on the reader's date.
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
  id="page-feed">`, written into the prerendered page and kept to the page shown by `useFeedLink`). The Following page
  downloads the feeds of the files followed as one OPML file, made in the browser (a `data:` link with `download`, which
  the Content-Security-Policy does not restrict; nothing is sent).
- `src/types/data.ts` is the **public data contract**. Pages lazy-load only the JSON they need:
  `home.json` for the homepage, `dossiers/index.json` for the explorer, `dossiers/<id>.json` per law, etc. The vote
  tables of the MEP and political group pages read `votes/titles.json` (the votes of `votes/index.json`, in its order,
  with only the date, title, kind of vote, procedure reference, distinction and result they show), not the whole
  index, which only the votes list needs.
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
  forward, and fails on a dated wording it does not know.
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
- `refresh.yml`: twice on Mondays (a scheduled run is skipped if data was committed in the last 20 hours): `fetch`
  (incremental, each record re-read at least every 8 weeks; a full refresh in the first week of each month or by hand) →
  `validate` per source → the data gate, recording activity → commit snapshot and state → deploy that commit, if CI
  has passed on its code.
- `watchdog.yml`: after each refresh and each CI run on `main`, and daily, opens, updates or closes the "Data health"
  issue (failed or stale sources, a failed refresh, red CI on `main`, live data more than 8 days old, the repository
  past 750 MB).

## Future analytics (not implemented)

The architecture leaves room for a self-hosted, cookieless Umami instance later. Nothing is loaded today; adding
it requires a privacy/ePrivacy assessment and an update of the privacy notice and CSP.
