# Data sources — audit

Status as of the first sprint (2026-10-22). "Reachable" means reachable anonymously from a script (the
pipeline runs in CI without credentials). Details are refined from each ingestion module's findings.

| Source | Interface | Reachable | Used for | Notes |
| --- | --- | --- | --- | --- |
| EP Open Data API v2 `data.europarl.europa.eu/api/v2` | JSON-LD REST | ✅ | MEPs, groups, national parties, committees, procedures + events, plenary decisions **with individual roll-call ballots** | Anonymous; paginated (`offset`/`limit`); stable ELI-style ids (`eli/dl/proc/2021-0106`, `person/197443`) |
| EP Legislative Observatory (OEIL) | HTML | ✅ | Human links to procedure files | Not scraped: the EP API carries the same procedure data |
| EP Legislative Train Schedule | HTML | ✅ | Official status of major files incl. "blocked" monitoring | No API; controlled crawl of theme + file pages |
| EP `doceo` documents (RCV XML/PDF) | HTML/XML | ⚠️ 202 bot challenge | — | Roll-calls come from the API instead |
| Cellar SPARQL `publications.europa.eu/webapi/rdf/sparql` | SPARQL 1.1 | ✅ | Legal acts (CELEX, ELI, dates incl. phased entry-into-force/application, procedure links, amendments), national implementing measures | Batched queries; CDM ontology |
| EUR-Lex website | HTML | ⚠️ 202 bot challenge | Human links only | Not scraped |
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
- 1,248 legislative acts 2014+ (808 regulations, 302 directives, 138 decisions), all linked to a procedure
  (1,106 COD, 111 CNS, 34 APP). Non-legislative (NLE, ~2,490) and budgetary acts are out of scope for v1.
- Procedure link: dossier with `procedure_code_interinstitutional_reference_procedure` via
  `dossier_produces_resource_legal`, `resource_legal_produced_by_dossier`, or the adopted proposal's
  `work_part_of_dossier`. References whose type contradicts the dossier's own type are not linked.
- Dates: OJ publication (`official-journal-act_date_publication`, else the OJ issue date); entry into force is the
  value tagged EV (else PE) of `resource_legal_date_entry-into-force` — the property mixes EV/PE/MA dates, and in
  166 acts the earliest value is not the entry into force. Other dates are kept as "further application dates"
  without claiming which provisions they concern. Placeholder `1001-01-01` dropped. Transposition:
  `directive_date_transposition`.
- Known gaps: 352 acts without signature date, 24 directives without transposition date, only explicit whole-act
  repeals, acts whose procedure is only in free text are unlinked.

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
