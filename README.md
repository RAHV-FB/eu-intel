# EU Legislative Intelligence

An independent, nonpartisan website that explains what the European Union is legislating: which laws are
proposed, negotiated, adopted or stuck; how Members of the European Parliament and Member States voted; and how
EU law reaches each country. Every institutional fact on the site comes from an official EU open-data source and
links back to it. Missing data is shown as missing, never guessed.

> **Not an official EU website.** This project is not affiliated with, endorsed by or operated on behalf of the
> European Union or any of its institutions. The official records (EUR-Lex, the European Parliament, the Council,
> the Commission) remain the authoritative sources.

The site is fully static (GitHub Pages): no backend, no cookies, no analytics, no third-party scripts, fonts or
images. Visitors never contact EU APIs; the data is fetched by a scheduled pipeline and published as static JSON.

## How it works

```
official EU APIs ──fetch──▶ data/snapshot/** (committed) ──build──▶ public/data/** ──▶ React SPA ──▶ GitHub Pages
                                      ▲
        data/curated/*.yaml (editorial selections, aliases, topics, checked corrections of dates and Council vote records)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) and
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Quick start

Requirements: Python 3.12+, Node.js 22. For `python -m pipeline fetch council` and the Council parser tests also
poppler-utils (`pdftoppm`, `pdftotext`); without it the council source is recorded as failed and those tests are
skipped.

```sh
# Pipeline (Python)
python -m venv .venv && . .venv/bin/activate      # or: uv venv && uv pip install -e '.[dev]'
pip install -e '.[dev]'
python -m pipeline validate      # check the committed snapshot (offline)
python -m pipeline build         # snapshot + curated data -> public/data (offline, deterministic)
python -m pipeline validate --built   # check the snapshot again, that public/data is complete, and its claims

# Frontend (React + TypeScript + Vite)
npm ci
npm run dev                      # http://localhost:5173/
```

`python -m pipeline fetch [source …]` refreshes `data/snapshot/` from the official APIs (network; slow; polite
rate limits). Sources: `ep_people ep_procedures ep_votes eurlex council implementation optouts train agenda`. A source
that fails keeps its previous files; `data/snapshot/_manifest.json` records each source's status and last
successful fetch. You rarely need this locally: the snapshot is committed and refreshed weekly by the *Data refresh*
workflow (below). The weekly refresh is incremental for EP procedures, EP votes and the Legislative Train: new, open
and recently changed records are read again, and the others are reused, except for a weekly share of them that is
read again on a rotation (every record at least every 8 weeks; Train files every 4). `EU_INTEL_FULL_REFRESH=1`, or a
change of a source's `PARSER_VERSION`, re-reads every record (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), "What a
weekly run re-reads").

## Checks

| Command | What it checks |
| --- | --- |
| `ruff check .` | Python lint |
| `pytest` | Offline unit tests (network tests are deselected; run them with `pytest -m network`) |
| `python -m pipeline validate` | Snapshot schema and invariants, and that no file is missing or emptied (against the manifest's record counts and minimum counts); once built, the claims in `public/data` against the rules and the files' own records (an act on two files, a file past adoption without Parliament's position, an adoption date on a file shown before adoption, a transposition deadline before its act, …). `--built` fails if there is no build, if it is incomplete (a missing or unreadable file, an empty list, a count of zero), or if it does not match `src/types/data.ts` (keys, nulls, types, enums; `pipeline/contract.py`, also for detail files no index lists). Warnings are by design (printed as INFO, not counted), integrity or backlog: it fails on any integrity finding that `pipeline/validate_baseline.json` does not accept, whatever the count (`--built --update-baseline` rewrites it once they are checked; it refuses while there are errors) |
| `python -m pipeline build --strict` | Also `EU_INTEL_STRICT=1`: fails, listing every problem at the end, when the build had to work around one (an analysis module or function that did not load, a curated file or entry not applied, a status that fell back, a vote margin or Council assessment that failed) |
| `npm run typecheck` · `npx vitest run` | TypeScript types · frontend unit tests |
| `BASE_PATH=/eu-intel/ npm run build` | Production build under the Pages subpath, with prerendered route shells |
| `node scripts/check_privacy.mjs` | No third-party loads, trackers, cookie writes or raw-HTML injection in `dist/` and `src/` |
| `npx playwright test` | End-to-end smoke, deep links, search, accessibility (axe-core) and privacy on the built site |
| `scripts/test-frozen.sh` | pytest, vitest and the Playwright tests (Chromium) on the frozen test data, as CI runs them, in a temporary worktree |
| `python -m pipeline health` | Sources that failed in their last run or are stale (exit 1 if any) |
| `python scripts/check_links.py` | Optional polite spot-check of official source links in `public/data` |

End-to-end tests need a build first: `python -m pipeline build && BASE_PATH=/eu-intel/ npm run build`, then
`npx playwright test` (it starts `vite preview` and a GitHub-Pages-like static server itself). On a fresh machine
install the browser once with `npx playwright install chromium`.

The tests that read real data pin ids, counts and dates of it. CI runs them on the **frozen test data**: the snapshot of
the commit named in `tests/frozen-data.txt`, built as of the moment it names, so a data refresh cannot turn them red.
`scripts/test-frozen.sh` does the same locally without touching the working tree; to move the tests to newer data, see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), "Frozen test data". The commit's own data goes through the data gate instead:
`validate`, the strict build (`EU_INTEL_STRICT=1`), `validate --built` (its error checks, `activity-duplicate` among them,
and the warning ratchet), `npx vitest run src/lib/format.test.ts`, the site build, the privacy check and the size limit.
CI runs both on every push to `main`, every pull request and on manual runs
([.github/workflows/ci.yml](.github/workflows/ci.yml)): every check above but the last two (the watchdog runs the health
check, and the link check depends on third-party sites).

## Following changes

- **What changed** (`/legislation/changes/`): the steps, votes and status changes the weekly refresh recorded, by week
  and by topic, each linked to its file and its official record. The home page opens with the latest week.
- **Atom feeds** (no account, nothing stored on a server): all recent changes (`data/feeds/updates.xml`), one per topic
  (`data/feeds/<topic>.xml`) and one per legislative file (`data/feeds/dossiers/<id>.xml`, linked as "Follow in a feed
  reader" on the file's page). Entries give the file's full title, what happened, the status it gave the file and the
  next step; a status change and the step that caused it are one entry. Entry ids are stable tag URIs: an entry keeps
  its id when its wording or the site's address changes.
- **OPML**: the Following page downloads the feeds of the files you follow as one OPML file, which feed readers import.
  It is made in your browser from the list kept there.
- **When new rules apply** (`/legislation/applies/`): the dates fixed in law from which rules start to apply (entry into
  force, application, transposition deadlines, national measures), by month, topic and Member State, each saying where
  it applies. For every date, each topic and each Member State there is an Atom feed of the next 90 days
  (`data/feeds/applies/{all,topics/<topic>,countries/<code>}.xml`) and a calendar of every date ahead (`.ics`, the same
  names), whose entries and events keep their ids from one refresh to the next.

## Data refresh and deployment

- **Weekly refresh** ([refresh.yml](.github/workflows/refresh.yml)): Mondays 05:17 UTC, a second try at 22:37 UTC
  unless data was committed in the last 20 hours (schedules are best effort), a full refresh in the first week of each
  month, and on demand from the Actions tab. Fetch → validate per source → the data gate (strict build recording
  verified activity, validation of the built data, its dated wording, site build, privacy, size) → commit
  `data/snapshot/` and `data/state/` → deploy that commit. A source whose new data fails validation gets its previous
  files and manifest entry back from the last commit; if the data then fails the gate, nothing is committed or deployed.
- **Deploy** ([pages.yml](.github/workflows/pages.yml)): once CI has passed on a push to `main`; the commit a refresh
  pushed, once CI has passed on its code; and on demand. It runs the data gate again on what it deploys; a failure
  never deploys, and the previous version stays online.
- **Data health** ([watchdog.yml](.github/workflows/watchdog.yml)): after each refresh and each CI run on `main`, and
  daily, it opens, updates or closes one "Data health" issue listing failed or stale sources, a failed refresh, red CI on
  `main` and live data more than 8 days old.

Repository owners: see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the one-time Pages setup.

## Repository layout

```
pipeline/            Python data pipeline: sources/ (one module per official source), analysis/, build.py, validate.py
data/snapshot/       committed, normalized source data (diff-friendly JSON) + _manifest.json
data/curated/        editorial YAML: featured files, topics, search aliases, checked corrections of act dates
                     (act_dates.yaml), amendment links (act_relations.yaml), transposition deadlines
                     (transposition.yaml), Denmark's Schengen decisions (denmark_schengen.yaml), Council
                     adoption dates (council_dates.yaml), Council voting records (council_votes.yaml), acts
                     named but not officially linked (unlinked_acts.yaml) and procedure links that the act's
                     own text rules out (act_links.yaml)
data/state/          refresh state (snapshot digest, verified activity log); created by the first recorded refresh
src/                 React app: pages/, features/ (one folder per area, insights/ included), components/, lib/,
                     types/data.ts (public data contract)
scripts/             prerender-routes.mjs, check_privacy.mjs, check_links.py, test-frozen.sh
tests/               pytest (offline, fixtures in tests/fixtures/) and tests/e2e/ (Playwright)
docs/                product, editorial policy, architecture, data sources, deployment, plan, roadmap, assessment
.github/workflows/   ci.yml, pages.yml, refresh.yml, watchdog.yml
```

## Licences

- **Code**: MIT — see [LICENSE](LICENSE).
- **Data** remains subject to the reuse terms of its publishers, with attribution:
  European Parliament — © European Union – Source: European Parliament. The EP Open Data Portal publishes its
  datasets of MEPs, of EU procedures involving the Parliament and of results of votes (2024 and 2025) under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); for its other data and pages (Legislative
  Observatory, Legislative Train, plenary minutes) the
  [European Parliament legal notice](https://www.europarl.europa.eu/legal-notice/en/) authorises reuse provided
  that the entire item is reproduced and the source is acknowledged, a partial reproduction citing the URL of the
  complete item or of the web page it comes from. The site shows this data adapted (selected, combined with other
  sources and reformatted) and links each item it takes data from;
  EUR-Lex / Publications Office (Cellar) — © European Union, https://eur-lex.europa.eu, reuse authorised under
  Commission Decision 2011/833/EU; Council and Commission content — reuse authorised with acknowledgement of the
  source. Details per source in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) and on the site's About page.
