# Data sources — audit

Status as of the first sprint (2026-10-22). "Reachable" means reachable anonymously from a script (the
pipeline runs in CI without credentials). Details are refined from each ingestion module's findings.

| Source | Interface | Reachable | Used for | Notes |
| --- | --- | --- | --- | --- |
| EP Open Data API v2 `data.europarl.europa.eu/api/v2` | JSON-LD REST | ✅ | MEPs, groups, national parties, committees, procedures + events, plenary decisions **with individual roll-call ballots** | Anonymous; paginated (`offset`/`limit`); stable ELI-style ids (`eli/dl/proc/2021-0106`, `person/197443`) |
| EP Legislative Observatory (OEIL) | HTML | ✅ | Status label, subjects, COM references, Commission/Council key events, final-act CELEX | One procedure-file page per procedure, ≥1 s apart; fills what the EP API does not carry |
| EP Legislative Train Schedule | HTML | ✅ | Official status of major files incl. "blocked" monitoring | No API; controlled crawl of theme + file pages |
| EP `doceo` documents (RCV XML/PDF) | HTML/XML | ⚠️ 202 bot challenge | — | Roll-calls come from the API instead |
| Cellar SPARQL `publications.europa.eu/webapi/rdf/sparql` | SPARQL 1.1 | ✅ | Legal acts (CELEX, ELI, dates incl. phased entry-into-force/application, procedure links, amendments), national implementing measures | Batched queries; CDM ontology |
| EUR-Lex website | HTML | ⚠️ 202 bot challenge | Human links only | Not scraped |
| Act texts (Cellar content negotiation `publications.europa.eu/resource/celex/{CELEX}`) | XHTML | ✅ | Directives' opt-out recitals (Protocols 21/22) | Each directive read once |
| Council voting results (consilium.europa.eu pages) | HTML | ❌ 403 "Browser check" | — | Not used; see Council section |
| Council "voting result" documents (ST notes) | Cellar SPARQL + PDF at data.consilium.europa.eu | ✅ | Member State positions, voting rule, outcome | Annex table is an image; parsed deterministically, fail-closed |
| Single Market Scoreboard | HTML/JSON | ❌ 403 | Transposition deficit indicators | Alternatives investigated by the implementation module |
| Commission infringement decisions | HTML / search | ⚠️ redirects to commission.europa.eu | Infringement cases | See implementation section below |

## Identifiers that connect the sources

- **Procedure reference** `2021/0106(COD)` — EP (process id `2021-0106`), Cellar (procedure link on the act),
  Council (written `2021/0106 (COD)`), Legislative Train (links to OEIL).
- **CELEX** `32024R1689` and **ELI** `http://data.europa.eu/eli/reg/2024/1689/oj` — legal acts; national measures
  reference the directive's CELEX.
- **EP person id** — MEPs in memberships and ballots. **EP organization id** — groups, parties, committees.
- **EP voting id** (`notation_votingId`) — plenary votes; votes link to documents (reports `A9-0188/2023`,
  amendments `…-AM-102`), and documents to procedures.

## Licences and attribution

- European Parliament: open data reusable with attribution (EP legal notice / open data portal terms).
- EUR-Lex / Publications Office: reuse authorised under Commission Decision 2011/833/EU, with attribution.
- Council and Commission websites: reuse authorised with acknowledgement of the source, unless stated otherwise.

The site footer and About page credit each source. MEP portraits are not used (avoids hot-linking third-party
images that would expose visitors' IP addresses to another host).

## Update frequency and refresh

EP data changes after each plenary session and committee meeting; Cellar is updated daily; the Legislative Train
monthly. A weekly scheduled refresh is sufficient for v1 and stays well within the free GitHub Actions allowance.
Scheduled runs are best-effort; the site shows the real retrieval timestamp per source.

## Module findings

### EP people (`ep_people`) — ok
- `/meps?parliamentary-term=9|10` + batched `/meps/{id,id,…}` (50 ids per call) and `/corporate-bodies/{…}`; ~42
  requests per full run. The API documents a cap of 500 requests / 5 minutes; the pipeline throttles to ≤1.5/s.
- 1,280 MEPs (term 9: 875, term 10: 746), 719 currently sitting; 18 political-group bodies, 528 national parties,
  83 committees, each membership dated. Group-at-date reproduced the API's own `show-current?mandate-date=` view
  with 0 mismatches on two group-change dates.
- Group codes from official labels (PPE→EPP, Verts/ALE→Greens/EFA). GUE/NGL (until 2020-12-17) and The Left
  (from 2020-12-18) are distinct bodies at source and kept distinct.
- Gaps: a few MEPs lack a national-party membership for part of a mandate (e.g. 197526 in term 10). "Independent"
  is recorded by EP as a per-country party. Portraits not used.

### EUR-Lex / Cellar (`eurlex`) — ok
- 1,248 legislative acts 2014+ that Cellar links to a COD, CNS or APP procedure, plus 21 final acts that OEIL
  records for procedures in the EP snapshot but Cellar does not link to them (e.g. Regulation 2019/816,
  2017/0144(COD)): 1,269 acts. Non-legislative (NLE, ~2,490) and budgetary acts are out of scope for v1. OEIL's
  "Corrigendum to final act" entries are not final acts: for 2021/0426(COD) (EPBD) one of them is Commission
  Implementing Regulation 2025/1328, which implements the directive. Acts of the Commission are never taken as
  the act of a legislative procedure.
- Procedure link: dossier with `procedure_code_interinstitutional_reference_procedure` via
  `dossier_produces_resource_legal`, `resource_legal_produced_by_dossier`, or the adopted proposal's
  `work_part_of_dossier`. References whose type contradicts the dossier's own type are not linked.
- Dates: OJ publication (`official-journal-act_date_publication`, else the OJ issue date); entry into force is the
  value tagged EV (else PE) of `resource_legal_date_entry-into-force` — the property mixes EV/PE/MA dates, and in
  166 acts the earliest value is not the entry into force. Other dates are kept as "further application dates"
  without claiming which provisions they concern, except that dates marked MA/PART or PE/PART (in the type or in
  the `comment_on_date` annotation) are shown as "some provisions apply from". A value of `1001-01-01` (comment
  DATNOT, "date of notification") only says that the date is not recorded; its date type says what kind of date
  it is. Type EV (entry into force) with a comment pointing to an article of the act ("V ART 2.2"): the act enters
  into force on a condition it sets, not yet recorded as met. The Electoral Act amendments (2018/994, 2026/1296)
  need the approval of every Member State in accordance with their constitutional requirements (Art. 223(1) TFEU,
  Art. 2 of each decision): "Published, not yet in force". Type PE (date of effect) without an EV date: a decision
  addressed to specific recipients, whose date of effect Cellar gives as the date of notification to them without
  recording that date, e.g. the empowerment decisions 2020/853 (Germany), 2020/854 (Italy) and 2020/1531
  (France), each "addressed to" its Member State (Art. 3): "Takes effect on notification", not "not yet in
  force". No Treaty rule is cited for them: Art. 297(2) TFEU (addressed decisions take effect upon notification)
  is about non-legislative acts, and these are legislative acts.
- End of validity: the `comment_on_date` annotation on each `resource_legal_date_end-of-validity` value (fd_330
  codes: A/PAR repealed by, AI/PAR implicitly repealed by, R/PAR replaced by, FIN/VAL/PART partial end of
  validity, with the acts it names) is kept as `validity_notes`. A no-longer-in-force act names the repealing act
  (by its number, linked to its file or to EUR-Lex): the whole-act repeal link, else the act in that annotation.
  When the repealing act's official title says "(codification)" or "(recast)" and it is later than the act, the
  status says that the rules continue in it. An end of validity earlier than the act itself (Regulation 1377/2014:
  31 December 2013, "Implicitly repealed by" the own-resources recast 609/2014) is stated as such, not as a plain
  end date. Dates the act records for after its end of validity are marked and are not its latest development
  (Regulation 2024/2822: validity ended 30 June 2026, some provisions recorded to apply from 1 July 2026). An
  in-force act with an end of validity still ahead says so, with the repealing act if one is recorded.
- Transposition: `directive_date_transposition` holds deadlines and application dates under one property. Each
  value's `comment_on_date` label (ADOPTION = adopt and publish by, APPLICATION = apply from, AU+TARD = at the
  latest, with the article) is kept (`pipeline/analysis/transposition.py`). Apply-from dates are never shown as
  deadlines (Consumer Credit Directive: deadline 20 Nov 2025, application 20 Nov 2026). Cellar does not say which
  deadline is the general one; it is the one checked against the text (`data/curated/transposition.yaml`), else
  the deadline whose article reference comes first when no other shares it (Directive 2023/2864: Art. 17(1)
  10 Jan 2026, Art. 17(2) 10 Jul 2025 for Article 3), else the earliest (`validate` lists these). The earliest
  is often a derogation (AMLD6, Art. 78(1): 10 Jul 2027 in general, 10 Jul 2025 for Article 74 only), so every
  directive with several deadlines that the article references do not decide is checked in the curated file. The
  other deadlines are "deadlines for specific provisions", earlier or later. The general application date is the
  deadline itself when Cellar labels it APPLICATION too and gives one article for it (AIFMD II, Art. 3(1)), else
  the first application date after it; later ones are "application dates for specific provisions", never "the
  date the measures apply from" (European Accessibility Act: 28 Jun 2025; the optional 28 Jun 2027 is for Article
  4(8) only). Dates whose role the data do not establish are "other dates recorded by EUR-Lex", kept off the
  timeline: a date from another article (Drinking Water Directive Art. 25, a transitional period), an
  application date before the general deadline in a paragraph that sets no deadline (VAT in the digital age,
  Art. 6(1): Member States "may apply ... from 14 April 2025"), or one the curated file marks. A directive with no
  transposition date (e.g. a codification) is described as such, never as one EU countries must transpose. The
  next step of a directive also names the transposition deadlines still ahead of the directives that have since
  amended it (CSRD: Directive (EU) 2026/470 by 19 Mar 2027).
- Withdrawals and replacements: Cellar procedure events WDW_byCOM / RPL_byCOM (`procedure_notices.json`, 350
  since 2014). OEIL often never records them (CCTB/CCCTB, Return Directive recast, standard-essential patents).
- Corrections: where Cellar's date metadata is wrong or was not updated after an amendment, the build applies
  `data/curated/act_dates.yaml`, each date citing the article that sets it (DSA Art. 93, AI Act Art. 113 as
  amended by Regulation 2026/1744, Return Regulation Art. 50, and three acts whose entry into force is tied to
  another act's: Regulation 2021/768 Art. 9, Decision 2015/457 Art. 3(2), Regulation 608/2014 Art. 9, where
  Cellar gives the application date or the other act's date). A date set by an amending act cites that act in
  the timeline, and the amending act's page lists the dates it set (`dates_set_for`); the status sentence says
  that the act's text, not EUR-Lex, sets the later dates. A checked date on the entry-into-force day is named in
  the entry-into-force event. The snapshot keeps the source values; `validate` warns about application dates a
  year or more before the act, and about an entry into force before the act's adoption (or before a
  regulation's publication).
- Timeline: an act's signature date is shown as "Signed by the Presidents of Parliament and Council" only for
  acts of the European Parliament and of the Council (by the act's title); a Council act is signed on the day
  of its adoption, which the Council's own step records.
- Related files: an amending, amended, repealing or repealed act is named by its number (from its official
  title, e.g. "Directive (EU) 2025/794"; for an act outside the snapshot from its CELEX id, 2015 onwards and
  directives from 1999, e.g. "Regulation 2026/2102"), followed by its file's short title when it has one; an
  act this file amends or repeals, or that repeals it, by its file's title too, unless that is an "Amending …"
  title.
- Known gaps: 352 acts without signature date, 24 directives without transposition date, only explicit whole-act
  repeals as repeal links (an implicit repeal is used only from the end-of-validity annotation), partial ends of
  validity are described only for decisions that take effect on notification, acts whose procedure is only in
  free text are unlinked.

### National implementation (`implementation`) — partial
- National measures: Cellar `cdm:measure_national_implementing` →
  `measure_national_implementing_implements_resource_legal` (directive), with country, Commission reference
  (`MNE(…)`), national OJ date and link. 551 directives queried; 61,957 measure records. Example — NIS2
  (32022L2555): measures notified by 25 Member States; none in the dataset for Ireland and Spain (both with open
  Court referrals); France has 15 measures and is also referred — notified ≠ fully transposed.
- Infringements: the Commission register's JSON API
  (`POST https://ec.europa.eu/implementing-eu-law/search-infringement-decisions/api/infringements`): all open cases
  plus all cases with a decision since 2019 — 7,195 cases, 2,006 open, 1,067 open non-communication cases. Stage is
  the register's latest decision type, verbatim. An act is linked only when the register names it.
- Country indicators (Single Market Scoreboard): **unavailable** — host returns a CloudFront 403 to scripts;
  data.europa.eu only links 2019 HTML/PDF pages; the Eurostat table was discontinued. Not bypassed.

### Opt-outs in directives' recitals (`optouts`) — ok
- Denmark (Protocol No 22) and Ireland (Protocol No 21) are not bound by most justice and home affairs measures
  unless they opt in; each directive says so in its recitals in standard wording ("… is not taking part in the
  adoption of this Directive and is not bound by it"). The source reads the English text of every directive in
  the EUR-Lex snapshot once (again when the matcher changes) and records the countries and the sentences quoted.
  Implementation tables then show "Not bound" instead of "No measures found" for those countries. The Council's
  voting results give the same fact for votes since 2019.
- Ireland can still take part after adoption (Protocol No 21, Article 4); the Commission then confirms it in a
  decision ("The participation of Ireland in Directive (EU) 2024/1346 is confirmed", Commission Decision (EU)
  2024/2087). One Cellar query per run finds such decisions by title; for those directives Ireland is treated as
  bound and the row links the decision (2 directives: 2023/2843 and 2024/1346).
- The generic Denmark/Ireland caveat on a dossier is shown only where neither the recitals nor a Council voting
  result say whether the country took part.

### Council of the EU (`council`) — ok
- The Council's voting-results web pages are behind a browser check (403), and the data.europa.eu dataset
  "Council votes on legislative acts" is marked discontinued (its download returns 404).
- Route used: Cellar lists the Council's official "Voting result" notes (ST documents); each PDF is downloadable
  from `https://data.consilium.europa.eu/doc/document/ST-NNNNN-YYYY-INIT/EN/pdf`. Page 1 (text) gives the procedure,
  title, meeting or written procedure and statements; the per-country table in the annex is a raster image with a
  fixed template, read deterministically (`pdftoppm` + pixel classification, no OCR). Every one of the slots must
  classify, otherwise positions are left empty ("fail closed"). The voting rule requires two agreeing signals, and
  the sheet's printed result is cross-checked against QMV arithmetic (0 contradictions).
- 720 votes 2019-01 → 2026-10; 717 with positions (672 QMV, 43 unanimity, 5 unknown). Verified against the
  rendered sheets: AI Act (ST 10199/24, 27 in favour), Copyright Directive 2019 (6 against, 3 abstentions),
  Eurodac 2024 (DK/IE not participating) and random samples.
- QMV population figures per year from the Council decisions amending Annex III of its Rules of Procedure
  (CELEX 32018D2076, 32019D2209, 32020D2030, 32021D2320, 32022D2518, 32023D2827, 32024D3231, 32025D2427).
- "Not participating" (opt-outs, e.g. DK/IE in justice and home affairs) is kept distinct from abstention.

### Legislative Train (`train`) — ok
- 1,492 files across the 2014–19, 2019–24 and 2024–29 Commission terms; 663 carry procedure references. Statuses
  verbatim. "Blocked" is the Train's own classification (no progress by a co-legislator for at least nine
  months); 35 Blocked files name the blocking institution(s). The Train updates monthly and can lag recorded
  facts, so EP/EUR-Lex records take precedence.

### Licences
- EP open data: CC BY 4.0 (stated by the EP Open Data Portal).
- EUR-Lex / Cellar: reuse authorised with acknowledgement ("© European Union, https://eur-lex.europa.eu") under the
  EUR-Lex legal notice and Commission Decision 2011/833/EU. The live notice page is bot-protected for scripts and
  should be re-checked manually before any change of attribution text.
- Commission infringement register: Commission reuse policy (Decision 2011/833/EU), "© European Union".
- Council documents: reuse permitted with acknowledgement of the source ("© European Union", Council of the EU),
  per the Council's copyright notice.
