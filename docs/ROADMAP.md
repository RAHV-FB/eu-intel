# Roadmap and known limitations

What the site does not do yet, or does only partly, and what would come next. Everything below is stated
so that nobody reads a gap as a fact about EU law.

## Coverage (by design)

- **Legislation**: procedures of the ordinary legislative procedure (COD), consultation (CNS) and consent
  (APP) with a reference year from 2014, plus older procedures that produced an act adopted since 2014.
  Non-legislative procedures and acts (NLE, delegated and implementing acts, budget procedures) are out of
  scope.
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
  be retrieved; their pages say so.
- Some files have no topic: their official subjects (EU institutions, external relations, development,
  regional policy, enlargement) fall outside the ten topics. They are listed under "No topic assigned".
- Some files have a Parliament position but no listed vote: mostly second-reading approvals without a
  roll-call vote, and a few votes the source does not link to a procedure.
- Some vote titles are still the raw label of the official record (mainly remote votes in 2020, announced
  on a different day from the minutes).
- EUR-Lex does not always record an act's dates correctly: it may miss a change made by an amending act, or
  give the application date or another act's date as the act's entry into force. Corrections checked against
  the acts' texts are kept in `data/curated/act_dates.yaml` (listed in DATA_SOURCES.md, "Corrections"); other
  amended acts carry a note on the page, and `pipeline validate` flags suspicious dates.
- The EP Legislative Train is used only for its own "Blocked" classification and as a caveat when it reports a
  file as adopted before the official records do; its other statuses lag or lead the records.
- National parties appear once per parliamentary term (the source records them as separate bodies).
- The activity log starts with the first recorded scheduled refresh; earlier changes are shown from the
  snapshot's own dates, without a detection date.

## Next steps

- Editorial summaries for more files (each reviewed against the act and its sources, see `docs/EDITORIAL.md`).
- More checked date corrections for amended acts, starting with featured files.
- Smaller vote files: individual ballots as compact arrays keyed by MEP id (the published site is about
  300 MB, mostly per-vote ballot lists).
- Merge each national party's per-term records on one page.
- Run the browser tests on the current Ubuntu image once the Playwright version supports it (the e2e job is
  pinned to Ubuntu 24.04).
