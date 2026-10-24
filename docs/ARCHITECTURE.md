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
| `analysis/activity.py`, `feeds.py` | Snapshot diffing → verified activity; Atom feeds |
| `build.py` | Joins everything by official identifiers → `public/data/**` per `src/types/data.ts` |
| `validate.py` | Schema + invariants (ballot totals, referential integrity, legal-type rules); on a build, the claims in `public/data` against the rules and the files' own dates |

### Identifiers and linking

Records are joined **only through official identifiers**: procedure reference `YYYY/NNNN(TYPE)` (EP process id
`YYYY-NNNN`), CELEX, ELI, EP person/organization ids, EP voting ids, ISO country codes. A dossier can link to
several acts, many events and many votes. No link is ever inferred from title similarity; an ambiguous
relationship is left unlinked.

### Provenance

Each record carries a `SourceRef` (institution, URL, identifier, retrieval time). The build forwards sources to
the UI; every institutional fact on a page has a reachable origin.

## Frontend (`src/`)

- React 19 + TypeScript + Vite; react-router `BrowserRouter` with the Pages base path.
- `scripts/prerender-routes.mjs` writes an `index.html` per known route (correct `<title>`, HTTP 200 on direct
  navigation) plus `404.html` as SPA fallback — no server rewrites needed.
- `src/types/data.ts` is the **public data contract**. Pages lazy-load only the JSON they need:
  `home.json` for the homepage, `dossiers/index.json` for the explorer, `dossiers/<id>.json` per law, etc. The vote
  tables of the MEP and political group pages read `votes/titles.json` (the votes of `votes/index.json`, in its order,
  with only the date, title, kind of vote, procedure reference, distinction and result they show), not the whole
  index, which only the votes list needs.
- Search: `search.json` + an in-browser engine (`src/lib/search.ts`): accent/case folding, aliases, identifier
  matching, prefix, word-family ("fish" -> "fisheries", ranked below whole words) and bounded fuzzy matching
  (flagged `approximate` and ranked last; /search, the header suggestions, /legislation and /votes say so), static
  boosts. A query that is an identifier matches only through identifiers (a split part also typed without its
  procedure type, "2016/0224A") and names citing it.
- Design tokens in `src/styles/tokens.css`; shared primitives in `src/components/ui.tsx`.
- Strict CSP meta (`default-src 'self'`), no third-party fonts/scripts, no cookies. The optional watchlist writes
  nothing to `localStorage` before the visitor's first "Follow" click (pages check for storage by reading only).
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

## Operations

- `ci.yml`: lint, Python tests, validate, build data, validate the built data, typecheck (app and e2e tests),
  vitest, build site, privacy check; then a Playwright e2e and accessibility job on the built site (runs by
  default; a manual run can skip it).
- `pages.yml`: deploy to GitHub Pages on push to `main`, manual dispatch, or after a successful refresh (validate,
  build data, validate the built data, build site).
- `refresh.yml`: scheduled weekly `fetch` (incremental; a manual run can do a full refresh) → `validate` → build
  and record activity → `validate --built` → commit snapshot.

## Future analytics (not implemented)

The architecture leaves room for a self-hosted, cookieless Umami instance later. Nothing is loaded today; adding
it requires a privacy/ePrivacy assessment and an update of the privacy notice and CSP.
