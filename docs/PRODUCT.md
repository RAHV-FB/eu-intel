# Product

## Proposition

**Understand what the European Union is doing:** which laws are moving forward, which are stuck, who
supported or opposed them, and how EU legislation reaches each country — in plain language, with every
fact traceable to an official EU record.

A beginner should grasp the key facts of any page in 15–30 seconds. A journalist, researcher or policy
professional should be able to follow those facts down to the official documents and individual votes.

## Who it is for, and the questions it answers

| Visitor | Typical questions |
| --- | --- |
| Citizen with little EU knowledge | What is the AI Act? Is it law yet? When does it apply to me? What happens next? |
| Journalist / researcher | Where is this proposal stuck? Who voted for it — which groups, which countries' MEPs? Did the Council agree? What do the official records say? |
| Student comparing Member States | Which directives has Spain transposed? Is there an infringement case? What do the published indicators show? |
| Professional following a topic | What changed recently on AI, climate, migration or financial services? What applies next year? |

## What already exists, and the gap

| Tool | Strength | Difficulty for ordinary users |
| --- | --- | --- |
| EP Legislative Observatory (OEIL) | Authoritative procedure files | Institutional vocabulary, document-centric, no voting breakdowns, no national implementation |
| EU Law Tracker (law-tracker.europa.eu; Parliament, Council and Commission) | Official joint record of ordinary-procedure files from proposal to adoption; 2026 Ombudsman Award for Good Administration | Stops at adoption: not when the rules apply, each Member State's transposition or infringement cases |
| Legislative Train Schedule | Curated status of major initiatives, official "blocked" monitoring | Covers priorities only; no votes; no link to national application |
| EUR-Lex | Authoritative legal texts, dates, national measures | Built for lawyers; status of proposals hard to read; bot-protected |
| Council voting results | Member State positions | Separate site, not linked to Parliament votes or the procedure |
| HowTheyVote.eu, similar independent explorers | Excellent EP roll-call exploration | Parliament-only; little about procedure status, Council or implementation |
| EuropeScope (featured by data.europa.eu, 11 September 2026) | Parliament roll calls and Council voting records together; MEP attendance, votes against their group, national delegations; public API | Built around votes and MEP activity; no national implementation |

**Our advantage is the combination**: discovery + plain explanation + procedural progress + Parliament
votes + Council positions + national implementation, joined by official identifiers in one coherent product.
Parliament and Council votes in one place are also on EuropeScope, and the EU Law Tracker follows each file until
adoption; none of the tools above joins what follows adoption (when each part applies, each Member State's
transposition, infringement cases) to how MEPs and Member States voted on the law.

## Principles (non-negotiable)

1. **Real utility over surface completeness.** Every feature answers a question someone actually has.
2. **Source integrity.** Only official data; nothing invented. Missing data is shown as missing. We separate
   *recorded facts*, *calculated statistics*, *editorial selections* and *unavailable information*.
3. **Accessible, not simplistic.** "Approved by Parliament" — not "Passed" — when the Council hasn't agreed.
4. **Nonpartisan.** Neutral labels; no rankings of parties or countries; disagreement documented, never invented.
5. **Simplicity.** Seven primary destinations; complexity revealed on request.
6. **Privacy by design.** No analytics, cookies or third-party requests.

## Information architecture

Discover (home) · Legislation · Insights · Votes · People & Parties · Countries · How the EU Works — with search
everywhere. Insights charts patterns across the records (where tracked files stand, proposals and adoptions by year,
Parliament's votes on complete texts, positions recorded by each government in the Council), each chart also given
in text, with a note on what the figures cannot show. Detail pages (a law, a vote, an MEP, a group, a national party, a country) live inside these.
What changed (the steps, votes and status changes recorded week by week, by topic) is a view of Legislation, not an
eighth destination: the home page opens with its latest week ("This week in EU law"), and Legislation and the footer
link it.

## What "done" means for the first release

See the acceptance criteria in `docs/PLAN.md`. The release is honest about coverage: where a source is not
available in a machine-readable form (e.g. the Single Market Scoreboard's headline indicators, published only in
embedded Power BI reports), the site says so instead of filling the gap.
