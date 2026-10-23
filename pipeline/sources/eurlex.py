"""EU legal acts from EUR-Lex / Cellar (Publications Office SPARQL endpoint).

Produces data/snapshot/eurlex/acts.json (list[LegalAct]).

Scope (v1)
    Sector-3 regulations, directives and decisions (base acts, CELEX 3YYYY[RLD]NNNN) with a document
    date >= 2014-01-01 that Cellar links to an interinstitutional procedure of type COD (ordinary
    legislative procedure), CNS (consultation) or APP (consent) - i.e. legislative acts and acts
    adopted under a special legislative procedure. Non-legislative (NLE) and budgetary (BUD)
    procedures, implementing/delegated acts and corrigenda are out of scope. CELEX ids listed under
    `celex:` in data/curated/featured.yaml are added whatever their date or procedure, and so are the
    final acts that OEIL records for procedures in the EP snapshot (`Procedure.celex_refs`): Cellar
    does not link every act to its procedure (e.g. Regulation 2019/816 ECRIS-TCN, 2017/0144(COD)).

Requests: one paged scope query (ORDER BY + LIMIT/OFFSET) and a COUNT of its rows (a short page also
ends a truncated answer), then per batch of works (VALUES blocks,
4 threads) one query each for literal properties, English title, Official Journal issue, typed
entry-into-force annotations, end-of-validity comments, procedure codes, subjects and amend/repeal
links, and one query for the procedure notices. A batch that
fails is split in halves down to single works; works whose data could not be fetched are not written
with gaps: they keep their previous record (status "partial"), and so do stored acts missing from a
scope answer whose rows fall short of the count. No query starts after the source's time budget
(EU_INTEL_FETCH_BUDGET_S, EU_INTEL_FETCH_DEADLINE).

Source facts relied on (checked against the live endpoint, see tests/test_eurlex.py)
- The procedure is a `cdm:dossier` (also typed `cdm:procedure_code_interinstitutional`) carrying
  `cdm:procedure_code_interinstitutional_reference_procedure` "2021/0106/COD". The act is linked
  to it by `?dossier cdm:dossier_produces_resource_legal ?act`, `?act
  cdm:resource_legal_produced_by_dossier ?dossier`, or via the adopted proposal
  (`?act cdm:resource_legal_adopts_resource_legal ?proposal . ?proposal cdm:work_part_of_dossier
  ?dossier`). Each path alone misses some acts (e.g. the Chips Act 32023R1781 only has the third).
  Free-text `resource_legal_information_miscellaneous` ("COD 2013/0162") is NOT used. A few
  dossiers' type concept (`..._has_type_concept_type_procedure_code_interinstitutional`, OLP/COD,
  CNS/SLP, APP, NLE...) contradicts the reference suffix (e.g. "2018/0359/COD" typed NLE); such
  references are not linked.
- `cdm:resource_legal_date_entry-into-force` holds several kinds of dates; an OWL axiom on each
  value says which (`annotation:type_of_date`): EV = entry into force, PE = date of effect
  (decisions taking effect on notification), MA / MA/PART / APPLICATION = (partial) application.
  The earliest value is often NOT the entry into force (retroactive application dates, and the
  placeholder 1001-01-01), so entry_into_force is the EV date (else PE); other values become
  other_application_dates, and those marked MA/PART or PE/PART (application of some provisions; in
  the type or in the comment_on_date annotation) are also listed in partial_application_dates. Values without any annotation fall back to "earliest".
  An entry-into-force date that is also marked MA/PART or PE/PART sets partial_on_entry_into_force (DMA
  32022R1925, Art. 54: some provisions apply from its entry into force on 1 November 2022).
- 1001-01-01 (unknown/undetermined) and 9999-12-31 (open-ended) are Cellar placeholder dates.
- Publication: acts in the act-by-act OJ (from Oct 2023) carry `official-journal-act_*`
  properties on the work; older acts link to an OJ issue via
  `resource_legal_published_in_official-journal` (number, collection, publication date).
- Transposition deadlines: `cdm:directive_date_transposition` (may hold several dates, e.g. NIS2
  "adopt and publish by" 2024-10-17 and "apply from" 2024-10-18). An OWL axiom on each value
  (`annotation:comment_on_date`, fd_361 codes) labels it ADOPTION (adopt and publish by),
  APPLICATION (apply from) and/or AU+TARD (at the latest), with the article that sets it
  ("{ART|...} 48.1"); kept as transposition_dates. Older or simpler directives carry no label.
- A value of 1001-01-01 (comment DATNOT, "date of notification") means the date is not recorded. Its
  type tells two cases apart. EV (entry into force), with a comment pointing to an article of the act
  ("V ART 2.2"): the act enters into force on a condition it sets, not yet recorded as met, e.g.
  Electoral Act amendments that need the approval of every Member State (32018D0994):
  entry_into_force_pending, with the article(s) in entry_into_force_articles. PE (date of effect)
  without an EV value: a decision addressed to someone, which takes effect on notification to its
  addressee on a date Cellar does not record, e.g. 32020D0853 "addressed to the Federal Republic of
  Germany": effect_on_notification.
- `cdm:resource_legal_date_end-of-validity` may hold several values (provisions expiring at
  different dates); the act's end of validity is the latest one, None when it is 9999-12-31. The
  `comment_on_date` annotation on a value (fd_330 codes: A/PAR repealed by, AI/PAR implicitly repealed
  by, R/PAR replaced by, FIN/VAL/PART partial end of validity...) and the CELEX ids it names are kept
  as validity_notes, e.g. 32014R1377: 2013-12-31 "AI/PAR 32014R0609" (implicitly repealed, with
  retroactive effect, by the own-resources Regulation 609/2014), 32020D1531: 2024-03-17 "FIN/VAL/PART V
  32024D0867 ART 6" next to 9999-12-31.
- amends / amended_by: `cdm:resource_legal_amends_resource_legal` (both directions). repeals /
  repealed_by: `cdm:resource_legal_repeals_resource_legal` for whole-act repeals only. A link is a
  partial repeal (kept apart, as partly_repeals / partly_repealed_by) when every OWL axiom on it names a modified
  location (`annotation:reference_to_modified_location`, an article/annex) or has role fd_375 "AP" (Partial
  repeal) - e.g. the MDR 32017R0745 -> Directive 93/42/EEC, Decision 2020/2053 -> Decision 2014/335/EU, Euratom. "Implicit repeals"
  (`..._implicitly_repeals_...`: e.g. the amending acts of a repealed act, or GDPR -> one annex
  point of Regulation 1882/2003) are left out too.
  A modified location that starts with a CELEX id ("32017R0625 {AR} 165 {PO} 16") names the
  provision of another act that changed the link, so it does not make the repeal partial.
- date_document / date_signature: the date in the official English title ("... of 29 January
  2020") prevails over `work_date_document` / `resource_legal_date_signature` when they differ
  (Cellar has 2019-01-29 for 32020R0127); jointly signed acts are dated by their signature.
- court_rulings: judgments linked by `cdm:case-law_amends_resource_legal` (kept only for actions for
  annulment defended by an institution that adopted the act; General Court trade-mark judgments
  are also linked this way to Regulation 2017/1001) or
  `cdm:case-law_declares_void_by_preliminary_ruling_resource_legal`; case number, title and
  keywords come from the judgment's English expression, provisions from the link's OWL axioms.
- Linked works are mapped to their CELEX id; only base-act ids are kept (corrigenda "…R(01)" and
  consolidated versions "0…" are dropped) and works without a CELEX id are skipped.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import yaml

from pipeline.http import HttpError
from pipeline.models.entities import (
    CourtRuling,
    LegalAct,
    ProcedureNotice,
    SourceRef,
    SourceStatus,
    Subject,
    TranspositionDate,
    ValidityNote,
)
from pipeline.snapshot import CURATED, fetch_deadline, now_iso, past, read_records, write_records, write_state

log = logging.getLogger("pipeline.sources.eurlex")

SOURCE_ID = "eurlex"
MIN_DOCUMENT_DATE = "2014-01-01"
PROCEDURE_TYPES = ("COD", "CNS", "APP")  # legislative / special legislative procedures
WORKERS = 4
BATCH = 60
SCOPE_PAGE = 1000
MAX_FAILED_SHARE = 0.05  # more dropped acts than this -> fail the source (keep previous snapshot)
FEATURED_FILE = CURATED / "featured.yaml"

CDM = "http://publications.europa.eu/ontology/cdm#"
ANN = "http://publications.europa.eu/ontology/annotation#"
CELLAR = "http://publications.europa.eu/resource/cellar/"
AUTH = "http://publications.europa.eu/resource/authority/"
ENG = AUTH + "language/ENG"
PREFIXES = f"""PREFIX cdm: <{CDM}>
PREFIX ann: <{ANN}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX cmr: <http://publications.europa.eu/ontology/cdm/cmr#>
"""

UNKNOWN_DATE = "1001-01-01"
OPEN_END = "9999-12-31"
PLACEHOLDER_DATES = {UNKNOWN_DATE, OPEN_END}

BASE_CELEX_RE = re.compile(r"^3\d{4}[RLD]\d{4}$")  # in-scope acts
FEATURED_CELEX_RE = re.compile(r"^3\d{4}[A-Z]\d{4}$")  # sector-3 base act, any type letter
LINKED_CELEX_RE = re.compile(r"^[1-4]\d{4}[A-Z]{1,2}\d{4}(\(\d{2}\))?$")  # amends/repeals targets
PROC_REF_RE = re.compile(r"^(\d{4})/(\d{4})(?:/([A-Z]{3})|\(([A-Z]{3})\))$")  # "2021/0106/COD" (or EP style)
# Reference suffix -> procedure-type concepts (authority table "procedure") consistent with it. When the
# dossier's type concept contradicts its reference (e.g. "2018/0359/COD" typed NLE), neither is trusted.
SUFFIX_TYPES = {"COD": {"COD", "OLP"}, "CNS": {"CNS", "SLP"}}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# Date of the act in its official title: "Regulation (EU) 2020/127 of the European Parliament and of the
# Council of 29 January 2020 amending ..." (first "of <day> <Month> <year>").
TITLE_DATE_RE = re.compile(r"\bof (\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})\b")
# A modified-location annotation that starts with a CELEX id names a provision of ANOTHER act (the act
# through which the link was made or changed, e.g. "32017R0625 {AR} 165 {PO} 16"), not part of the target.
OTHER_ACT_LOCATION_RE = re.compile(r"^\s*\d{5}[A-Z]{1,2}\d{4}\b")

# EIF annotation types (fd_335 authority codes) -> role
EIF_TYPES = ("EV",)  # entry into force
EFFECT_TYPES = ("PE",)  # date of effect (decisions addressed to Member States: on notification)

# Literal / IRI properties fetched for every work (predicate local name -> facts key)
PROPS = {
    "resource_legal_id_celex": "celex",
    "resource_legal_eli": "eli",
    "work_has_resource-type": "resource_type",
    "work_date_document": "date_document",
    "resource_legal_date_signature": "date_signature",
    "resource_legal_date_entry-into-force": "eif",
    "resource_legal_date_end-of-validity": "end_of_validity",
    "resource_legal_in-force": "in_force",
    "work_created_by_agent": "authors",
    "directive_date_transposition": "transposition",
    "official-journal-act_date_publication": "ojact_date",
    "official-journal-act_number": "ojact_number",
    "official-journal-act_year": "ojact_year",
    "official-journal-act_part_of_collection_document": "ojact_collection",
}

RESOURCE_TYPE_PREFIX = {"REG": "regulation", "DIR": "directive", "DEC": "decision", "RECO": "recommendation"}
CELEX_LETTER_TYPE = {"R": "regulation", "L": "directive", "D": "decision", "H": "recommendation"}
SUBJECT_SCHEMES = ("subject-matter", "eurovoc", "directory")


class SparqlClient(Protocol):
    def sparql(self, query: str) -> list[dict[str, str]]: ...


# ------------------------------------------------------------------------------------- small parsers
def format_procedure_ref(raw: str, type_concept: str | None = None) -> str | None:
    """Cellar "2021/0106/COD" -> EP format "2021/0106(COD)".

    None if the reference is not in that shape, or if the dossier's procedure-type concept
    (".../authority/procedure/OLP") is given and contradicts the reference suffix.
    """
    m = PROC_REF_RE.match(raw.strip())
    if not m:
        return None
    suffix = m[3] or m[4]
    if type_concept:
        if _authority_code(type_concept) not in SUFFIX_TYPES.get(suffix, {suffix}):
            return None
    return f"{m[1]}/{m[2]}({suffix})"


def _date(v: str | None) -> str | None:
    return v[:10] if v and DATE_RE.match(v) else None


def _real_dates(values: Iterable[str]) -> list[str]:
    """Distinct ISO dates, ascending, without Cellar placeholder dates."""
    return sorted({d for v in values if (d := _date(v)) and d not in PLACEHOLDER_DATES})


def _authority_code(uri: str) -> str:
    """Last path segment of an authority-table IRI, e.g. ".../fd_335/EV" -> "EV"."""
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _annotation_code(value: str) -> str:
    """Annotation values look like "{EV|http://.../fd_335/EV}" (or a bare IRI/code) -> "EV"."""
    v = value.strip()
    if v.startswith("{") and "|" in v:
        return v[1:].split("|", 1)[0].strip()
    return _authority_code(v) if v.startswith("http") else v


def directory_code(raw: str) -> str:
    """Directory-of-legislation authority code "131030" -> "13.10.30" (pairs of digits)."""
    return ".".join(raw[i : i + 2] for i in range(0, len(raw), 2)) if raw.isdigit() else raw


def title_date(title: str) -> str | None:
    """ISO date of the act as stated in its official title, or None."""
    m = TITLE_DATE_RE.search(title)
    if not m:
        return None
    try:
        return date(int(m[3]), MONTHS.index(m[2]) + 1, int(m[1])).isoformat()
    except ValueError:
        return None


def oj_date_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day}.{d.month}.{d.year}"


def eurlex_url(celex: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"


def act_type_for(resource_type: str | None, celex: str) -> str:
    if resource_type:
        code = _authority_code(resource_type)
        for prefix, kind in RESOURCE_TYPE_PREFIX.items():
            if code == prefix or code.startswith(prefix + "_"):
                return kind
    return CELEX_LETTER_TYPE.get(celex[5:6], "other")


def split_eif(values: Iterable[str], types: dict[str, set[str]]) -> tuple[str | None, list[str]]:
    """Split resource_legal_date_entry-into-force values into (entry_into_force, other dates).

    types maps a date value to its annotation:type_of_date codes. EV (else PE) gives the entry into
    force; if no value carries any annotation, the earliest value is used (the property's plain
    meaning). Everything else - application dates, partial application - goes to the other list.
    """
    dates = _real_dates(values)
    if not dates:
        return None, []
    eif: str | None = None
    for wanted in (EIF_TYPES, EFFECT_TYPES):
        hits = [d for d in dates if types.get(d, set()) & set(wanted)]
        if hits:
            eif = hits[0]
            break
    if eif is None and not any(types.get(d) for d in dates):
        eif = dates[0]
    return eif, [d for d in dates if d != eif]


# ------------------------------------------------------------------------------------------ queries
def _values(works: Iterable[str]) -> str:
    return "VALUES ?w { " + " ".join(f"<{w}>" for w in works) + " }"


def _celex_literal(c: str) -> str:
    return f'"{c}"^^xsd:string'


DOSSIER_LINK = """{ ?dos cdm:dossier_produces_resource_legal ?w }
  UNION { ?w cdm:resource_legal_produced_by_dossier ?dos }
  UNION { ?w cdm:resource_legal_adopts_resource_legal ?prop . ?prop cdm:work_part_of_dossier ?dos }
  ?dos cdm:procedure_code_interinstitutional_reference_procedure ?ref .
  OPTIONAL { ?dos cdm:procedure_code_interinstitutional_has_type_concept_type_procedure_code_interinstitutional ?ptype }"""


def _scope_select() -> str:
    types = "|".join(PROCEDURE_TYPES)
    return f"""SELECT DISTINCT ?w ?celex ?ref ?ptype WHERE {{
  ?w cdm:resource_legal_id_sector "3"^^xsd:string ;
     cdm:resource_legal_type ?t ;
     cdm:work_date_document ?d ;
     cdm:resource_legal_id_celex ?celex .
  FILTER(?t IN ("R"^^xsd:string, "L"^^xsd:string, "D"^^xsd:string))
  FILTER(?d >= "{MIN_DOCUMENT_DATE}"^^xsd:date)
  FILTER(REGEX(STR(?celex), "^3[0-9]{{4}}[RLD][0-9]{{4}}$"))
  {DOSSIER_LINK}
  FILTER(REGEX(STR(?ref), "({types})\\\\)?$"))
}}"""


def scope_query(offset: int, limit: int = SCOPE_PAGE) -> str:
    """Candidate acts with their procedure references; the procedure-type filter is in Python."""
    return PREFIXES + f"{_scope_select()} ORDER BY ?w ?celex ?ref ?ptype LIMIT {limit} OFFSET {offset}"


def scope_count_query() -> str:
    """The number of rows of the scope query (all pages): a paged answer with fewer rows is incomplete."""
    return PREFIXES + f"SELECT (COUNT(*) AS ?n) WHERE {{ {_scope_select()} }}"


def celex_lookup_query(celexes: Iterable[str]) -> str:
    vals = " ".join(_celex_literal(c) for c in celexes)
    return (
        PREFIXES
        + f"SELECT DISTINCT ?w ?celex WHERE {{ VALUES ?celex {{ {vals} }} ?w cdm:resource_legal_id_celex ?celex }}"
    )


def props_query(works: list[str]) -> str:
    preds = " ".join(f"cdm:{p}" for p in PROPS)
    return (
        PREFIXES
        + f"""SELECT ?w ?p ?v WHERE {{ {_values(works)}
  {{ VALUES ?p {{ {preds} }} ?w ?p ?v }}
  UNION {{ ?w cmr:lastModificationDate ?v BIND(cmr:lastModificationDate AS ?p) }}
}}"""
    )


def title_query(works: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT ?w ?title WHERE {{ {_values(works)}
  ?e cdm:expression_belongs_to_work ?w ;
     cdm:expression_uses_language <{ENG}> ;
     cdm:expression_title ?title .
}}"""
    )


def oj_query(works: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT ?w ?oj ?date ?number ?collection WHERE {{ {_values(works)}
  ?w cdm:resource_legal_published_in_official-journal ?oj .
  OPTIONAL {{ ?oj cdm:publication_general_date_publication ?date }}
  OPTIONAL {{ ?oj cdm:official-journal_number ?number }}
  OPTIONAL {{ ?oj cdm:official-journal_part_of_collection_document ?collection }}
}}"""
    )


def eif_types_query(works: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT ?w ?d ?type ?comment WHERE {{ {_values(works)}
  ?ax owl:annotatedSource ?w ;
      owl:annotatedProperty cdm:resource_legal_date_entry-into-force ;
      owl:annotatedTarget ?d ;
      ann:type_of_date ?type .
  OPTIONAL {{ ?ax ann:comment_on_date ?comment }}
}}"""
    )


def validity_query(works: list[str]) -> str:
    """End-of-validity values that Cellar comments on (repealed by, partial end of validity...)."""
    return (
        PREFIXES
        + f"""SELECT ?w ?d ?c WHERE {{ {_values(works)}
  ?w cdm:resource_legal_date_end-of-validity ?d .
  ?ax owl:annotatedSource ?w ;
      owl:annotatedProperty cdm:resource_legal_date_end-of-validity ;
      owl:annotatedTarget ?d ;
      ann:comment_on_date ?c .
}}"""
    )


def transposition_query(works: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT ?w ?d ?c WHERE {{ {_values(works)}
  ?w cdm:directive_date_transposition ?d .
  ?ax owl:annotatedSource ?w ;
      owl:annotatedProperty cdm:directive_date_transposition ;
      owl:annotatedTarget ?d ;
      ann:comment_on_date ?c .
}}"""
    )


def procedure_query(works: list[str]) -> str:
    return PREFIXES + f"SELECT DISTINCT ?w ?ref ?ptype WHERE {{ {_values(works)}\n  {DOSSIER_LINK}\n}}"


def subjects_query(works: list[str]) -> str:
    return (
        PREFIXES
        + f"""SELECT ?w ?scheme ?s ?label WHERE {{ {_values(works)}
  {{ ?w cdm:resource_legal_is_about_subject-matter ?s BIND("subject-matter" AS ?scheme) }}
  UNION {{ ?w cdm:work_is_about_concept_eurovoc ?s BIND("eurovoc" AS ?scheme) }}
  UNION {{ ?w cdm:resource_legal_is_about_concept_directory-code ?s BIND("directory" AS ?scheme) }}
  OPTIONAL {{ ?s skos:prefLabel ?label FILTER(LANG(?label) = "en") }}
}}"""
    )


def relations_query(works: list[str]) -> str:
    """Amend/repeal links in both directions. For repeal links also the link's OWL axioms: whether
    each names a modified location (article, annex point...) and its role (fd_375 A = repeal,
    AP = partial repeal)."""
    rep = "cdm:resource_legal_repeals_resource_legal"
    axiom = """OPTIONAL {{ ?ax owl:annotatedSource {s} ; owl:annotatedProperty {p} ; owl:annotatedTarget {o} .
      OPTIONAL {{ ?ax ann:reference_to_modified_location ?loc }} OPTIONAL {{ ?ax ann:role2 ?role }} }}"""
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?w ?rel ?celex ?ax ?loc ?role WHERE {{ {_values(works)}
  {{ ?w cdm:resource_legal_amends_resource_legal ?x BIND("amends" AS ?rel) }}
  UNION {{ ?x cdm:resource_legal_amends_resource_legal ?w BIND("amended_by" AS ?rel) }}
  UNION {{ ?w {rep} ?x BIND("repeals" AS ?rel) {axiom.format(s="?w", p=rep, o="?x")} }}
  UNION {{ ?x {rep} ?w BIND("repealed_by" AS ?rel) {axiom.format(s="?x", p=rep, o="?w")} }}
  ?x cdm:resource_legal_id_celex ?celex .
}}"""
    )


RULING_LINKS = (
    ("cdm:case-law_amends_resource_legal", "annulment"),
    ("cdm:case-law_declares_void_by_preliminary_ruling_resource_legal", "invalidity"),
)


def rulings_query(works: list[str]) -> str:
    """Judgments linked to the acts as amending (annulment actions) or declaring them void."""
    links = " ".join(f'({p} "{e}")' for p, e in RULING_LINKS)
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?w ?effect ?s ?celex ?date ?ecli ?procjur ?defender ?loc ?case ?title ?keywords
WHERE {{ {_values(works)}
  VALUES (?p ?effect) {{ {links} }}
  ?s ?p ?w ; cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?s cdm:work_date_document ?date }}
  OPTIONAL {{ ?s cdm:case-law_ecli ?ecli }}
  OPTIONAL {{ ?s cdm:case-law_has_procjur ?procjur }}
  OPTIONAL {{ ?s cdm:case-law_defended_by_agent ?defender }}
  OPTIONAL {{ ?ax owl:annotatedSource ?s ; owl:annotatedProperty ?p ; owl:annotatedTarget ?w ;
                 ann:reference_to_modified_location ?loc }}
  OPTIONAL {{ ?e cdm:expression_belongs_to_work ?s ; cdm:expression_uses_language <{ENG}> .
    OPTIONAL {{ ?e cdm:expression_case-law_identifier_case ?case }}
    OPTIONAL {{ ?e cdm:expression_title ?title }}
    OPTIONAL {{ ?e cdm:expression_case-law_indicator_decision ?keywords }} }}
}}"""
    )


# ------------------------------------------------------------------------------- facts accumulation
@dataclass
class Facts:
    """Everything fetched about one work, as raw source values."""

    props: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    titles: set[str] = field(default_factory=set)
    oj_issues: dict[str, dict[str, str]] = field(default_factory=dict)
    eif_types: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    eif_notes: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # raw comment_on_date
    validity_notes: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # end of validity
    # transposition date -> comment_on_date annotations (raw "{CODE|iri} ... {ART|iri} 48.1")
    transposition_notes: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    procedure_refs: set[tuple[str, str]] = field(default_factory=set)  # (reference, type concept or "")
    subjects: dict[tuple[str, str], str | None] = field(default_factory=dict)
    relations: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # (rel, celex) -> {axiom id -> (names a modified location, role codes)} for repeal links
    repeal_axioms: dict[tuple[str, str], dict[str, tuple[bool, set[str]]]] = field(default_factory=dict)
    # (judgment CELEX, effect) -> field -> values, merged over the judgment's Cellar works
    rulings: dict[tuple[str, str], dict[str, set[str]]] = field(default_factory=dict)


PROP_KEYS = {CDM + k: v for k, v in PROPS.items()} | {
    "http://publications.europa.eu/ontology/cdm/cmr#lastModificationDate": "last_modified"
}


def add_props(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        key = PROP_KEYS.get(r["p"])
        if key:
            facts[r["w"]].props[key].add(r["v"])


def add_titles(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        facts[r["w"]].titles.add(r["title"])


def add_oj(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        issue = facts[r["w"]].oj_issues.setdefault(r["oj"], {})
        for k in ("date", "number", "collection"):
            if r.get(k):
                issue[k] = r[k]


def add_eif_types(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        d = _date(r["d"])
        if d:
            facts[r["w"]].eif_types[d].add(_annotation_code(r["type"]))
            if r.get("comment"):
                facts[r["w"]].eif_notes[d].add(r["comment"])
            # partial application is sometimes only in the comment: type MA, comment "{MA/PART|...} ..."
            for code in ANNOTATION_CODE_RE.findall(r.get("comment") or ""):
                if code.endswith("/PART"):
                    facts[r["w"]].eif_types[d].add(code)


def add_validity_notes(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        d = _date(r["d"])
        if d and r.get("c"):
            facts[r["w"]].validity_notes[d].add(r["c"])


def add_transposition_notes(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        d = _date(r["d"])
        if d and r.get("c"):
            facts[r["w"]].transposition_notes[d].add(r["c"])


TRANSPOSITION_LABELS = ("ADOPTION", "APPLICATION", "AU+TARD")
ANNOTATION_CODE_RE = re.compile(r"\{([^|{}]+)\|[^{}]*\}")
ARTICLE_RE = re.compile(r"\{ART\|[^{}]*\}\s*([0-9][0-9A-Za-z.()]*)")


def transposition_dates(dates: list[str], notes: dict[str, set[str]]) -> list[TranspositionDate]:
    """Annotate each transposition date with Cellar's labels and the article(s) setting it."""
    out = []
    for d in dates:
        labels: set[str] = set()
        articles: set[str] = set()
        for c in notes.get(d, set()):
            labels |= {code for code in ANNOTATION_CODE_RE.findall(c) if code in TRANSPOSITION_LABELS}
            articles |= {m.rstrip(".") for m in ARTICLE_RE.findall(c)}
        out.append(TranspositionDate(date=d, labels=sorted(labels), articles=sorted(articles)))
    return out


def add_procedures(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        facts[r["w"]].procedure_refs.add((r["ref"], r.get("ptype", "")))


def add_subjects(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        key = (r["scheme"], r["s"])
        f = facts[r["w"]]
        if f.subjects.get(key) is None:
            f.subjects[key] = r.get("label")


def add_relations(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        f = facts[r["w"]]
        if r["rel"] in ("amends", "amended_by"):
            f.relations[r["rel"]].add(r["celex"])
            continue
        axioms = f.repeal_axioms.setdefault((r["rel"], r["celex"]), {})
        if r.get("ax"):
            located, roles = axioms.get(r["ax"], (False, set()))
            if r.get("role"):
                roles = roles | {_annotation_code(r["role"])}
            axioms[r["ax"]] = (located or _target_location(r.get("loc")), roles)


def _target_location(loc: str | None) -> bool:
    """Does a modified-location annotation name a part of the link's target?"""
    return bool(loc and loc.strip()) and not OTHER_ACT_LOCATION_RE.match(loc)


def whole_repeal(axioms: dict[str, tuple[bool, set[str]]]) -> bool:
    """A repeal link is a whole-act repeal unless every annotation on it limits it to a modified
    location (article, annex point...) or classifies it as a partial repeal (role AP)."""
    return not axioms or any(not located and "AP" not in roles for located, roles in axioms.values())


def add_rulings(facts: dict[str, Facts], rows: list[dict[str, str]]) -> None:
    for r in rows:
        ruling = facts[r["w"]].rulings.setdefault((r["celex"], r["effect"]), defaultdict(set))
        for k in ("date", "ecli", "procjur", "defender", "loc", "case", "title", "keywords"):
            if r.get(k):
                ruling[k].add(r[k])


# Query kinds: (name, query builder, accumulator)
QUERIES: list[
    tuple[str, Callable[[list[str]], str], Callable[[dict[str, Facts], list[dict[str, str]]], None]]
] = [
    ("props", props_query, add_props),
    ("title", title_query, add_titles),
    ("oj", oj_query, add_oj),
    ("eif_types", eif_types_query, add_eif_types),
    ("validity", validity_query, add_validity_notes),
    ("transposition", transposition_query, add_transposition_notes),
    ("procedure", procedure_query, add_procedures),
    ("subjects", subjects_query, add_subjects),
    ("relations", relations_query, add_relations),
    ("rulings", rulings_query, add_rulings),
]


# ------------------------------------------------------------------------------------- record build
def _one(values: set[str]) -> str | None:
    """A single-valued property; if Cellar has several values, the earliest/smallest (deterministic)."""
    return min(values) if values else None


def _oj_ref_and_date(f: Facts, celex: str) -> tuple[str | None, str | None]:
    p = f.props
    # Act-by-act Official Journal (from 1 October 2023): "OJ L, 2024/1689, 12.7.2024"
    ojact_date = _date(_one(p.get("ojact_date", set())))
    if ojact_date:
        series = _series(_one(p.get("ojact_collection", set())))
        year, number = _one(p.get("ojact_year", set())), _one(p.get("ojact_number", set()))
        ref = None
        if series and year and number:
            ref = f"OJ {series}, {year}/{number}, {oj_date_label(ojact_date)}"
        return ref, ojact_date
    # Issue-based Official Journal: "OJ L 119, 4.5.2016" (earliest issue if several)
    issues = [i for i in f.oj_issues.values() if _date(i.get("date"))]
    if not issues:
        return None, None
    issue = min(issues, key=lambda i: (i["date"], i.get("number", "")))
    d = _date(issue["date"])
    series, number = _series(issue.get("collection")), issue.get("number")
    ref = f"OJ {series} {number}, {oj_date_label(d)}" if series and number and d else None
    return ref, d


def _series(collection: str | None) -> str | None:
    """document-collection/OJ-L -> "L"."""
    if not collection:
        return None
    code = _authority_code(collection)
    return code[3:] if code.startswith("OJ-") and len(code) > 3 else None


def _title(f: Facts) -> str | None:
    titles = sorted({" ".join(t.split()) for t in f.titles if t.strip()})
    return titles[0] if titles else None


def _subjects(f: Facts) -> list[Subject]:
    out: list[Subject] = []
    for (scheme, uri), label in f.subjects.items():
        raw = _authority_code(uri)
        code = directory_code(raw) if scheme == "directory" else raw
        out.append(Subject(code=code, label=label, scheme=scheme))  # type: ignore[arg-type]
    return sorted(out, key=lambda s: (SUBJECT_SCHEMES.index(s.scheme), s.code))


def _court_rulings(f: Facts) -> list[CourtRuling]:
    """Judgments Cellar links to the act as annulling or declaring it invalid.

    An "amends" link counts as an annulment only for an action for annulment (procjur ACTION_ANNU)
    defended by an institution that adopted the act: Cellar also links some General Court trade-mark
    judgments (which annul EUIPO decisions, defended by EUIPO) to the regulation they apply.
    """
    authors = {_authority_code(a) for a in f.props.get("authors", set())}
    out: list[CourtRuling] = []
    for (celex, effect), r in f.rulings.items():
        if effect == "annulment":
            defenders = {_authority_code(d) for d in r.get("defender", set())}
            if not (
                {_authority_code(p) for p in r.get("procjur", set())} & {"ACTION_ANNU"}
                and defenders & authors
            ):
                continue
        titles = sorted(" ".join(t.split()) for t in r.get("title", set()))
        if not titles:
            log.warning("eurlex: judgment %s has no English title; not recorded", celex)
            continue
        # Cellar titles are "#"-separated: court and date, parties, keywords...; keep the first two parts
        parts = [x.strip() for x in titles[0].split("#") if x.strip()]
        title = " ".join(parts[:2])
        case = _one(r.get("case", set()))
        if case and case.startswith("Case "):
            case = case[len("Case ") :]
        keywords = _one(r.get("keywords", set()))
        out.append(
            CourtRuling(
                celex=celex,
                case_number=case,
                ecli=_one(r.get("ecli", set())),
                date=_date(_one(r.get("date", set()))),
                title=title,
                effect=effect,  # type: ignore[arg-type]
                effect_text=" ".join(keywords.split()) if keywords else None,
                provisions=sorted(r.get("loc", set())),
                url=eurlex_url(celex),
            )
        )
    return sorted(out, key=lambda c: (c.date or "", c.celex))


def _act_dates(title: str, p: dict[str, set[str]], celex: str) -> tuple[str | None, str | None]:
    """(date_document, date_signature). The date in the official title prevails over Cellar's metadata
    when they differ (e.g. 32020R0127, "of 29 January 2020", recorded as 2019-01-29); acts signed by the
    Presidents of Parliament and Council bear the date of signature in their title."""
    meta_doc = _date(_one(p.get("date_document", set())))
    meta_sig = _date(_one(p.get("date_signature", set())))
    official = title_date(title)
    if official and meta_doc and official != meta_doc:
        log.warning(
            "eurlex: %s document date %s differs from title date %s; using the title",
            celex,
            meta_doc,
            official,
        )
    if official and meta_sig and official != meta_sig:
        log.warning(
            "eurlex: %s signature date %s differs from title date %s; using the title",
            celex,
            meta_sig,
            official,
        )
        meta_sig = official
    return official or meta_doc, meta_sig


def unrecorded_entry_into_force(f: Facts, eif: str | None) -> tuple[bool, list[str], bool]:
    """(entry_into_force_pending, entry_into_force_articles, effect_on_notification) of an act whose entry
    into force or date of effect Cellar gives as the placeholder 1001-01-01 (see the module docstring)."""
    if eif is not None or not any(_date(v) == UNKNOWN_DATE for v in f.props.get("eif", set())):
        return False, [], False
    types = f.eif_types.get(UNKNOWN_DATE, set())
    if types & set(EFFECT_TYPES) and not types & set(EIF_TYPES):
        return False, [], True
    articles = {m.rstrip(".") for c in f.eif_notes.get(UNKNOWN_DATE, set()) for m in ARTICLE_RE.findall(c)}
    return True, sorted(articles), False


NOTE_CELEX_RE = re.compile(r"(?<![\w/])([1-4]\d{4}[A-Z]{1,2}\d{4})(?!\w)")


def validity_notes(f: Facts) -> list[ValidityNote]:
    """Cellar's comments on the end-of-validity values (not on the 9999-12-31 placeholder), by date."""
    out = []
    for d in sorted(f.validity_notes):
        if d in PLACEHOLDER_DATES:
            continue
        for c in sorted(f.validity_notes[d]):
            plain = re.sub(r"\|[^{}]*\}", "}", c)  # "{A/PAR|http://...}" -> "{A/PAR}"
            codes = [x.strip() for x in re.findall(r"\{([^{}]+)\}", plain)]
            codes = [x for x in codes if not NOTE_CELEX_RE.fullmatch(x)]
            acts = list(dict.fromkeys(NOTE_CELEX_RE.findall(plain)))
            out.append(ValidityNote(date=d, partial="FIN/VAL/PART" in codes, codes=codes, acts=acts))
    return out


def _whole_repeals(f: Facts, rel: str) -> set[str]:
    return {c for (r, c), axioms in f.repeal_axioms.items() if r == rel and whole_repeal(axioms)}


def _partial_repeals(f: Facts, rel: str) -> set[str]:
    return {c for (r, c), axioms in f.repeal_axioms.items() if r == rel and not whole_repeal(axioms)}


def partial_on_entry_into_force(f: Facts, eif: str | None) -> bool:
    """Cellar also marks the entry-into-force date MA/PART or PE/PART (in the type or the comment)."""
    return bool(eif) and any(c.endswith("/PART") for c in f.eif_types.get(eif or "", ()))


def _linked(values: set[str], own: str) -> list[str]:
    return sorted({c for c in values if LINKED_CELEX_RE.match(c) and c != own})


def build_act(work: str, f: Facts, retrieved_at: str) -> LegalAct | None:
    """Assemble one LegalAct from fetched facts; None if essential data (CELEX, title) is missing."""
    p = f.props
    celexes = sorted(c for c in p.get("celex", set()) if FEATURED_CELEX_RE.match(c))
    if not celexes:
        log.warning("eurlex: %s has no base CELEX id (%s); skipped", work, sorted(p.get("celex", set())))
        return None
    celex = celexes[0]
    title = _title(f)
    if not title:
        log.warning("eurlex: %s has no English title; skipped", celex)
        return None
    act_type = act_type_for(_one(p.get("resource_type", set())), celex)
    eif, other_dates = split_eif(p.get("eif", set()), f.eif_types)
    eif_pending, eif_articles, on_notification = unrecorded_entry_into_force(f, eif)
    partial = [d for d in other_dates if any(c.endswith("/PART") for c in f.eif_types.get(d, ()))]
    eov_values = {d for v in p.get("end_of_validity", set()) if (d := _date(v))}
    end_of_validity = None if not eov_values or OPEN_END in eov_values else max(eov_values)
    in_force_raw = _one(p.get("in_force", set()))
    in_force = {"1": True, "true": True, "0": False, "false": False}.get((in_force_raw or "").lower())
    oj_ref, date_publication = _oj_ref_and_date(f, celex)
    proc_refs = sorted({r for raw, pt in f.procedure_refs if (r := format_procedure_ref(raw, pt or None))})
    transposition = _real_dates(p.get("transposition", set())) if act_type == "directive" else []
    eli = _one(p.get("eli", set()))
    date_document, date_signature = _act_dates(title, p, celex)
    last_modified = _date(_one(p.get("last_modified", set())))
    url = eurlex_url(celex)
    return LegalAct(
        celex=celex,
        eli=eli,
        act_type=act_type,  # type: ignore[arg-type]
        title=title,
        date_document=date_document,
        date_signature=date_signature,
        date_publication=date_publication,
        oj_ref=oj_ref,
        entry_into_force=eif,
        entry_into_force_pending=eif_pending,
        entry_into_force_articles=eif_articles,
        effect_on_notification=on_notification,
        other_application_dates=other_dates,
        partial_application_dates=partial,
        partial_on_entry_into_force=partial_on_entry_into_force(f, eif),
        end_of_validity=end_of_validity,
        validity_notes=validity_notes(f),
        in_force=in_force,
        transposition_deadlines=transposition,
        transposition_dates=transposition_dates(transposition, f.transposition_notes),
        procedure_refs=proc_refs,
        subjects=_subjects(f),
        amends=_linked(f.relations.get("amends", set()), celex),
        amended_by=_linked(f.relations.get("amended_by", set()), celex),
        repeals=_linked(_whole_repeals(f, "repeals"), celex),
        repealed_by=_linked(_whole_repeals(f, "repealed_by"), celex),
        partly_repeals=_linked(_partial_repeals(f, "repeals"), celex),
        partly_repealed_by=_linked(_partial_repeals(f, "repealed_by"), celex),
        court_rulings=_court_rulings(f),
        eurlex_url=url,
        source=SourceRef(
            institution="EUR-Lex",
            url=url,
            label=f"EUR-Lex / Cellar – CELEX {celex}",
            identifier=celex,
            retrieved_at=retrieved_at,
            published=last_modified,
        ),
    )


# ------------------------------------------------------------------------------------------ fetching
def _splittable(e: Exception) -> bool:
    """Worth retrying with fewer works? Not for a malformed query (HTTP 400 without a timeout)."""
    if isinstance(e, HttpError) and e.status == 400:
        msg = str(e).lower()
        return "time" in msg or "limit" in msg
    return True


def run_batched(
    http: SparqlClient,
    build: Callable[[list[str]], str],
    works: list[str],
    *,
    batch: int = BATCH,
    workers: int = WORKERS,
    deadline: float | None = None,
) -> tuple[list[dict[str, str]], set[str]]:
    """Run build(chunk) for chunks of works; split a failing chunk in halves down to single works. No query
    is started after `deadline` (monotonic; the source's time budget): its works count as not fetched.

    Returns (all rows, works that could not be fetched even alone).
    """

    def run(chunk: list[str]) -> tuple[list[dict[str, str]], set[str]]:
        if past(deadline):
            return [], set(chunk)
        try:
            return http.sparql(build(chunk)), set()
        except (HttpError, ValueError, KeyError) as e:
            if not _splittable(e):
                raise
            if len(chunk) == 1:
                log.error("eurlex: query failed for %s: %s", chunk[0], e)
                return [], set(chunk)
            log.warning("eurlex: query failed for %d works (%s); splitting", len(chunk), e)
            mid = len(chunk) // 2
            a_rows, a_bad = run(chunk[:mid])
            b_rows, b_bad = run(chunk[mid:])
            return a_rows + b_rows, a_bad | b_bad

    chunks = [works[i : i + batch] for i in range(0, len(works), batch)]
    rows: list[dict[str, str]] = []
    failed: set[str] = set()
    with ThreadPoolExecutor(workers) as ex:
        for r, bad in ex.map(run, chunks):
            rows += r
            failed |= bad
    return rows, failed


def discover_scope(http: SparqlClient, page: int = SCOPE_PAGE) -> tuple[dict[str, str], str | None]:
    """work IRI -> CELEX for all in-scope acts (paged, deterministic order), and why the answer may be
    incomplete: the pages end at the first short one, which a truncated answer (Virtuoso can return a partial
    result with HTTP 200) also is, so their rows are checked against Cellar's count of the same query."""
    out: dict[str, str] = {}
    offset = rows_seen = 0
    while True:
        rows = http.sparql(scope_query(offset, page))
        rows_seen += len(rows)
        for r in rows:
            ref = format_procedure_ref(r["ref"], r.get("ptype"))
            if ref and ref[-4:-1] in PROCEDURE_TYPES and BASE_CELEX_RE.match(r["celex"]):
                out.setdefault(r["w"], r["celex"])
        if len(rows) < page:
            break
        offset += page
    try:
        counted = int(http.sparql(scope_count_query())[0]["n"])
    except Exception as e:  # noqa: BLE001 - an unchecked answer is treated as possibly incomplete
        return out, f"not checked: the count query failed ({e})"[:200]
    return out, None if rows_seen >= counted else f"{rows_seen} rows against {counted} counted by Cellar"


def read_featured_celex(path: Path = FEATURED_FILE) -> list[str]:
    """CELEX ids listed under `celex:` keys in featured.yaml.

    The file is a list of dossier entries, each with `celex: [ids...]`; a top-level mapping with a
    `celex:` list, and mappings with a `celex` key inside the lists, are accepted too.
    """
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(x: Any, under_celex: bool) -> None:
        if isinstance(x, str) and under_celex:
            if FEATURED_CELEX_RE.match(x.strip()):
                found.add(x.strip())
            else:
                log.warning("eurlex: featured.yaml celex %r is not a sector-3 base CELEX id; ignored", x)
        elif isinstance(x, dict):
            if "celex" in x:
                walk(x["celex"], True)
        elif isinstance(x, list):
            for i in x:
                walk(i, under_celex)

    walk(doc, False)
    return sorted(found)


# Cellar procedure events (authority table "event") recording that the Commission withdrew a proposal
PROCEDURE_NOTICE_TYPES = {"WDW_byCOM": "withdrawn", "WDW_PROPLEG_byCOM": "withdrawn", "RPL_byCOM": "replaced"}


def procedure_notices_query() -> str:
    types = " ".join(f"<{AUTH}event/{t}>" for t in sorted(PROCEDURE_NOTICE_TYPES))
    return (
        PREFIXES
        + f"""SELECT DISTINCT ?ref ?ptype ?type ?date ?doc WHERE {{
  VALUES ?type {{ {types} }}
  ?ev cdm:event_legal_has_type_concept_type_event_legal ?type ;
      cdm:event_legal_part_of_dossier ?dos ;
      cdm:event_legal_date ?date .
  ?dos cdm:procedure_code_interinstitutional_reference_procedure ?ref .
  OPTIONAL {{ ?dos cdm:procedure_code_interinstitutional_has_type_concept_type_procedure_code_interinstitutional ?ptype }}
  OPTIONAL {{ ?ev cdm:event_legal_document_reference ?doc }}
  FILTER(?date >= "{MIN_DOCUMENT_DATE}"^^xsd:date)
}} ORDER BY ?ref ?date ?type ?doc"""
    )


COM_DOC_RE = re.compile(r"^COM/(\d{4})/0*(\d+)")


def build_notices(rows: list[dict[str, str]], retrieved_at: str) -> list[ProcedureNotice]:
    """One notice per procedure, kind and date; a replacement names the new proposal (COM document)."""
    out: dict[tuple[str, str, str], ProcedureNotice] = {}
    for r in rows:
        ref = format_procedure_ref(r["ref"], r.get("ptype") or None)
        kind = PROCEDURE_NOTICE_TYPES.get(_authority_code(r["type"]))
        d = _date(r.get("date"))
        if not (ref and kind and d):
            continue
        m = COM_DOC_RE.match(r.get("doc") or "")
        doc = f"COM({m[1]}){int(m[2]):04d}" if m else None
        key = (ref, kind, d)
        if key in out and (out[key].document or not doc):
            continue
        out[key] = ProcedureNotice(
            id=f"{ref}:{kind}:{d}",
            reference=ref,
            kind=kind,  # type: ignore[arg-type]
            date=d,
            document=doc,
            source=SourceRef(
                institution="EUR-Lex",
                url=f"https://eur-lex.europa.eu/procedure/EN/{ref[:4]}_{int(ref[5:9])}",
                label=f"EUR-Lex procedure {ref}",
                identifier=ref,
                retrieved_at=retrieved_at,
            ),
        )
    return sorted(out.values(), key=lambda n: (n.reference, n.date, n.kind))


def procedure_celex_refs() -> list[str]:
    """Final-act CELEX ids that OEIL records for the procedures in the EP snapshot."""
    from pipeline.models.entities import Procedure

    procs = read_records("ep_procedures", "procedures", Procedure)
    return sorted({c for p in procs for c in p.celex_refs if FEATURED_CELEX_RE.match(c)})


def resolve_celex(http: SparqlClient, celexes: list[str]) -> dict[str, str]:
    """CELEX -> work IRI (cellar URIs only)."""
    out: dict[str, str] = {}
    for i in range(0, len(celexes), BATCH):
        for r in http.sparql(celex_lookup_query(celexes[i : i + BATCH])):
            if r["w"].startswith(CELLAR):
                out.setdefault(r["celex"], r["w"])
    return out


def collect(
    http: SparqlClient, works: list[str], retrieved_at: str, deadline: float | None = None
) -> tuple[list[LegalAct], set[str]]:
    """Fetch all facts for the works and build acts. Returns (acts, works dropped)."""
    facts: dict[str, Facts] = defaultdict(Facts)
    failed: set[str] = set()
    for name, build, add in QUERIES:
        rows, bad = run_batched(http, build, works, deadline=deadline)
        add(facts, rows)
        failed |= bad
        log.info("eurlex: %s: %d rows%s", name, len(rows), f", {len(bad)} works failed" if bad else "")
    acts: dict[str, LegalAct] = {}
    dropped = set(failed)
    for w in works:
        if w in failed:
            continue
        act = build_act(w, facts[w], retrieved_at)
        if act is None:
            dropped.add(w)
        elif act.celex in acts:
            log.warning("eurlex: duplicate CELEX %s (work %s); keeping the first", act.celex, w)
        else:
            acts[act.celex] = act
    return list(acts.values()), dropped


def fetch(http: Any) -> SourceStatus:
    """Writes acts.json and procedure_notices.json, and in _state.json `unsettled`: the acts kept from the
    previous snapshot and the procedures whose notices were not refreshed (or lost one) in this run, for change
    detection (pipeline/analysis/activity.py)."""
    attempted = now_iso()
    deadline = fetch_deadline()
    scope, scope_gap = discover_scope(http)
    log.info(
        "eurlex: %d in-scope acts (%s procedures, document date >= %s)",
        len(scope),
        "/".join(PROCEDURE_TYPES),
        MIN_DOCUMENT_DATE,
    )
    if scope_gap:
        log.warning("eurlex: the scope answer may be incomplete (%s)", scope_gap)
    featured = read_featured_celex()
    featured_works = resolve_celex(http, featured) if featured else {}
    missing_featured = sorted(set(featured) - set(featured_works))
    if missing_featured:
        log.warning("eurlex: featured CELEX not found in Cellar: %s", missing_featured)
    known = set(scope.values()) | set(featured_works)
    linked = [c for c in procedure_celex_refs() if c not in known]
    linked_works = resolve_celex(http, linked) if linked else {}
    if linked:
        log.info("eurlex: %d final acts recorded by OEIL outside the scope query, %d found", len(linked),
                 len(linked_works))  # fmt: skip
    works = sorted(set(scope) | set(featured_works.values()) | set(linked_works.values()))
    if not works:
        raise RuntimeError("eurlex: scope query returned no acts")

    acts, dropped = collect(http, works, attempted, deadline)
    if not acts:
        raise RuntimeError("eurlex: no acts could be built")
    if len(dropped) > MAX_FAILED_SHARE * len(works):
        raise RuntimeError(f"eurlex: {len(dropped)} of {len(works)} acts could not be fetched/built")
    # A work that could not be fetched this time keeps its previous record: dropping it would change the
    # status of its dossier (e.g. "In force" -> "Published") on a transient failure.
    previous = {a.celex: a for a in read_records(SOURCE_ID, "acts", LegalAct)}
    celex_of = {**{w: c for w, c in scope.items()}, **{w: c for c, w in featured_works.items()},
                **{w: c for c, w in linked_works.items()}}  # fmt: skip
    have = {a.celex for a in acts}
    kept = [previous[c] for w in sorted(dropped) if (c := celex_of.get(w)) in previous and c not in have]
    acts += kept
    # So does a stored act that this run's answers left out: missing from a scope answer that may be incomplete
    # (see discover_scope), or a featured / OEIL-recorded CELEX that Cellar did not resolve this time. Only a
    # complete scope answer without it removes it.
    have |= {a.celex for a in kept}
    unresolved = set(missing_featured) | (set(linked) - set(linked_works))
    carried = [a for c, a in sorted(previous.items()) if c not in have and (scope_gap or c in unresolved)]
    acts += carried
    if previous and len(acts) < (1 - MAX_FAILED_SHARE) * len(previous):
        raise RuntimeError(f"eurlex: {len(acts)} acts against {len(previous)} in the snapshot; not overwriting")

    write_records(SOURCE_ID, "acts", acts, key=lambda a: a.celex)  # type: ignore[attr-defined]
    # Withdrawals / replacements recorded on procedures (some dossiers are "withdrawn" or "replaced" on these
    # notices alone). As for the acts, the stored file is kept when the answer fails, is empty or much smaller.
    stored_notices = read_records(SOURCE_ID, "procedure_notices", ProcedureNotice)
    notices: list[ProcedureNotice] | None = None
    try:
        if past(deadline):
            raise RuntimeError("time budget reached")
        notices = build_notices(http.sparql(procedure_notices_query()), attempted)
    except Exception as e:  # noqa: BLE001 - optional data: never fail the acts
        log.warning("eurlex: procedure notices not fetched: %r", e)
        notices_note = "procedure notices not refreshed (fetch failed; previous file kept)"
    if notices is not None and stored_notices and len(notices) < (1 - MAX_FAILED_SHARE) * len(stored_notices):
        log.warning("eurlex: %d procedure notices against %d stored; not overwriting", len(notices),
                    len(stored_notices))  # fmt: skip
        notices_note = (
            f"procedure notices not refreshed: the answer had {len(notices)} against {len(stored_notices)} in the "
            "snapshot (previous file kept)"
        )
        notices = None
    if notices is not None:
        write_records(SOURCE_ID, "procedure_notices", notices, key=lambda n: (n.reference, n.date, n.kind))
        notices_note = f"{len(notices)} withdrawal/replacement notices on procedures"
        new_ids = {n.id for n in notices}
        unsettled_refs = sorted({n.reference for n in stored_notices if n.id not in new_ids})
        if unsettled_refs:
            notices_note += f" ({len(unsettled_refs)} procedures lost one: {', '.join(unsettled_refs[:10])})"
    else:
        unsettled_refs = sorted({n.reference for n in stored_notices})
    write_state(SOURCE_ID, {"unsettled": {
        "attempted_at": attempted,
        "acts": sorted(a.celex for a in kept + carried),
        "procedures": unsettled_refs,
    }})  # fmt: skip
    with_proc = sum(1 for a in acts if a.procedure_refs)
    notes = [
        f"{len(scope)} acts in scope ({'/'.join(PROCEDURE_TYPES)} procedures, date >= {MIN_DOCUMENT_DATE})",
        f"{len(featured_works)} featured",
        f"{len(linked_works)} more recorded by OEIL as final acts of procedures in the EP snapshot",
        f"{with_proc} with procedure reference",
        notices_note,
    ]
    if scope_gap:
        notes.append(f"scope answer possibly incomplete ({scope_gap})")
    if dropped:
        notes.append(f"{len(dropped)} not fetched or built this run ({len(kept)} kept from the previous snapshot)"
                     + (" (time budget reached)" if past(deadline) else ""))  # fmt: skip
    if carried:
        shown = ", ".join(a.celex for a in carried[:10]) + (" …" if len(carried) > 10 else "")
        notes.append(f"{len(carried)} stored acts missing from this run's answers kept from the previous snapshot: "
                     f"{shown}")  # fmt: skip
    if missing_featured:
        notes.append(f"featured not found: {', '.join(missing_featured)}")
    return SourceStatus(
        source=SOURCE_ID,
        status="partial" if dropped or missing_featured or carried or notices is None else "ok",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records={"acts": len(acts)},
        note="; ".join(notes),
    )
