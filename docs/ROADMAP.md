# Roadmap and known limitations

What the site does not do yet, or does only partly, and what would come next. Everything below is stated
so that nobody reads a gap as a fact about EU law.

## Coverage (by design)

- **Legislation**: procedures of the ordinary legislative procedure (COD), consultation (CNS) and consent
  (APP) with a reference year from 2014, plus older procedures that produced an act adopted since 2014.
  Non-legislative procedures and acts (NLE, delegated and implementing acts, budget procedures) are out of
  scope, except a few files that Parliament classes as non-legislative (NLE) but whose act EUR-Lex records
  under the consultation or consent procedure: these are shown, labelled "Non-legislative act" (the About page
  gives their number). A non-legislative act that EUR-Lex links to a legislative procedure that cannot have adopted
  it is not shown (Council Decision (EU) 2020/2059 and 2020/3521(COD): `data/curated/act_links.yaml`).
- **Parliament votes**: plenary votes from 18 July 2019 (9th and 10th terms). Votes on whole texts,
  resolutions, motions, final and negotiating-mandate votes and votes on entering negotiations are listed;
  how each MEP voted is shown only for those votes, not for amendments or split votes. A national party's page lists
  its MEPs' final and negotiating-mandate votes only (not resolutions or motions); for MEP-level analysis, each vote
  links to the same vote on HowTheyVote.eu, an independent site.
- **Council votes**: the Council's published voting results from 2019, read from its own documents (the
  Council's open-data datasets were discontinued in 2025 and its web pages are bot-protected).
- **National implementation**: measures notified to the Commission and listed by EUR-Lex, and the
  Commission's infringement decisions. A notified measure is not proof of complete or correct transposition,
  and the absence of one is not proof of non-compliance. Of the Single Market Scoreboard, only each Member State's
  count of overdue Single Market directives is shown, on its own country page, read from the Scoreboard's HTML table;
  its headline indicators are published only in embedded Power BI reports, not in a machine-readable form.

## Known gaps

- A few adopted laws are shown from their EUR-Lex record only, because Parliament's procedure record could not
  be retrieved or merges several procedures; their pages say so.
- Some files have no topic: their official subjects (mostly regional and cohesion policy, EU institutions and
  EU law, external relations, development and enlargement, cultural programmes) fall outside the ten topics, or
  our data has no subject for them (proposals split into several procedures, whose parts have their own pages,
  and the laws shown from their EUR-Lex record only). They are listed under "No topic assigned".
- Some files have a Parliament position but no listed vote: mostly second-reading approvals without a
  roll-call vote, and a few votes the source does not link to a procedure.
- A decision of Parliament that its open data records only as a vote, and that no listed vote dates, is shown as
  "Vote in Parliament": 2018/0229(COD), InvestEU, on 18 April 2019, which the Legislative Observatory lists as
  "Decision by Parliament, 1st reading" (T8-0433/2019, among the file's documents). That Observatory entry is not
  read as a decision: it also names votes after which the file went back to committee for negotiations.
- EUR-Lex does not always record an act's dates correctly: it may miss a change made by an amending act, or
  give the application date or another act's date as the act's entry into force. Corrections checked against
  the acts' texts are kept in `data/curated/act_dates.yaml` (listed in DATA_SOURCES.md, "Corrections"); other
  amended acts carry a note on the page, and `pipeline validate` flags suspicious dates.
- The Legislative Observatory's date for the Council's adoption of an act is sometimes days or weeks off, and a
  few Council voting-result documents print "qualified majority" for an act whose legal basis requires
  unanimity. Corrections checked against the act's text and the Council's documents are kept in
  `data/curated/council_dates.yaml` and `data/curated/council_votes.yaml`; the voting rule a sheet prints is not
  checked against the act's legal basis automatically (our data does not record legal bases).
- Some acts' application dates are "not yet set" in EUR-Lex (Cellar's placeholder 1001-01-01): their rules apply
  from a date a later act sets. The page says EUR-Lex gives no date; the later acts are read only for the dates
  curated in `act_dates.yaml` (e.g. the Clinical Trials Regulation, the EPPO), not yet for the others (19 acts in
  force on 23 October 2026, among them ETIAS and PEPP; `pipeline validate` lists them as `application-not-recorded`).
- An act adopted on a file but not linked to it by any official record (Cellar, the Legislative Observatory, the
  EP API) is not linked here either; where its text shows the connection, `data/curated/unlinked_acts.yaml` lets
  the status name it without asserting a link (2025/0806(CNS), Council Regulation (EU) 2026/415).
- Council adoption dates are checked against the act's text for 37 files; for acts adopted before 2019 there is
  no Council voting result to compare with, and the other acts dated from the Legislative Observatory, which
  Cellar confirms, have not been read one by one. Council adoptions recorded only in another Council document
  (the outcome of a written procedure) are included only where curated (CM 5860/22); others may be missing.
- Parliament votes that the EP records do not tie to their file stay unlinked (the Ombudsman Statute's vote of
  2021, 2019/0900(APP), would need Parliament's adopted texts, which are not fetched). Referral votes (sending a
  file back to committee) are not listed, so referral steps link no vote. A few recommendations to the Council are
  shown as resolutions because their records call them so, and discharge votes headed only "Decision on
  discharge" do not say whether discharge was granted, postponed or refused.
- Infringement cases: open cases and cases with a decision since 1 January 2019; earlier closed cases are not
  fetched. Exemptions that a directive's own text gives some Member States are recorded for a few directives
  (`transposition.yaml`); for the others the general deadline sentence is shown.
- Which Member States a regulation binds is not read from its text: Treaty opt-outs (Denmark, Ireland) are read
  from directives' texts only (`optouts`), so a regulation's page says that it binds the Member States it binds and
  names only those the Council's voting record lists as not taking part, and a later participation that a Commission
  decision confirms (Protocol No 21, Article 4); acts implementing enhanced cooperation are recognised from their
  title. Reading regulations' recitals needs a fetch of their texts (about 800). A later participation that no
  Commission decision titled "confirming the participation of ..." records is not read.
- Amending acts known only by their CELEX id (outside our EUR-Lex data, such as delegated acts) are named by the
  number in that id ("Regulation 2026/2102"), not by their full type, unless a curated date correction cites
  their text ("Commission Delegated Regulation (EU) 2026/2102"). Such an act's publication is not dated on the
  timeline, so the EUDR's latest step (23 December 2025) is older than its amendment published on 17 September 2026.
- A proposal whose withdrawal is challenged before the Court of Justice is shown as withdrawn, with the Legislative
  Observatory's stage where that stage is not "lapsed or withdrawn" (5 withdrawn files on 24 October 2026); its page
  also says that the withdrawal is challenged (2023/0133(COD): Parliament's action for annulment, Case C-727/25,
  pending).
- Court cases on an act are shown as pending only when EUR-Lex links the case to its file, which it does for cases
  brought from 2024 and some of 2023; earlier pending cases are not shown as pending. EUR-Lex summaries it marks as
  obsolete are not shown.
- Initiatives of Member States are named from the Legislative Observatory's file title, and requests of the
  Court of Justice from its record; other initiators, such as the ECB, are not named.
- Links to committee documents on www.europarl.europa.eu could not be checked automatically (the site refuses
  scripted requests); a few may lead to pages that no longer exist.
- Status labels and explanations are written when the data is built (weekly); sentences about dates that have
  since passed are reworded on the reader's date, and the page notes when a status may be out of date. Home and the
  footer give the date to which procedures, votes and acts are current (the oldest last retrieval of their sources)
  and name any source that is not up to date on the reader's date.
- A publication or signature of the act that only Parliament's procedure record lists does not change a file's
  status until the act is in our EUR-Lex data (a signature also counts once the act's adoption is recorded); the
  status explanation says what Parliament's record lists. Parliament's records of the latest publications are
  sometimes wrong and corrected within days (2023/0421(COD), "published" on 30 October 2026, an event since deleted).
- The automated tests (layouts, keyboard use, axe-core accessibility rules) run in Chromium, Firefox and WebKit
  (Safari's engine) on Linux, not on real phones or tablets, and no screen reader has been used to test the site.
- The EP Legislative Train's statuses are used only for its own "Blocked" classification and as a caveat when it
  reports a file as adopted before the official records do; its other statuses lag or lead the records. Its site
  answers requests from GitHub's runners, where the refresh runs, with a bot challenge (AWS WAF, HTTP 202): every
  refresh since 26 October 2026 has kept the copy of 22 October. Until a refresh succeeds, About marks its retrieval
  as failed; once the copy is older than 35 days, home and the footer name the source as not up to date, and once it
  is older than 42 days no file is shown as officially blocked.
- National parties appear once per parliamentary term (the source records them as separate bodies; a few have
  two records in one term).
- The activity log starts with the first recorded scheduled refresh; earlier changes are shown from the
  snapshot's own dates, without a detection date. A status change cites the record that gave the status; those
  recorded by the refreshes of 2 and 5 November 2026 cite the Legislative Observatory's procedure file once the
  file's status has changed again. An item is withdrawn from the feeds and the file's page once the current records
  no longer support it: its record deleted or re-dated at source, its act no longer linked to the file, or a reported
  adoption or later stage that the file's status has fallen back from. Feed readers may keep their copy.

## Next steps

- The ordered plan of November 2026 (trust, autonomy, value, reach) is in `docs/ASSESSMENT_2026-11.md`, section 5.
- Editorial summaries for more files (each reviewed against the act and its sources, see `docs/EDITORIAL.md`).
- More checked date corrections for amended acts, starting with featured files.
- Smaller vote files: individual ballots as compact arrays keyed by MEP id (the published site is about
  340 MB, more than half of it the per-vote lists of ballots and MEP names).
- Merge each national party's per-term records on one page.
- Run the browser tests on the current Ubuntu image once the Playwright version supports it (the e2e job is
  pinned to Ubuntu 24.04).
