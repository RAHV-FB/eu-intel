# Data sources — audit

Status as of the first sprint (2026-10-22). "Reachable" means reachable anonymously from a script (the
pipeline runs in CI without credentials). Details are refined from each ingestion module's findings.

| Source | Interface | Reachable | Used for | Notes |
| --- | --- | --- | --- | --- |
| EP Open Data API v2 `data.europarl.europa.eu/api/v2` | JSON-LD REST | ✅ | MEPs, groups, national parties, committees, procedures + events, plenary decisions **with individual roll-call ballots** | Anonymous; paginated (`offset`/`limit`); stable ELI-style ids (`eli/dl/proc/2021-0106`, `person/197443`) |
| EP Legislative Observatory (OEIL) | HTML | ✅ | Status label, subjects, COM references, Commission/Council key events, final-act CELEX, type of act proposed | One procedure-file page per procedure, at most 4 at a time; requests start at least 0.25 s apart, usually about 0.5–0.7 s; fills what the EP API does not carry |
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

- European Parliament: "© European Union – Source: European Parliament"; CC BY 4.0 for the Open Data Portal's
  datasets of MEPs, procedures and results of votes (2024 and 2025), the European Parliament legal notice for its
  other data and web pages (details under "Licences" below).
- EUR-Lex / Publications Office: reuse authorised under Commission Decision 2011/833/EU, with attribution.
- Council and Commission websites: reuse authorised with acknowledgement of the source, unless stated otherwise.

The site footer and About page credit each source. MEP portraits are not used (avoids hot-linking third-party
images that would expose visitors' IP addresses to another host). "Data refreshed" (`meta.json` `snapshot_at`) is
the latest retrieval among the sources the About page lists (`SOURCES` in `build.py`, one per manifest entry), so
a reader can trace it to one of them.

## Update frequency and refresh

EP data changes after each plenary session and committee meeting; Cellar is updated daily; the Legislative Train
monthly. A weekly scheduled refresh is sufficient for v1 and stays well within the free GitHub Actions allowance.
Scheduled runs are best-effort; the site shows the real retrieval timestamp per source. The weekly run is
incremental for EP procedures, EP votes and the Legislative Train; a full refresh re-reads every stored record
(docs/DEPLOYMENT.md, "What a weekly run re-reads").

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
- An MEP's membership data cites the API record it was read from (`source.url`
  `…/api/v2/meps/<id>?format=application%2Fld%2Bjson`); `official_url` is the profile page on the EP website.
- Party pages (`people/parties/<id>.json`): `terms` are the terms the record's memberships fall in (also in
  `parties.json`), `start`/`end` the record's `temporal`. Per MEP, `active` means still in this record and
  sitting; `mep_active` is the MEP's own status (Current MEP / Former MEP on the page), and `now_party` the party
  record a sitting MEP who left this one is in now (open membership), e.g. the 2024–2029 record of the same party
  (5494 → 6848) or a new party (Platforma Obywatelska 6703 → Koalicja Obywatelska 7979: 18 MEPs, most from
  1 December 2025). `same_name` lists the records with the same name and country, `now_parties` the records of
  `now_party` with how many of this record's MEPs sit under each. A record whose `temporal` has ended and has no
  current member shows its period instead of "Current MEPs 0"; otherwise the page counts its current MEPs in this
  record (`members_active`) and, next to them, those listed here who now sit under another record (the sum of
  `now_parties`). `outside_period` lists the memberships Parliament records in the record outside its `temporal`
  (PSD 5320 ends on 15 July 2024, but `/api/v2/meps/124784` lists Dan Nica in it from 16 July 2024 with no end
  date), which the page states as such. Records that share a name and country also differ in their page title,
  by their term (and their period when they share the term).

### EP plenary votes (`ep_votes`) — ok
- Fields are documented in `pipeline/sources/ep_votes.py`; the points below are where we read more than one
  field of the record.
- Counts: the API leaves out a count of zero (decision 162156 of 12 Dec 2023 has 604 for, 5 abstentions and no
  "against"; the minutes print 604 | 0 | 5). When a decision publishes any count, a missing one is the number of
  MEPs listed in that position, i.e. 0; a decision without counts (show of hands) keeps all three empty.
- Procedure links keep the letter of a split procedure's reference (`2021/0211A(COD)`), and document numbers
  are read with any hyphen-like character (`A9‑0256/2020`, U+2011). A vote item that names neither procedure
  nor document (a secret ballot) is linked through the report in its structured label.
- Before 2024, a vote that no vote item, label or document links is linked through the minutes block that
  records it: the one block with a row of the vote's counts that lists a document of its label, has its title or
  rapporteurs, or has the title the label opens with. The block's procedure reference is used ("Proposal for a
  regulation (COM(2020)0826 - C9-0399/2020 - 2020/0362(COD))"), else the procedures of the vote items based on
  its documents ("Report: Véronique Trillet-Lenoir (A9-0247/2021)" → 2020/0322(COD)) when these include the
  label's document or the label names none (the minutes misprint some numbers too). This links the
  urgent-procedure votes labelled only "C9-0399/2020 - Commission proposal" (Brexit contingency, EU Digital COVID
  Certificate), labels with a misprinted year ("Gas storage - C9-0126/2021", minutes "C9-0126/2022") and joint
  motions for resolutions (`RC-B9-…`, through the motions the block lists). Two blocks with the same counts that
  both fit leave the vote unlinked. An English label without a document number takes the one its French label
  gives ("A9-0088/202" / "A9-0088/2020"), and a label without any is linked to the one vote item of the sitting
  whose (French) title is the French label's title ("Règlement modifiant le cadre financier pluriannuel 2014-2020
  - Approbation", 113149, 2020/0055(APP)).
- Before 2024 a decision is the vote on the provisional agreement (kind `final`) when its row in the sitting's
  minutes has the Subject "Provisional agreement", even if the label gives only the amendment number
  (European Climate Law, 24 Jun 2021, "Am 176"); a roll call labelled only with the title of the text takes its
  kind from the Subject of its minutes row (Withdrawal Agreement, 29 Jan 2020: "Consent procedure", `final`).
  A final vote is a negotiating mandate when the procedure's referral back for negotiations is recorded on the
  vote's day or up to two days later (remote voting in 2020–21 recorded it the next day), or, before 2024, when
  the text was adopted and an adopted "Referral (Rule 59(4))" on the same document follows it in the sitting
  (ECDC and cross-border health threats, 15 Sep 2021; EU Digital COVID Certificate, 28 Apr 2021: "Renvoi (article
  59, paragraphe 4 du règlement)"). A rejected text followed by such a referral stays the final vote: under Rule
  59(4) the file then goes back to committee "for reconsideration" (ETS revision, 8 Jun 2022, 144283), and the
  vote's note says so.
- A proposal to reject the Commission proposal or the Council's position that groups table as a numbered
  amendment is a motion with kind_detail `reject_proposal` / `reject_council_position`, not an amendment:
  referenceText "Proposal for rejection" / "Proposal to reject the Council position" / "Rejection", the label
  part "Rejection" / "Rejet" before "Am N", or (old labels ending only in "Am 1") the minutes Subject
  "Rejection" (VIS, 7 Jul 2021). Rules 59(2) and 67(1) of the Rules of Procedure have it voted first, on the whole
  text. The second-reading symbol is also read when printed "*** II" (IPA III, 15 Sep 2021).
- Majority rule: where the Treaties alone do not settle it, the rule Parliament's record states for a whole-text
  vote: the vote item's structured label (2024+, "(Majority of votes cast required)") or the minutes block
  description (before 2024, "(Majority of Parliament’s component Members required)"). Only statements that hold
  for the whole text are read; conditional or mixed ones ("… required to amend or reject the Council position",
  "… + 3/5 of votes cast") leave the rule unknown. A statement that contradicts the rule assumed for the vote
  leaves it unknown, so no margin is shown: the objections under Rule 112 of 25 Nov 2020 on RSP files (125373,
  125374), whose minutes say "(majority of Parliament’s component Members)" where RSP files are given the votes
  cast. A negotiating mandate on an ordinary-procedure file is a first-reading vote (majority of the votes cast)
  also when its item's title carries no procedure symbol (142178, 3 May 2022; the latest sitting's items, first
  published with French titles only).
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
  Agency report A9-0074/2021; minutes "Report: Joachim Stanisław Brudziński (A9-0094/2021)"). An English label
  whose document no minutes block and no vote item of the sitting lists takes the document of its French label
  when the one block with the vote's counts lists that one: the bluefin tuna vote of 28 Apr 2021 (130719),
  English label "A9-0149/2021" (an own-initiative report, 2020/2216(INI)), French label and minutes "A9-0149/2020"
  (2019/0272(COD)); likewise 125904 (16 Dec 2020, "A9-0621/2020" for A9-0261/2020). A number misprinted only in
  the minutes leaves the label's (153312).
- Kinds: a whole-text marker ("Single vote", or a mistaken "Commission proposal") on an own-initiative, topical
  or legislative-initiative procedure (INI, RSP, INL) without a legislative procedure symbol is the vote on the
  resolution, not a final vote on a law; a proposal for a decision stays a decision. A "Recommendation for a
  decision" to raise no objections to a delegated act or measure (Rule 111(6) of the Rules of Procedure, 9th
  term) has kind_detail `no_objection`: it is decided by a majority of the votes cast ("it shall be put to the
  vote"; only the objection itself needs a majority of component Members, Rule 111(5) and Art. 290(2) TFEU), and
  its adoption makes any later objection inadmissible. A label opening "Objection pursuant to Rule …" makes the
  whole-text vote an objection also without a vote item (157978, 12 Sep 2023, GM maize MON 87419).
- Discharge: a final vote on a discharge report's proposal for a decision has kind_detail `grant_discharge`,
  `postpone_discharge` or `refuse_discharge` where Parliament's record says what was proposed: before 2024 the
  minutes heading above the row ("Proposal for a decision to postpone the discharge", "Decision to refuse
  discharge", "Décision d'ajournement de la décharge", "Refusal of discharge") or its Subject ("Proposal for a
  decision to grant discharge"), from 2024 the decision's headingLabel ("Decision to refuse discharge", 179920).
  "Decision on discharge" or "Proposal for a decision" alone says nothing, and the detail is left empty (175931).
  A heading "Decision to postpone discharge" no longer makes the vote procedural (168778, 191886). The vote page
  says what the outcome decided: adopted, discharge was granted, postponed or refused; a rejected proposal to
  postpone or to refuse discharge means, under the Rules of Procedure of the 9th term (Annex V, Article 5(1)(b)
  and 5(2)(b)), that discharge is deemed to have been granted (142787, 4 May 2022, Court of Auditors 2020: "If a
  proposal to postpone discharge fails to secure a majority, discharge shall be deemed to have been granted").
  This is not stated for later terms, whose Rules we have not checked.
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
  OEIL record names a later final act carries a note saying the procedure continued. A decision recorded on a
  day without a vote of the file is linked to its one final vote (second reading: motion to reject the Council's
  position) dated from one day before to two days after it, preferring one whose report the decision lists, with
  a note giving both dates (remote voting: 2020/0331(CNS), vote 6 Jul 2021, decision 7 Jul 2021); a decision
  recording the amendments voted before a referral back ("Parliament voted amendments to the proposal") is linked
  the same way to its mandate vote (2021/0008(COD): vote 15 Sep 2021, decision 16 Sep 2021). On a day with votes, a
  step links the day's final vote, else its mandate vote, else the one vote of the file that day; a motion to
  reject the text that was rejected never decides such a step (2021/0206(COD), 8 Jun 2022). A referral back to
  committee for negotiations ("Parliament sent the file back to committee to negotiate with the Council") is a
  decision of its own, voted after the text (Rule 59(4) of the 9th-term Rules of Procedure: "Parliament decides to
  refer the matter back"; 2025/0524(COD), 13 Nov 2025: 181375 on the text, 181446 "Request for referral back (Rule
  60(4))"); referral votes are not listed, so that step links no vote, and the mandate vote stays on the step that
  records the vote on the text, which is then a key step shown by default (2021/0106(COD), 14 Jun 2023, vote
  156022); a step built from a vote that the procedure record does not show yet links that vote (2026/0325(COD),
  "Parliament voted to open negotiations with the Council", 199592). Parliament's confirmation of a committee's decision to negotiate links the vote on
  that decision, if one was held. A second-reading approval links the motions to reject the Council's position that
  decided it; a decision amending the Council's position links none (its amendments decided it: 2025/0429(COD), 9 Jul
  2026, motion 195775 rejected) and names, on any day, the votes on amendments adopted by a majority of the
  component Members, counting votes, not amendments (one vote may cover "Am 1-243": 2013/0072(COD), 21 Jan 2026),
  since votes on amendments are not listed.
- Final votes (`final_role`, build): what a final vote decides, from the type of its one linked procedure (COD
  legislative, CNS consultation, APP consent, BUD budget, DEC discharge, RSO / REG / ACI Parliament's own
  decisions), else from the symbol ending its subject (`*` consultation, `***` consent, `***I`–`***III`
  legislative; NLE files are either), else, for an NLE file, from its label naming the consent procedure ("A9-0199/
  2020 - Iuliu Winkler - Consent procedure", "… - procédure d'approbation": the 2020 votes recorded only in French
  minutes have subjects without a symbol), and "Election of the Commission" (Art. 17(7) TEU). Consent,
  consultation, discharge and the election of the Commission get their own label ("Vote on consent", "Vote on
  Parliament's opinion (consultation)", "Vote on discharge", "Vote of consent on the Commission") and the vote page
  explains what that vote decides; a vote whose role is not established gets the general explanation of a vote on
  a text as a whole, never one about a law. The consultation explanation names no institution as the one deciding
  (the Ombudsman adopts its implementing provisions after consulting Parliament, Regulation (EU, Euratom)
  2021/1163, Article 18: vote 152545). A discharge vote whose record says what was proposed is labelled and
  explained by that (see Discharge above); otherwise its note says that the record does not tell whether the
  proposed decision grants, postpones or refuses discharge, and, for a rejection, that its effect depends on that.
- Margin (`analysis/ep_margin.py`, build): computed only for an adopted or rejected outcome under an established
  majority rule. Its label is about the majority that vote needed, "Majority reached: N votes more than needed" /
  "Majority not reached: N votes short", never about a law passing (a final vote can be a consultation opinion or
  a position the Council has not yet agreed to). `python -m pipeline validate` (run after the build in CI, the
  deploy and the refresh, with `--built`) fails a build in which a margin stands next to another outcome or on the
  other side of the threshold. A vote is *close* when the distance is at most 5% of the votes cast for and against
  (`CLOSE_RELATIVE` in `build.py` and `src/features/votes/labels.ts`).
- `outcome_basis` `derived` (calculated from the counts where they settle the result: under the votes-cast or
  component-Members rule that applies, or under every rule when none is known) is shown as such wherever the
  outcome is: vote pages, the /votes list, dossier vote cards and the home lists.
- Home lists (`build_home`): *Close votes* are the most recent close final votes (no time window: one final vote
  in the 12 months to October 2026 was close). *Rejected* holds final votes on a whole text that were rejected
  and adopted motions to reject the proposal or the Council's position, each with the file's decision as its
  timeline words it and what followed (adopted later, withdrawn; a consultation opinion is not binding), then
  files recorded as rejected without such a vote. Rejected objections and motions of censure are not listed: they
  leave the Commission measure or the Commission in place. Neither list holds decisions on discharge (procedure
  type DEC, or titled "Discharge 2020: …" / "2019 Discharge: …"; `activity.is_discharge_vote`): a discharge vote
  grants, postpones or refuses discharge, and its "adopted" or "rejected" does not say which without the proposal
  voted on (vote 142787 rejected a proposal to postpone, so discharge was granted; 149084 adopted a refusal).
  *Under discussion* badges name the procedure in plain words ("Ordinary procedure", "Consultation procedure",
  "Consent procedure", else the procedure's type label), not its code; a bare "Consent" next to a file not yet
  adopted could read as consent given. The lists' descriptions say that decisions on budget discharge (for the
  EU's general budget and for the budgets of EU agencies and bodies: 149084, "Discharge 2020: European Border
  and Coast Guard Agency") are not listed. A featured card's `latest_note` names the amending acts EUR-Lex
  lists for the file's act that are not in our EUR-Lex data (so the timeline cannot date them): the latest step
  shown may be older than they are (2021/0366(COD): Delegated Regulation 2026/2102).
- Feeds and activity: a final vote not already a file's milestone is titled by Parliament's step when the file is
  a consultation or consent procedure (CNS, APP, or the "*" / "***" symbol ending the vote's published subject):
  "Parliament delivered its opinion" / "a negative opinion", "Parliament gave its consent" / "did not give its
  consent", rather than "Parliament adopted". A motion to reject says what became of the text, then names the
  file: "Parliament did not reject the Commission proposal: <file>" for a rejected motion (vote 199567), "Parliament
  rejected the Commission proposal" for an adopted one (179804), and likewise for the Council's position at second
  reading (195807). A discharge decision is "Parliament voted on a discharge decision: …". A consent milestone
  titled "Parliament voted on consent" says "Parliament gave its consent" (or "did not give …") when the final
  vote linked to it records the outcome officially (published or in the minutes; 2025/0313(APP), vote 197472).
  A Council vote is titled by its list title (`display_title`, below); an item with no page on the site links to
  its official document instead of the site root.
- `subject` in `votes/index.json`: the vote's published subject (vote item or minutes block title, without its
  procedure symbol), only when the display title and Parliament's label lack some of its words; the vote search
  matches it (vote 195775, titled after the act it amends, has the subject "Temporary derogation from the ePrivacy
  directive"). `votes/<id>.json` keeps the full published subject.
- `title` in `votes/index.json`: Parliament's label with session document numbers written with an ASCII hyphen,
  as officially numbered (label "A10–0049/2025 – Gilles Boyer – …" of vote 175067), so the vote search finds the
  number as typed; the search also reads a number typed with another dash as the official one. `votes/<id>.json`
  keeps the label as published.

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
  the `comment_on_date` annotation) are shown as "some provisions apply from"; so is the entry-into-force date
  when Cellar marks it that way too (`partial_on_entry_into_force`, 78 acts: DMA, Art. 54, "Article 3(6) and (7)
  and Articles 40, 46, 47, 48, 49 and 50 shall apply from 1 November 2022", its entry into force), in the "When it
  applies" box and the in-force status. When EUR-Lex records no other date for such an act (6 acts, e.g. Regulation
  (EU) 2025/12, whose Art. 46 ties the rest to "the date two years from the date on which the router starts
  operations, as determined by the Commission"), both say that EUR-Lex records no date for the other provisions.
  A value of `1001-01-01` (comment
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
  validity, with the acts it names) is kept as `validity_notes`. The end of validity is usually the act's last day of
  validity (Directive 95/46/EC: 24 May 2018, repealed by the GDPR with effect from 25 May 2018): an act is "No longer
  in force" from the day after, which is the date its status gives. The date from which a repeal takes effect is the
  `start_of_validity` annotation on the repeal link (`repeal_dates`, 60 acts; whole or `partial`); where Cellar
  records it, the status gives that date. In 89 of the 93 no-longer-in-force acts with such a date (repeal or
  implicit-repeal links, checked live on 23 October 2026) it is the day after the end of validity; for Regulations
  543/2014 and 252/2014 it is the end of validity itself (Regulation (EU) 2015/2219, Art. 40(1): "with effect from
  1 July 2016"; the codification 2015/754 repeals Regulation 774/94 with its amendments, 252/2014 among them,
  Art. 11 and Annex I, from its entry into force on 8 June 2015), and the status says "EUR-Lex gives 1 July 2016 as
  the end of its validity and records it as repealed by Regulation (EU) 2015/2219 with effect from 1 July 2016". A
  repeal in stages, with later dates on the axioms of some provisions (Directive 2014/61/EU: repealed by Regulation
  (EU) 2024/1309 with effect from 12 November 2025, Art. 18(2) keeping some provisions "in force until" 12 February
  and 12 May 2026; Regulation 517/2014 and Regulation (EU) 2024/573, Art. 35), gives the repeal's date and the end
  of validity and no "since" date: the texts do not settle the day.
  Only the repeal links are read (implicit-repeal links are not fetched; their dates matched the day after in all
  48 acts). A no-longer-in-force act names the repealing act
  (by its number, linked to its file or to EUR-Lex): the whole-act repeal link, else the act in that annotation.
  When the repealing act's official title says "(codification)" or "(recast)" and it is later than the act, the
  status says that the rules continue in it. An end of validity earlier than the act itself (Regulation 1377/2014:
  31 December 2013, "Implicitly repealed by" the own-resources recast 609/2014) is stated as such, not as a plain
  end date. Dates the act records for after its end of validity are marked and are not its latest development
  (Regulation 2024/2822: validity ended 30 June 2026, some provisions recorded to apply from 1 July 2026). An
  in-force act with an end of validity still ahead says so, with the repealing act and the date from which it repeals
  the act if those are recorded (AMLD4: Directive (EU) 2024/1640, with effect from 10 July 2027).
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
  next step speaks of "the Member States bound by the directive" (Art. 288 TFEU: not those it is not addressed
  to, Directive (EU) 2016/1629, Art. 40; nor Denmark or Ireland under a Treaty opt-out). Where the directive's own
  text gives some Member States more time or exempts them, the next step adds "except as its text provides" and
  says how (`exceptions` in the curated file, checked against the text; also the detail of the deadline's
  timeline step): Directive (EU) 2016/798, Art. 33(2) and (2a), extensions to 16 June 2020 and 31 October 2020,
  and Art. 33(4), Cyprus and Malta while they have no rail system; Directive (EU) 2016/797, Art. 57(2), (2a) and
  (5); Directive (EU) 2017/2397, Art. 39(2) to (4); Directive (EU) 2021/1233, Art. 2(1). The site's pages put a
  deadline that has passed by the visitor's date in the build's past wording (src/lib/format.ts). The
  next step of a directive also names what the directives that have since amended it still require: the deadline
  that covers their changes to it, as their transposition article sets it (`amends` in the curated file;
  Directive (EU) 2026/470, Art. 5(1): Article 3, which amends the CSRD, by 19 Mar 2027; Article 4, which amends the
  CSDDD, by 26 Jul 2028), else the amending directive's deadline only when it records a single one; an amending
  directive with several deadlines and no such check is named without dates. An amending directive that also
  repeals the directive names the repeal instead (AMLD4: Directive (EU) 2024/1640 repeals it with effect from
  10 Jul 2027). A transposition deadline has passed only once its day is over: measures are due "by" it
  (Product Liability Directive (EU) 2024/2853, Art. 22(1): "... necessary to comply with this Directive by
  9 December 2026"), so the next step says it has passed from the next day; an entry into force or a date from
  which provisions apply has come on its day. The site restates these dates on the visitor's date by the same
  rules (`src/lib/format.ts`). A build run on a deadline's day still counts it as passed in `pipeline/build.py`:
  in the timeline (state "done", title "(passed)"), which the dossier page restates on the visitor's date, in
  "Coming up", which then lacks it, and for an amending directive's deadline, which the next step then leaves out.
- Withdrawals and replacements: Cellar procedure events WDW_byCOM / RPL_byCOM (`procedure_notices.json`, 272
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
  Cellar gives the application date or the other act's date). Dates a corrigendum set, which the text as first
  published does not give, cite the corrigendum (AMMR, Regulation (EU) 2024/1351, Art. 85: "It shall apply from
  1 July 2026" as published, 12 June 2026 after the corrigendum OJ L, 2025/90929; also Regulations (EU) 2024/1347,
  2024/1359, 2024/1252 and 2022/2560); corrigenda are otherwise not read. An entry with a reason only explains
  recorded dates (Directives (EU) 2016/797 and 2016/798: 31 October 2020, the optional extension added by Directive
  (EU) 2020/700). A date set by an amending act cites that act in
  the timeline, and the amending act's page lists the dates it set (`dates_set_for`); the status sentence says
  that the act's text, not EUR-Lex, sets the later dates. A checked date on the entry-into-force day is named in
  the entry-into-force event. The snapshot keeps the source values; `validate` warns about application dates a
  year or more before the act, and about an entry into force before the act's adoption (or before a
  regulation's publication).
- Timeline: an act of the European Parliament and of the Council (by the act's own title, not one it names) is
  signed by both Presidents (Art. 297(1) TFEU): its signature is shown once, as "Signed by the Presidents of
  Parliament and Council" (actor `EP and Council`), on the act's signature date (else the date in its title),
  in place of the EP's or OEIL's "Final act signed", which can be a week off (2017/0329(COD): 11 April 2018,
  before the Council adopted the act; Directive (EU) 2018/597 of 18 April 2018). Without such an act in our data
  the EP's record is shown as it is ("Final act signed", actor `EP`, on the EP's date), since that date is not
  established as the date both Presidents signed (9 files on 23 October 2026, e.g. 2016/0397(COD)). A Council
  act is signed on the day of its adoption, which the Council's own step records.
- Related files: an amending, amended, repealing or repealed act is named by its number (from its official
  title, e.g. "Directive (EU) 2025/794"; for an act outside the snapshot from its CELEX id, 2015 onwards and
  directives from 1999, e.g. "Regulation 2026/2102"), followed by its file's short title when it has one; an
  act this file amends or repeals, or that repeals it, by its file's title too, unless that is an "Amending …"
  title. Cellar records two titles without the space after the act type ("Directive2014/63/EU of the European
  Parliament …", "Regulation(EU) 2022/870 …"); their numbers are read as if it were there ("Directive 2014/63/EU").
- Search index (`search.json`): a file's keywords (`x`) hold its procedure reference and number, its acts' CELEX
  ids and numbers, its COM references and the types of its acts as EUR-Lex records them (`act_type`:
  "regulation", "directive", "decision"), so that "whistleblower directive" finds Directive (EU) 2019/1937.
- Partial repeals: a repeal link that every Cellar annotation limits to a provision or marks as partial (role
  AP) is kept apart (`partly_repeals`, `partly_repealed_by`: 19 links on 13 acts, e.g. Decision 2014/335/EU,
  Euratom, partly repealed by Decision (EU, Euratom) 2020/2053, whose Art. 11(1) reads "Subject to paragraph 2,
  Decision 2014/335/EU, Euratom is repealed"). It is listed with the act and in the related files as EUR-Lex's
  classification ("Partly repealed by (EUR-Lex)", "Partly repeals (EUR-Lex)"): the repealing act's text need not
  use the word (Decision (EU) 2024/867 has no repeal article; its Art. 6 reads "Decision (EU) 2020/1531 remains
  applicable to the extent referred to in Article 5(2)"). An in-force act's status names it, with the date from
  which Cellar records it (`repeal_dates`: Decision 2014/335/EU, Euratom, with effect from 1 January 2021, the date
  from which Decision 2020/2053 applies, Art. 12); what remains of Decision 2014/335/EU, Euratom (Art. 11(2) of
  Decision 2020/2053: Articles 2, 4 and 5, for the calculation of revenue and of the United Kingdom correction for
  earlier years) is a checked note in `data/curated/act_dates.yaml`. A partial repeal never makes an act "no
  longer in force", which follows EUR-Lex's in-force flag and end of validity.
- Known gaps (snapshot of 23 October 2026): 372 of 1,269 acts without signature date, 24 of 303 directives without
  transposition date, implicit repeals are used only from the end-of-validity annotation, partial ends of validity
  are described only for decisions that take effect on notification, acts whose procedure is only in free text are
  unlinked. The timeline does not list partial repeals.

### Procedure steps as shown (`build.py` `procedure_event`, `proposal_date`, `adoption_dates`)
- Who acted is read from the documents: OEIL lists a consent file's Commission proposal as a "Preparatory document"
  (shown as "Commission published its proposal", a proposal step); a text cited as T9-0129/2022 is Parliament's
  adopted text; a numbered Council document (09941/2017) is the Council's text submitted to Parliament, except in
  an ordinary procedure, which the Council does not initiate: there it is the initiative of Member States or the
  recommendation of the ECB (Art. 294(15) TFEU), which our record does not name, so the step is shown as
  "Legislative proposal published (as recorded by the Legislative Observatory)" (2010/0817(COD), 09288/2010, OEIL
  "Initiative Belgium, Bulgaria, …"; 2013/0812(COD); 2017/0810(COD)). In a non-legislative file (NLE) the Council's
  text is its request for Parliament's consent or opinion, not the proposal it acts on: it is not a proposal step
  and does not date the proposal (2008/0027(NLE), 13395/2014; Council Decision (EU) 2016/1218 "Having regard to the
  proposal from the European Commission", which OEIL does not list, so the file's "Proposed" date is not recorded).
  N-numbered documents are attributed as OEIL's documentation gateway lists them (`OEIL_PROPOSAL_AUTHORS`),
  otherwise to the Legislative Observatory's record. A proposal that OEIL's gateway of other institutions lists
  under the Court of Justice ("CJEC | Legislative proposal | 07307/2022", 2022/0906(COD)) is the Court's request
  (Art. 281 TFEU), not a Commission proposal. OEIL prints some references as plain text next to a EUR-Lex flag link
  ("COM(2018)0825", 2018/0417(CNS)); they are read like linked ones, so every recorded proposal step carries its
  document.
- Consent files: Parliament's decision in an interim or accompanying report (R/M procedure) and any earlier
  plenary decision in a file that has a later one (2013/0255(APP), 2013/0361(APP)) are interim resolutions, not
  its consent. Statutes adopted by Parliament with the Council's consent (Articles 223(2) and 228(4) TFEU,
  `status.PARLIAMENT_ADOPTS`, or an act titled "of the European Parliament of …") show the Council's consent and
  Parliament's adoption. Consultation and consent files show no readings. The status of a consent file says
  "Parliament gave its consent" (or "Consent refused by Parliament") when the final votes linked to the file on
  the day of Parliament's decision have that officially recorded outcome (decision or minutes): 2025/0313(APP),
  vote 197472 of 6 October 2026, adopted 462-121-75. Otherwise it says only that Parliament voted on consent. The
  timeline step of that day says the same ("Parliament gave its consent", "Parliament did not give its consent").
- Parliament's decision at a sitting that the EP API records as amendments (`PLENARY_AMEND`, OEIL "Decision by
  Parliament") is, in a consultation file, Parliament's opinion ("Parliament delivered its opinion", 2018/0173(CNS):
  T8-0415/2018 "Approves the Commission proposal as amended") and, in a consent file, its decision on consent: a
  key step, with the text adopted that OEIL's "Decision by Parliament" of that day cites, and no second opinion
  derived from the day's final vote. It stays "Parliament voted amendments to the proposal" when a referral back
  to committee was voted that day.
- "Proposed" (`started`): the earliest recorded proposal or COM document. "Adopted": Parliament's
  second-reading approval of the Council's position (Art. 294(7)(a) TFEU), else the date of the Council's
  adopted voting result on the act, else OEIL's Council step; a Council act (consultation, consent) is dated
  by its voting result, else by the act itself, which bears its adoption date (OEIL's Council date is then
  shown on the act's date, with OEIL's date in the detail); never after publication.
- The Council's adoption checked against the act's text: every act of the ordinary legislative procedure gives
  the date of the Council's decision in the footnote to "Acting in accordance with the ordinary legislative
  procedure" ("… and decision of the Council of 24 May 2024", Directive (EU) 2024/1760). That is the date as the
  act records it, not the Council's own record of its vote, and the two can differ (Regulation (EU) 2018/1807:
  "decision of the Council of 6 November 2018"; the Council's voting result ST 14173/18 is of 9 November 2018).
  The Council's voting result therefore comes first; the footnote is used where we have none, in place of OEIL's
  Council step; OEIL's step comes last. Where the footnote differs from the date we have,
  `data/curated/council_dates.yaml` gives it with the footnote quoted; the build then dates OEIL's Council step
  (timeline, status, "Adopted", with OEIL's date in the detail and the act linked) by it, and treats OEIL's other
  Council adoption steps of the file within 92 days as the same decision, merged into that step (2014/0174(COD):
  OEIL 13 July and 6 October 2015, "decision of the Council of 18 September 2015"). An entry names a Council
  voting result only when its voting sheet's "Sitting date" is the footnote's day: a note for a meeting held over
  several days gives the range and is otherwise dated by its first day (ST 10263/24 and ST 10264/24, 23-24 May
  2024, "Sitting date: 24/05/2024"; the sheets of the other 150 such voting results in the snapshot give the date
  shown, and OEIL's date, on another day of the meeting for six of them, would have been wrong). No entry is made
  where the Council's own voting result gives another day than the footnote (2017/0228(COD) keeps 9 November
  2018). Checked on 2026-10-23: the 58 ordinary-procedure acts dated from OEIL alone whose date differs from
  Cellar's Council approval event (`APR_R1_byCONSIL`) or that have none; 35 differ from their text (by up to six
  weeks: 2015/0283(COD), OEIL 18 April 2017, "decision of the Council of 29 May 2017"). Acts dated from OEIL whose
  date Cellar confirms (341) were not read. Entries for acts adopted before 2019 rest on the footnote alone (the
  Council source starts in 2019).
- OEIL's "Act adopted by Council after Parliament's 1st reading" in a file where Parliament later decided at
  second reading is not the act's adoption: the second reading was on the Council's first-reading position (Art.
  294(5) to (7) TFEU). It is shown as "Recorded by the Legislative Observatory: …", not as a key step, with that
  explanation (2018/0202(COD): OEIL 21 April 2021, the day the Council's position was published; Regulation (EU)
  2021/691, "position of the Council at first reading of 19 April 2021", Parliament's second reading 27 April
  2021). `validate` fails a build in which an ordinary-procedure file with one act shows Council adoption steps on
  more than one day, or one before Parliament's second-reading decision.
- Negotiations: "Negotiations with the Council" runs from the first recorded trilogue after Parliament's
  mandate; mandate decisions (not their announcement in plenary) are key timeline steps and activity items.
  Parliament holds a mandate from its own decision (a referral back to committee for negotiations, a plenary
  vote, or its confirmation of a committee's decision) or from the announcement in plenary of a committee's
  decision. A committee's decision before Parliament's first reading that is not yet announced (OEIL "Committee
  decision to open interinstitutional negotiations with report adopted in committee", 2025/0255(COD)) is shown
  as "Committee decided to negotiate with the Council", and a decision Parliament rejected (2025/0045(COD),
  22 October 2025) as "Parliament rejected the committee's decision to negotiate"; neither is a mandate, so the
  file stays at the proposal stage. A
  first-reading vote followed by a referral back to committee in the same vote item (a "mandate" vote) is
  shown as "Parliament voted amendments to the proposal" and a mandate, also when the EP API already records
  a first-reading position and OEIL has not recorded the referral (2025/0393(COD)).
- Plenary vote records: the EP API attaches to a procedure the vote items of each sitting (`PLENARY_VOTE`,
  `PLENARY_VOTE_RESULTS`). They are folded into that day's decision of Parliament (its position, opinion, consent,
  or, when there is none, its decision on negotiations or on a referral back). An item may cover every file voted
  at the sitting ("Announcement of voting results" lists 20 documents on 2020/0128(COD), 19 of them of other
  files), so a vote record keeps only the documents the procedure itself references: its own documents and those of
  its other activities, OEIL key events and EP documentation gateway, amendments to them, the item's own minutes
  and verbatim record, every document of an item of this file alone (one document, or this file's documents and
  registered texts such as the Council's position), and the registered text (C) that an EP vote on this file alone
  names in its label, when the item lists one text of that number (2020/0127(COD): vote 117279 "C9-0186/2020 -
  Commission Proposal", C-9-2020-0186; matched by term and number, as vote 128850 prints "C9-0430/2021" for
  C-9-2020-0430 of 2020/0378(COD)). The labels are read from the ep_votes snapshot of the previous fetch (ep_votes
  is fetched after this source). Re-derived offline on 23 October 2026 from the cached EP API and OEIL answers: 34
  records gained such a document on 56 steps (files of 2020–2022), in 2 the documents of one step changed order,
  and every other record came out unchanged. A joint debate keeps the reports of every file debated with this one
  on its own step, but they are not this file's "Key documents" (the asylum files 2016/0132-0225(COD) were debated
  together). A vote record whose only votes on the file that day are on a request for urgent procedure is titled by
  that vote, in the EP's wording ("Parliament approved the request for urgent procedure", "… for an urgent
  decision"), with its counts or "By show of hands", and sourced to the decision; the day's records are shown as
  one step.
- Second reading: the committee steps the EP API records at stage RDG2 are the recommendation for second
  reading ("Parliament committee adopted its recommendation for second reading", "Committee recommendation for
  second reading tabled for the plenary", "Draft recommendation for second reading presented in Parliament
  committee"). OEIL's "Approval in committee of the text agreed at 2nd reading interinstitutional negotiations"
  is shown as the committee's approval of the provisional agreement, without a reading: OEIL also gives it where
  Parliament then concluded at first reading (2016/0357A(COD)).
- Steps of one day are listed in procedural order (proposal, committee, plenary vote, Parliament's decision,
  the Council's, signature, publication, the act's dates), not by record id. A trilogue follows Parliament's
  decisions of the day, since negotiations open on Parliament's mandate (2025/0132(COD), 17 December 2025); a text
  tabled for the plenary follows the committee's approval of it (2024/0071(COD), 16 June 2025); a second-reading
  step follows the Council's first-reading position of the same day (2018/0136(COD), 14 December 2020: ST 14020/20,
  then the referral and the committee's recommendation). `validate` fails a build in which a trilogue or a
  second-reading step is listed before what it follows.
- Rejection by Parliament: a final vote officially recorded as rejected, or an adopted motion to reject the
  proposal (2023/0413(COD), vote 179804), unless OEIL shows the file past Parliament's first reading.
- Type of act (`instrument`): the type of the file's adopted act; for a file without a linked act of a known type,
  the type of act proposed as the OEIL procedure file records it ("Legislative instrument"), else as the procedure
  title names it. On 23 October 2026 OEIL's entry named the same type as the English title of the Commission
  proposal in Cellar for all 257 files without a linked act that have both (2023/0085(COD): "Directive";
  COM(2023) 166, "Proposal for a DIRECTIVE OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL on substantiation and
  communication of explicit environmental claims"). The adopted act can differ (2016/0284(COD) was proposed as a
  regulation and became Directive (EU) 2019/789). The dossier page marks a proposed type "(as proposed)", and the
  explorer's filter says how the type is read and how many files of each type are counted by the type proposed.
  "How it applies in the Member States" describes an adopted file by the type of a linked act only: a file signed
  or adopted with no act linked yet (11 on 23 October 2026) says so and names the type proposed, and a file still
  being decided says what the proposed type would mean "if adopted in that form".
- OEIL has no procedure file for split parents (e.g. 2016/0224(COD)) or for 2020/3521(COD); those pages carry no
  OEIL link (`oeil_url` null). Regulation 2015/2422 (2011/0901(COD) in EUR-Lex) links OEIL's 2011/0901B(COD).
- Timeline sources: a step whose source is an EP Open Data API record (`/api/v2/events/…`, `/procedures/…`:
  RDF/XML or JSON-LD) is labelled "Machine-readable record (EP Open Data API)"; the timeline introduction links
  the readable OEIL procedure file. `SourceRef.published` is the source's own date for a record: Cellar's
  `cmr:lastModificationDate` (shown as "record updated", not the Official Journal date), a Legislative Train
  page's update, a Council register document's date.

### Split procedures and Parliament reports (`build.py` `classify`, related files)
- A split procedure's parent known only from EUR-Lex (10 of the 12, e.g. 2016/0400(COD)) has no title of its own
  in the sources: its page title says what it was split into and `official_title` is null ("Not recorded" on the
  page). Its "Split into" relations carry each part's `ref` and `status_label`, and its status text links the
  parts (`status.named_acts` entries with an empty `celex`: a procedure reference linked to its file).
- An R/M file (Parliament's interim or accompanying report, e.g. 2020/0112R(APP)) links the main procedure in
  its status text and next step the same way; the main file lists it among its related files ("Parliament's
  interim report", "Parliament's report").

### Rapporteurs (`ep_procedures` participants, `build.py` `rapporteur_entries`)
- Roles: rapporteur (EP `RAPPORTEUR`, `_CO`, `_CHAIR`), shadow (`RAPPORTEUR_SHADOW`, `_SHADOW_REPORT`),
  opinion_rapporteur (`RAPPORTEUR_OPINION`, `_CHAIR_OPINION`) and shadow_opinion (`RAPPORTEUR_SHADOW_OPINION`;
  stored as "other" before October 2026). Files without EP API participations (mostly older ones) take them from
  OEIL's key players: the rapporteur of a committee responsible or for opinion, then the shadow rapporteurs.
- `committee`: the committee the participation is `participation_in_name_of`. Where the EP API names none
  ("org/null"), or one that is not among the file's committees, the rapporteur (or rapporteur for an opinion)
  takes the committee OEIL's key players list the MEP under in that role, when they list exactly one: 2021/0240(COD)
  José Manuel Fernandes "org/null" → CONT ("CONT Budgetary Control FERNANDES José Manuel (EPP) 28/10/2021");
  2025/0045(COD) Barry Andrews, the subcommittee DROI → AFET ("AFET Foreign Affairs ANDREWS Barry (Renew)
  10/04/2025"); 2023/0187(CNS) Herbert Dorfmann, FISC → ECON, where the API also lists him for ECON (one entry,
  with the later date). The 8 JURI opinions on the legal basis keep JURI, which OEIL lists too. These three snapshot
  records were re-derived with the module's code over the cached API and OEIL answers (network blocked): the
  previous code reproduces all 1,564 stored records from that cache, and no other record changes.
- `date`: the participation's `activity_date` (the appointment; the latest when an MEP was re-appointed, e.g. in
  a new term). `group`: for OEIL entries, the group OEIL prints after the name ("KONEČNÁ Kateřina (The Left)").
- The group shown is the one held in the role, never the MEP's current group: the MEP's group membership on
  `date`, else OEIL's printed group (PPE → EPP, Verts/ALE → Greens/EFA as for groups; groups before 2019 such as
  ALDE, EFDD or ENF are shown by their code without a group page). Left out when neither establishes it: 152
  of the 12,375 entries (snapshot of 23 October 2026): 144 API entries dated before the group memberships we hold
  (2 July 2019), and 8 whose API date is earlier than the MEP's first group membership (e.g. Johan Nissinen on
  2021/0379(COD), dated 9 December 2021, ECR member from 11 October 2022), so for them `date` is not the
  appointment in a group. Checked against the EP API's own `politicalGroup` on each participation (the cached
  API records of that snapshot): the membership on `date` agrees on all 5,494 entries it covers.
  2021/0106(COD): Konečná The Left, Madison ID, Solís Pérez Renew, as in OEIL.

### National implementation (`implementation`) — partial
- National measures: Cellar `cdm:measure_national_implementing` →
  `measure_national_implementing_implements_resource_legal` (directive), with country, Commission reference
  (`MNE(…)`), national OJ date and link. 551 directives queried; 61,957 measure records. Example — NIS2
  (32022L2555): measures notified by 25 Member States; none in the dataset for Ireland and Spain (both with open
  Court referrals); France has 15 measures and is also referred — notified ≠ fully transposed.
- Infringements: the Commission register's JSON API
  (`POST https://ec.europa.eu/implementing-eu-law/search-infringement-decisions/api/infringements`): all open cases
  plus all cases with a decision since 2019 — 7,195 cases, 2,006 open, 1,067 open non-communication cases. Stage is
  the register's latest decision type, verbatim. An act is linked only when the register names it. Cases closed
  before 2019 are not in the data: closed non-communication cases of directives with a deadline before 2019 are
  missing (32014L0051: 20 of the register's 30 cases, closed in 2017–18). The coverage note, the About page and the
  country pages say so, and a directive's table whose deadline is before 2019 (`infringements_from`, 87 files)
  repeats it in its note and in each "None in the dataset" cell.
- One table per directive: a file that adopted several directives has a table for each, with its own heading,
  deadline and counts (`implementation` for the first, `implementation_more` for the others; 2013/0400(CNS):
  Directive 2014/86/EU and Directive (EU) 2015/121, whose Irish and Swedish measures concern the second only).
  Country pages name each directive's number in its row.
- Exemptions written into a directive (`exemption` in `data/curated/transposition.yaml`, quoted with every
  subparagraph): the countries a provision exempts from the whole directive, or to which the directive is not
  addressed, show "Not required by the directive" (`not_required`) instead of "No measures found", and their
  country pages add the provision and its condition (`status_note`): Directive (EU) 2016/798, Art. 33(4), Cyprus
  and Malta "for as long as no rail system is established within their territories" (with measures due within
  two years of an official application to build a railway line); Directive (EU) 2016/1629, Art. 40, addressed to
  all Member States except eleven. A derogation that names no country (Directive (EU) 2017/2397, Art. 39(4), which
  Directive (EU) 2021/1233 applies) is quoted under the table, which says that "No measures found" may reflect it.
  One that exempts named countries from some articles only (Directive (EU) 2016/797, Art. 57(5): Cyprus and Malta,
  Article 13 and others; `named`) is quoted with those countries named, and their rows are not marked: they must
  still transpose the rest.
- Country indicators (Single Market Scoreboard): **unavailable** — host returns a CloudFront 403 to scripts;
  data.europa.eu only links 2019 HTML/PDF pages; the Eurostat table was discontinued. Not bypassed. Country
  pages show an indicators section only when a release has indicators, and the source is named "national
  transposition measures and infringements" (meta.json, under the country pages' Implementation section), with
  "and indicators" only then.
- Country pages' directive rows (`countries/<cc>.json` `transposition`) carry the directive's own number as its
  official title cites it (`act`: "Directive (EU) 2022/2555", "Directive 2014/35/EU"; read also from a title that
  Cellar records without the space after the act type, "Directive2014/63/EU"; from the CELEX id only when the
  title has none) and the names its file is known by (`names`, as `known_as.names` on the file's page, else the
  act's own short title). The page's directive search matches the words of the title, `act`, `names` and the CELEX
  id whole (singular or plural, as the site search does: "ban" is not "Urban"; only when no directive has them,
  words of 4+ letters as the start of a longer word, and the page says so), the number however it is written, and
  the files the site search finds for the query; a directive whose own number is searched for is listed first, and
  rows found only because their title cites that number (amending acts) or only because the site search finds
  their file say so.

### Opt-outs in directives' recitals (`optouts`) — ok
- Denmark (Protocol No 22) and Ireland (Protocol No 21) are not bound by most justice and home affairs measures
  unless they opt in; each such directive says so in its recitals in standard wording ("… is not taking part in
  the adoption of this Directive and is not bound by it"). The source reads the English text of every directive in
  the EUR-Lex snapshot once (again when the matcher changes) and records the countries and the sentences quoted.
  Most directives contain no such statement: 36 of the 303 read in the 23 October snapshot do.
  Implementation tables then show "Not bound" instead of "No measures found" for those countries. The Council's
  voting results give the same fact for votes since 2019.
- Ireland can still take part after adoption (Protocol No 21, Article 4); the Commission then confirms it in a
  decision ("The participation of Ireland in Directive (EU) 2024/1346 is confirmed", Commission Decision (EU)
  2024/2087). One Cellar query per run finds such decisions by title; for those directives Ireland is treated as
  bound and the row links the decision (2 directives: 2023/2843 and 2024/1346).
- The generic Denmark/Ireland caveat on a dossier is shown only where neither the recitals nor a Council voting
  result say whether the country took part.
- A Commission decision confirming a participation stays in Cellar, so an opt-in recorded earlier that a later
  answer lacks means that answer was incomplete (Cellar can cut a query short and still answer HTTP 200): it is
  kept and the run is `partial`. A run that read no text and whose opt-in query failed keeps the previous
  retrieval time. A directive due to be read again (the matcher changed) whose text cannot be fetched keeps its
  earlier reading, "not bound" countries and quotes included; the run is `partial` until the text is read.
- The source is listed on the About page like the others (`SOURCES["optouts"]`), with the number of directives
  read, how many of them contain the statement, and how many Denmark and Ireland are not bound by.

### Council of the EU (`council`) — ok
- The Council's voting-results web pages are behind a browser check (403), and the data.europa.eu dataset
  "Council votes on legislative acts" is marked discontinued (its download returns 404).
- Route used: Cellar lists the Council's official "Voting result" notes (ST documents: English title starting
  "Voting result", also after a dash or bullet as in "- Voting result -", "· Voting result ·", "− Voting result −",
  26 notes of 2020–2025 such as ST 9887/25 on the wolf's protection status); each PDF is downloadable
  from `https://data.consilium.europa.eu/doc/document/ST-NNNNN-YYYY-INIT/EN/pdf`. Page 1 (text) gives the procedure,
  title, meeting or written procedure and statements; the per-country table in the annex is a raster image with a
  fixed template, read deterministically (`pdftoppm` + pixel classification, no OCR). Every one of the slots must
  classify, otherwise positions are left empty ("fail closed"). The voting rule is read from two features of the
  sheet that must agree (population column, footnote), and the sheet's printed result is cross-checked against the
  arithmetic of that rule (0 contradictions). Both come from the same sheet, so they cannot catch a sheet that
  prints the wrong rule: see the corrections below.
- A note on a written procedure "initiated by CM 2163/21" without a completion date (ST 7108/21, 8502/21) is dated
  by the Council event Cellar attaches it to (16 March and 7 September 2021), else by the note's own date.
- 746 voting results 2019-01 → 2026-10 (747 Council votes listed and counted on the About page, with the curated
  record CM-5860-2022); 744 with positions; rules: 702 QMV, 44 unanimity (as the sheets print them); 2 notes
  without positions (ST 7085/20: two voting sheets that cannot be told apart; ST 7080/24: one country's vote
  unreadable). `meta.json` (`sources[council].note`) gives the counts of each release. Verified against the
  rendered sheets: AI Act (ST 10199/24, 27 in favour), Copyright Directive 2019 (6 against, 3 abstentions),
  Eurodac 2024 (DK/IE not participating), the wolf Directive 2025 (ST 9887/25: 24 in favour, Belgium, Spain and
  Poland abstaining) and random samples.
- QMV population figures per year from the Council decisions amending Annex III of its Rules of Procedure
  (CELEX 32018D2076, 32019D2209, 32020D2030, 32021D2320, 32022D2518, 32023D2827, 32024D3231, 32025D2427).
- "Not participating" (opt-outs, e.g. DK/IE in justice and home affairs) is kept distinct from abstention.
- Statements: the headings of the texts in the note's annexes, in order: "Statement by …", "Declaration …",
  "Explanation of vote …", "Explanation by Hungary of its vote", "Draft Joint Statement by the Council, …" (ST
  14020/20), "Joint political statement …", "Commission declaration …", "Additional declaration …". A heading is
  centred (indented; its further lines indented too), or printed at the margin when it starts the page or follows a
  blank line, names its author ("Statement by …", "Statement of the European Commission on …") and is set off by a
  blank line within four lines (ST 8502/21: four statements, two of them at the margin; ST 7232/20 REV 1: three
  statements by eight Member States). A subheading naming no author ("Statement in relation to Recital 6" under
  "Statement by the Commission", ST 14341/20) is not a statement. A heading printed again for another text is
  numbered ("Statement by the Commission (2)"). The annex heading alone ("STATEMENTS") is not listed. They are
  taken from the latest version of the note that prints any: a REV replaces the INIT (ST 11580/20 INIT carried
  another act's statements; REV 1 has only Italy's).
- `council_doc`: the note's reference document: a PE-CONS document, else the first Council document number (four
  or five digits; the note prints them without "ST": "9890/20"). A bare shorter number is of another series and is
  not recorded ("102/24" in ST 6219/25, whose file OEIL lists with the draft final act 00102/2024/LEX).
- Parser changes: `PARSER_VERSION` is part of each note's fingerprint (notes.json), so after a change the next
  fetch re-reads every note. On 23 October 2026 (parser 2026-10-23.2: the statement and reference-document rules
  above) every note was re-derived offline from the cached PDFs: 18 records changed (statements of 8 notes, the
  reference document of 10) and the other 749 came out unchanged.
- Corrections (`data/curated/council_votes.yaml`): where the sheet prints "qualified majority" but the act's legal
  basis, cited in the act, requires unanimity (Article 19(1), 81(3) or 312(2) TFEU, quoted in `UNANIMITY_BASES`),
  the rule shown is unanimity, with `sheet_voting_rule` and a `voting_rule_note` saying what the sheet prints and
  why (ST 9781/24, 5698/24, 7391/20, 15907/22). The outcome must then follow from the positions: ST 15907/22
  (6 December 2022, MFF amendment, Hungary against) did not adopt the Regulation (`sheet_outcome` adopted,
  `outcome_note`); the Council adopted it by written procedure on 15 December 2022 with Hungary abstaining, a
  curated record (CM-5860-2022) taken from the Council's communication CM 5860/22, with a `source_note` saying
  that the voting-result documents Cellar lists include none for that adoption. Each correction lists the texts
  it was checked against (the act's citations, the Council's documents: ST 15179/22, which said before the
  6 December meeting that "the Council may adopt the Regulation acting unanimously", ST 15179/1/22 REV 1,
  CM 5842/22, CM 5860/22); they are linked on the vote (`correction_sources`) and on its timeline step, which also
  carries the outcome note. The records are not a complete list of adoptions recorded only in such communications:
  CM 5860/22 also records the Pillar Two Directive (2021/0433(CNS)), Hungary abstaining, in the written procedure
  "completed on 15 December 2022", while Council Directive (EU) 2022/2523 is "of 14 December 2022"; these texts do
  not settle its date, so it is not recorded.
- `display_title` (lists: country pages, activity): the title without legal-form boilerplate, and for a vote on
  another item than the act or the Council's first-reading position, the item voted on, as the subject lists it:
  "Amendments of the European Parliament to the Council's position on the draft budget for 2027 – Non-approval of
  the European Parliament's amendment(s)" (ST 14700/26), so that a country's "For" reads as support for the
  non-approval. That item is `vote_on_label`, which the vote card shows under "Vote on" and country rows carry:
  for the separate vote on derogating from the eight-week period, "Derogation from the eight-week period for
  national parliaments (Article 3(3) of the Council's Rules of Procedure)" (ST 8160/20, whose subject lists
  "Adoption of the legislative act" first); in the budget procedure (a budget title or a BUD reference) without
  "Adoption of the legislative act", which some notes add (ST 14735/24), as a Council vote there does not by itself
  adopt the budget: Parliament and the Council establish it together and the President of Parliament declares it
  adopted (Art. 314(1) and (9) TFEU). A row whose vote names no other item is tagged "Other Council decision".
  Country rows also carry `stage` and `outcome` ("Act not adopted by this vote").
- Build-time checks against the procedure record (`vote_on_note` says when one applies): a note headed
  "Adoption of the legislative act" whose reference document is the Council's first-reading position (same
  number as OEIL's "Council position published"), followed by Parliament's second-reading decision, adopted
  that position (ST 12604/20, 12592/20, 13733/20); a note naming no item, dated the day OEIL records the
  Council's adoption of the act, is the adoption of the act. A vote citing the reference of a split procedure
  (2021/0211(COD)) is listed on the part holding an act of the type voted on (2021/0211A for the directive);
  the parent keeps a pointer (`council_votes_in_parts`). A note in the budget procedure (a BUD reference) labelled
  "Adoption of the legislative act" is not the adoption of an act (ST 10354/25, the Council's position on draft
  amending budget No 1/2025): `vote_on` "other", with a note.
- A separate vote on derogating from the eight-week period for national parliaments (Rules of Procedure,
  Art. 3(3), second subparagraph): a note that lists, after "Adoption of the legislative act", the item
  "Derogation, on the basis of the second subparagraph of Article 3(3) of the Council's Rules of Procedure, from
  the eight-week period …", next to another note of the same day on the same reference document that does not,
  is that procedural decision (`vote_on` "other", with a note): ST 8160/20 (its voting sheet: the regulation's
  title followed by that derogation; 25 in favour) beside ST 8159/20, which adopted the act (22-4-1), on
  2020/0067(COD). It is shown as "Council decided to derogate from the eight-week period for national
  parliaments", not as an adoption, and Member States' positions on it are listed under that item. Its
  qualified-majority threshold is the act's: the Council "shall decide in accordance with the voting rule
  applicable for the adoption of the act or position concerned" (Art. 3(3), second subparagraph, Council Decision
  2009/937/EU), which the note quotes.
  The note "= Derogation from the 8-week period …" that accompanies an adoption (ST 8159/20, ST 7391/20 REV 1)
  does not make a vote one; the dossier lists the vote adopting the act first among the day's votes.
- A vote on the "Consent of the Council" to an act Parliament adopts (Art. 223(2), 226, 228(4) TFEU; ST 9947/21,
  Statute of the European Ombudsman) is shown as the Council's step ("Council gave its consent"), in place of
  OEIL's record of the same step.
- `date_note`: a voting result of a meeting held over several days, which the note does not date to one day, is
  dated by its first day unless `data/curated/council_dates.yaml` gives the day from the act's text, which the
  voting sheet's "Sitting date" confirms (ST 10263/24 and ST 10264/24: "Sitting date: 24/05/2024"); the note then
  says so.
- QMV threshold: when it is not established whether the Council acted on a Commission proposal (an ordinary
  procedure opened by OEIL's "Legislative proposal published" with its COM document and no other initiator's
  document counts as one), both numbers of Member States are given (`states_required` 55%,
  `states_required_alt` 72%); the note says that the sheet's footnote on the threshold is part of the image we
  do not read, and that the vote is not linked to a procedure file in our data (13 votes, mostly budget votes) or
  that our record of the procedure names no proposal (2018/0900(COD)). An ordinary procedure whose recorded
  proposal is the Court of Justice's request (OEIL "CJEC | Legislative proposal", `court_request`) is not on a
  Commission proposal: 72% of Member States, TFEU Art. 238(2) (2022/0906(COD), ST 8001/24; Regulation (EU,
  Euratom) 2024/2019 "Having regard to the request of the Court of Justice", Art. 281 TFEU, second paragraph).
  The Council's consent to Parliament's own regulation ("Consent of the Council (Article 228(4) TFEU)",
  ST 9947/21, the Ombudsman Statute) is never on a Commission proposal: 72% of Member States, TFEU Art. 238(2).

### Legislative Train (`train`) — ok
- 1,492 files across the 2014–19, 2019–24 and 2024–29 Commission terms; 663 carry procedure references. Statuses
  verbatim. "Blocked" is the Train's own classification (no progress by a co-legislator for at least nine
  months); 35 Blocked files name the blocking institution(s). The Train updates monthly and can lag recorded
  facts, so EP/EUR-Lex records take precedence.
- Procedure discovery: the EP API's paged procedure list omits some files, so `ep_procedures` also requests the
  in-scope procedures that EUR-Lex acts, EP votes and (since October 2026) Legislative Train files name. The
  snapshot predates the Train's addition: the next refresh requests 7 files the Train names and the snapshot
  lacks (2017/0398(COD), 2018/0073(CNS) digital services tax, 2018/0226(COD), 2018/0245(CNS), 2018/0302(COD),
  2019/0197(COD), 2022/0430(CNS)). Files that only Cellar's own procedure list names (2018/0802(CNS)) are still
  not discovered.

### Licences
- European Parliament (MEPs, procedures, votes, Legislative Train): "© European Union – Source: European
  Parliament", with the terms the Parliament gives for each kind of data (`build.SOURCES`, shown on the About page).
  The European Parliament legal notice (https://www.europarl.europa.eu/legal-notice/en/, read 2026-10-23): "As a
  general rule, the reuse (reproduction or use) of textual data and multimedia items which are the property of the
  European Union ... is authorised, for personal use or for further non-commercial or commercial dissemination,
  provided that the entire item is reproduced and the source is acknowledged. However, the reuse of certain data
  may be subject to different conditions in some instances; in this case, the item concerned is accompanied by a
  mention of the specific conditions relating to it. Any partial reproduction of data or multimedia items from this
  website must also cite the URL link of the complete item or the web page from which it was sourced."
  The EP Open Data Portal gives such a mention per dataset (`OdpDatasetService/DatasetsLight`, labels from
  `OdpDatasetService/LabelSite/en`, read 2026-10-23): licence "CC BY 4.0 - Attribution 4.0 International"
  (https://creativecommons.org/licenses/by/4.0/deed.en) for "Members of the European Parliament (MEPs)" (every
  term, e.g. dataset 1886, term 10), "Corporate bodies of the European Parliament", "EU procedures involving the
  European Parliament" (every year, e.g. 1909 and 1910, 2024 and 2025) and "Results of votes of the European
  Parliament" (1980 and 1979, 2024 and 2025: no other year is listed); "European Parliament's Legal Notice" for
  others (e.g. the plenary session documents of sessions up to 9 November 2022). CC BY 4.0, Section 3(a)(1): "If
  You Share the Licensed Material (including in modified form), You must: retain ... identification of the
  creator(s) ...; a copyright notice; a notice that refers to this Public License; ... a URI or hyperlink to the
  Licensed Material to the extent reasonably practicable; indicate if You modified the Licensed Material ...; and
  indicate the Licensed Material is licensed under this Public License, and include the text of, or the URI or
  hyperlink to, this Public License." The site reads this data from the Open Data API rather than the datasets,
  shows it adapted (selected, combined with other sources and reformatted, as the About page says) and links each
  item it takes data from: a dossier its procedure file and Legislative Train page, a vote the minutes it comes
  from. The Legislative Observatory, the Legislative Train and the minutes are Parliament web pages under the
  legal notice; for the votes of years with no "Results of votes" dataset (2019–2023 and 2026) the About page
  states the legal notice's terms, its general rule.
- EUR-Lex / Cellar: reuse authorised with acknowledgement ("© European Union, https://eur-lex.europa.eu") under the
  EUR-Lex legal notice and Commission Decision 2011/833/EU. The live notice page is bot-protected for scripts and
  should be re-checked manually before any change of attribution text.
- Commission infringement register: Commission reuse policy (Decision 2011/833/EU), "© European Union".
- Council documents: reuse permitted with acknowledgement of the source ("© European Union", Council of the EU),
  per the Council's copyright notice.
