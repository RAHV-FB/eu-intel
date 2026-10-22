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
| Council voting results (consilium.europa.eu) | HTML / open data | ❌ 403 "Browser check" | Member State positions | See Council section below |
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

## Sections completed by the ingestion modules

(Filled in from module findings — see below.)
