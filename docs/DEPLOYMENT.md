# Deployment and operations

The site is a static build deployed to **GitHub Pages** by GitHub Actions. Three workflows:

| Workflow | Trigger | Does | Permissions |
| --- | --- | --- | --- |
| `ci.yml` (CI) | push to `main`, pull requests, manual | ruff, pytest (offline), `pipeline validate`, `pipeline build`, `pipeline validate --built`, typecheck, vitest, site build with `BASE_PATH=/eu-intel/`, privacy check; Playwright e2e and accessibility tests on the built site | `contents: read` |
| `pages.yml` (Deploy to GitHub Pages) | after *CI* passes on a push to `main`, after a successful *Data refresh*, manual | validate → build data → validate the built data → check its dated wording (`src/lib/format.test.ts`) → build site with the Pages base path → privacy check → size check → upload → deploy | build: `contents: read`; deploy: `pages: write`, `id-token: write` |
| `refresh.yml` (Data refresh) | Mondays 05:17 UTC, manual (optionally a full refresh) | fetch all sources (incremental, see below) → validate → build with activity recording → validate the built data → commit `data/snapshot/` + `data/state/` to `main` | `contents: write` (this job only) |

All actions are pinned to full commit SHAs (with the version in a comment); Dependabot
(`.github/dependabot.yml`) proposes weekly grouped updates. The Python runtime dependencies in `pyproject.toml` have a
ceiling at the next major version (`httpx<1`, `pydantic<3`, `lxml<7`, `pyyaml<7`), so that a major release, which can change an
API, does not reach the unattended refresh and deploy before CI has run on it; Dependabot's pip entry proposes raising a ceiling
once a release passes it. Within those ranges the versions are pinned, with the sha256 hashes of their files, in
`requirements.txt`, which the refresh, the deploy and CI install with `pip install --require-hashes -r requirements.txt`
(the pipeline runs from the checkout, `python -m pipeline`): the refresh job holds a token that can push to `main`, and
an unattended run installs only the files CI has tested. Dependabot proposes updates of the pins; CI runs on them before
they reach `main`. To regenerate the file (Python 3.12, as the workflows use): `uv pip compile pyproject.toml
--python-version 3.12 --generate-hashes -o requirements.txt` (or `pip-compile --generate-hashes`).

## One-time setup (repository owner)

1. **Enable Pages with Actions as the source**: *Settings → Pages → Build and deployment → Source:*
   **GitHub Actions**. (Do not choose "Deploy from a branch".) Until this is done, `pages.yml` fails at
   *Configure Pages* and nothing is deployed. The runs before it have failed, and nothing starts another until the
   next push or refresh: run the first deploy by hand, *Actions → Deploy to GitHub Pages → Run workflow* on `main`
   (`gh workflow run pages.yml --ref main`), and check that `https://rahv-fb.github.io/eu-intel/` loads once it is green.
2. **Allow the refresh job to push**: *Settings → Actions → General → Workflow permissions*. The workflows
   request permissions explicitly, so the default "Read repository contents" is fine, but the
   organisation/repository must not forbid `contents: write` for `GITHUB_TOKEN`.
3. **If `main` is protected** by a ruleset or branch protection that blocks direct pushes, add
   `github-actions[bot]` (or the "GitHub Actions" app) to the bypass list, or the refresh commit will be rejected.
   Required status checks on `main` also block bot pushes unless bypassed. (The deploy waits for CI by itself, see
   "Deploys and CI" below; protection is not needed for that.)
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
(`feeds.TAG_BASE`) never change with it, as an Atom id must not when a feed moves (RFC 4287, section 4.2.6). `pages.yml` gives
the site build the same `SITE_URL`, from which `scripts/prerender-routes.mjs` writes each page's `<link rel="canonical">`
(`<SITE_URL><route>/`, the address of the prerendered page, which is also the address the Atom entries link to); without it
(CI, local builds, forks) the pages have none, so that they do not point at another host. `404.html` carries `noindex`.

Pages has no server-side rewrites, so `scripts/prerender-routes.mjs` writes an `index.html` for every known route
(`/legislation/2021-0106/`, `/votes/<id>/`, …) so that deep links return HTTP 200 with a route-specific
`<title>`, plus `404.html` as the SPA fallback for anything else (served with status 404).
The app's own links are written without the trailing slash (`/eu-intel/legislation/2021-0106`), as the router makes
them. Inside the site the router follows such a link without loading a page, but loading the address itself (a reload, a
new tab, a shared or bookmarked link) gets a 301 from Pages to the address with the slash, keeping the query and the
fragment: one extra round trip, nothing breaks. The canonical links and the Atom entries use the address with the slash.
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
  (EP procedures also removes one that no longer passes validation, at most 5% of its stored files in a run: beyond
  that it keeps them, marked `partial` with their ids in the note, since the 5% check under "Validation fails" compares
  the file with the count the same run writes to the manifest). The manifest records `partial` or `failed`
  (with the previous successful `fetched_at`), and the run continues with the other sources. The site shows each
  source's last successful retrieval.
- **A source stops early**: no source starts after the run deadline, and every source starts no new work after
  its own budget (`EU_INTEL_FETCH_BUDGET_S`). EP procedures also stops starting files once 8 in a row have failed
  (an EP API or OEIL outage; files that already failed in an earlier run do not count), and the EP procedure list
  starts at the page size that worked last time (kept in `_state.json`).
- **Validation fails** for one source (a structural error; a file that is missing, or has more than 5% fewer records
  than `_manifest.json` records for it, or fewer than the minimum for a complete snapshot, `MIN_RECORDS` in
  `pipeline/validate.py`, so that an emptied file is not built and deployed as an empty section; or for `ep_people` a
  count of sitting MEPs that does not match their open political-group memberships): that source's snapshot directory and manifest entry are
  restored from the previous commit (marked `partial`), the whole snapshot must then validate, and the other
  sources' new data is committed. The activity log (`data/state`) is committed only after a successful build.
  Status changes are recorded only from complete procedure and EUR-Lex data: a partial fetch lists in its
  `_state.json` (`unsettled`) the files it did not refresh completely (pending, kept from an earlier run, recorded
  without OEIL data, an act or notice kept or lost), and only those dossiers keep their stored stage until a later
  run refreshes them. A partial fetch without that list (e.g. a restored state file) suspends all status changes for
  the run. The build log warns in both cases, with the date since when.
- **The built data fails validation**: after the build, `python -m pipeline validate --built` checks the claims
  the build derived against the rules and the files' own dates (`pipeline/validate.py`, e.g. a vote margin that
  contradicts its outcome, a withdrawn file with an act, Council adoption steps on more than one day, a step
  listed before the one it follows, a single-state veto outside unanimity), and that the build is complete: every file of
  `PUBLIC_FILES` present and readable, the lists that are never empty (dossiers, votes, Council votes, MEPs, groups,
  parties, countries, topics, search) not empty, no count in `meta.json` that is zero or below the snapshot's, and every
  file the dossier and vote indexes list written. If it fails, the run commits nothing
  (neither the snapshot nor `data/state`) and fails, so nothing is deployed; `main` keeps the last snapshot whose
  build passed, and the next run fetches again. A build that fails outright still commits the snapshot without
  `data/state` (above).
- **No changes**: nothing is committed (the deploy still re-runs; harmless).
- **Push rejected** because `main` moved during the run: the job resets onto the new `main`, re-applies only the
  data files this run changed (this run's version wins for those; `_manifest.json` is merged per source) and
  pushes again, up to five times. Do not commit snapshot data by hand while a refresh is running.
- **Deploy build fails** (validation of the snapshot or of the built data, data build, the dated-wording check,
  TypeScript, Vite, privacy check, > 900 MB): the deploy job does not run and the previous deployment stays live. Fix
  and push, or re-run the workflow.
- Deploys are serialised (`concurrency: pages`, never cancelled mid-flight).
- **Deploys and CI**: a push to `main` runs CI, and the deploy starts only when the whole CI run (lint, tests, build
  and the browser tests in the three engines) has passed: `pages.yml` runs on `workflow_run` of *CI* for a push to
  `main` that succeeded. It builds the commit CI tested; if `main` has moved on since only by data refresh commits
  (changes to `data/snapshot` and `data/state` alone), it builds `main`, so that it does not take that data off the
  site. A failed or cancelled CI run (a newer push cancels it) deploys nothing; CI on pull requests and manual CI
  runs never deploy. Some of CI's data tests (`src/**/*.data.test.ts`) pin values of the committed snapshot, such as
  the date of the latest Council vote: after a refresh changes one, a push fails CI until the test is brought up to
  date, and its deploy waits for that (the refreshed data itself is deployed by the refresh's own deploy).
- Commits made by the refresh use `GITHUB_TOKEN`, which by design does not trigger `push` workflows; the deploy
  is chained with `workflow_run` instead, and CI does not run on refresh commits. The refresh and the deploy each
  validate the snapshot and the built data, and the deploy runs the checks of `src/lib/format.test.ts` on it (every
  date a next step, status explanation or timeline step states as still ahead is restated correctly once it has
  passed, and no dated wording is unknown to `src/lib/format.ts`); pytest, the other vitest data tests (they pin values
  of the committed snapshot) and the browser tests do not run on refreshed data. A deploy after a refresh builds the
  latest `main`: a code commit pushed while CI has not yet passed on it is published with it, so do not leave a
  commit that failed CI on `main` (fix or revert it).

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
  A manual run builds the branch it is started on, without waiting for CI.
- **Roll back** a data refresh: see "Rolling back a bad data refresh" below. A plain `git revert` is enough only when the bad
  refresh is the latest commit that touched `data/`.
- **Refresh locally** (e.g. to debug a source): `EU_INTEL_NO_CACHE=1 python -m pipeline fetch ep_votes`, then
  `python -m pipeline validate && EU_INTEL_RECORD_ACTIVITY=1 python -m pipeline build && python -m pipeline
  validate --built`, review the diff, commit. If the last check fails, do not commit: the build has already
  written the activity it recorded to `data/state`.

## Rolling back a bad data refresh

For data on the site that is wrong because of a refresh (a commit "Data refresh YYYY-MM-DD" by `github-actions[bot]`, which
changes only `data/snapshot/` and `data/state/`). Fixing the cause and rolling back are two jobs: the next scheduled refresh
starts from whatever `main` holds and fetches again, so a rollback alone does not last.

1. **Stop the refresh from moving `main`.** Cancel a run that is going (*Actions → Data refresh → the run → Cancel workflow*, or
   `gh run list --workflow refresh.yml --status in_progress`, then `gh run cancel <run-id>`; likewise for `--status queued`): when
   its push is rejected, a refresh re-applies its own data files on top of `main`, and it would overwrite your restore. Then
   disable the schedule: `gh workflow disable refresh.yml` (or *Actions → Data refresh → ⋯ → Disable workflow*), which does not stop a
   run that is already going.
2. **Find the last good commit.** `git log --format='%h %ad %s' --date=short -- data/snapshot data/state` lists the commits that
   changed data; take the one before the bad refresh (`data/snapshot/_manifest.json` in it has each source's `fetched_at`).
3. **Put that commit's data back in a new commit on `main`.**
   - If the bad refresh is the newest commit that changed data (`git log -1 --format=%h -- data/snapshot data/state` prints its
     hash), `git revert <bad-sha>` applies cleanly.
   - Otherwise do not revert it. Every refresh rewrites `_manifest.json` and usually `ep_votes/_state.json`, so reverting an older
     refresh after a newer one stops with conflicts, and a hand-merged partial revert is a snapshot that never existed. Restore
     the good commit's data instead:
     `git restore --source=<good-sha> --staged --worktree -- data/snapshot data/state`, then `python -m pipeline validate`, then
     `git commit -m "Restore data from <good-sha>"` and `git push origin main`.

     Use `restore`, not `git checkout <good-sha> -- data/snapshot data/state`: `checkout` stops with "pathspec 'data/state' did
     not match" when the good commit predates the first refresh (no `data/state` yet), and it keeps files added since, while
     `restore` removes them. Afterwards `git diff <good-sha> HEAD -- data/snapshot data/state` prints nothing.
4. **Check the deploy.** The push runs CI, and *Deploy to GitHub Pages* once CI has passed. CI's data tests pin values of the
   current snapshot, so they can fail on restored data; the restore is then deployed by hand, *Actions → Deploy to GitHub Pages →
   Run workflow* on `main` (`gh workflow run pages.yml --ref main`), which does not wait for CI. When it has succeeded, the footer's "Data last
   refreshed" (`snapshot_at` in `https://rahv-fb.github.io/eu-intel/data/meta.json`) shows the date of the restored data.
   `built_at` moves with every deploy, so it does not show that the data is the good one.
5. **While you prepare that, an earlier version can be deployed again.** *Actions → Deploy to GitHub Pages*, an earlier successful
   run, *Re-run all jobs* (`gh run list --workflow pages.yml --status success --json databaseId,headSha,createdAt,displayTitle`,
   then `gh run rerun <run-id>`). A re-run builds the commit of the original run (a re-run keeps the original event and commit),
   so it deploys that commit's data; GitHub allows re-runs for 30 days. It changes what is published only: `main`
   still has the bad data, and the next deploy (after CI passes on a push to `main`, or after the next refresh) publishes `main` again. Step 3 must
   follow. Dispatching `pages.yml` on another branch does not help: it builds but does not deploy (setup, point 4).
6. **Fix the cause.** The next refresh starts from the restored data and fetches again. If the cause is at the source, the same
   data comes back: hold that source back (below), and keep the schedule disabled until it is corrected. If the cause was how
   the pipeline reads or derives a source, fix the code and run a full refresh of that source ("What a weekly run
   re-reads"); otherwise the records a run does not re-read keep the old derivation. Then switch the schedule back on
   (`gh workflow enable refresh.yml`).

### Holding one source back

The weekly run fetches every source and has no switch to skip one. To keep a source at the data of a good commit, restore just
that source and its manifest entry (what the refresh does for a source that fails validation):

    git show <good-sha>:data/snapshot/_manifest.json > /tmp/manifest_good.json
    git restore --source=<good-sha> --staged --worktree -- data/snapshot/<source>
    python -m pipeline restore-manifest --previous /tmp/manifest_good.json --reason "Held at the data of <date>: <why>." <source>
    python -m pipeline validate

then commit and push as in step 3. The manifest entry is marked `partial` with the reason, and the About page shows its last
successful retrieval. Then disable the schedule (step 1) and refresh by hand without that source, naming the others in the `sources`
input of *Run workflow* (the names are `ep_people ep_procedures ep_votes eurlex council implementation optouts train`; those not
listed are not fetched and keep their files and manifest entries):

    gh workflow run refresh.yml -f sources="ep_people ep_procedures eurlex council implementation optouts train"

(that holds back `ep_votes`). Sources read the files of earlier ones in that order, so a held-back `ep_people` or
`ep_procedures` leaves the later sources working from its older records. To let the source go again, run it once by hand
(`-f sources=ep_votes`, with `-f full_refresh=true` for `ep_procedures`, `ep_votes` or `train` after a change to how they are
derived), check the result, and enable the schedule.

## End-to-end tests in CI

The `e2e` job in `ci.yml` (Playwright + axe-core on the built site) runs on every push to `main` and every pull
request; a manual run (*Actions → CI → Run workflow*) can skip it by unticking "Run Playwright e2e + accessibility tests".

It runs once per browser engine (Chromium, Firefox and WebKit, the engine of Safari; one failing engine does not
cancel the others). Each run reuses the site built by the `check` job (uploaded as the `site-dist` artifact),
installs its browser, runs `npx playwright test --project=<browser>` (`E2E_BROWSERS` adds the Firefox and WebKit
projects to `playwright.config.ts`; locally only Chromium runs unless it is set), and uploads the HTML report and
traces as the `playwright-report-<browser>` artifact.

## Free-plan limits

Public repositories get unlimited standard GitHub-hosted runner minutes. Every job has a `timeout-minutes` cap
(CI: check 20, e2e 20; deploy: build 20, deploy 15; refresh: 120, with the fetch step capped at 100). Pages limits: published site ≤ 1 GB (checked at
build time), soft bandwidth limit 100 GB/month. Artifacts are kept 1–7 days.

## Optional link check

`python scripts/check_links.py` samples official URLs from `public/data` (default 5 per host, at most 60) and
checks them politely (one request at a time, 1.5 s per host). EUR-Lex, the Council website and parts of
europarl.europa.eu answer scripts with bot challenges (HTTP 202/403); those are reported as *unverifiable*, not
broken. It is not part of CI (it depends on third-party availability).
