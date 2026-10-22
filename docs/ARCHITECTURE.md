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
| `models/entities.py` | **Snapshot contract** (pydantic): Procedure, Event, LegalAct, EpVote, EpBallots, Mep, Organization, Membership, CouncilVote, NationalMeasure, InfringementCase, CountryIndicator, TrainFile, SourceRef |
| `models/countries.py` | Member State table and code normalization (EU "EL" → ISO "GR") |
| `sources/ep_people.py` | MEPs, groups, national parties, committees, dated memberships (EP Open Data API v2) |
| `sources/ep_procedures.py` | Procedures and their events/documents (EP Open Data API v2) |
| `sources/ep_votes.py` | Plenary decisions with roll-call ballots (EP Open Data API v2) |
| `sources/eurlex.py` | Legal acts: CELEX, ELI, dates, procedure links, amendments (Cellar SPARQL) |
| `sources/council.py` | Council voting results (see DATA_SOURCES.md for availability) |
| `sources/implementation.py` | National implementing measures (Cellar), infringements, country indicators |
| `sources/legislative_train.py` | EP Legislative Train status of major files |
| `analysis/status.py` | Lifecycle stage, next step, inactivity vs official "blocked" |
| `analysis/ep_margin.py` | Vote margin relative to the legally applicable majority |
| `analysis/council_qmv.py` | Council QMV/unanimity arithmetic |
| `analysis/activity.py`, `feeds.py` | Snapshot diffing → verified activity; Atom feeds |
| `build.py` | Joins everything by official identifiers → `public/data/**` per `src/types/data.ts` |
| `validate.py` | Schema + invariants (ballot totals, referential integrity, legal-type rules) |

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
  `home.json` for the homepage, `dossiers/index.json` for the explorer, `dossiers/<id>.json` per law, etc.
- Search: `search.json` + an in-browser engine (`src/lib/search.ts`): accent/case folding, aliases, identifier
  matching, prefix and bounded fuzzy matching, static boosts.
- Design tokens in `src/styles/tokens.css`; shared primitives in `src/components/ui.tsx`.
- Strict CSP meta (`default-src 'self'`), no third-party fonts/scripts, no cookies. The optional watchlist uses
  `localStorage` only after an explicit click.

## Operations

- `ci.yml`: lint, tests, validate, build data, typecheck, build site, privacy check.
- `pages.yml`: deploy to GitHub Pages on push to `main`, manual dispatch, or after a successful refresh.
- `refresh.yml`: scheduled weekly `fetch` → `validate` → record activity → commit snapshot.

## Future analytics (not implemented)

The architecture leaves room for a self-hosted, cookieless Umami instance later. Nothing is loaded today; adding
it requires a privacy/ePrivacy assessment and an update of the privacy notice and CSP.
