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
- Two party records, corporate bodies 5500 (FR) and 5719 (HR), are labelled "-" in all 24 languages: the site
  shows "Party name not recorded" for them and leaves them out of the parties list and search. Party records of
  the same name and country are told apart in search by their term, and when they share a term (Azione 6103 and
  6478, both 2019–2024) by the period of each record (`temporal`: 20 November 2019 – 8 November 2022 and
  6 December 2023 – 15 July 2024). Search subtitles name the former member state as "United Kingdom", as the MEP
  and party pages do.

### EP plenary votes (`ep_votes`) — ok
- Fields are documented in `pipeline/sources/ep_votes.py`; the points below are where we read more than one
  field of the record.
- Counts: the API leaves out a count of zero (decision 162156 of 12 Dec 2023 has 604 for, 5 abstentions and no
  "against"; the minutes print 604 | 0 | 5). When a decision publishes any count, a missing one is the number of
  MEPs listed in that position, i.e. 0; a decision without counts (show of hands) keeps all three empty.
- Procedure links keep the letter of a split procedure's reference (`2021/0211A(COD)`), and document numbers
  are read with any hyphen-like character (`A9‑0256/2020`, U+2011). A vote item that names neither procedure
  nor document (a secret ballot) is linked through the report in its structured label.
- Before 2024 a decision is the vote on the provisional agreement (kind `final`) when its row in the sitting's
  minutes has the Subject "Provisional agreement", even if the label gives only the amendment number
  (European Climate Law, 24 Jun 2021, "Am 176"). A final vote is a negotiating mandate when the procedure's
  referral back for negotiations is recorded on the vote's day or up to two days later (remote voting in
  2020–21 recorded it the next day).
- Minutes: the remote-voting sittings of April–November 2020 have their "Results of votes" in French only
  (`PV-9-2020-05-13-VOT-FNL_fr.xml`); outcomes, documents and procedure symbols are read from them, block
  titles are not (the subject must be English).
- Subject: the vote item title (2024+) or the block title of the English minutes, else the title of the vote's
  only linked procedure (`process_title` of the EP API procedure, kept in `_state.json` `proc_titles`): the vote
  labelled "A9-0027/2020 - Tomáš Zdechovský - Resolution" is about "2018 discharge: General budget of the EU -
  Court of Justice" (2019/2058(DEC)). Vote pages show the subject without Parliament's procedure symbol and give the symbol in
  words, as the minutes' "Keys to symbols used" explain it (`***I` = ordinary legislative procedure, first
  reading; `*` consultation; `***` consent).
- Wrong document numbers in labels: a label naming a document whose block in the minutes has neither the
  label's title nor its rapporteur, and none of the decision's counts, is linked through the one block that
  records the counts and fits the label (130628 and 130862, Eurofound 2019 discharge, labelled with the GNSS
  Agency report A9-0074/2021; minutes "Report: Joachim Stanisław Brudziński (A9-0094/2021)").
- Kinds: a whole-text marker ("Single vote", or a mistaken "Commission proposal") on an own-initiative, topical
  or legislative-initiative procedure (INI, RSP, INL) without a legislative procedure symbol is the vote on the
  resolution, not a final vote on a law; a proposal for a decision stays a decision. A "Recommendation for a
  decision" to raise no objections to a delegated act or measure (Rule 111(6) of the Rules of Procedure, 9th
  term) has kind_detail `no_objection`: it is decided by a majority of the votes cast ("it shall be put to the
  vote"; only the objection itself needs a majority of component Members, Rule 111(5) and Art. 290(2) TFEU), and
  its adoption makes any later objection inadmissible.
- Outcome `derived`: also when the counts settle the result under a component-Members rule (votes for above half
  the statutory seats, or at most half of the MEPs who voted) or, with no established rule, under every rule
  Parliament applies (two thirds of the votes cast and a majority of the seats; or fewer for than against).
  Early termination of Eva Kaili's term as Vice-President (151201, 625-1-2) is recorded only in the main minutes
  (PV-9-2022-12-13, item 8.1, "Approved by RCV (625 in favour, 1 against, 2 abstentions)"), not in the "Results
  of votes" annex, and is derived.
- Margins under component-Member rules are not given for votes from 2 July 2019 to 12 January 2020: the
  membership records date three Spanish mandates from 2 July 2019 that Parliament took note of only on 13 January
  2020 "with effect from 2 July 2019" (minutes PV-9-2020-01-13, item 6), while it counted 747 Members on 16 July
  2019 (press release 20190711IPR56824) against the records' 751 (vote 109166).
- Titles (build): same-day votes that would share a title get the text they are on ("motion B9-0069/2020",
  "joint motion RC-B9-0073/2020"), else their amendment numbers, else the label's last part. Parliament's fixed
  French procedural terms in a label used as title and in "Text voted on" are given in Parliament's English
  wording ("Proposition de résolution (ensemble du texte)" → "Motion for a resolution (text as a whole)");
  other French text keeps `lang="fr"`.
- Timeline (build): Parliament's first-reading decision recorded only as "took its decision" is titled as a
  rejection when every final vote of that day linked to the file was officially rejected (2025/0429(COD),
  26 Mar 2026, OEIL: "the European Parliament rejected the proposal"). A rejected final vote on a file whose
  OEIL record names a later final act carries a note saying the procedure continued.
- Margin (`analysis/ep_margin.py`, build): computed only for an adopted or rejected outcome under an established
  majority rule. Its label is about the majority that vote needed, "Majority reached: N votes more than needed" /
  "Majority not reached: N votes short", never about a law passing (a final vote can be a consultation opinion or
  a position the Council has not yet agreed to). `python -m pipeline validate` fails a build in which a margin
  stands next to another outcome or on the other side of the threshold. A vote is *close* when the distance is at
  most 5% of the votes cast for and against (`CLOSE_RELATIVE` in `build.py` and `src/features/votes/labels.ts`).
- `outcome_basis` `derived` (calculated from the counts where they settle the result: under the votes-cast or
  component-Members rule that applies, or under every rule when none is known) is shown as such wherever the
  outcome is: vote pages, the /votes list, dossier vote cards and the home lists.
- Home lists (`build_home`): *Close votes* are the most recent close final votes (no time window: one final vote
  in the 12 months to October 2026 was close). *Rejected* holds final votes on a whole text that were rejected
  and adopted motions to reject the proposal or the Council's position, each with the file's decision as its
  timeline words it and what followed (adopted later, withdrawn; a consultation opinion is not binding), then
  files recorded as rejected without such a vote. Rejected objections and motions of censure are not listed: they
  leave the Commission measure or the Commission in place.
- Feeds and activity: a final vote not already a file's milestone is titled by Parliament's step when the file is
  a consultation or consent procedure (CNS, APP, or the "*" / "***" symbol ending the vote's published subject):
  "Parliament delivered its opinion" / "a negative opinion", "Parliament gave its consent" / "did not give its
  consent", rather than "Parliament adopted".
- `subject` in `votes/index.json`: the vote's published subject (vote item or minutes block title, without its
  procedure symbol), only when the display title and Parliament's label lack some of its words; the vote search
  matches it (vote 195775, titled after the act it amends, has the subject "Temporary derogation from the ePrivacy
  directive"). `votes/<id>.json` keeps the full published subject.

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
  A notice is ignored when the procedure went on to adopt the act (a later Council adoption, signature or
  publication, an OEIL "Procedure completed" stage or final act, or a linked act: 2010/0095(COD) has a notice
  of 7 March 2015 and produced Directive (EU) 2015/1535). A replacement notice, or a notice where OEIL dates
  its own withdrawal before the proposal (2018/0213(COD)), takes the place of OEIL's withdrawal event.
  `validate` fails a build in which a withdrawn file has an act or adoption steps after the withdrawal, or is
  withdrawn before its proposal.
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

### Procedure steps as shown (`build.py` `procedure_event`, `proposal_date`, `adoption_dates`)
- Who acted is read from the documents: OEIL lists a consent file's Commission proposal as a "Preparatory
  document" (shown as "Commission published its proposal", a proposal step); a text cited as T9-0129/2022 is
  Parliament's adopted text; a numbered Council document (09941/2017) is the Council's text submitted to
  Parliament; N-numbered documents are attributed as OEIL's documentation gateway lists them
  (`OEIL_PROPOSAL_AUTHORS`), otherwise to the Legislative Observatory's record.
- Consent files: Parliament's decision in an interim or accompanying report (R/M procedure) and any earlier
  plenary decision in a file that has a later one (2013/0255(APP), 2013/0361(APP)) are interim resolutions, not
  its consent. Statutes adopted by Parliament with the Council's consent (Articles 223(2) and 228(4) TFEU,
  `status.PARLIAMENT_ADOPTS`, or an act titled "of the European Parliament of …") show the Council's consent and
  Parliament's adoption. Consultation and consent files show no readings.
- "Proposed" (`started`): the earliest recorded proposal or COM document. "Adopted": Parliament's
  second-reading approval of the Council's position (Art. 294(7)(a) TFEU), else the date of the Council's
  adopted voting result on the act, else OEIL's Council step; a Council act (consultation, consent) is dated
  by its voting result, else by the act itself, which bears its adoption date (OEIL's Council date is then
  shown on the act's date, with OEIL's date in the detail); never after publication.
- Negotiations: "Negotiations with the Council" runs from the first recorded trilogue after Parliament's
  mandate; mandate decisions (not their announcement in plenary) are key timeline steps and activity items. A
  first-reading vote followed by a referral back to committee in the same vote item (a "mandate" vote) is
  shown as "Parliament voted amendments to the proposal" and a mandate, also when the EP API already records
  a first-reading position and OEIL has not recorded the referral (2025/0393(COD)).
- Rejection by Parliament: a final vote officially recorded as rejected, or an adopted motion to reject the
  proposal (2023/0413(COD), vote 179804), unless OEIL shows the file past Parliament's first reading.
- OEIL has no procedure file for split parents (e.g. 2016/0224(COD)) or for 2020/3521(COD); those pages carry no
  OEIL link (`oeil_url` null). Regulation 2015/2422 (2011/0901(COD) in EUR-Lex) links OEIL's 2011/0901B(COD).

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
- Statements: the annex heading alone ("STATEMENTS") is not listed as a statement.
- Build-time checks against the procedure record (`vote_on_note` says when one applies): a note headed
  "Adoption of the legislative act" whose reference document is the Council's first-reading position (same
  number as OEIL's "Council position published"), followed by Parliament's second-reading decision, adopted
  that position (ST 12604/20, 12592/20, 13733/20); a note naming no item, dated the day OEIL records the
  Council's adoption of the act, is the adoption of the act. A vote citing the reference of a split procedure
  (2021/0211(COD)) is listed on the part holding an act of the type voted on (2021/0211A for the directive);
  the parent keeps a pointer (`council_votes_in_parts`).
- QMV threshold: when it is not established whether the Council acted on a Commission proposal (an ordinary
  procedure opened by OEIL's "Legislative proposal published" without another initiator's document counts as
  one), both numbers of Member States are given (`states_required` 55%, `states_required_alt` 72%).

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
