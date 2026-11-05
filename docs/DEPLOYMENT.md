# Deployment and operations

The site is a static build deployed to **GitHub Pages** by GitHub Actions. Four workflows:

| Workflow | Trigger | Does | Permissions |
| --- | --- | --- | --- |
| `ci.yml` (CI) | push to `main`, pull requests, manual | ruff, typecheck; on the [frozen test data](#frozen-test-data): pytest (offline), data build, vitest, site build, Playwright e2e and accessibility tests in three engines; on the commit's own data: the [data gate](#the-data-gate) | `contents: read` |
| `pages.yml` (Deploy to GitHub Pages) | after *CI* passes on a push to `main`; called by *Data refresh* with the commit it pushed; manual | the data gate on the commit it deploys (data built with the Pages URL and base path) → a browser smoke test of the built site on its own data → upload → deploy → check the public URL | build: `contents: read`; deploy: `pages: write`, `id-token: write` |
| `refresh.yml` (Data refresh) | Mondays 05:17 and 22:37 UTC (a scheduled run is skipped if every core source on `main` was retrieved in the last 20 h), manual | fetch all sources (incremental, see below; a full refresh in the first week of each month) → validate per source → data gate (with activity recording) → commit `data/snapshot/` + `data/state/` to `main` → deploy that commit once CI has passed on its code | `contents: write`, `actions: read`; its deploy job: as `pages.yml` |
| `watchdog.yml` (Watchdog) | after each *Data refresh* and each *CI* run on `main`, daily 19:41 UTC, manual | opens, updates or closes the [Data health](#data-health) issue | `contents: read`, `issues: write`, `actions: read` |

All actions are pinned to full commit SHAs (with the version in a comment); Dependabot
(`.github/dependabot.yml`) proposes weekly grouped updates. The Python runtime dependencies in `pyproject.toml` have a
ceiling at the next major version (`httpx<1`, `pydantic<3`, `lxml<7`, `pyyaml<7`), so that a major release, which can change an
API, does not reach the unattended refresh and deploy before CI has run on it; Dependabot's pip entry proposes raising a ceiling
once a release passes it. Within those ranges the versions are pinned, with the sha256 hashes of their files, in
`requirements.txt`, which the refresh, the deploy and CI install with `pip install --require-hashes -r requirements.txt`
(the pipeline runs from the checkout, `python -m pipeline`): the refresh job holds a token that can push to `main`, and
an unattended run installs only the files CI has tested. That token is not kept in the refresh's checkout
(`persist-credentials: false`): only its push step gets it, so the npm packages the job also runs (`npm ci`, vitest, the
site build) cannot read it. Dependabot proposes updates of the pins; CI runs on them before
they reach `main`. To regenerate the file (Python 3.12, as the workflows use): `uv pip compile pyproject.toml
--python-version 3.12 --generate-hashes -o requirements.txt` (or `pip-compile --generate-hashes`).

The deploy job also makes an independent HTTP smoke check **against the public Pages URL**, including the
homepage, Insights, legislation, votes, people, countries, and data/meta.json. A successful GitHub Pages
publish that serves missing routes or empty data is treated as a failed release, and so is one the public URL does not
serve: the check waits (up to 5 minutes) until `data/meta.json`, fetched with a query string past Pages' 10-minute
cache, has the `built_at` of the build it deployed.

### The data gate

What data must pass before it reaches `main` (the refresh) or the site (the deploy), and what CI checks on each commit's
data: `pipeline validate` (the snapshot) → the strict data build (`EU_INTEL_STRICT=1`) → `pipeline validate --built` (exit 1
on any error class of `pipeline/validate.py`, `activity-duplicate` among them: one step reported twice in the activity feed,
once from a record the source has corrected; and on an integrity warning class above `pipeline/validate_baseline.json`) →
`src/lib/format.test.ts` on that build (every date a next step, status explanation or timeline step states as still ahead
is restated correctly once it has passed, and no dated wording is unknown to `src/lib/format.ts`) → site build → privacy
check → size check (fails over 900 MB; Pages allows 1 GB).

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
   "Paths to production" below; protection is not needed for that.)
4. **Environment**: enabling Pages creates the `github-pages` environment, which by default only accepts
   deployments from `main`. Keep it that way (manual runs from other branches will build but not deploy; a refresh
   started from another branch commits to `main` but does not deploy).
5. Optional: a custom domain (*Settings → Pages → Custom domain*). The base path then becomes `/` automatically,
   and so do the absolute links in the Atom feeds (`SITE_URL`, see below) from the next deploy. The feed and
   entry ids stay the same (`tag:rahv-fb.github.io,2026:eu-intel/…`), so feed readers do not show old entries
   again as new. Set the repository variable `SITE_URL` (*Settings → Secrets and variables → Actions → Variables*) to
   the new address, for the watchdog's check of the live site.
6. **Issues** must stay enabled (*Settings → General → Features*): the watchdog reports in a "Data health" issue. Watch
   the repository (at least *Issues*) to be notified when it opens or lists a new problem.

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

- **Refresh** runs weekly on Monday at 05:17 UTC, and again at 22:37 UTC; a scheduled run is skipped when every core
  source (`CORE_SOURCES` in `pipeline/freshness.py`: EP procedures, EP votes, EUR-Lex, Council) was retrieved
  successfully in the last 20 hours (`RECENT_HOURS`) by `main`'s `data/snapshot/_manifest.json`, so the second one does
  not run after a first one that refreshed them, and does run after one whose core sources failed (an outage) or that
  never came: GitHub runs schedules on a best-effort basis (the 05:17 run has started up to 8 hours late) and can drop a
  run at busy times. A commit of other data (a manual refresh of one source, a restore) does not skip it. A scheduled
  run in the first seven days of a month is a full refresh (`EU_INTEL_FULL_REFRESH=1`; decided in the job, since cron
  would OR a day of the month with the weekday). A manual run is never skipped. GitHub also disables every scheduled
  workflow of a public repository after 60 days without activity in it. A commit is activity: the refresh's weekly
  commits keep the repository active as long as it commits. A scheduled run that commits nothing (the watchdog's) is
  not. The watchdog's daily run is disabled together with the refresh's, so it cannot report this by itself: it then
  runs only after a CI run for a push to `main` or a deploy, and the first of those reports the live data as overdue.
  Re-enable each under *Actions → <workflow> → Enable workflow* (`gh workflow enable refresh.yml`, `gh workflow enable
  watchdog.yml`).
- **Time limits**: the fetch has a run-wide deadline (`EU_INTEL_FETCH_DEADLINE`, set by the workflow); after it
  no source starts and running sources start no new work. A request made after it gets a single short attempt
  (at most 30 s, no retries), and none starts at all 5 minutes after it. `timeout --signal=INT` then stops the
  fetch well before the job limit, so the checkpoints already written (`_state.json`, chunked snapshot files)
  still go through validation and the data gate, and are committed if they pass. Sources resume their pending work on the next run; EP procedures fetches
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
  source's last successful retrieval. A failed source does not fail the run (the Legislative Train fails on every
  GitHub runner): the [Data health](#data-health) issue lists it, and a source past its staleness threshold.
- **A source stops early**: no source starts after the run deadline, and every source starts no new work after
  its own budget (`EU_INTEL_FETCH_BUDGET_S`). EP procedures also stops starting files once 8 in a row have failed
  (an EP API or OEIL outage; files that already failed in an earlier run do not count), and the EP procedure list
  starts at the page size that worked last time (kept in `_state.json`).
- **Validation fails** for one source (a structural error; a file that is missing, or has more than 5% fewer records
  than `_manifest.json` records for it, or fewer than the minimum for a complete snapshot, `MIN_RECORDS` in
  `pipeline/validate.py`, so that an emptied file is not built and deployed as an empty section; or for `ep_people` a
  count of sitting MEPs that does not match their open political-group memberships): that source's snapshot directory and manifest entry are
  restored from the previous commit (marked `partial`), the whole snapshot must then validate, and the other
  sources' new data goes on to the data gate. Status changes are recorded only from complete procedure and EUR-Lex data: a partial fetch lists in its
  `_state.json` (`unsettled`) the files it did not refresh completely (pending, kept from an earlier run, recorded
  without OEIL data, an act or notice kept or lost), and only those dossiers keep their stored stage until a later
  run refreshes them. A partial fetch without that list (e.g. a restored state file) suspends all status changes for
  the run. The build log warns in both cases, with the date since when.
- **A record count differs from the manifest's** within that margin, in either direction: `validate` warns
  (`manifest-count`). Records re-derived offline need their source's manifest entry recounted with them, or the
  About page's technical details give the counts of before (the EP votes entry, recounted on 24 October 2026: the
  vote kinds re-derived on 23 October had left it at 2,995 ballots for the 2,996 stored).
- **The data fails the [data gate](#the-data-gate)**: the strict build fails, or `python -m pipeline validate --built`
  finds a claim the build derived that contradicts the rules or the files' own dates (`pipeline/validate.py`, e.g. a
  vote margin that contradicts its outcome, a withdrawn file with an act, Council adoption steps on more than one day, a
  step listed before the one it follows, a single-state veto outside unanimity) or an incomplete build (a file of
  `PUBLIC_FILES` missing or unreadable, an empty list that never is, a count in `meta.json` that is zero or below the
  snapshot's, a file the dossier and vote indexes list not written), or the dated-wording check, the site build, the
  privacy check or the size check fails. Then the run commits nothing (neither the snapshot nor `data/state`), deploys
  nothing and fails, and the Data health issue says so; `main` and the site keep the last data that passed, and the
  next run fetches again. Per-source quarantine (committing the sources whose data passes without the one that breaks
  the gate) is not implemented yet (TODO in `refresh.yml`); hold a source back by hand meanwhile (below).
- **No changes**: nothing is committed or deployed.
- **Push rejected** because `main` moved during the run: the job resets onto the new `main`, re-applies only the
  data files this run changed (this run's version wins for those; `_manifest.json` is merged per source) and
  pushes again, up to five times. Do not commit snapshot data by hand while a refresh is running.
- **Deploy build fails** (the data gate on what it deploys, or the browser smoke test): the deploy job does not run and the previous deployment
  stays live. Fix and push, or re-run the workflow.
- Deploys are serialised (`concurrency: pages`, never cancelled mid-flight).
- **Paths to production**, each deploying one known commit:

  | Path | Checks the code passed | Checks the data passed |
  | --- | --- | --- |
  | push to `main` → CI → `pages.yml` (`workflow_run`) | the whole CI run: ruff, typecheck, pytest, vitest and the browser tests in three engines, on the frozen test data | the data gate in CI, then again in the deploy |
  | refresh → `pages.yml` (`workflow_call`, `ref` = the pushed commit) | a successful CI run for a push to `main` on a commit with the same files outside `data/snapshot` and `data/state` | the data gate before the push, then again in the deploy |
  | manual `pages.yml` | none (emergency redeploy) | the data gate in the deploy |

  After CI or a refresh, if `main` has moved on since that commit only by data refresh commits, the deploy builds `main`
  (same code, newer data), so that it does not take refreshed data off the site. A failed or cancelled CI run (a newer
  push cancels it) deploys nothing; CI on pull requests and manual CI runs never deploy, and a manual run does not cancel
  the run of a push (the event is part of CI's concurrency group). A refresh whose code has not
  passed CI (yet), e.g. a commit pushed while the refresh ran, commits its data but does not deploy it: the deploy that
  follows the next successful CI run on `main` does.
- Commits made by the refresh use `GITHUB_TOKEN`, which by design does not trigger workflows: the refresh deploys its
  commit itself (`pages.yml` as a reusable workflow, granted `pages: write` and `id-token: write`), and CI does not run on
  it. It does not need to: a refresh commit changes only `data/snapshot` and `data/state`, CI's tests run on the frozen
  test data (so they would test the same code on the same data again), and the refresh ran the data gate on its data
  before pushing. `main` therefore stays green across refreshes, and so do Dependabot's pull requests.

## What a weekly run re-reads

A scheduled refresh, except the full refresh in the first week of each month, is incremental for three sources. A
stored record that is not re-read keeps the data and the derivation of the run that last read it, but a rotation
re-reads each one at least every 8 weeks, as long as the source answers:

- **EP procedures**: files new to the list, still open (not adopted, published, in force, no longer in force,
  taking effect on notification, withdrawn, rejected or lapsed), with a recorded step in the last 120 days,
  without OEIL data, featured, or pending from the last run. The run also re-reads the closed files whose rotation
  slot (a SHA-256 hash of the id, modulo 8) is due that week, so every stored file is re-read at least every
  8 weeks. Stored files and the ids pending from the last run stay in scope when the EP's paged list misses them,
  which happens because the list repeats rows between pages. Ids the EP API cannot serve because the procedure was
  split or merged are retried only by a full pass; other unusable ids are retried every run.
- **EP votes**: the sittings from 60 days before the latest stored sitting, the sittings still pending, and the
  older sittings whose rotation slot (the same hash of the sitting id, modulo 8) is due that week.
- **Legislative Train**: new files, and file pages whose status changed or that are marked "Recently updated" on
  the theme page, were updated in the last 90 days, are pending, or are due in a four-week rotation of the quiet
  files.

The weeks of the 8-week rotation run from Monday to Sunday, like ISO weeks, but they are counted without starting
again in January, so 8 weekly runs in a row take each slot once, also across a new year. After a missed or failed
run, the next run also takes the slots of the weeks that had no run. A second run in the same week takes none. On
the snapshot of 2 Nov 2026, EP procedures re-read 425 to 450 stored files a run, plus the new ones (about 900
requests in all), against 420 to 430 before. The 152 files no longer in force or taking effect on notification
were re-read every week; the rotation's 150 to 180 closed files take their place. EP votes read 33 to 52 older
sittings on top of the window, which adds about 100 to 160 requests, or 2 to 3 minutes.

The other sources read their whole scope each run, except that Council notes whose Cellar record and parser are
unchanged are reused and opt-outs read each directive's text once (again when the recital matcher changes).

A **full pass** re-reads every stored record of one of those three sources. It runs with a full refresh
(`EU_INTEL_FULL_REFRESH=1`: the scheduled runs in the first week of each month, and manual runs with "Full refresh"
ticked, see "Manual operations"). It also runs by itself when the source's `PARSER_VERSION` (in
`pipeline/sources/ep_procedures.py`, `ep_votes.py` or `legislative_train.py`) differs from the `parser` recorded in
its `_state.json`. Bump that version with any change to how the source reads or derives its records, so that reused
records do not keep the old derivation. The monthly full refresh also picks up late corrections at source. A full
pass is chunked and resumable like any run. One interrupted by its time
budget stays a full pass in the next runs until it completes (`pass_parser` in `_state.json`); only then does
`parser` take the new version. A pass started for another version starts again. A source that cannot be reached
keeps its records and its old `parser`, and its pass waits until the source answers. This is the case of the
Legislative Train, which the EP's WAF blocks on GitHub's runners.

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
  `python -m pipeline validate && EU_INTEL_STRICT=1 EU_INTEL_RECORD_ACTIVITY=1 python -m pipeline build && python -m
  pipeline validate --built` (the first steps of the data gate, which CI runs on the commit), review the diff, commit.
  If a step fails, do not commit: the build has already written the activity it recorded to `data/state`.

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
4. **Check the deploy.** The push runs CI (its tests run on the frozen test data; its data gate checks the restored data),
   and *Deploy to GitHub Pages* once CI has passed. To deploy without waiting for CI: *Actions → Deploy to GitHub Pages → Run
   workflow* on `main` (`gh workflow run pages.yml --ref main`). When it has succeeded, `snapshot_at` in
   `https://rahv-fb.github.io/eu-intel/data/meta.json` (the latest retrieval of any source) is that of the restored data, and
   the footer's "Procedures, votes and acts current to" date (`core_data_at`, the oldest retrieval of the core sources) is too,
   and `commit` is the commit the deploy built (`git log -1 <commit>`: your restore, or a later commit with the same data).
   `built_at` moves with every deploy, so it does not show that the data is the good one.
5. **While you prepare that, an earlier version can be deployed again.** Each deploy's job summary names the commit it built
   (*Built commit … / Deployed commit …*), and so does the live `data/meta.json` (`commit`). Deploys after CI or by hand are
   *Deploy to GitHub Pages* runs; a refresh's deploy is the *Deploy* jobs of its *Data refresh* run, and GitHub's Pages
   deployment history (and `headSha`) lists it under the commit the refresh started from, not the data commit it deployed:
   find it by the summary or with `gh run list --workflow refresh.yml --status success --json databaseId,createdAt` then
   `gh run view <run-id>`. Redeploy one: *Actions → Deploy to GitHub Pages*, an earlier successful run, *Re-run all jobs*
   (`gh run list --workflow pages.yml --status success --json databaseId,headSha,createdAt,displayTitle`, then `gh run rerun
   <run-id>`), or, for the data of an earlier refresh, the *Deploy / Build site* job of that *Data refresh* run (*Re-run this
   job*, which also re-runs the jobs that depend on it). A re-run builds what the original run built (a re-run keeps the
   original event, commit and job outputs), so it deploys that commit's data; GitHub allows re-runs for 30 days. It changes what is published only: `main`
   still has the bad data, and the next deploy (after CI passes on a push to `main`, or after the next refresh) publishes `main` again. Step 3 must
   follow. Dispatching `pages.yml` on another branch does not help: it builds but does not deploy (setup, point 4).
6. **Fix the cause.** The next refresh starts from the restored data and fetches again. If the cause is at the source, the same
   data comes back: hold that source back (below), and keep the schedule disabled until it is corrected. If the cause was how
   the pipeline reads or derives a source, fix the code and bump that source's `PARSER_VERSION` (EP procedures, EP votes,
   Legislative Train), so that the next runs re-read all its records ("What a weekly run re-reads"); otherwise the records
   a run does not re-read keep the old derivation until the rotation reaches them. Then switch the schedule back on
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

## Frozen test data

The tests that read real data (pytest through `data/snapshot`, e.g. `tests/test_build_real_records.py`; the vitest
tests that read `public/data`; the Playwright tests on the built site) pin ids, counts and dates of the data they read.
CI therefore runs them on fixed data, not on the commit's own: `data/snapshot` and `data/state` of the commit named in
`tests/frozen-data.txt` (`commit=`), built with `EU_INTEL_BUILT_AT` and `EU_INTEL_TODAY` set to the moment it names
(`built_at=`) and its date. Each browser page's clock starts at that moment too (`tests/e2e/fixtures.ts` reads `built_at`
from `dist/data/meta.json`; a test that installs its own clock replaces it). A data refresh changes none of this, so it
cannot turn `main` red. The commit's own data goes through the [data gate](#the-data-gate) instead, in the same CI job.

Locally: `scripts/test-frozen.sh` runs pytest, the frozen data build, vitest, the site build and the Playwright tests
(Chromium) in a temporary git worktree with this checkout's code (uncommitted changes included) and the frozen data,
leaving the working tree alone (`--no-e2e` skips the browser tests). A plain `pytest`, `npx vitest run` or `npx
playwright test` runs on whatever data is checked out and built.

**Moving the tests to newer data**, deliberately and in one pull request:

1. Pick a data refresh commit on `main` (`git log --format='%h %ad %s' --date=iso -- data/snapshot`); it must have both
   `data/snapshot` and `data/state`.
2. In `tests/frozen-data.txt`, set `commit=` to its full hash and `built_at=` to a moment after its last retrieval (the
   largest `fetched_at` in its `data/snapshot/_manifest.json`) and before 22:00 UTC, so that the tests' day is the same
   in Brussels.
3. Run `scripts/test-frozen.sh` and bring the pins that fail up to date (ids, counts, dates), in the same pull request.

## End-to-end tests in CI

The `e2e` job in `ci.yml` (Playwright + axe-core on the site built from the frozen test data) runs on every push to
`main` and every pull request; a manual run (*Actions → CI → Run workflow*) can skip it by unticking "Run Playwright
e2e + accessibility tests".

It runs once per browser engine (Chromium, Firefox and WebKit, the engine of Safari; one failing engine does not
cancel the others). Each run reuses the site built by the `check` job (uploaded as the `site-dist` artifact),
installs its browser, runs `npx playwright test --project=<browser>` (`E2E_BROWSERS` adds the Firefox and WebKit
projects to `playwright.config.ts`; locally only Chromium runs unless it is set), and uploads the HTML report and
traces as the `playwright-report-<browser>` artifact.

**The deploy's smoke test on the data it publishes.** These tests run on the frozen test data only, so every deploy
(`pages.yml`, whichever way it starts) also opens the site it has just built, on that site's own data, before uploading
it: `tests/e2e/live-smoke.spec.ts`, Chromium, with the reader's real clock. It picks the pages from `dist/data` when it
runs (files of every stage plus an even sample, about 20; votes of every kind, 10; MEPs, groups and parties; every
country; search by a procedure reference; the main pages), serves them as GitHub Pages does (`tests/e2e/pages-server.mjs`)
and fails on a console error, an uncaught exception, a failed or third-party request, the error page, a "not found" page
or an empty heading; then nothing is uploaded or deployed, and the report is kept as the `live-smoke-report` artifact.
`E2E_LIVE=1` selects it (and only it); the other runs leave it out. Locally, after a build of the current data:
`E2E_LIVE=1 npx playwright test --project=chromium` (about 1 minute).

## Data health

`watchdog.yml` keeps one issue titled "Data health" (label `data-health`) open while anything below is wrong, rewrites
it with the current list on each run, comments when a problem is new (an edit alone notifies no one; a source that gets
worse counts as new: failed, then stale, then its official labels withdrawn), and closes it once
everything passes. It runs after each *Data refresh*, each *CI* run on `main` and each *Deploy to GitHub Pages* run, daily
at 19:41 UTC, and by hand (*Actions → Watchdog → Run workflow*). It writes nothing to the repository. It lists:

- each source that failed in its last run or is stale: its last successful retrieval is older than its threshold in
  `pipeline/freshness.py` (EP votes and procedures, EUR-Lex, Council 9 days; MEPs 14; the others 35), as
  `python -m pipeline health` reports from `main`'s `_manifest.json`;
- a failed latest *Data refresh* (with its failed job and step: a failed data gate, push or deploy). The latest is the
  latest that ran: a scheduled run its plan skipped concludes "success" without doing anything and is passed over
  (`scripts/latest_run.py`), so it cannot hide a failure of the run before it;
- red CI on `main` (the latest CI run for a push): nothing deploys after it, and a refresh's data waits on `main` until CI
  passes on its code. When only WebKit's browser tests failed, the issue says to re-run them once if the log shows the
  known WebKit CSP flake ("Refused to apply a stylesheet because its hash…", docs/ASSESSMENT_2026-11.md 4.5);
- a failed latest deploy after CI or by hand (*Deploy to GitHub Pages*), or one cancelled with no later deploy that replaced
  it; a refresh's own deploy is part of its run (above);
- data on `main` that the live site lacks: a core source retrieved on `main` after the live site's copy of it, more than 6
  hours ago (`--deploy-grace-hours`): the refresh's deploy did not run (it waits for CI to pass on `main`'s code) or failed;
- the live site's data overdue: the newest retrieval in `https://rahv-fb.github.io/eu-intel/data/meta.json` (or the
  repository variable `SITE_URL`; fetched with a query string, past Pages' 10-minute cache) is older than 8 days, whether the schedule was late, dropped or disabled or the refresh
  or its deploy failed. This also fails the watchdog run, so GitHub sends its own notification;
- the repository past 750 MB (GitHub recommends under 1 GB; each refresh commit adds to every clone).

`python -m pipeline health` runs the source and site checks locally (`--meta FILE` for a downloaded `meta.json`,
`--markdown` for the issue body, `--json`); it exits 1 when anything is wrong.

## Known limitations

- **Re-apply onto new code**: a refresh whose push is rejected because a code commit reached `main` re-applies its data on
  that code without running the data gate again; the deploy runs the gate (the site is safe), but `main` can hold data
  that fails its own code's gate until the next refresh.
- **Pending deploys are replaced**: deploys share one concurrency group (`pages`) and GitHub keeps one pending run per
  group, so a newer deploy cancels a pending one; a refresh whose deploy was replaced ends `cancelled` (the watchdog skips
  it), and the replacement publishes its data only if it builds a commit that contains it (the "undeployed" check says so).
- **Before `meta.json` loads**, the pages treat the Legislative Train's "blocked" as not current (a dossier's status badge
  and official-status box, the home page's Stalled rows and featured badges), then switch: a brief flash, never a label
  shown past its expiry.
- **The home page's Stalled list** drops expired "blocked" rows by matching the build's wording (`badge: "Officially
  blocked"` and the list's description, `src/pages/Home.tsx`); a change of that wording in `build_home` must change both.

## Free-plan limits

Public repositories get unlimited standard GitHub-hosted runner minutes. Every job has a `timeout-minutes` cap
(CI: check 30, e2e 20; deploy: build 20, deploy 15; refresh: plan 5, refresh 120, with the fetch step capped at 100;
watchdog 10). Pages limits: published site ≤ 1 GB (checked at build time), soft bandwidth limit 100 GB/month. Artifacts
are kept 1–7 days.

## Optional link check

`python scripts/check_links.py` samples official URLs from `public/data` (default 5 per host, at most 60) and
checks them politely (one request at a time, 1.5 s per host). EUR-Lex, the Council website and parts of
europarl.europa.eu answer scripts with bot challenges (HTTP 202/403); those are reported as *unverifiable*, not
broken. It is not part of CI (it depends on third-party availability).
