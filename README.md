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
python -m pipeline validate --built   # check the snapshot again and the claims in public/data

# Frontend (React + TypeScript + Vite)
npm ci
npm run dev                      # http://localhost:5173/
```

`python -m pipeline fetch [source …]` refreshes `data/snapshot/` from the official APIs (network; slow; polite
rate limits). Sources: `ep_people ep_procedures ep_votes eurlex council implementation optouts train`. A source
that fails keeps its previous files; `data/snapshot/_manifest.json` records each source's status and last
successful fetch. You rarely need this locally: the snapshot is committed and refreshed weekly by CI. The weekly
refresh is incremental for EP procedures, EP votes and the Legislative Train (new, open and recently changed
records are read again, the others reused); `EU_INTEL_FULL_REFRESH=1` re-reads every record (see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), "What a weekly run re-reads").

## Checks

| Command | What it checks |
| --- | --- |
| `ruff check .` | Python lint |
| `pytest` | Offline unit tests (network tests are deselected; run them with `pytest -m network`) |
| `python -m pipeline validate` | Snapshot schema and invariants; once built, the claims in `public/data` against the rules and the files' own dates (`--built` fails if there is no build) |
| `npm run typecheck` · `npx vitest run` | TypeScript types · frontend unit tests |
| `BASE_PATH=/eu-intel/ npm run build` | Production build under the Pages subpath, with prerendered route shells |
| `node scripts/check_privacy.mjs` | No third-party loads, trackers, cookie writes or raw-HTML injection in `dist/` and `src/` |
| `npx playwright test` | End-to-end smoke, deep links, search, accessibility (axe-core) and privacy on the built site |
| `python scripts/check_links.py` | Optional polite spot-check of official source links in `public/data` |

End-to-end tests need a build first: `python -m pipeline build && BASE_PATH=/eu-intel/ npm run build`, then
`npx playwright test` (it starts `vite preview` and a GitHub-Pages-like static server itself). On a fresh machine
install the browser once with `npx playwright install chromium`.

All of the above except the link checks run in CI on every push to `main`, every pull request and on manual runs
([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Data refresh and deployment

- **Weekly refresh** ([refresh.yml](.github/workflows/refresh.yml)): Mondays 05:17 UTC (best effort) and on demand
  from the Actions tab (optionally as a full refresh). Fetch → validate → build and record verified activity →
  validate the built data → commit `data/snapshot/` and `data/state/`. A source whose new data fails validation
  gets its previous files and manifest entry back from the last commit, and the other sources' new data is
  committed; nothing is committed if the snapshot still fails after that, or if the built data fails validation.
  `data/state/` is committed only after a successful build.
- **Deploy** ([pages.yml](.github/workflows/pages.yml)): on push to `main`, on demand, and after each successful
  refresh. A failed build or validation never deploys; the previous version stays online.

Repository owners: see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the one-time Pages setup.

## Repository layout

```
pipeline/            Python data pipeline: sources/ (one module per official source), analysis/, build.py, validate.py
data/snapshot/       committed, normalized source data (diff-friendly JSON) + _manifest.json
data/curated/        editorial YAML: featured files, topics, search aliases, checked corrections of act dates
                     (act_dates.yaml), amendment links (act_relations.yaml), transposition deadlines
                     (transposition.yaml), Denmark's Schengen decisions (denmark_schengen.yaml), Council
                     adoption dates (council_dates.yaml), Council voting records (council_votes.yaml) and acts
                     named but not officially linked (unlinked_acts.yaml)
data/state/          refresh state (snapshot digest, verified activity log); created by the first recorded refresh
src/                 React app: pages/, features/, components/, lib/, types/data.ts (public data contract)
scripts/             prerender-routes.mjs, check_privacy.mjs, check_links.py
tests/               pytest (offline, fixtures in tests/fixtures/) and tests/e2e/ (Playwright)
docs/                product, editorial policy, architecture, data sources, deployment, plan, roadmap
.github/workflows/   ci.yml, pages.yml, refresh.yml
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
