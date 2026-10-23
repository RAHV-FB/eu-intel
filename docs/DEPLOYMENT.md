# Deployment and operations

The site is a static build deployed to **GitHub Pages** by GitHub Actions. Three workflows:

| Workflow | Trigger | Does | Permissions |
| --- | --- | --- | --- |
| `ci.yml` (CI) | push to `main`, pull requests, manual | ruff, pytest (offline), `pipeline validate`, `pipeline build`, typecheck, vitest, site build with `BASE_PATH=/eu-intel/`, privacy check; Playwright e2e and accessibility tests on the built site | `contents: read` |
| `pages.yml` (Deploy to GitHub Pages) | push to `main`, manual, after a successful *Data refresh* | validate → build data → build site with the Pages base path → privacy check → size check → upload → deploy | build: `contents: read`; deploy: `pages: write`, `id-token: write` |
| `refresh.yml` (Data refresh) | Mondays 05:17 UTC, manual (optionally a full refresh) | fetch all sources (incremental, see below) → validate → build with activity recording → commit `data/snapshot/` + `data/state/` to `main` | `contents: write` (this job only) |

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
5. Optional: a custom domain (*Settings → Pages → Custom domain*). The base path then becomes `/` automatically,
   and so do the absolute links in the Atom feeds (`SITE_URL`, see below) from the next deploy. The feed and
   entry ids stay the same (`tag:rahv-fb.github.io,2026:eu-intel/…`), so feed readers do not show old entries
   again as new.

The site will be at `https://rahv-fb.github.io/eu-intel/`.

## Base path

GitHub Pages serves a project site under `/<repo>/`. `pages.yml` takes the path from
`actions/configure-pages` (`steps.pages.outputs.base_path`, e.g. `/eu-intel`, or empty for a custom domain) and
builds with `BASE_PATH=<base_path>/`. `vite.config.ts` uses it as Vite's `base`, the router uses it as its
`basename`, and data is loaded from `${BASE_URL}data/`. The Atom feeds (`data/feeds/*.xml`) need absolute links:
the data build takes them from `SITE_URL`, which `pages.yml` sets to the Pages URL
(`steps.pages.outputs.base_url`, e.g. `https://rahv-fb.github.io/eu-intel` or the custom domain); without it
(CI, local builds) they point at `https://rahv-fb.github.io/eu-intel/`. `SITE_URL` sets the links only: the ids
(`feeds.TAG_BASE`) never change with it, as an Atom id must not when a feed moves (RFC 4287, section 4.2.6).

Pages has no server-side rewrites, so `scripts/prerender-routes.mjs` writes an `index.html` for every known route
(`/legislation/2021-0106/`, `/votes/<id>/`, …) so that deep links return HTTP 200 with a route-specific
`<title>`, plus `404.html` as the SPA fallback for anything else (served with status 404).
Locally, `tests/e2e/pages-server.mjs` reproduces these semantics (`node tests/e2e/pages-server.mjs dist`, then
open http://127.0.0.1:4174/eu-intel/).

## Schedule and failure behaviour

- **Refresh** runs weekly on Monday at 05:17 UTC. GitHub runs schedules on a best-effort basis: runs can start
  late or be dropped at busy times. GitHub also disables scheduled workflows in a public repository after 60
  days without repository activity; re-enable it under *Actions → Data refresh → Enable workflow*.
- **Time limits**: the fetch has a run-wide deadline (`EU_INTEL_FETCH_DEADLINE`, set by the workflow); after it
  no source starts and running sources start no new work. A request made after it gets a single short attempt
  (at most 30 s, no retries), and none starts at all 5 minutes after it. `timeout --signal=INT` then stops the
  fetch well before the job limit, so the checkpoints already written (`_state.json`, chunked snapshot files)
  are always validated and committed. Sources resume their pending work on the next run; EP procedures fetches
  the files that already failed in an earlier run after all the others, so a few files that keep failing do
  not hold up the rest (`_state.json` `failing` records since when, and the manifest note lists them).
- **A source fails or returns less** (API down, timeout, schema change, an empty answer): a source that fails
  keeps all its files, and a record that could not be fetched keeps its previous version (EP procedures, EUR-Lex
  acts, MEPs and organisations, Council notes, Legislative Train files, infringement cases' legal basis). Some
  files also refuse a short answer: EUR-Lex `acts.json` and `procedure_notices.json`, `ep_people`
  `meps.json`/`orgs.json`, the implementation measures, coverage and infringements and the Train's `files.json`
  are not rewritten when they would lose more than 5% of their records; EUR-Lex keeps stored acts missing from a
  scope answer whose rows fall short of Cellar's count of them; Council stops when Cellar lists fewer than 90% of
  its stored notes; an EP vote sitting keeps its stored votes when a new answer has less than half of its votes,
  procedure links or subjects; `ep_people` fails when the EP's list of current Members has more than 5% fewer
  entries than the MEPs marked as sitting (every Member missing from it would be shown as former); opt-outs keep
  the Commission's opt-in decisions recorded earlier when an answer lacks them (marked `partial`). Smaller drops
  are written (a record can be removed at source). EP procedures and opt-outs otherwise add or replace records
  (EP procedures also removes one that no longer passes validation). The manifest records `partial` or `failed`
  (with the previous successful `fetched_at`), and the run continues with the other sources. The site shows each
  source's last successful retrieval.
- **A source stops early**: no source starts after the run deadline, and every source starts no new work after
  its own budget (`EU_INTEL_FETCH_BUDGET_S`). EP procedures also stops starting files once 8 in a row have failed
  (an EP API or OEIL outage; files that already failed in an earlier run do not count), and the EP procedure list
  starts at the page size that worked last time (kept in `_state.json`).
- **Validation fails** for one source (a structural error, or for `ep_people` a count of sitting MEPs that does
  not match their open political-group memberships): that source's snapshot directory and manifest entry are
  restored from the previous commit (marked `partial`), the whole snapshot must then validate, and the other
  sources' new data is committed. The activity log (`data/state`) is committed only after a successful build.
  Status changes are recorded only from complete procedure and EUR-Lex data: a partial fetch lists in its
  `_state.json` (`unsettled`) the files it did not refresh completely (pending, kept from an earlier run, recorded
  without OEIL data, an act or notice kept or lost), and only those dossiers keep their stored stage until a later
  run refreshes them. A partial fetch without that list (e.g. a restored state file) suspends all status changes for
  the run. The build log warns in both cases, with the date since when.
- **No changes**: nothing is committed (the deploy still re-runs; harmless).
- **Push rejected** because `main` moved during the run: the job resets onto the new `main`, re-applies only the
  data files this run changed (this run's version wins for those; `_manifest.json` is merged per source) and
  pushes again, up to five times. Do not commit snapshot data by hand while a refresh is running.
- **Deploy build fails** (validation, data build, TypeScript, Vite, privacy check, > 900 MB): the deploy job does
  not run and the previous deployment stays live. Fix and push, or re-run the workflow.
- Deploys are serialised (`concurrency: pages`, never cancelled mid-flight).
- Commits made by the refresh use `GITHUB_TOKEN`, which by design does not trigger `push` workflows; the deploy
  is chained with `workflow_run` instead, and CI does not run on refresh commits (the deploy re-validates).

## What a weekly run re-reads

A scheduled refresh is incremental for three sources; a stored record that is not re-read keeps the data and the
derivation of the run that last read it:

- **EP procedures**: files new to the list, still open (not adopted, published, in force, withdrawn, rejected or
  lapsed), with a recorded step in the last 120 days, without OEIL data, featured, or pending from the last run.
  Ids the EP API cannot serve because the procedure was split or merged are retried only by a full refresh;
  other unusable ids every run.
- **EP votes**: the sittings from 60 days before the latest stored sitting, and the sittings still pending.
- **Legislative Train**: new files, and file pages whose status changed or that are marked "Recently updated" on
  the theme page, were updated in the last 90 days, are pending, or are due in a four-week rotation of the quiet
  files.

The other sources read their whole scope each run, except that Council notes whose Cellar record and parser are
unchanged are reused and opt-outs read each directive's text once (again when the recital matcher changes).

A **full refresh** (`EU_INTEL_FULL_REFRESH=1`) re-reads every stored record of those three sources: run one after
a change to how a source reads or derives its records, so that reused records do not keep the old derivation, and
from time to time to pick up late corrections at source. It is chunked and resumable like any run: one interrupted
by its time budget stays a full refresh in the next runs until it completes.

## Manual operations

- **Refresh now**: *Actions → Data refresh → Run workflow*. Optionally list sources, e.g. `ep_votes eurlex`.
  Or from a terminal: `gh workflow run refresh.yml -f sources="ep_votes eurlex"`.
- **Full refresh**: tick "Full refresh" in the same form, best with the sources concerned listed (each full pass
  can use its source's whole time budget): `gh workflow run refresh.yml -f sources=ep_procedures -f
  full_refresh=true`. Locally: `EU_INTEL_FULL_REFRESH=1 python -m pipeline fetch ep_procedures`.
- **Redeploy** without data changes: *Actions → Deploy to GitHub Pages → Run workflow* (`gh workflow run pages.yml`).
- **Roll back**: revert the offending commit on `main` (a data refresh is a single commit); the push redeploys.
- **Refresh locally** (e.g. to debug a source): `EU_INTEL_NO_CACHE=1 python -m pipeline fetch ep_votes`, then
  `python -m pipeline validate && EU_INTEL_RECORD_ACTIVITY=1 python -m pipeline build`, review the diff, commit.

## End-to-end tests in CI

The `e2e` job in `ci.yml` (Playwright + axe-core on the built site) runs on every push to `main` and every pull
request; a manual run (*Actions → CI → Run workflow*) can skip it by unticking "Run Playwright e2e + accessibility tests".

It reuses the site built by the `check` job (uploaded as the `site-dist` artifact), installs Chromium, runs
`npx playwright test`, and uploads the HTML report and traces as the `playwright-report` artifact.

## Free-plan limits

Public repositories get unlimited standard GitHub-hosted runner minutes. Every job has a `timeout-minutes` cap
(CI: check 20, e2e 20; deploy: build 20, deploy 15; refresh: 120, with the fetch step capped at 100). Pages limits: published site ≤ 1 GB (checked at
build time), soft bandwidth limit 100 GB/month. Artifacts are kept 1–7 days.

## Optional link check

`python scripts/check_links.py` samples official URLs from `public/data` (default 5 per host, at most 60) and
checks them politely (one request at a time, 1.5 s per host). EUR-Lex, the Council website and parts of
europarl.europa.eu answer scripts with bot challenges (HTTP 202/403); those are reported as *unverifiable*, not
broken. It is not part of CI (it depends on third-party availability).
