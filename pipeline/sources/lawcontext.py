"""The law in context, from EUR-Lex / Cellar: official summaries, court cases, consolidated texts, advisory opinions.

For each act of the EUR-Lex snapshot (data/snapshot/eurlex/acts.json) and each procedure of the EP snapshot, what
Cellar records about it beyond the act's own record. Joined only by official identifiers (CELEX, procedure
reference); nothing is matched by title.

- Summaries of EU legislation (EUR-Lex, "LEGISSUM"): `?s cdm:summary_summarizes_work ?act`, with the summary's
  identifier (cdm:summary_legislation_eu_id_legissum, "310401_2"), last update (cdm:work_date_document), obsolete flag
  (cdm:summary_legislation_eu_obsolete), English title and one-sentence abstract, and the types of its English text
  (xhtml5, xhtml, fmx4). On 5 November 2026, 576 of the 1,279 acts had one (44 summaries obsolete). The text is
  fetched by Cellar content negotiation: GET https://publications.europa.eu/resource/legissum/{id} with
  Accept-Language: eng and Accept: "application/xhtml+xml;type=xhtml5" (current summaries), else
  "application/xhtml+xml" or "text/html" (summaries of 2014-2022 in earlier formats; each answers only its own type).
  Kept as plain text: the opening section ("WHAT IS THE AIM OF THE REGULATION?", or "WHAT DOES THIS DIRECTIVE DO?"),
  else the first paragraphs of "KEY POINTS" (or "SUMMARY"): at most three paragraphs and six with list items (whose
  places are kept, so that a list is shown as one), about 900 characters. Glossary markers (an asterisk after a
  defined term) are dropped; nothing else is changed. A summary's text is read again only when its date
  changes (or the reader does, PARSER_VERSION); obsolete summaries are not read (the site does not show them).
- Court cases on each act:
  - judgments and orders interpreting it (cdm:case-law_interpretes_resource_legal), with the case identifier of their
    English expression ("Case C-312/24", "Joined Cases C-26/22 and C-64/22");
  - new cases concerning it, from the Official Journal notice of the case: requests for a preliminary ruling
    (cdm:communication_case_new_submits_preliminary_question_resource_legal) and actions for annulment
    (..._requests_annulment_of_resource_legal, ..._requests_partial_annulment_of_resource_legal). A notice belongs to
    the case's Cellar file (a cdm:case_court, "C-660/26"); the case is "decided" when that file lists a judgment or
    order (CELEX 6YYYY{CJ,CO,TJ,TO}...), an event of the delivery of one (DELIV_JUDG_ORDER) or of the publication of
    the decision (CC_CD_PUB_OJ), or the status closed or withdrawn, or when a judgment interpreting the act names the
    case (joined cases are decided under the first case's number); "pending" when it lists none of these; not known
    when the notice links no case file (5 November 2026, of the 922 notices on the acts: none of the 453 of cases
    lodged before 2023, 53 of the 117 of 2023, all but one of the 352 since). The file's status "in progress" is not
    used: it is not kept up to date (C-26/22, decided on 7 December 2023, still has it).
  Annulments and declarations of invalidity themselves are read by the eurlex source (LegalAct.court_rulings).
- Consolidated versions of each act (cdm:act_consolidated_consolidates_resource_legal), only those of the act
  itself: the answer also lists versions of acts it amended (for NIS2, 02018L1972-20241018 and 02014R0910-20241018
  besides 02022L2555-20221227), so a version must have the act's own CELEX with "0" for its sector.
- Opinions of the European Economic and Social Committee and the European Committee of the Regions in a procedure's
  file (cdm:work_part_of_dossier of the procedure's dossier, cdm:work_created_by_agent EESC or COR).
- Actions against the withdrawal of a proposal (data/snapshot/lawcontext/procedure_cases.json): for a procedure the
  Commission withdrew (eurlex procedure_notices), a new case whose notice seeks the annulment of an act in the
  procedure's file that renders the procedure's proposal obsolete (the withdrawal notice) and cites that proposal.
  On 5 November 2026: Case C-727/25, the European Parliament's action (lodged 14 November 2025) for the partial
  annulment of the Commission's notice "Withdrawal of Commission proposals" (52025XC05423) as regards the proposal on
  standard essential patents (52023PC0232), 2023/0133(COD); the case file records no judgment or order.

Reuse: the summaries are documents of the Publications Office (each XHTML text carries "© European Union, <year>",
author PUBL). Commission Decision 2011/833/EU, Article 1, covers "documents held by the Commission or on its behalf by
the Publications Office"; reuse is authorised for commercial or non-commercial purposes (Article 4), on conditions
that may include acknowledging the source and not distorting the original meaning or message of the documents
(Article 6(2)). The site quotes the opening section unchanged, labelled with its source and date, and links the full
summary.

Produces data/snapshot/lawcontext/: acts.json (ActContext, one per act of the eurlex snapshot), summaries.json
(OfficialSummary), opinions.json (AdvisoryOpinion), procedure_cases.json (ProcedureCase). Requests: SPARQL queries of
BATCH acts or procedures each (VALUES blocks), about 30 a run; summary texts one by one, only those due. A query that
fails, or answers with less than half of the links recorded for its batch (Cellar can cut an answer short and still
answer HTTP 200), leaves that batch's records as they were and makes the run "partial". Stops starting new
downloads after EU_INTEL_FETCH_BUDGET_S; the texts left are read next run.
"""

from __future__ import annotations

import html
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from html.parser import HTMLParser
from typing import Any

from pipeline.http import HttpError
from pipeline.models.entities import (
    ActContext,
    AdvisoryOpinion,
    ConsolidatedVersion,
    CourtCase,
    CourtDecision,
    LegalAct,
    OfficialSummary,
    Procedure,
    ProcedureCase,
    ProcedureNotice,
    SourceRef,
    SourceStatus,
)
from pipeline.snapshot import fetch_deadline, now_iso, read_records, write_records
from pipeline.sources.eurlex import AUTH, ENG, PREFIXES, eurlex_url, format_procedure_ref

log = logging.getLogger("pipeline.sources.lawcontext")

SOURCE_ID = "lawcontext"
PARSER_VERSION = 1
BATCH = 300  # acts or procedures per query (5 queries of each kind for the 1,279 acts of November 2026)
SUMMARY_URL = "https://publications.europa.eu/resource/legissum/{id}"
SUMMARY_PAGE = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=LEGISSUM:{id}"
# Accept headers by manifestation type, in the order tried: each text answers only its own type (a current summary is
# not served as text/html, a 2014 one only as text/html)
ACCEPT = (
    ("xhtml5", "application/xhtml+xml;type=xhtml5"),
    ("xhtml", "application/xhtml+xml"),
    ("xhtml", "text/html"),
)
AIM_PARAGRAPHS = 3  # at most this many paragraphs of the opening section (list items aside)
AIM_BLOCKS = 6  # and at most this many paragraphs and list items in all
AIM_CHARS = 900  # no further paragraph once the kept ones are this long
PARAGRAPH_CHARS = 1200  # a longer paragraph is cut after its last full sentence within this length, with "…"
MIN_LINKS_CHECKED = 10  # a batch answer with fewer than half the links recorded (at least this many) is incomplete
BODIES = {"EESC": "EESC", "COR": "CoR"}  # corporate-body codes of the authors of advisory opinions
DECIDED_STATUS = {"CLOSED", "WITHDRAW"}  # case-status codes of a case file: closed, withdrawn
DECIDED_EVENTS = {"DELIV_JUDG_ORDER", "CC_CD_PUB_OJ"}  # judgment or order delivered; decision published in the OJ
DECISION_CELEX_RE = re.compile(r"^6\d{4}(CJ|CO|TJ|TO)\d{4}")  # a judgment or order of either court
CASE_KINDS = {
    "communication_case_new_submits_preliminary_question_resource_legal": "preliminary_reference",
    "communication_case_new_requests_annulment_of_resource_legal": "annulment",
    "communication_case_new_requests_partial_annulment_of_resource_legal": "annulment",
}
GENERIC_PARTIES = {"IC"}  # fd_110 "Institutions": a category, not a party's name


# ------------------------------------------------------------------------------------------------ identifiers
def cellar_ref(reference: str) -> str | None:
    """EP "2021/0106(COD)" -> Cellar "2021/0106/COD"; None for other shapes (a split part such as "2016/0224A(COD)")."""
    m = re.fullmatch(r"(\d{4})/(\d{4})\(([A-Z]{3})\)", reference or "")
    return f"{m[1]}/{m[2]}/{m[3]}" if m else None


def case_number(celex: str) -> str | None:
    """The case number a sector-6 CELEX number gives: "62024CJ0312" -> "C-312/24", "62025TN0730" -> "T-730/25"."""
    m = re.fullmatch(r"6(\d{4})([CT])[A-Z]0*(\d+)", celex or "")
    return f"{m[2]}-{m[3]}/{m[1][2:]}" if m else None


_CASE_NO = re.compile(r"\b([CT])-(\d+)/(\d{2})\b")


def case_numbers(identifier: str | None) -> set[str]:
    """The case numbers in a published case identifier: "Joined Cases C-26/22 and C-64/22" -> {C-26/22, C-64/22};
    a range "Joined Cases C-541/20 to C-555/20" gives every number in it."""
    text = identifier or ""
    out = {f"{c}-{n}/{y}" for c, n, y in _CASE_NO.findall(text)}
    for a, b in re.findall(r"([CT]-\d+/\d{2})\s+to\s+([CT]-\d+/\d{2})", text):
        (ca, na, ya), (cb, nb, yb) = _CASE_NO.match(a).groups(), _CASE_NO.match(b).groups()  # type: ignore[union-attr]
        if ca == cb and ya == yb and 0 < int(nb) - int(na) < 200:
            out |= {f"{ca}-{n}/{ya}" for n in range(int(na), int(nb) + 1)}
    return out


def _code(uri: str | None) -> str:
    return (uri or "").rstrip("/").rsplit("/", 1)[-1]


def _date(v: str | None) -> str | None:
    return v[:10] if v and re.match(r"^\d{4}-\d{2}-\d{2}", v) else None


def _values(var: str, items: Iterable[str]) -> str:
    return f"VALUES ?{var} {{ " + " ".join(f'"{x}"^^xsd:string' for x in items) + " }"


def batches[T](items: list[T], size: int = BATCH) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# ---------------------------------------------------------------------------------------------------- queries
def summaries_query(celexes: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?c ?id ?date ?obsolete ?title ?abstract ?mtype WHERE {{
  {_values("c", celexes)}
  ?w cdm:resource_legal_id_celex ?c .
  ?s cdm:summary_summarizes_work ?w ; cdm:summary_legislation_eu_id_legissum ?id .
  OPTIONAL {{ ?s cdm:work_date_document ?date }}
  OPTIONAL {{ ?s cdm:summary_legislation_eu_obsolete ?obsolete }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?s ; cdm:expression_uses_language <{ENG}> .
    OPTIONAL {{ ?e cdm:expression_title ?title }}
    OPTIONAL {{ ?e cdm:expression_abstract ?abstract }}
    OPTIONAL {{ ?m cdm:manifestation_manifests_expression ?e ; cdm:manifestation_type ?mtype }} }}
}}"""
    )


def consolidated_query(celexes: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?c ?cc ?cdate WHERE {{
  {_values("c", celexes)}
  ?w cdm:resource_legal_id_celex ?c .
  ?k cdm:act_consolidated_consolidates_resource_legal ?w ; cdm:resource_legal_id_celex ?cc .
  FILTER(STRSTARTS(STR(?cc), CONCAT("0", SUBSTR(STR(?c), 2), "-")))
  OPTIONAL {{ ?k cdm:act_consolidated_date ?cdate }}
}}"""
    )


def interpretations_query(celexes: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?c ?j ?date ?ecli WHERE {{
  {_values("c", celexes)}
  ?w cdm:resource_legal_id_celex ?c .
  ?s cdm:case-law_interpretes_resource_legal ?w ; cdm:resource_legal_id_celex ?j .
  OPTIONAL {{ ?s cdm:work_date_document ?date }}
  OPTIONAL {{ ?s cdm:case-law_ecli ?ecli }}
}}"""
    )


def case_ids_query(judgments: list[str]) -> str:
    """The case identifier of each judgment's English expression (a separate query: in the query above it is slow)."""
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?j ?case WHERE {{
  {_values("j", judgments)}
  ?s cdm:resource_legal_id_celex ?j .
  ?e cdm:expression_belongs_to_work ?s ; cdm:expression_uses_language <{ENG}> ;
     cdm:expression_case-law_identifier_case ?case .
}}"""
    )


def _case_file(notice: str, var: str = "cd") -> str:
    """The case's Cellar file of a notice ?{notice}: its number, status, decision events and decisions listed."""
    return f"""OPTIONAL {{ ?{notice} cdm:work_part_of_dossier ?{var} . ?{var} a cdm:case_court ; cdm:dossier_title ?case .
    OPTIONAL {{ ?{var} cdm:case_court_has_case-status ?status }}
    OPTIONAL {{ ?ev cdm:event_part_of_dossier ?{var} ; cdm:event_has_type_concept_type_event ?etype }}
    OPTIONAL {{ ?x cdm:work_part_of_dossier ?{var} ; cdm:resource_legal_id_celex ?decided
               FILTER(REGEX(STR(?decided), "^6[0-9]{{4}}(CJ|CO|TJ|TO)")) }} }}"""


def cases_query(celexes: list[str]) -> str:
    kinds = " ".join(f"cdm:{p}" for p in CASE_KINDS)
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?c ?p ?n ?lodged ?case ?status ?etype ?decided WHERE {{
  {_values("c", celexes)}
  VALUES ?p {{ {kinds} }}
  ?w cdm:resource_legal_id_celex ?c .
  ?s ?p ?w ; cdm:resource_legal_id_celex ?n .
  OPTIONAL {{ ?s cdm:work_date_document ?lodged }}
  {_case_file("s")}
}}"""
    )


def opinions_query(refs: list[str]) -> str:
    bodies = " ".join(f"<{AUTH}corporate-body/{b}>" for b in BODIES)
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?ref ?celex ?agent ?date ?title WHERE {{
  {_values("ref", refs)}
  VALUES ?agent {{ {bodies} }}
  ?d cdm:procedure_code_interinstitutional_reference_procedure ?ref .
  ?w cdm:work_part_of_dossier ?d ; cdm:work_created_by_agent ?agent ; cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?w cdm:work_date_document ?date }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language <{ENG}> ; cdm:expression_title ?title }}
}}"""
    )


def withdrawal_cases_query(refs: list[str]) -> str:
    """New cases seeking the annulment of an act in the procedure's file that renders its proposal obsolete (the
    withdrawal notice) and citing that proposal."""
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?ref ?n ?lodged ?target ?proposal ?applicant ?alabel ?case ?status ?etype ?decided WHERE {{
  {_values("ref", refs)}
  VALUES ?p {{ cdm:communication_case_new_requests_annulment_of_resource_legal
              cdm:communication_case_new_requests_partial_annulment_of_resource_legal }}
  ?d cdm:procedure_code_interinstitutional_reference_procedure ?ref .
  ?t cdm:work_part_of_dossier ?d ; cdm:resource_legal_id_celex ?target .
  ?s ?p ?t ; cdm:resource_legal_id_celex ?n ; cdm:work_cites_work ?pw .
  ?t cdm:resource_legal_renders_obsolete_resource_legal ?pw .
  ?pw cdm:work_part_of_dossier ?d ; cdm:resource_legal_id_celex ?proposal .
  OPTIONAL {{ ?s cdm:work_date_document ?lodged }}
  OPTIONAL {{ ?s cdm:communication_cjeu_requested_by_agent ?applicant .
    OPTIONAL {{ ?applicant skos:prefLabel ?alabel FILTER(LANG(?alabel) = "en") }} }}
  {_case_file("s")}
}}"""
    )


# ------------------------------------------------------------------------------------------- answers -> records
def _case_state(f: dict[str, Any], decided_cases: set[str]) -> str | None:
    """'decided', 'pending' or None (no case file) from what a notice's case file lists (see the module docstring)."""
    if f["case"] and f["case"] in decided_cases:
        return "decided"
    if f["decided"] or f["events"] & DECIDED_EVENTS or f["status"] & DECIDED_STATUS:
        return "decided"
    return "pending" if f["case"] else None


def _case_files(rows: list[dict[str, str]], key: Callable[[dict[str, str]], tuple]) -> dict[tuple, dict[str, Any]]:
    """The rows of a cases query grouped by `key`, with their case file's facts merged."""
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        f = out.setdefault(key(r), {"case": None, "status": set(), "events": set(), "decided": set(), "lodged": None,
                                    "kinds": set(), "applicants": set(), "row": r})  # fmt: skip
        f["case"] = f["case"] or (r.get("case") or "").strip() or None
        f["lodged"] = f["lodged"] or _date(r.get("lodged"))
        if r.get("status"):
            f["status"].add(_code(r["status"]))
        if r.get("etype"):
            f["events"].add(_code(r["etype"]))
        if DECISION_CELEX_RE.match(r.get("decided") or ""):
            f["decided"].add(r["decided"])
        if r.get("p"):
            f["kinds"].add(CASE_KINDS.get(r["p"].rsplit("#", 1)[-1], ""))
        if r.get("applicant") and _code(r["applicant"]) not in GENERIC_PARTIES:
            f["applicants"].add(" ".join((r.get("alabel") or _code(r["applicant"])).split()))
    return out


def parse_consolidated(rows: list[dict[str, str]]) -> dict[str, list[ConsolidatedVersion]]:
    out: dict[str, dict[str, ConsolidatedVersion]] = defaultdict(dict)
    for r in rows:
        c, cc = r.get("c", ""), r.get("cc", "")
        # only the act's own versions ("02022L2555-20221227" for 32022L2555), dated
        m = re.fullmatch(r"0(\d{4}[A-Z]\d{4})-(\d{4})(\d{2})(\d{2})", cc)
        if not m or m[1] != c[1:]:
            continue
        d = _date(r.get("cdate")) or f"{m[2]}-{m[3]}-{m[4]}"
        out[c][cc] = ConsolidatedVersion(celex=cc, date=d)
    return {c: sorted(v.values(), key=lambda x: (x.date, x.celex)) for c, v in out.items()}


def parse_interpretations(rows: list[dict[str, str]], case_ids: dict[str, str]) -> dict[str, list[CourtDecision]]:
    out: dict[str, dict[str, CourtDecision]] = defaultdict(dict)
    for r in rows:
        j = r.get("j", "")
        if not DECISION_CELEX_RE.match(j):
            continue
        out[r["c"]][j] = CourtDecision(celex=j, case=case_ids.get(j), date=_date(r.get("date")), ecli=r.get("ecli") or None)
    return {c: sorted(v.values(), key=lambda x: (x.date or "", x.celex)) for c, v in out.items()}


def parse_cases(rows: list[dict[str, str]], decided_by_act: dict[str, set[str]]) -> dict[str, list[CourtCase]]:
    """Each act's cases, from a cases query's rows; `decided_by_act`: the case numbers of the judgments and orders
    interpreting the act (a case decided jointly under another case's number)."""
    files = _case_files(rows, key=lambda r: (r["c"], r["n"]))
    out: dict[str, list[CourtCase]] = defaultdict(list)
    for (c, n), f in files.items():
        kind = "annulment" if "annulment" in f["kinds"] else "preliminary_reference"
        out[c].append(CourtCase(celex=n, case=f["case"], kind=kind, lodged=f["lodged"],  # type: ignore[arg-type]
                                state=_case_state(f, decided_by_act.get(c, set()))))  # type: ignore[arg-type]  # fmt: skip
    return {c: sorted(v, key=lambda x: (x.lodged or "", x.celex)) for c, v in out.items()}


def parse_opinions(rows: list[dict[str, str]], retrieved: str) -> list[AdvisoryOpinion]:
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        body = BODIES.get(_code(r.get("agent")))
        ref = format_procedure_ref(r.get("ref", ""))
        celex = r.get("celex", "")
        if not (body and ref and re.fullmatch(r"5\d{4}[A-Z]{2}\d{4}(\(\d{2}\))?", celex)):
            continue
        o = by.setdefault(celex, {"body": body, "refs": set(), "date": None, "titles": set()})
        o["refs"].add(ref)
        o["date"] = o["date"] or _date(r.get("date"))
        if r.get("title"):
            o["titles"].add(" ".join(r["title"].split()))
    return [
        AdvisoryOpinion(
            celex=c, body=o["body"], procedure_refs=sorted(o["refs"]), date=o["date"],
            title=min(o["titles"]) if o["titles"] else None, url=eurlex_url(c),
            source=SourceRef(institution="EUR-Lex", url=eurlex_url(c), label=f"EUR-Lex – opinion, CELEX {c}",
                             identifier=c, retrieved_at=retrieved),
        )  # fmt: skip
        for c, o in sorted(by.items())
    ]


def parse_withdrawal_cases(rows: list[dict[str, str]], retrieved: str) -> list[ProcedureCase]:
    files = _case_files(rows, key=lambda r: (r["ref"], r["n"], r["target"], r["proposal"]))
    out: dict[str, ProcedureCase] = {}
    for (ref, n, target, proposal), f in files.items():
        reference = format_procedure_ref(ref)
        if not reference:
            continue
        pid = f"{n}:{reference}"
        out[pid] = ProcedureCase(
            id=pid, celex=n, reference=reference, case=f["case"], lodged=f["lodged"], annulled=target,
            proposal=proposal, applicants=sorted(f["applicants"]), state=_case_state(f, set()),  # type: ignore[arg-type]
            source=SourceRef(institution="EUR-Lex", url=eurlex_url(n), label=f"EUR-Lex – notice of Case {f['case'] or n}",
                             identifier=n, retrieved_at=retrieved),
        )  # fmt: skip
    return sorted(out.values(), key=lambda x: x.id)


def parse_summaries(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Summary id -> its metadata and the acts (of the query) it summarises."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        sid = (r.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{2,40}", sid):
            continue
        s = out.setdefault(sid, {"acts": set(), "date": None, "obsolete": False, "titles": set(), "abstract": None,
                                 "formats": set()})  # fmt: skip
        s["acts"].add(r["c"])
        s["date"] = max(filter(None, (s["date"], _date(r.get("date")))), default=None)
        s["obsolete"] = s["obsolete"] or (r.get("obsolete") or "").strip() in ("1", "true")
        if r.get("title"):
            s["titles"].add(" ".join(r["title"].split()))
        if r.get("abstract") and not s["abstract"]:
            s["abstract"] = plain_fragment(r["abstract"]) or None
        if r.get("mtype"):
            s["formats"].add(r["mtype"].strip())
    return out


# ------------------------------------------------------------------------------------------- summary texts
def plain_fragment(markup: str) -> str:
    """Plain text of a short XML/HTML fragment (the abstract: <div><description>…</description></div>)."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup or "")).split())


class _Blocks(HTMLParser):
    """The text of a summary as a list of blocks: (level, text, item), level 1-2 a chapter heading (h1, h2, an older
    text's <p class="ti-main"> / "ti-chapter"), 3 a lower heading, 0 a paragraph or list item (`item`: inside <li>).
    Inline markup adds nothing; the glossary links of older texts (<a href="#keyterm_...">*</a>) are dropped."""

    HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 3, "h5": 3, "h6": 3}
    BLOCKS = {"p", "li", "td", "th", "dd", "dt", "div", "section", "header", "footer", "ul", "ol", "table", "tr",
              "tbody", "body", "blockquote"}  # fmt: skip

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[int, str, bool]] = []
        self._buf: list[str] = []
        self._level = 0
        self._li = 0  # depth of the <li> elements open
        self._skip = 0  # inside <script>, <style>, <head> or a glossary marker link

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.blocks.append((self._level, text, self._li > 0 and self._level == 0))
        self._buf, self._level = [], 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in ("script", "style", "head") or (tag == "a" and (a.get("href") or "").startswith("#keyterm")):
            self._skip += 1
            return
        if tag in self.HEADINGS or tag in self.BLOCKS:
            self._flush()
            cls = a.get("class") or ""
            if tag == "li":
                self._li += 1
            if tag in self.HEADINGS:
                self._level = self.HEADINGS[tag]
            elif tag == "p" and re.search(r"\bti-(?:main|chapter)\b", cls):
                self._level = 2
            elif tag == "p" and re.search(r"\bti-grseq", cls):
                self._level = 3
        elif tag == "br":
            self._buf.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head", "a") and self._skip:
            self._skip -= 1
            return
        if tag in self.HEADINGS or tag in self.BLOCKS:
            self._flush()
            if tag == "li" and self._li:
                self._li -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)


AIM_RE = re.compile(r"^(?:WHAT (?:IS|ARE) THE (?:MAIN )?AIMS? OF\b|WHAT DOES (?:THE|THIS)\b.*\bDO\b)", re.IGNORECASE)
KEY_POINTS_RE = re.compile(r"^(?:KEY POINTS|SUMMARY)\s*:?$", re.IGNORECASE)
GLOSSARY_MARK_RE = re.compile(r"(?<=[\w)’'])\s?\*(?=[\s,.;:)]|$)")  # "plants*," -> "plants,"
ENUMERATOR_RE = re.compile(r"^(?:\(?(?:\d{1,3}|[ivx]{1,4}|[a-z])[.)]|[–—•-])$", re.IGNORECASE)  # "1.", "(a)", "—"


def _clean(text: str) -> str:
    return " ".join(GLOSSARY_MARK_RE.sub("", text).split())


def _is_label(text: str) -> bool:
    """A line set as a heading inside a section ("Operational objectives", in bold in older texts): short, with no
    sentence punctuation at its end."""
    return len(text) <= 80 and len(text.split()) <= 8 and not re.search(r"[.!?:;…,]$", text)


def _cut(text: str, limit: int = PARAGRAPH_CHARS) -> str:
    """A paragraph longer than `limit`: cut after its last full sentence within it (else its last word), with "…"."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    end = max(head.rfind(". "), head.rfind("; "))
    head = head[: end + 1] if end > limit // 3 else head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:") + " …"


def summary_text(body: bytes) -> tuple[list[str], str | None, bool, list[int]]:
    """(paragraphs, heading, complete, items): the opening section of a summary's text, see the module docstring;
    `items`: the indexes of the paragraphs that are list items in the text (an <li>, or a numbered row of an older
    text's table). ([], None, True, []) when the text has none of the sections looked for."""
    p = _Blocks()
    p.feed(body.decode("utf-8", errors="replace"))
    p.close()
    p._flush()
    blocks = p.blocks
    for pattern in (AIM_RE, KEY_POINTS_RE):
        start = next((i for i, (lvl, t, _) in enumerate(blocks) if 1 <= lvl <= 2 and pattern.search(t)), None)
        if start is None:
            continue
        paras: list[str] = []
        items: list[int] = []
        more = numbered = False
        for lvl, t, item in blocks[start + 1 :]:
            if 1 <= lvl <= 2:
                break
            text = _clean(t)
            if not text:
                continue
            if ENUMERATOR_RE.match(text):  # the number of an older text's numbered row: the next block is an item
                numbered = True
                continue
            is_item, numbered = item or numbered, False
            # a lower heading inside the section ("Individuals' rights"): skipped before the first paragraph, after
            # it the end of the opening part
            if lvl == 3 or (_is_label(text) and not is_item):
                if paras:
                    more = True
                    break
                continue
            prose = len(paras) - len(items) + (not is_item)
            if len(paras) >= AIM_BLOCKS or prose > AIM_PARAGRAPHS or (paras and sum(map(len, paras)) >= AIM_CHARS):
                more = True
                break
            if is_item:
                items.append(len(paras))
            paras.append(_cut(text))
        if paras:
            complete = not more and not any(x.endswith(" …") for x in paras)
            return paras, " ".join(blocks[start][1].split()), complete, items
    return [], None, True, []


def fetch_summary_text(http: Any, sid: str, formats: Iterable[str]) -> bytes:
    """The English text of summary `sid` by content negotiation, in the first format it is served in."""
    url = SUMMARY_URL.format(id=sid)
    have = set(formats)
    last: Exception | None = None
    for fmt, accept in ACCEPT:
        if have and fmt not in have:
            continue
        try:
            return http.get(url, headers={"Accept": accept, "Accept-Language": "eng"}, use_cache=False)
        except HttpError as e:
            last = e
    raise last or HttpError(url, None, "no text format recorded")


# ------------------------------------------------------------------------------------------------------ fetch
class _Answers:
    """Runs the batched queries of one kind; a batch that fails or comes back short keeps its earlier records."""

    def __init__(self, http: Any) -> None:
        self.http = http
        self.failed: list[str] = []

    def run(
        self,
        kind: str,
        items: list[str],
        query: Callable[[list[str]], str],
        parse: Callable[[list[dict[str, str]]], dict[str, list[Any]]],
        stored: dict[str, list[Any]],
    ) -> tuple[dict[str, list[Any]], set[str]]:
        """(item -> values, the items answered). Items of a batch not answered keep `stored`'s values."""
        out: dict[str, list[Any]] = {}
        answered: set[str] = set()
        for batch in batches(items):
            try:
                rows = self.http.sparql(query(batch), use_cache=False)
            except Exception as e:  # noqa: BLE001 - one failed batch keeps its earlier records
                log.warning("lawcontext: %s query failed for %d items: %r", kind, len(batch), e)
                self.failed.append(f"{kind} ({len(batch)} items: query failed)")
                continue
            new = parse(rows)
            before = sum(len(stored.get(c, [])) for c in batch)
            after = sum(len(new.get(c, [])) for c in batch)
            if before >= MIN_LINKS_CHECKED and after < before / 2:
                log.warning("lawcontext: %s answer has %d links for a batch with %d recorded; kept", kind, after, before)
                self.failed.append(f"{kind} ({len(batch)} items: answer with {after} links, {before} recorded)")
                continue
            answered.update(batch)
            out.update({c: v for c, v in new.items() if c in batch})
        return out, answered


def fetch(http: Any) -> SourceStatus:
    attempted = now_iso()
    deadline = fetch_deadline()
    acts = sorted(read_records("eurlex", "acts", LegalAct), key=lambda a: a.celex)
    if not acts:
        raise RuntimeError("no EUR-Lex acts in the snapshot: run the eurlex source first")
    celexes = [a.celex for a in acts]
    known = set(celexes)
    prev_ctx = {r.celex: r for r in read_records(SOURCE_ID, "acts", ActContext)}
    prev_sum = {r.id: r for r in read_records(SOURCE_ID, "summaries", OfficialSummary)}
    q = _Answers(http)

    # consolidated versions, judgments interpreting the acts, cases concerning them
    cons, cons_ok = q.run("consolidated", celexes, consolidated_query, parse_consolidated,
                          {c: r.consolidated for c, r in prev_ctx.items()})  # fmt: skip
    raw_interp: dict[str, list[dict[str, str]]] = {}

    def keep_rows(rows: list[dict[str, str]]) -> dict[str, list[Any]]:
        by: dict[str, list[dict[str, str]]] = defaultdict(list)
        for r in rows:
            by[r["c"]].append(r)
        raw_interp.update(by)
        return dict(by)

    _, interp_ok = q.run("interpretations", celexes, interpretations_query, keep_rows,
                         {c: r.interpreted_by for c, r in prev_ctx.items()})  # fmt: skip
    judgments = sorted({r["j"] for rows in raw_interp.values() for r in rows if DECISION_CELEX_RE.match(r.get("j", ""))})
    case_ids: dict[str, str] = {}
    for batch in batches(judgments):
        try:
            for r in http.sparql(case_ids_query(batch), use_cache=False):
                case_ids.setdefault(r["j"], " ".join(r["case"].split()))
        except Exception as e:  # noqa: BLE001 - the case identifiers are then those recorded earlier, if any
            log.warning("lawcontext: case identifiers not fetched: %r", e)
            q.failed.append(f"case identifiers ({len(batch)} judgments)")
    earlier_ids = {d.celex: d.case for r in prev_ctx.values() for d in r.interpreted_by if d.case}
    interp = parse_interpretations([r for rows in raw_interp.values() for r in rows], {**earlier_ids, **case_ids})
    decided_by_act = {
        c: {n for d in v for n in case_numbers(d.case) | ({case_number(d.celex)} - {None})}  # type: ignore[operator]
        for c, v in interp.items()
    }
    cases, cases_ok = q.run("cases", celexes, cases_query, lambda rows: parse_cases(rows, decided_by_act),
                            {c: r.cases for c, r in prev_ctx.items()})  # fmt: skip

    contexts: list[ActContext] = []
    for c in celexes:
        prev = prev_ctx.get(c)
        rec = ActContext(
            celex=c,
            consolidated=cons.get(c, []) if c in cons_ok else (prev.consolidated if prev else []),
            interpreted_by=interp.get(c, []) if c in interp_ok else (prev.interpreted_by if prev else []),
            cases=cases.get(c, []) if c in cases_ok else (prev.cases if prev else []),
            source=SourceRef(institution="EUR-Lex", url=eurlex_url(c), identifier=c, retrieved_at=attempted,
                             label=f"EUR-Lex (Cellar) – case law, consolidated versions of CELEX {c}"),
        )  # fmt: skip
        contexts.append(rec)

    # summaries: metadata of every summary of the acts, then the texts due
    meta: dict[str, dict[str, Any]] = {}
    sum_ok: set[str] = set()
    for batch in batches(celexes):
        try:
            rows = http.sparql(summaries_query(batch), use_cache=False)
        except Exception as e:  # noqa: BLE001 - the batch's summaries keep their earlier records
            log.warning("lawcontext: summaries query failed for %d acts: %r", len(batch), e)
            q.failed.append(f"summaries ({len(batch)} acts: query failed)")
            continue
        got = parse_summaries(rows)
        before = sum(1 for s in prev_sum.values() if set(s.acts) & set(batch))
        if before >= MIN_LINKS_CHECKED and len(got) < before / 2:
            q.failed.append(f"summaries ({len(batch)} acts: answer with {len(got)} summaries, {before} recorded)")
            continue
        sum_ok.update(batch)
        for sid, s in got.items():
            m = meta.setdefault(sid, {**s, "acts": set()})
            m["acts"] |= s["acts"]
            m["date"] = max(filter(None, (m["date"], s["date"])), default=None)
            m["titles"] = m["titles"] | s["titles"]
            m["formats"] = m["formats"] | s["formats"]
            m["obsolete"] = m["obsolete"] or s["obsolete"]
    if not (cons_ok or interp_ok or cases_ok or sum_ok):  # nothing written: the previous files stay as they are
        raise RuntimeError(f"no Cellar query answered: {'; '.join(q.failed[:5])}")
    summaries: dict[str, OfficialSummary] = {}
    for sid, s in prev_sum.items():  # a summary of an act whose batch was not answered keeps its record
        if set(s.acts) & known and not set(s.acts) & sum_ok:
            summaries[sid] = s
    for sid, s in meta.items():
        old = prev_sum.get(sid)
        acts_of = sorted((s["acts"] & sum_ok) | (set(old.acts) - sum_ok if old else set()))
        title = min(s["titles"]) if s["titles"] else (old.title if old else sid)
        rec = OfficialSummary(
            id=sid, acts=[c for c in acts_of if c in known], title=title, date=s["date"], obsolete=s["obsolete"],
            abstract=s["abstract"] or (old.abstract if old else None), formats=sorted(s["formats"]),
            url=SUMMARY_PAGE.format(id=sid),
            source=SourceRef(institution="EUR-Lex", url=SUMMARY_PAGE.format(id=sid), identifier=f"LEGISSUM:{sid}",
                             label=f"EUR-Lex – summary of EU legislation “{title}”", retrieved_at=attempted,
                             published=s["date"]),
        )  # fmt: skip
        if old and old.text_status == "ok":  # its text as last read (of the version dated text_date)
            rec = rec.model_copy(update={k: getattr(old, k) for k in ("aim", "aim_items", "aim_heading",
                                                                       "aim_complete", "text_status", "text_date",
                                                                       "parser")})  # fmt: skip
        summaries[sid] = rec

    due = sorted(
        (s for s in summaries.values() if not s.obsolete and s.acts
         and (s.text_status != "ok" or s.text_date != s.date or s.parser < PARSER_VERSION)),
        key=lambda s: (s.text_status == "ok", s.id),
    )  # fmt: skip — never read first, then those updated since they were read
    read_now = unavailable = 0
    for s in due:
        if deadline is not None and time.monotonic() > deadline:
            break
        try:
            body = fetch_summary_text(http, s.id, s.formats)
        except Exception as e:  # noqa: BLE001 - one text missing must not stop the others
            log.warning("lawcontext: summary %s text not fetched: %r", s.id, e)
            unavailable += 1
            if s.text_status != "ok":  # else the earlier reading stays until it is read again
                summaries[s.id] = s.model_copy(update={"text_status": "unavailable"})
            continue
        paras, heading, complete, items = summary_text(body)
        summaries[s.id] = s.model_copy(update={"aim": paras, "aim_items": items, "aim_heading": heading,
                                               "aim_complete": complete, "text_status": "ok", "text_date": s.date,
                                               "parser": PARSER_VERSION})  # fmt: skip
        read_now += 1

    # procedures: advisory opinions; actions against the withdrawal of a proposal
    procs = read_records("ep_procedures", "procedures", Procedure)
    refs = sorted({r for p in procs if (r := cellar_ref(p.reference))})
    prev_ops = read_records(SOURCE_ID, "opinions", AdvisoryOpinion)
    opinions: dict[str, AdvisoryOpinion] = {}
    for batch in batches(refs):
        try:
            got = parse_opinions(http.sparql(opinions_query(batch), use_cache=False), attempted)
        except Exception as e:  # noqa: BLE001 - the batch's opinions keep their earlier records
            log.warning("lawcontext: opinions query failed for %d procedures: %r", len(batch), e)
            q.failed.append(f"opinions ({len(batch)} procedures: query failed)")
            asked = {format_procedure_ref(r) for r in batch}
            opinions.update({o.celex: o for o in prev_ops if set(o.procedure_refs) & asked})
            continue
        for o in got:
            if o.celex in opinions:  # an opinion on files of two batches
                o = o.model_copy(update={"procedure_refs": sorted(set(o.procedure_refs) | set(opinions[o.celex].procedure_refs))})
            opinions[o.celex] = o
    withdrawn = sorted({r for n in read_records("eurlex", "procedure_notices", ProcedureNotice)
                        if n.kind == "withdrawn" and (r := cellar_ref(n.reference))})  # fmt: skip
    proc_cases: list[ProcedureCase] = []
    try:
        for batch in batches(withdrawn):
            proc_cases += parse_withdrawal_cases(http.sparql(withdrawal_cases_query(batch), use_cache=False), attempted)
    except Exception as e:  # noqa: BLE001 - the actions recorded earlier stay
        log.warning("lawcontext: withdrawal cases query failed: %r", e)
        q.failed.append("actions against withdrawals (query failed)")
        proc_cases = read_records(SOURCE_ID, "procedure_cases", ProcedureCase)

    write_records(SOURCE_ID, "acts", contexts, key=lambda r: r.celex)
    write_records(SOURCE_ID, "summaries", summaries.values(), key=lambda r: r.id)
    write_records(SOURCE_ID, "opinions", opinions.values(), key=lambda r: r.celex)
    write_records(SOURCE_ID, "procedure_cases", proc_cases, key=lambda r: r.id)

    shown = [s for s in summaries.values() if not s.obsolete and s.acts]
    with_text = sum(1 for s in shown if s.text_status == "ok")
    pending_texts = sum(1 for s in shown if s.text_status != "ok" or s.text_date != s.date or s.parser < PARSER_VERSION)
    acts_with = {s for x in shown for s in x.acts}
    n_cons = sum(1 for r in contexts if r.consolidated)
    n_interp = sum(len(r.interpreted_by) for r in contexts)
    pending = {k.celex for r in contexts for k in r.cases if k.state == "pending"}  # distinct cases
    return SourceStatus(
        source=SOURCE_ID,
        status="ok" if not (q.failed or pending_texts) else "partial",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records={
            "acts": len(contexts), "summaries": len(summaries), "summaries_with_text": with_text,
            "summaries_pending": pending_texts, "acts_with_summary": len(acts_with), "acts_consolidated": n_cons,
            "interpretations": n_interp, "pending_cases": len(pending), "opinions": len(opinions),
            "procedure_cases": len(proc_cases),
        },  # fmt: skip
        note=(
            f"{len(contexts)} acts: {len(acts_with)} with a summary of EU legislation ({len(shown)} summaries not "
            f"obsolete, {with_text} with their text read; {read_now} read this run, {unavailable} unavailable"
            + (f", {pending_texts} pending, resumed next run" if pending_texts else "")
            + f"), {n_cons} with a consolidated version, {n_interp} links to judgments or orders interpreting them, "
            f"{len(pending)} cases before the Court with no recorded decision; {len(opinions)} EESC and CoR opinions; "
            f"{len(proc_cases)} actions against the withdrawal of a proposal"
            + (f"; kept from earlier runs: {', '.join(q.failed[:6])}" if q.failed else "")
        ),
    )
