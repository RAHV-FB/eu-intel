# Editorial policy

EU Legislative Intelligence explains EU legislation using only official, verifiable data. Almost
everything on the site is computed from official sources. The one exception is a small curated layer
in `data/curated/`: editorial selections and texts, and a few date corrections checked against the acts'
texts. This document covers what goes into that layer and how it is written and reviewed.

| File | Contents |
|---|---|
| `featured.yaml` | 20–30 major dossiers, each with a short title, two plain-language sentences (`what`, `why`), search aliases, topics and the sources behind the text. 5–6 of them are marked for the homepage. |
| `topics.yaml` | The 10 browsing topics, mapped to the EP/OEIL subject classification, plus everyday search words. |
| `aliases.yaml` | General search synonyms (standard, official abbreviations) and per-file names that the institutions themselves use, each with a cited source. |
| `act_dates.yaml` | Corrections to the entry-into-force and application dates Cellar records for an act. Each date cites the provision that sets it (or the amending act), and the entry lists the official texts it was checked against. The correction applies in the build only; the snapshot keeps Cellar's values. |
| `transposition.yaml` | Which of the transposition dates EUR-Lex records for a directive is its general deadline (one of the recorded dates), with the provision quoted verbatim, the text checked and a review date. |

## What the curated layer must not contain

- **No procedural status or next steps.** Stage, votes, adoption, entry into force and upcoming
  steps are computed from the snapshot (EP Open Data, OEIL, Cellar/EUR-Lex, Council, Legislative
  Train), so they cannot go stale in the YAML. The one exception is the dates in `act_dates.yaml` and
  `transposition.yaml`: corrections of recorded dates, each checked against the act's text. Dates are allowed when they are part of the legal
  content, such as a cut-off date ("land not deforested after 31 December 2020"), a target year,
  an application or transposition date ("from 30 December 2026"), or a deadline the act sets.
- **Exceptions that change the substance.** Name, by act number, any later act that changes what
  the law does, such as a postponement, a scope change or a new prohibition (for example "Directive
  (EU) 2026/470 limits the obligation to …"). A withdrawn proposal is described in the past tense,
  and its sources include the withdrawal notice. A review the act required may be described with
  its outcome when the review has been delivered, citing the document.
- **No judgements.** Do not call a dossier good, bad, controversial, historic, ambitious and so on.
- **No unverifiable claims.** Every statement in `what`/`why` must be supported by one of the
  sources listed for that entry.

## Selection criteria for featured dossiers

A dossier is included in `featured.yaml` if it is a recognisable EU legislative file (normally an
ordinary legislative procedure) that meets at least one of these criteria:

1. **Major package or Commission priority.** It is part of a headline package, such as the
   Migration and Asylum Pact, the Green Deal, the Digital package or the Omnibus simplification
   packages, or it is a named priority in the Commission Work Programme or the Legislative Train.
2. **Significant institutional attention.** For example, a plenary vote with a recorded division,
   repeated trilogues, or a Council general approach that was itself a news item.
3. **Clear effects on citizens or businesses.** People or companies must do, or may do, something
   concrete because of it.
4. **Notable recorded disagreement.** Positions of the institutions that differ on the record,
   member-state statements published by the Council, or a close or divided recorded vote.
5. **Important milestone.** Recently adopted or published, a provisional agreement, or the start of
   negotiations.
6. **Officially recognised delay.** A postponement adopted as law, or a file the Legislative Train
   classes as "Blocked".

**Balance.** The list mixes all of the following:

- acts that are adopted and in force
- acts adopted recently
- proposals under negotiation
- stalled proposals
- withdrawn proposals

It covers all 10 topics. Amending acts get their own entry when they change what the law does in a
way people would notice. Examples are the two Deforestation Regulation postponements, Omnibus I and
the Digital Omnibus on AI.

**Homepage (`featured: true`, 5–6 items).** Every homepage item must meet at least two of the
criteria above. The set as a whole must include at least one adopted act and at least one pending
proposal. At most two items may come from the same topic.

**Identity checks (required for every entry):**

- `id` must resolve in the EP Open Data API (`/api/v2/procedures/<id>`).
- `reference` must match `id`.
- `celex` lists the final act(s) that Cellar links to the procedure dossier, or `[]` if none is
  linked. Each CELEX number must resolve in Cellar with a matching title.
- If Parliament split a proposal into several procedures (for example 2016/0224A(COD) and
  2016/0224B(COD)), the entry uses the split procedure that records the votes and the final act.
  Cellar may still group both acts under the parent dossier. The OEIL link must open.

## Writing standards

- **`what`.** One or two sentences on what the act does (or, for a proposal, would do), in concrete
  terms: who must do what, what is banned, what is created.
- **`why`.** One or two sentences on the concrete effect on people, businesses or public
  authorities.
- **Legal precision.**
  - A pending proposal is always "Proposal would …" in `what` and "If adopted, …" in `why`. Never
    call a proposal a "law". A withdrawn proposal is "The Commission proposed …", followed by what
    happened to it (rejection, withdrawal), and `why` starts "The proposal did not become law".
  - **Tense.** Obligations and rights that do not yet apply on the review date are written in the
    future tense, with their application date ("will have to …", "from March 2029, … will be able
    to …"). Only provisions that already apply are written in the present tense.
  - Use "regulation" and "directive" correctly.
  - Amending acts say what they amend.
- **Neutral wording.** Use plain verbs (requires, prohibits, sets, creates, allows). Do not use
  evaluative adjectives or political framing. Where institutions disagree, say what the
  disagreement is about, without taking sides.
- **Short and plain.** Each field is 10–75 words. Explain jargon or replace it.
- **Sources.** Each entry lists official sources: the act on EUR-Lex (ELI link) for adopted acts,
  the Commission proposal for pending ones, and the OEIL file. Where the text relies on them, it
  also lists Council/EP/Commission press releases or Legislative Train pages.

`tests/test_curated.py` enforces the schema, the proposal wording, a list of banned words, the
"no status wording" rule, word counts and the homepage rules. `act_dates.yaml` and `transposition.yaml` are
checked by `python -m pipeline validate` and `tests/test_build.py`; their entries follow the same review
process, including the re-review of their `reviewed` dates.

## Alias policy

- **`aliases.yaml`** contains only standard abbreviations and official short names that the
  institutions themselves use, such as GDPR, DSA, DMA, CSRD, ETS and CBAM, and everyday words for the
  term that legal texts use instead ("pesticides" for "plant protection products", "medicines" for
  "medicinal products"); a new entry of this kind carries a comment citing an official page that
  uses both. It does not
  include ambiguous everyday words (for example, plain "safe" or "red").
- **Per-file names in `aliases.yaml`** (`{procedure: "2023/0083(COD)", names: [...]}`) attach a name
  to one procedure for search only. Each entry needs a `# source:` comment citing a Commission,
  Parliament or Council page that uses the name for that file (a test enforces the comment).
  Names an act gives itself in its Official Journal title, and Legislative Train file names, are
  added automatically from the snapshot.
- **`featured.yaml` `aliases`** may also include common names that the public actually uses.
- **Contested names.** A name that is contested, or used mainly by one side of a debate, may be
  attached only if it is verifiably in common use for that specific proposal. It must have a YAML
  comment citing where it is used, and it is used for search only, never as a display title.
  - Current case: "chat control" for the child sexual abuse proposal 2022/0155(COD). It is used in
    European Parliament written questions (e.g. E-000489/2023, E-003690/2025) and in German
    Bundestag hearing documents. The Commission rejects the label.
- **`topics.yaml` `search_aliases`** are everyday words ("AI", "farmers", "privacy") that steer a
  query to a topic.

## Topics

Topics are mapped to EP/OEIL subject codes. A code prefix matches the code itself and its
sub-codes. The labels quoted in `topics.yaml` are the official OEIL labels. Topics may overlap where
an official subject fits more than one theme. Curated entries set their topics explicitly.

## Review process

1. **Researching.** Verify identity (EP API, Cellar) and content (the act or proposal, and official
   press releases or Legislative Train pages) before writing. Record the sources in the entry.
2. **Writing.** Follow the standards above, then run `pytest tests/test_curated.py`.
3. **Second review.** Changes are made by pull request and reviewed by a second person, who checks
   each sentence against the cited sources.
4. **Re-review.** Each entry carries a `reviewed` date. An entry is re-reviewed:
   - when the computed data show a material change, such as a new act amending it, adoption,
     withdrawal, or a new Legislative Train status; and
   - at least every three months.
   The homepage selection is reconsidered on the same schedule.
5. **Corrections.** Factual errors are corrected as soon as they are found, and git history keeps
   the trail.

## Current homepage selection (reviewed 2026-10-22)

| # | Dossier | Criteria met |
|---|---|---|
| 1 | Artificial Intelligence Act, 2021/0106(COD) | (1) Commission digital priority; (3) obligations for AI providers and deployers across sectors; (5) amended in 2026 by the Digital Omnibus on AI, which changed when the high-risk rules apply |
| 2 | Return Regulation, 2025/0059(COD) | (1) migration priority, follow-up to the Pact; (4) Council-published member-state statements opposing parts of it (return hubs); (5) adopted and published in October 2026 |
| 3 | Regulation to prevent and combat child sexual abuse online, 2022/0155(COD) | (2) trilogues throughout 2026; (3) obligations for messaging and hosting services; (4) Parliament and Council mandates differ on detection orders and encryption |
| 4 | EU Deforestation Regulation, 2021/0366(COD) | (6) application postponed twice by law, Regulations (EU) 2024/3234 and 2025/2650; (3) traceability duties for companies and non-EU producers |
| 5 | 2040 climate target, 2025/0524(COD) | (1) Green Deal / Climate Law; (4) divided recorded plenary vote; (5) adopted in 2026 |
| 6 | Digital euro, 2023/0212(COD) | (2) interinstitutional negotiations recorded in 2026; (3) a new means of payment for people and businesses in the euro area |

## Other featured dossiers and why they are included

| Dossier | Criteria |
|---|---|
| Digital Omnibus on AI, 2025/0359(COD) | (1) Omnibus simplification; (5) adopted in 2026 |
| Digital Services Act, 2020/0361(COD) | (1), (3) |
| Digital Markets Act, 2020/0374(COD) | (1), (3) |
| General Data Protection Regulation, 2012/0011(COD) | (3); the reference act for data protection |
| Digital Omnibus, 2025/0360(COD) | (1) Omnibus simplification; (3) changes to GDPR and cookie rules; proposal under negotiation |
| European Media Freedom Act, 2022/0277(COD) | (1) democracy priority; (3) media outlets and platforms |
| Asylum and Migration Management Regulation, 2020/0279(COD) | (1) Migration Pact; (3) |
| Asylum Procedure Regulation, 2016/0224A(COD) | (1) Migration Pact; (3) |
| Nature Restoration Regulation, 2022/0195(COD) | (1) Green Deal; (3) restoration obligations for Member States |
| Deforestation Regulation postponements, 2024/0249(COD) and 2025/0329(COD) | (6) |
| Carbon Border Adjustment Mechanism, 2021/0214(COD) | (1) Fit for 55; (3) importers |
| Packaging and Packaging Waste Regulation, 2022/0396(COD) | (1) Green Deal; (3) |
| CSRD, 2021/0104(COD) and CSDDD, 2022/0051(COD) | (1), (3) |
| Omnibus I, 2025/0045(COD) | (1) Omnibus simplification; (4) divided plenary vote; (5) |
| Critical Raw Materials Act, 2023/0079(COD) | (1) industrial priority; (3) |
| Ending seasonal clock changes, 2018/0332(COD) | (6) classed "Blocked" by the Legislative Train (blocking institution: Council); (3) everyone in the EU |
| CO2 standards for cars and vans, 2025/0420(COD) | (1) Automotive package; (3); proposal under negotiation |
| European Health Data Space, 2022/0140(COD) | (3) patients and health professionals |
| Platform Work Directive, 2021/0414(COD) | (3) people working through apps and the platforms |
| European Defence Industry Programme, 2024/0061(COD) | (1) defence readiness; (5) |
| New genomic techniques, 2023/0226(COD) | (1) Green Deal food-system file; (3) farmers, seed sector, food labelling; (5) adopted in 2026 |
| Sustainable Use of Plant Protection Products, 2022/0196(COD) | withdrawn proposal (Cellar marks the dossier as withdrawn), included for balance; (3) farmers |

**Considered but not included.** The ETS reform, 2021/0211(COD), is not listed for now. Its EP Open
Data API record currently has no label, type or title, so pages computed from it would be
incomplete. The final act is Directive (EU) 2023/959. Revisit once the EP record is complete.
