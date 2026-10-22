# Deployment and operations

The site is a static build deployed to **GitHub Pages** by GitHub Actions. Three workflows:

| Workflow | Trigger | Does | Permissions |
| --- | --- | --- | --- |
| `ci.yml` (CI) | push to `main`, pull requests, manual | ruff, pytest (offline), `pipeline validate`, `pipeline build`, typecheck, vitest, site build with `BASE_PATH=/eu-intel/`, privacy check; optional Playwright e2e | `contents: read` |
| `pages.yml` (Deploy to GitHub Pages) | push to `main`, manual, after a successful *Data refresh* | validate → build data → build site with the Pages base path → privacy check → size check → upload → deploy | build: `contents: read`; deploy: `pages: write`, `id-token: write` |
| `refresh.yml` (Data refresh) | Mondays 05:17 UTC, manual | fetch all sources → validate → build with activity recording → commit `data/snapshot/` + `data/state/` to `main` | `contents: write` (this job only) |

All actions are pinned to full commit SHAs (with the version in a comment); Dependabot
(`.github/dependabot.yml`) proposes weekly grouped updates.

## One-time setup (repository owner)

1. **Enable Pages with Actions as the source**: *Settings → Pages → Build and deployment → Source:*
   **GitHub Actions**. (Do not choose "Deploy from a branch".) Until this is done, `pages.yml` fails at
   *Configure Pages* and nothing is deployed.
2. **Allow the refresh job to push**: *Settings → Actions → General → Workflow permissions*. The workflows
   request permissions explicitly, so the default "Read repository contents" is fine, but the
   organisation/repository must not forbid `contents: write` for `GITHUB_TOKEN`.
3. **If `main` is protected** by a ruleset or branch protection that blocks direct pushes, add
   `github-actions[bot]` (or the "GitHub Actions" app) to the bypass list, or the refresh commit will be rejected.
   Required status checks on `main` also block bot pushes unless bypassed.
4. **Environment**: enabling Pages creates the `github-pages` environment, which by default only accepts
   deployments from `main`. Keep it that way (manual runs from other branches will build but not deploy).
5. Optional: *Settings → Secrets and variables → Actions → Variables* → `E2E_ENABLED = true` turns on the
   Playwright job in CI (see below).
6. Optional: a custom domain (*Settings → Pages → Custom domain*). The base path then becomes `/` automatically.

The site will be at `https://rahv-fb.github.io/eu-intel/`.

## Base path

GitHub Pages serves a project site under `/<repo>/`. `pages.yml` takes the path from
`actions/configure-pages` (`steps.pages.outputs.base_path`, e.g. `/eu-intel`, or empty for a custom domain) and
builds with `BASE_PATH=<base_path>/`. `vite.config.ts` uses it as Vite's `base`, the router uses it as its
`basename`, and data is loaded from `${BASE_URL}data/`.

Pages has no server-side rewrites, so `scripts/prerender-routes.mjs` writes an `index.html` for every known route
(`/legislation/2021-0106/`, `/votes/<id>/`, …) so that deep links return HTTP 200 with a route-specific
`<title>`, plus `404.html` as the SPA fallback for anything else (served with status 404).
Locally, `tests/e2e/pages-server.mjs` reproduces these semantics (`node tests/e2e/pages-server.mjs dist`, then
open http://127.0.0.1:4174/eu-intel/).

## Schedule and failure behaviour

- **Refresh** runs weekly on Monday at 05:17 UTC. GitHub runs schedules on a best-effort basis: runs can start
  late or be dropped at busy times. GitHub also disables scheduled workflows in a public repository after 60
  days without repository activity; re-enable it under *Actions → Data refresh → Enable workflow*.
- **A source fails** (API down, timeout, schema change): its previous snapshot files are kept, the manifest
  records `failed` with the previous successful `fetched_at`, the run logs a warning and continues with the other
  sources. The site shows each source's last successful retrieval.
- **Validation fails** after fetching: the job fails before committing; nothing changes on `main` and no deploy
  is triggered. The run's summary shows the per-source status table.
- **No changes**: nothing is committed (the deploy still re-runs; harmless).
- **Push rejected** because `main` moved during the run: the job rebases and retries up to three times.
- **Deploy build fails** (validation, data build, TypeScript, Vite, privacy check, > 900 MB): the deploy job does
  not run and the previous deployment stays live. Fix and push, or re-run the workflow.
- Deploys are serialised (`concurrency: pages`, never cancelled mid-flight).
- Commits made by the refresh use `GITHUB_TOKEN`, which by design does not trigger `push` workflows; the deploy
  is chained with `workflow_run` instead, and CI does not run on refresh commits (the deploy re-validates).

## Manual operations

- **Refresh now**: *Actions → Data refresh → Run workflow*. Optionally list sources, e.g. `ep_votes eurlex`.
  Or from a terminal: `gh workflow run refresh.yml -f sources="ep_votes eurlex"`.
- **Redeploy** without data changes: *Actions → Deploy to GitHub Pages → Run workflow* (`gh workflow run pages.yml`).
- **Roll back**: revert the offending commit on `main` (a data refresh is a single commit); the push redeploys.
- **Refresh locally** (e.g. to debug a source): `EU_INTEL_NO_CACHE=1 python -m pipeline fetch ep_votes`, then
  `python -m pipeline validate && EU_INTEL_RECORD_ACTIVITY=1 python -m pipeline build`, review the diff, commit.

## End-to-end tests in CI

The `e2e` job in `ci.yml` (Playwright + axe-core on the built site) is opt-in while pages are being completed:

- one run: *Actions → CI → Run workflow* and tick "Run Playwright e2e + accessibility tests";
- always: set the repository variable `E2E_ENABLED` to `true`.

It reuses the site built by the `check` job (uploaded as the `site-dist` artifact), installs Chromium, runs
`npx playwright test`, and uploads the HTML report and traces as the `playwright-report` artifact.

## Free-plan limits

Public repositories get unlimited standard GitHub-hosted runner minutes. Each workflow is a single small job with
a `timeout-minutes` cap (CI 20, deploy 20 + 15, refresh 120). Pages limits: published site ≤ 1 GB (checked at
build time), soft bandwidth limit 100 GB/month. Artifacts are kept 1–7 days.

## Optional link check

`python scripts/check_links.py` samples official URLs from `public/data` (default 5 per host, at most 60) and
checks them politely (one request at a time, 1.5 s per host). EUR-Lex, the Council website and parts of
europarl.europa.eu answer scripts with bot challenges (HTTP 202/403); those are reported as *unverifiable*, not
broken. It is not part of CI (it depends on third-party availability).
