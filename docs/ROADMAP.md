# Roadmap and known limitations

What the site does not do yet, or does only partly, and what would come next. Everything below is stated
so that nobody reads a gap as a fact about EU law.

## Coverage (by design)

- **Legislation**: procedures of the ordinary legislative procedure (COD), consultation (CNS) and consent
  (APP) with a reference year from 2014, plus older procedures that produced an act adopted since 2014.
  Non-legislative procedures and acts (NLE, delegated and implementing acts, budget procedures) are out of
  scope, except a few files that Parliament classes as non-legislative (NLE) but whose act EUR-Lex records
  under the consultation or consent procedure: these are shown, labelled "Non-legislative act" (the About page
  gives their number).
- **Parliament votes**: plenary votes from 18 July 2019 (9th and 10th terms). Votes on whole texts,
  resolutions, motions, final and negotiating-mandate votes and votes on entering negotiations are listed;
  how each MEP voted is shown only for those votes, not for amendments or split votes.
- **Council votes**: the Council's published voting results from 2019, read from its own documents (the
  Council's open-data datasets were discontinued in 2025 and its web pages are bot-protected).
- **National implementation**: measures notified to the Commission and listed by EUR-Lex, and the
  Commission's infringement decisions. A notified measure is not proof of complete or correct transposition,
  and the absence of one is not proof of non-compliance. The Single Market Scoreboard indicators could not be
  retrieved (the host refuses scripted access) and are not shown.

## Known gaps

- A few adopted laws are shown from their EUR-Lex record only, because Parliament's procedure record could not
  be retrieved or merges several procedures; their pages say so.
- Some files have no topic: their official subjects (mostly regional and cohesion policy, EU institutions and
  EU law, external relations, development and enlargement, cultural programmes) fall outside the ten topics, or
  our data has no subject for them (proposals split into several procedures, whose parts have their own pages,
  and the laws shown from their EUR-Lex record only). They are listed under "No topic assigned".
- Some files have a Parliament position but no listed vote: mostly second-reading approvals without a
  roll-call vote, and a few votes the source does not link to a procedure.
- EUR-Lex does not always record an act's dates correctly: it may miss a change made by an amending act, or
  give the application date or another act's date as the act's entry into force. Corrections checked against
  the acts' texts are kept in `data/curated/act_dates.yaml` (listed in DATA_SOURCES.md, "Corrections"); other
  amended acts carry a note on the page, and `pipeline validate` flags suspicious dates.
- The Legislative Observatory's date for the Council's adoption of an act is sometimes days or weeks off, and a
  few Council voting-result documents print "qualified majority" for an act whose legal basis requires
  unanimity. Corrections checked against the act's text and the Council's documents are kept in
  `data/curated/council_dates.yaml` and `data/curated/council_votes.yaml`; the voting rule a sheet prints is not
  checked against the act's legal basis automatically (our data does not record legal bases).
- The EP Legislative Train's statuses are used only for its own "Blocked" classification and as a caveat when it
  reports a file as adopted before the official records do; its other statuses lag or lead the records.
- National parties appear once per parliamentary term (the source records them as separate bodies; a few have
  two records in one term).
- The activity log starts with the first recorded scheduled refresh; earlier changes are shown from the
  snapshot's own dates, without a detection date.

## Next steps

- Editorial summaries for more files (each reviewed against the act and its sources, see `docs/EDITORIAL.md`).
- More checked date corrections for amended acts, starting with featured files.
- Smaller vote files: individual ballots as compact arrays keyed by MEP id (the published site is about
  340 MB, more than half of it the per-vote lists of ballots and MEP names).
- Merge each national party's per-term records on one page.
- Run the browser tests on the current Ubuntu image once the Playwright version supports it (the e2e job is
  pinned to Ubuntu 24.04).
