# Assessment and plan — November 2026

An audit of the project two weeks after its first release (22 Oct 2026): objectives, what falls short, and an
ordered plan. Snapshot audited: refresh of 2 Nov 2026 (live site built 2 Nov 13:52 UTC). Checked 5 Nov 2026.

**Method.** Six independent audits ran in parallel: data correctness (21 records re-checked against the live
EP API, OEIL, Cellar and Council PDFs), sourcing (every endpoint requested live), the refresh/deploy loop (Actions
logs of every run), the site against its four personas (Playwright, desktop and mobile), engineering health
(all checks run, coverage measured) and the competitive landscape. The findings that drive the plan were then
verified again by hand. These are marked ✔ below. Unmarked figures come from one audit's own measurement.

---

## 1. Objectives

The goals already in docs/PRODUCT.md, restated so that each can be tested:

| # | Objective | Test |
|---|---|---|
| O1 | **Never publish a wrong fact.** Every claim traces to an official record; missing data is shown as missing. | Zero known contradictions on the live site; every integrity rule gates deploys. |
| O2 | **Update itself without babysitting.** | `main` green after every refresh; a failed source or stale data reaches the owner within a day; no manual step in a normal week. |
| O3 | **Be the place to answer questions others answer badly.** | For each persona's core question, the site gives a correct, plain answer in under 30 s. |
| O4 | **Be found and reused.** | Pages preview when shared; search engines index content; the data is citable and downloadable. |

## 2. Verdict in brief

The engineering is unusually careful: official identifiers only, curated corrections with quoted evidence,
date wording that tracks the reader's clock, a strict CSP, 858 Python and 310 TS tests. Its competitive
position is also real (§4).

But the project currently fails O1 and O2. Both failures have one cause: **the self-updating loop publishes
before it verifies, and its verifier only warns.**

- Five factual errors are live today. The validator flagged one of them and the deploy went ahead.
- `main` has been red for about 68% of the time since the first scheduled refresh.
- The Legislative Train source has never once succeeded from CI.
- Nobody is alerted to any of this.

O3 is partly met. Depth is excellent for specialists, but only 30 of 1,587 files (1.9%) have a plain-language
summary. Nothing on the site shows *what changed* or *what comes next*. O4 is not addressed at all.

The plan therefore orders work as **trust → autonomy → value → reach**.

---

## 3. Shortcomings

### 3.1 Wrong facts on the live site (O1)

| File | The site says | The records say | Root cause | ✔ |
|---|---|---|---|---|
| 2023/0421(COD), codification of Dir. 2004/37 | "Published in the Official Journal" (30 Oct). Also in `activity.json` and both Atom feeds. | No Parliament position, no Council adoption, no act in Cellar. OEIL: "Awaiting committee decision". The EP has since deleted the publication event (404). | `analysis/status.py:681`: one EP-API publication event sets stage `published`, with no act and no adoption behind it. | ✔ |
| 2025/0177(COD), defence-related products | Act **Decision (EU) 2026/2402**, which belongs to 2025/0380. | OEIL now lists **32026L2383** as the final act, and Cellar links it. | The OEIL final-act list was briefly wrong upstream, and `build.py:2316-2325` let it override EUR-Lex. Open PR #14 adds a heuristic for this one case. Its "Published 28 Oct" fallback comes from an EP event that now returns 404 (the actual publication was 3 Nov). | ✔ |
| 2025/0312(COD) | "Approved by Parliament … It is not law yet: the Council must still formally approve it". The next step is the Council. | The same file has `adopted: 2026-10-26`, and its timeline shows "Council adopted the act, 27–0–0" (ST 14961/26 matches). | `build.py:4102` `council_dated` only re-dates Council steps OEIL already has. A Council vote never *adds* an adoption to what `classify` sees. | ✔ |
| 2010/0208(COD), Dir. (EU) 2015/412 (GMOs) | "The transposition deadline (17 October 2002) has passed". 27 country rows carry that deadline. | The date is a Cellar error carried over from Dir. 2001/18. | `analysis/transposition.py`: an unlabelled date is treated as a deadline, even when it falls before the act. | ✔ |
| 2020/3521(COD) | Shown as an ordinary legislative procedure, "In force". | Council Decision (EU) 2020/2059 is an EU position in a trade committee, not legislation. | Cellar's tag. The validator warns (`act-procedure-mismatch`) but publishes anyway. | |
| All 8 recorded status changes | Each cites the OEIL page as its source. | Several came from EUR-Lex or the EP API. For 2023/0421 the cited page contradicts the claim. | `analysis/activity.py:446` always takes `det["sources"][0]`. | ✔ |

The **pattern** matters more than the individual bugs. For the most recent ~7 days, the EP's data on
publications and final acts is unreliable, and is corrected at source within days. Three of the last week's
publication records were wrong. Eight historical EP signature/publication dates disagree with EUR-Lex. The build
treats a single source's claim about the newest events as fact. **Corroboration, not special-casing, is the
fix** (Plan 1.1).

Separately, 4 files still show "Signed, awaiting publication" (2025/0176, 2026/0078, 2024/0098, 2025/0172). They
were published on 3–4 Nov. This is ordinary weekly lag, not a bug.

**The validator does not protect O1.** `validate --built` printed 28,834 warnings on 2 Nov, including
`act-on-two-dossiers: 32026D2402 is shown on 2025-0177, 2025-0380`. It then printed `OK — 0 errors`, and the site
deployed. That rule is a `rep.warn` at `pipeline/validate.py:586` ✔, under a comment that reads "one law, one
page". 99.9% of the warnings are by design:
- 25,681 `ref-procedure` warnings: votes on out-of-scope files;
- 3,086 `ref-mep` warnings: past-term rapporteurs.

The real signals are buried, and three of the five errors above raise no warning at all.

### 3.2 The self-updating loop (O2)

**Data reaches production by a weaker path than code.**

| Path to production | pytest | vitest data invariants | e2e + axe | validate --built |
|---|---|---|---|---|
| Code push → CI → `pages.yml` | ✓ | ✓ | ✓ | ✓ |
| Refresh → `pages.yml` (workflow_run, `pages.yml:15`) | ✗ | ✗ (only `format.test.ts`) | ✗ | ✓ (warnings only) |

On 2 Nov, Deploy 41456717477 succeeded at 13:54:59 and CI 41456717608 failed at 13:55:04, at the vitest data
tests ✔. CI after a refresh only reports; it gates nothing. The deploy also checks out the *latest* `main`, not
the refresh commit, so it can ship untested code.

**Tests mix invariants with snapshot pins.**
- Of 1,834 assertions over real data (vitest `*.data.test.ts`, e2e specs, `test_build_real_records.py`), about
  1,226 (67%) pin specific ids, counts or dates that legitimately change with a refresh.
- 4 pins broke in 2 refreshes. On that rate, a refresh turns `main` red about 86% of the time. The figure is
  rough: 2 refreshes is a small sample.
- Red `main` then fails every Dependabot PR (#15, #16 and the earlier python group).
- The 26 Oct break went unnoticed for 3 days. No CI ran after refreshes then.

**Failures are silent.**
- A source that fails only produces a `::warning`; the run is green.
- The Legislative Train has returned an AWS WAF challenge (HTTP 202) on *every* CI run. Its 22 Oct data came from
  a local run. The block depends on IP reputation, so GitHub's data-centre runners are hit.
- The repository has zero issues: no alert of any kind has fired.
- On the site, `snapshot_at = max(fetched)` (`build.py:4986`) ✔. So home and footer say "Data refreshed 2 Nov"
  while the Train copy dates from 22 Oct, and dossier pages show "officially blocked" with no retrieval date.

**Scheduled runs are late and incomplete.**
- The Monday 05:17 UTC cron started 5 h 46 min (26 Oct) and 8 h 10 min (2 Nov) late. The delay is in GitHub's
  scheduler.
- A full refresh is never scheduled (`refresh.yml:105` ✔: manual only).
- 1,147 of 1,574 procedures (73%) are closed and quiet, so they are **never re-read**. A wrong "closed" stage
  protects itself from correction. 2023/0421 would have stayed wrong permanently had its bad event been 120+
  days old.
- EP votes are re-read only within 60 days of the latest sitting.
- `ep_procedures`, `ep_votes` and `train` have no `PARSER_VERSION`, so a parsing fix reaches only records that
  happen to be re-read.

**Storage grows for nothing.**
- Each refresh adds about 12 MB to a fresh clone.
- `implementation/measures.json` changed 124,178 lines on 2 Nov, of which **2** were real changes ✔. Every
  record carries its own `source.retrieved_at`.
- At this rate the repo passes GitHub's recommended 1 GB around mid-2028, or about Apr 2027 if refreshes become
  more frequent before this is fixed.
- The published site is 332 MB (deploy 66 s, 61 MB compressed). It is far from Pages limits unless ballots are
  extended to all 26,267 roll-call votes, which would mean about 1.6 GB, over the 1 GB limit.

### 3.3 Sourcing

| Source | State | Fragility |
|---|---|---|
| EP API (people, procedures, votes) | Healthy. Some secondary endpoints answered 500 on 5 Nov (`/procedures/feed`, vocabularies); 8 HTTP 429s on 2 Nov. | Low |
| OEIL HTML | Healthy. Same web estate as the bot-walled `www.europarl`. | Medium |
| Cellar (EUR-Lex, NIM, opt-outs) | Healthy. | Low |
| Council | Cellar lists the notes, but the PDFs exist **only** on `data.consilium` (Cellar holds no datastream). Positions are read by pixel colour from a rendered page. A template change would leave new votes without positions while the source stays "ok" (it is judged on ≥95% of *all* 749 votes). | Medium–High |
| Infringements (Themis) | Undocumented POST API. | Medium |
| Legislative Train | Broken in CI since day one (WAF). | High |
| Single Market Scoreboard | Answered 403 on 22/26 Oct and 200 since 2 Nov. ROADMAP, DATA_SOURCES and the module docstring still say "refuses scripted access". The headline indicators exist only in Power BI embeds. Overdue directives per Member State are in a plain HTML table. | — |

**Unused official data with high value**, all tested live on 5 Nov:

| Source | Evidence | Enables | Effort |
|---|---|---|---|
| **Cellar planned events** (`cdm:event_legal_projected`) | ✔ Dated, typed upcoming steps per dossier, about 3 weeks ahead. Examples: `APR_R1_byCONSIL` and `DELIB_byCONSIL` on 19 Nov; `VOTE_byEP` on 25 Nov. Linked to Council agenda documents. | "Coming up" on every file and on the home page | S |
| **EUR-Lex official summaries** (`cdm:summary_summarizes_work`) | ✔ 576 of the site's 1,273 files with an act (45%) have one. Today 30 files have a hand-written summary. | Plain language at scale, labelled "Official EUR-Lex summary" | S |
| EP plenary agenda (`/meetings/{id}/foreseen-activities`) | Vote items carrying procedure ids, about 3 weeks ahead | "Parliament votes on this next week" | S |
| OEIL forecasts and legal basis (pages already fetched) | "Indicative plenary sitting date"; "TFEU 114" | Forecast dates; automatic QMV/unanimity check (closes a ROADMAP gap) | S |
| CJEU rulings via Cellar | `case-law_interpretes_…`, `…declares_void…`, pending references | "Court rulings on this law"; annulment badges (C-727/25 gap) | S |
| Consolidated versions via Cellar | `act_consolidated_consolidates_resource_legal` | "Current consolidated text" link | S |
| EP adopted texts / committee documents | TA ids linked to procedures; 178 provisional agreements | Vote → adopted text; "provisional agreement published" | S–M |
| EESC / CoR opinions | `work_part_of_dossier` | Advisory opinions on the timeline | S |
| Have your say (`brpapi`) | 4,157 initiatives; feedback deadlines | "Feedback open until …" (counts and dates only; no personal data) | M |

Not available in machine-readable form: Council votes in any form other than PDF, EP committee roll calls, an EU
Law Tracker API, and a Legislative Train data feed.

### 3.4 Value to readers (O3)

What works is exactly what specialists need:
- the Council vote with named countries and the QMV maths;
- Parliament votes by group and country, with filters that can be shared by link;
- the 27-country transposition table with each country's infringement case;
- corrected application dates;
- identifier search: procedure, CELEX, nicknames like "chat control".

Search is fast (1–12 ms per query on the real index). Mobile layouts never overflow.

What fails the personas:

1. **Too little plain language.** 30 of 1,587 files have a summary. Green Claims, the Affordable Housing Act,
   the minimum-wage directive and NIS2 all say "We have not written a plain-language summary". 382 titles start
   with "Amending…".
2. **Nothing says what happened.**
   - `activity.json` (148 KB, built weekly) is **not fetched by any page** ✔.
   - List rows and search results say only "Latest recorded step <date>", never *which* step.
   - There is no "changed in the last 7/30 days" view.
3. **Nothing says what comes next** beyond dates fixed in law. The home page leads with hero and search. "What's
   moving" sits 4 screens down on desktop and 9 on mobile, and its "Close votes" list reaches back to April 2024.
4. **Being stuck is buried.** 55 pending files have had no recorded step for over a year, and only 13 are on
   the "blocked" list. There is no sort by time without a recorded step. The blocked box sits 2.5 screens down
   the file page.
5. **Dates are given as legal references instead of meaning**, e.g. "Chapter III Section 4, Chapters V, VII and
   XII and Art. 78, except Art. 101 (Art. 113(3)(b))".
6. **Feeds are low-signal.**
   - Titles are truncated, and status changes are listed twice.
   - Each summary is just the date plus the title.
   - There is no feed per file, so following a file means opening it in a browser.
7. **Journalists' core question is half-answered.** "How did my country's parties vote on this law?" has a
   country table but no national-party breakdown, and party pages list no votes.
8. **Scope is silent.** "glyphosate" returns 0 results with no note that implementing acts are out of scope.
9. **No reuse.** No CSV download, no documented JSON, no citable release.

Performance is adequate. Gzip shrinks `votes/index.json` from 2.5 MB to 303 KB. /votes, /search and Insights
take about 5 s on a slow mobile profile. Splitting the votes index by year, plus a `<link rel=preload>` for each
route's data file, fixes most of that.

### 3.5 Engineering

- **The build fails soft and still deploys.**
  - `_lazy()` (`build.py:1070` ✔, 17 call sites) turns any import or attribute error into `None`, disabling a
    feature with a warning.
  - A `classify` crash falls back to `fallback_status`, whose code is almost all untested.
  - An unreadable curated YAML drops all its corrections.
  - `build()` always returns 0 ✔.
- **The contract check is weak.** It runs only on the fixture build and checks keys, not nulls or types. On the
  real output one drift exists: `CouncilAssessment.states_required` is `number` in `data.ts` but `null` for 98
  unanimity objects. It is latent: the UI does not yet read it there.
- **Tests depend on the snapshot.** 17% of pytest and 51% of vitest need the live snapshot or build. 111 tests in
  `test_build_real_records.py` drive `Builder` methods through 46 hand-built stand-in objects, which makes
  splitting `build.py` (5,547 lines; `Builder` 3,247 lines, 79 methods) expensive.
- **Adding a source touches six registries.** Term dates are written out in four files. Some special cases live
  in code instead of curated YAML: `OEIL_NO_FILE`, `OEIL_PROPOSAL_AUTHORS`, `PARLIAMENT_ADOPTS`,
  `GROUP_SLUG_MERGE`, and the EP-vs-EUR-Lex act rule.
- **The Council PDF text path is barely tested** (`parse_document` 1/25 statements).
- **Dependencies:** vite 8 (#13) and `@vitejs/plugin-react` 6 (#5) must be merged *together*. The Playwright bump
  (#2) fails in WebKit on a CSP stylesheet hash.

### 3.6 Reach (O4)

- The 6,443 prerendered pages have a good `<title>` and description ✔, but **no `og:` tags, no sitemap.xml, no
  robots.txt and an empty `<body>`** ✔.
- A dossier link pasted into Slack, X, LinkedIn or Mastodon gets a bare preview, and crawlers that don't run JS
  see nothing.
- The data is not packaged for reuse or citation.
- The repository is two weeks old with no stars. Being found matters as much as features.

---

## 4. Where the value is

The landscape changed after docs/PRODUCT.md was written:
- **EuropeScope** (featured by data.europa.eu, 11 Sep 2026) joins EP and Council votes, with MEP attendance and
  rebel counts.
- The official **EU Law Tracker** (Ombudsman award, July 2026) follows files *until adoption*.
- **HowTheyVote.eu** covers EP roll calls within 30 minutes, with an API, and uses the same EP vote ids as this
  site ✔.

So "EP + Council votes in one place" is no longer unique, and MEP analytics is a crowded field.

**The defensible wedge is the second half of a law's life, joined to the first:**
- when each part applies (with corrected dates);
- whether each Member State has transposed it;
- whether there is an infringement case;
- who in Parliament and Council passed it.

All of this sits on one page with sources. Official tools stop at adoption. EUR-Lex has the pieces, but with
date errors and a bot wall. Transposition is tracked one directive at a time by law firms and NGOs, or behind
paywalls.

A free, zero-cost pipeline that keeps running is itself a differentiator: VoteWatch, EU Monitor and the SWP
Council Monitor all stopped.

**Realistic audiences, in order:**
1. National and regional journalists and fact-checkers: "what did our government and MEPs do, and has our country
   implemented it?"
2. NGOs and associations tracking implementation.
3. Compliance generalists priced out of Politico Pro and similar (~€12k/yr).
4. Researchers.

Citizens are best reached through 1 and 2.

---

## 5. Plan

Effort: **S** ≤ 1 day, **M** 2–5 days, **L** > 1 week. Each item states when it is done.

### Phase 0 — Correct the live site (this week)

| # | Action | Done when |
|---|---|---|
| 0.1 | Merge PR #14. It removes the wrong act from 2025/0177, and its Insights ordering and `/topics` redirects stand on their own. Note that its "Published 28 Oct" fallback is from a now-deleted EP event. | Live 2025/0177 shows no act from 2025/0380 |
| 0.2 | Dispatch a manual refresh straight after. The sources have already corrected 2023/0421, 2025/0177 (act 32026L2383, published 3 Nov) and the four "awaiting publication" files. Expect snapshot pins to go red again: that is what 1.4 removes. | Live 2023/0421 not "Published"; 2025/0177 shows 32026L2383 |
| 0.3 | Fix the two build bugs no refresh will fix: feed linked Council adoption votes into `classify` (2025/0312), and treat a transposition date before the act as "other" with a warning (2010/0208). Add a test for each. | Both files correct in a rebuild; tests fail with the fix reverted |

### Phase 1 — Trust and autonomy (weeks 1–3)

| # | Action | Effort | Done when |
|---|---|---|---|
| 1.1 | **Corroborate the leading edge.** A stage of published, in force or adopted needs an act in Cellar, a Council voting result, or OEIL agreeing with the EP API. Otherwise show the previous stage, plus "The EP records publication on …; not yet confirmed in EUR-Lex". Replace the special-case act rule (`build.py:2316`) with "EUR-Lex wins unless a curated `act_links` entry says otherwise". | M | The 2023/0421 and 2025/0177 snapshots reproduce no false stage |
| 1.2 | **Make the validator gate.** Promote to errors: `act-on-two-dossiers`, `act-procedure-mismatch`, and new invariants: (a) post-adoption stage ⇒ Parliament position (COD); (b) `adopted` set ⇒ stage ≥ adopted; (c) transposition date ≥ act date; (d) an activity item's cited source supports its claim. Demote by-design classes (`ref-procedure`, `ref-mep`, `procedure-ref`) to info. Keep a per-class baseline of counts, and fail when an integrity class rises. | S | 2 Nov's snapshot fails validation |
| 1.3 | **Strict build** in CI and refresh: fail on `_lazy` → `None`, a skipped curated file or entry, any `classify` fallback, or an assessment failure. `build()` returns non-zero. Move the contract check into `validate --built` on the real output, with null/enum checks; fix `states_required: number \| null`. | S | Renaming a status function fails CI |
| 1.4 | **Split tests** into a gate tier (invariants; e2e picks its examples from the data at run time) and a golden tier (pins in `tests/golden/*.json`, regenerated by each refresh and proposed as a PR that never blocks deploys). Freeze the 264 real records used by `test_build_real_records.py` as fixtures, with a regeneration script. | M | A refresh with ordinary changes leaves `main` green |
| 1.5 | **Gated promotion.** The refresh commits to `refresh/<run>`, calls CI (`workflow_call`) on that SHA, fast-forwards `main` only if CI passes, then calls Pages on that exact SHA. Remove the "Data refresh" trigger from `pages.yml:15`. A source whose data breaks the build is quarantined (reverted to its last good files, marked partial) rather than blocking all the others. | M–L | No path deploys data that skipped vitest or e2e |
| 1.6 | **Alerting.** Final `if: always()` steps in refresh and CI open, update or close one "Data health" issue. It lists non-ok sources since when, red `main`, and validator ratchet breaches. A source failing twice in a row fails the run. A daily `watchdog.yml` checks the live `meta.json` age, which also catches a delayed or dropped cron. | S | The Train failure has an open issue |
| 1.7 | **Honest freshness on the site.** Add per-source staleness thresholds (votes, procedures, Council, EUR-Lex 9 days; people 14; others 35). Base `snapshot_at` on the oldest core source, or flag stale ones on home and in the footer. The "officially blocked" box shows its retrieval date and drops after 6 stale weeks. | S–M | Home flags a source past its threshold on the reader's date (the Train's 22 Oct copy from 26 Nov), and its "blocked" labels are withdrawn after 42 days (from 3 Dec) unless it is retrieved again |
| 1.8 | **No permanent blind spots.** Schedule a monthly full refresh. Re-read closed procedures on a rotation (1/8 per week). Add `PARSER_VERSION` to `ep_procedures`, `ep_votes` and `train`. Add a second cron with a skip-if-recent guard. | S–M | No record older than 60 days without a re-read |
| 1.9 | **Stop storage churn.** Drop per-record `retrieved_at` (keep it per source in the manifest). Use `filter: blob:none` instead of `fetch-depth: 50` in `pages.yml`. Add a repo-size guard. | S | A refresh adds < 2 MB to a clone |

### Phase 2 — Value on the wedge (weeks 3–8)

Ordered by value ÷ effort. Each uses official data only.

| # | Feature | Data | Effort | Done when |
|---|---|---|---|---|
| 2.1 | **Coming up**: next Council and Parliament steps on each file ("Council adoption scheduled 19 Nov, General Affairs Council"), and a "Next 3 weeks" list on home | Cellar `event_legal_projected` + EP `foreseen-activities` | S–M | ≥ 30 files show a dated upcoming step |
| 2.2 | **What changed**: a page and home strip built from `activity.json`, by topic and week; every list row names its latest event; full titles and merged entries in feeds; **one Atom feed per file**; export Following as OPML | Already built | S–M | Following a file works in any feed reader |
| 2.3 | **Official summaries**: show the EUR-Lex summary (labelled, linked) where no curated one exists; put common names (NIS2, CSDDD) in page titles | Cellar `summary_summarizes_work` | S | 576 more files have a plain explanation |
| 2.4 | **What applies when, where**: a calendar of rules starting to apply in the next 30/90 days by topic and country (page, Atom and `.ics`), with plain glosses for the dates on featured files | Existing act dates + curated glosses | M | A compliance reader can subscribe to "applies next quarter" |
| 2.5 | **Implementation tracker**: for each directive, 27 countries × time since deadline, infringement stage and opt-outs; a feed per country; the Scoreboard's overdue-per-country table as context. No league tables. | Existing + Scoreboard HTML table | M | A national NGO can link one URL per directive |
| 2.6 | **National-party breakdown** on vote pages, and votes on party pages; link each vote to HowTheyVote for MEP-level analytics | Ballots + `meps.json` | S–M | "How did CDU vote on the Nature Restoration Law" is answered on the vote page |
| 2.7 | **Law context links**: CJEU rulings (and annulment/pending badges), current consolidated text, EP adopted text, EESC/CoR opinions | Cellar | S each | Each shows on the AI Act and GDPR pages |
| 2.8 | **Stuck view**: sort by "longest without a recorded step"; put blocked status and its age in the status line, not 2.5 screens down | Existing | S | The home page "Stalled" link opens that sort |
| 2.9 | **Scope-aware empty states**: a search with no results says what is out of scope (implementing/delegated acts, NLE) and links to EUR-Lex | — | S | "glyphosate" explains why there is nothing |

After Phase 1.9, add a light **Friday refresh** (EP votes, procedures, Council, EUR-Lex; about 15 min). 97.7% of
EP votes fall Tue–Thu, so this cuts the average lag from about 5 days to about 2.

### Phase 3 — Reach (in parallel with Phase 2)

| # | Action | Effort |
|---|---|---|
| 3.1 | `prerender-routes.mjs`: `og:title`, `og:description`, `og:url`, `og:type`; a static key-facts block (stage, dates, act, next step) inside `<body>` of each dossier shell; `sitemap.xml` + `robots.txt`. | S |
| 3.2 | **Open dataset**: a weekly CSV/JSON release with a schema and the identifier crosswalk (procedure ↔ CELEX ↔ EP vote ↔ Council document ↔ national measures ↔ infringement), on GitHub Releases, with a Zenodo DOI. Document `/data/*.json` on About. CSV export buttons on vote, transposition and list tables. | S–M |
| 3.3 | Offer the crosswalk to HowTheyVote and EuropeScope so they can link back to the law pages; add a "report an error" issue template. | S |
| 3.4 | Update docs/PRODUCT.md's competitor table (EuropeScope, EU Law Tracker). Correct the stale Scoreboard statements in ROADMAP, DATA_SOURCES and `implementation.py`. | S |

### Phase 4 — Hardening (continuous)

| # | Action | Effort |
|---|---|---|
| 4.1 | **Legislative Train**: switch to the site's own search form: Blocked (46 results) plus recently updated (171), about 100 requests instead of crawling 1,492 pages. Ask the EP Open Data Portal to publish the data or allowlist the crawler. Do not work around the WAF. Until then, 1.7 marks the data stale. | S |
| 4.2 | **Council**: read the embedded bitmap (`pdfimages`), not a 100-dpi render; fingerprint the template; mark the source partial when any note from the last 60 days lacks positions; cross-check adoptions with Cellar `APR_R1_byCONSIL`; check the printed voting rule against the legal basis already on OEIL pages; test the PDF text path. | M |
| 4.3 | **One source registry** (replace the six parallel lists) and one table of term dates. Move the code special cases above into curated YAML with evidence. | M |
| 4.4 | Extract the pure sections of `build.py` (search docs, curated loaders, labels) when next touched; leave `Builder` until the stand-in tests are gone (after 1.4). | M |
| 4.5 | Merge #13 and #5 together. Fix the WebKit CSP stylesheet-hash failure so #2 can land. Group vite with its plugin in `dependabot.yml`. | S |

---

## 6. What not to build

- **MEP attendance, rebel scores, cohesion rankings, co-signature networks.** EuropeScope, HowTheyVote and
  MEPwatch do this faster, and scores amount to rankings (Principle 4). Link out per vote instead (2.6).
- **Lobbying or influence analysis.** Commission meeting data carries no procedure references, and joining it
  would need title matching, which the identifier rule forbids. Integrity Watch and LobbyFacts cover it.
- **LLM-written summaries, chatbots, "AI analysis".** They conflict with source integrity, and others already
  ship them. Get breadth from official summaries (2.3); keep hand-written ones for featured files.
- **Accounts, e-mail or push alerts.** They need a server and personal data. OEIL, the Law Tracker and EUR-Lex
  already offer account alerts. Per-file feeds (2.2) are the static, private equivalent.
- **Horizon scanning before a proposal exists, or newsletters.** That is the paid tools' core and needs a
  newsroom.
- **Judging national transposition quality, or "worst transposer" tables.** It needs lawyers in 27 countries,
  and rankings break the nonpartisan principle.
- **Ballots for every roll-call vote** before vote files are made compact. That would mean about 1.6 GB, over
  the Pages 1 GB limit.

## 7. How to know it is working (no analytics, by policy)

| Objective | Signal | Target |
|---|---|---|
| O1 | Integrity-rule violations reaching the live site | 0 |
| O1 | Live spot check of 20 random records each month (script from this audit) | ≥ 19/20 match, or differ only by source lag |
| O2 | Share of days `main` is green | ≥ 95% (now ≈ 32%) |
| O2 | Hours from a refresh to an alert when something fails | < 24 h (now: never) |
| O2 | Median lag from an EP vote to the site | ≤ 2 days (now ≈ 5) |
| O3 | Files with a plain explanation (curated + official) | ≥ 600 (now 30) |
| O3 | Files with a dated upcoming step | ≥ 30 at any time (now: legal dates only) |
| O4 | Pages with preview tags in sitemap; inbound links; GitHub stars and issues; dataset DOI downloads; feed subscriber counts shown by public readers (Feedly, Inoreader) | Rising |

## 8. Keep

- Fetch and build kept separate.
- The committed, diff-friendly snapshot, with failure isolated per source.
- Joining only by official identifiers.
- Curated corrections with quoted evidence and review dates.
- Date wording that follows the reader's clock (`format.test.ts`).
- Separating Parliament approval from adoption from application.
- Saying "not recorded" rather than "abstained".
- The CSP and privacy checks.
- Hash-pinned dependencies.
- The search engine.

---

## 9. Status after Phase 0–1 (5 November 2026)

Phase 0 and Phase 1 were merged as #14 and #17 and ran in production the same day. A second, independent audit
of the merged code, the data, the workflows and the docs followed; its findings are fixed in the follow-up PR or
listed below. Measured, not estimated, unless marked otherwise.

### What production showed

| Check | Result |
|---|---|
| CI on `main` (frozen-data tests, live-data gate, e2e in 3 engines) | green on 43342c0 |
| A refresh: fetch → validate → strict build → gate → commit → deploy of that commit (`workflow_call`) | run 42038313824 (the first on the new workflow): green, live 14:19 UTC |
| Refresh → `main` stays green | the tests that pin values read frozen data, so a refresh no longer moves them; the first CI run on refreshed data is the follow-up PR's |
| Data health issue | #20 opened by the watchdog (the Legislative Train, failing since 22 Oct), edited in place on the next run |
| Storage per refresh (thin pack, as pushed) | 0.06 MB, down from 0.92 MB: `measures.json` is no longer rewritten |
| Dependabot | vite + `@vitejs/plugin-react` bumped together (#18); dependency PRs no longer fail on red `main` |

**Correction to §3.2.** "Each refresh adds about 12 MB" counted whole files without delta compression. Git's
delta-compressed growth was about 0.9 MB per refresh before the snapshot-writer fix and is now under 0.1 MB, so the
repository-size limits in §3.2 are decades away, not 2027–2028.

### Plan items

| # | Status | Evidence / remaining |
|---|---|---|
| 0.1–0.3 | Done | 2025/0177, 2023/0421, 2025/0312, 2010/0208 correct live; feeds carry none of the withdrawn claims |
| 1.1 Corroborate the leading edge | Done | an EP publication or signature record alone no longer moves a file; differential build on the 2 Nov and 5 Nov snapshots: only intended changes |
| 1.2 Validator gates | Done; strengthened in follow-up | follow-up: `act-procedure-mismatch` an error (2020/3521), identity-based ratchet, published ⇒ act invariant, duplicate check per file and step, 1.2(d): an activity item cites the record it reports |
| 1.3 Strict build | Done; gaps closed in follow-up | follow-up: skipped `council_dates` / `unlinked_acts` entries fail `--strict` |
| 1.4 Frozen test data | Done | `tests/frozen-data.txt` (5f83a06), `scripts/test-frozen.sh` |
| 1.5 Gated promotion | Done; extended in follow-up | follow-up: a Chromium smoke of live data before every deploy (the data gate had no browser step) |
| 1.6 Alerting | Done; blind spots closed in follow-up | follow-up: watch deploys too, escalate a worsening source, a data-age check against `main` |
| 1.7 Freshness on the site | Done | "current to" date; stale notes on the reader's clock; Train labels withdrawn after 42 days |
| 1.8 Re-read blind spots | Done | 8-week rotation, carried-forward ids, `PARSER_VERSION`; first scheduled full refresh 7 Dec 2026 |
| 1.9 Storage churn | Done | see above |
| Per-source quarantine | Not done | a failed gate commits nothing (documented TODO in `refresh.yml`) |

### Found by the second audit

Fixed in the follow-up PR (each with a test that fails without it):

- **2020/3521(COD)** was still shown as an ordinary legislative procedure "In force": Council Decision (EU) 2020/2059,
  a position in the EU–Pacific trade committee, tagged COD by Cellar. Excluded as a checked correction.
- **Activity history**:
  - a status change was withdrawn when only its date moved within a stage (a file signed after its adoption lost its
    "Adopted" entry);
  - the same step was listed twice when a second source reported it under a new id (2025/0232, 2025/0380, 2023/0134);
  - an item still repeated a withdrawn claim in its "previously" text (2023/0421).
- **Two of the new checks were themselves wrong**:
  - the duplicate check would have failed future refreshes on twin files that share a title;
  - a Legislative Train run that read nothing looked fresh.
- **Council votes**: one listing query against Cellar replicas that disagree. ST 14946/26 was missed by two snapshots,
  and a known note missing from one answer was dropped. Now the union of three passes, keeping known notes.
- **/legislation** said "No file is officially reported as blocked" when `meta.json` had not loaded (15 were).
- **Workflows**:
  - a manual CI run could cancel the push run that a deploy waits for;
  - the skip guard was fooled by manifest-only commits;
  - the refresh job exposed its push token to npm install scripts;
  - a deploy did not record the commit it built (GitHub labels a refresh's deploy with the caller's commit): it is now
    in `meta.json` and the job summary;
  - e2e jobs were cancelled while installing OS packages from a slow apt mirror (now run in the Playwright image).
- **Status labels were fixed at build time** while explanations follow the reader's date ("Published, not yet in
  force" beside "It entered into force on 17 November"). A daily rebuild without fetching now keeps them within a day.
- **Docs**: 20 statements that #17 had made false (deploy paths, schedules, the Scoreboard, the Train), and the
  competitor table (EuropeScope, the EU Law Tracker).

Left as known limitations: a pending deploy can be replaced by a newer one; a re-applied refresh push is not
re-gated with newly merged code (the deploy re-gates it); a short "not yet blocked" flash before `meta.json` loads;
the home "Stalled" list keys on display strings; the WebKit stylesheet-hash flake (Plan 4.5).

### Next

Phase 2 is under way:
- 2.1 Coming up (Cellar planned events, EP plenary agenda);
- 2.2 What changed, with a feed per file;
- 2.3 Official EUR-Lex summaries and 2.7 law context;
- 2.6 the national-party breakdown;
- 2.4 (calendar) and 2.5 (implementation tracker) follow.
