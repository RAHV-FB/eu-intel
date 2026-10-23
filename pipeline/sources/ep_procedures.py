"""European Parliament legislative procedures (COD / CNS / APP, reference year >= 2014, plus older
procedures that produced an act in the EUR-Lex snapshot).

Sources (both official European Parliament publications):

1. EP Open Data API v2 (https://data.europarl.europa.eu/api/v2), the primary source:
   - ``GET /procedures?process-type=COD`` lists procedure ids (no year filter, no ordering;
     the year is the first part of the process id).
   - ``GET /procedures/{process-id}`` returns one JSON-LD ``Process`` with the English title
     (``process_title.en``), ``process_type``, ``current_stage`` (only the reading phase,
     e.g. ``procedure-phase/RDG1`` = first reading, NOT a lifecycle status), the EP
     activities (``consists_of``: committee/plenary events with typed activity
     ``def/ep-activities/...`` and linked EP document ids) and ``had_participation``
     (committees responsible/for opinion and rapporteurs, as EP person ids).
   The API does NOT provide: subjects, the Commission (COM) document number, Commission or
   Council events (proposal, Council adoption, withdrawal), a status label, or the final act
   (CELEX). It does record signature and Official Journal publication dates.

2. EP Legislative Observatory (OEIL) procedure file, ``/oeil/en/procedure-file?reference=``
   (HTML), used to fill exactly those gaps: the official status label ("Stage reached in
   procedure"), EP subject codes, COM references, the Commission/Council key events,
   withdrawal, and the final act's CELEX number. OEIL data is recorded with
   ``SourceRef(institution="OEIL")``. If an OEIL page cannot be fetched or parsed (an HTTP 200
   page without the procedure file counts as a failure), a file without earlier OEIL data is
   recorded with EP API data only (stage_raw/subjects/com_refs/celex_refs empty); a file whose
   snapshot record has OEIL data keeps that record unchanged and is retried next run.

Event normalization (deterministic, nothing invented):
- one Event per EP activity, kind/title from ACTIVITY_MAP (unknown types -> "other");
- PLENARY_VOTE / PLENARY_VOTE_RESULTS records of a sitting are folded (with their minutes,
  verbatim and vote-result documents) into that day's plenary decision event, if any;
- amendment tablings (committee or plenary) are grouped per day into one event;
- OEIL key events listed in OEIL_EVENT_MAP are added (Commission proposal and withdrawal,
  Council positions/adoption, ...) unless the EP API already has an event of the same kind and
  institution on the same day.

Output: data/snapshot/ep_procedures/procedures.json (list[Procedure], sorted by id).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import yaml
from lxml import html as lxml_html

from pipeline.http import EP_API, Http, HttpError
from pipeline.models.entities import (
    CommitteeRole,
    DocRef,
    EpVote,
    Event,
    EventKind,
    Institution,
    LegalAct,
    Mep,
    Procedure,
    Rapporteur,
    SourceRef,
    SourceStatus,
    Subject,
)
from pipeline.snapshot import (
    CURATED,
    fetch_deadline,
    global_deadline,
    now_iso,
    past,
    read_records,
    read_state,
    upsert_records,
    write_records,
    write_state,
)

log = logging.getLogger("pipeline.sources.ep_procedures")

SOURCE_ID = "ep_procedures"

PROCEDURE_TYPES = ("COD", "CNS", "APP")  # ordinary + the two special legislative procedures
MIN_YEAR = 2014
OEIL_FILE = "https://oeil.europarl.europa.eu/oeil/en/procedure-file"
JSONLD = {"format": "application/ld+json"}
DOCEO = "https://www.europarl.europa.eu/doceo/document/{id}_EN.html"

MAX_WORKERS = 4  # team rule: at most 4 concurrent threads
EP_API_GAP_S = 0.75  # EP API allows 500 requests / 5 min; stay well below (~400) as hosts are shared
OEIL_GAP_S = 0.5
FALLBACK_TERMS = (7, 8, 9, 10)  # parliamentary terms covering procedures from 2009 onwards
CHUNK_SIZE = 100  # procedures per checkpoint (snapshot upsert + _state.json)
RECENT_DAYS = 120  # incremental mode re-fetches files with an event in this window
# Lifecycle stages (pipeline.analysis.status) after which a file is not re-fetched incrementally.
TERMINAL_STAGES = {"adopted", "published", "in_force", "withdrawn", "rejected", "lapsed"}

# --------------------------------------------------------------------------------------
# EP activity types -> EventKind + deterministic plain-English title.
# Complete for the EP vocabulary https://data.europarl.europa.eu/def/ep-activities
# (procedure-relevant concepts). Unknown types map to EventKind.other with a neutral title
# derived from the type name (see `activity_title`).
# --------------------------------------------------------------------------------------
ACTIVITY_MAP: dict[str, tuple[EventKind, str]] = {
    # announcement / referral
    "REFERRAL": (EventKind.referral, "Announced in Parliament and referred to committee"),
    "ANNOUNCE_PLENARY_COUNCIL_POSITION": (
        EventKind.council_position,
        "Council's first-reading position announced in Parliament",
    ),
    # committee stage
    "COMMITTEE_APPOINT_RAPPORTEUR": (EventKind.other, "Parliament committee appointed a rapporteur"),
    "COMMITTEE_TABLING_REPORT": (EventKind.other, "Draft report presented in Parliament committee"),
    "COMMITTEE_TABLING_OPINION": (EventKind.other, "Draft opinion presented in Parliament committee"),
    "COMMITTEE_TABLING_AMENDMENT": (EventKind.other, "Amendments tabled in Parliament committee"),
    "COMMITTEE_ADOPTING_OPINION": (EventKind.committee_opinion, "Parliament committee adopted its opinion"),
    "COMMITTEE_ADOPTING_REPORT": (EventKind.committee_report, "Parliament committee adopted its report"),
    "COMMITTEE_VOTE": (EventKind.other, "Vote in Parliament committee"),
    "COMMITTEE_DEBATE": (EventKind.other, "Debate in Parliament committee"),
    "COMMITTEE_MEETING": (EventKind.other, "Parliament committee meeting"),
    "COMMITTEE_VOTE_PROVISIONAL_AGREEMENT": (
        EventKind.provisional_agreement,
        "Parliament committee voted on the provisional agreement with the Council",
    ),
    "COMMITTEE_APPROVE_PROVISIONAL_AGREEMENT": (
        EventKind.provisional_agreement,
        "Parliament committee approved the provisional agreement with the Council",
    ),
    "COMMITTEE_REJECT_PROVISIONAL_AGREEMENT": (
        EventKind.other,
        "Parliament committee rejected the provisional agreement with the Council",
    ),
    # interinstitutional negotiations
    "PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": (
        EventKind.negotiation_mandate,
        "Parliament sent the file back to committee to negotiate with the Council",
    ),
    "PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": (
        EventKind.negotiation_mandate,
        "Parliament confirmed the committee's mandate to negotiate with the Council",
    ),
    "PLENARY_REJECT_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS": (
        EventKind.plenary_vote,
        "Parliament rejected the committee's decision to negotiate with the Council",
    ),
    # sic: the EP data uses this misspelling in some records
    "PLENARY_REJECT_COMMITTEE_INTERINSTUTIONAL_NEGOTIATIONS": (
        EventKind.plenary_vote,
        "Parliament rejected the committee's decision to negotiate with the Council",
    ),
    "INTERINSTITUTIONAL_NEGOTIATION": (EventKind.other, "Negotiation meeting with the Council (trilogue)"),
    "INTERINSTITUTIONAL_NEGOTIATIONS_MEETING": (
        EventKind.other,
        "Negotiation meeting with the Council (trilogue)",
    ),
    "REQUEST_CONCILIATION_COMMITTEE": (EventKind.other, "Conciliation Committee convened"),
    # plenary
    "TABLING_PLENARY": (EventKind.other, "Committee report tabled for the plenary"),
    "PLENARY_DEBATE": (EventKind.plenary_debate, "Debate in Parliament"),
    "PLENARY_VOTE": (EventKind.plenary_vote, "Vote in Parliament"),
    "PLENARY_VOTE_RESULTS": (EventKind.plenary_vote, "Results of vote in Parliament"),
    "PLENARY_VOTE_URGENCY": (EventKind.plenary_vote, "Parliament voted on a request for urgent procedure"),
    "REQUEST_VOTE_URGENCY": (EventKind.other, "Urgent procedure requested"),
    "PLENARY_REFER_COMMITTEE_RECONSIDERATION": (
        EventKind.plenary_vote,
        "Parliament referred the file back to committee for reconsideration",
    ),
    "PLENARY_AMEND": (EventKind.plenary_vote, "Parliament voted amendments to the proposal"),
    # Neutral on purpose: in the EP data this type also covers decisions whose outcome was a
    # rejection (e.g. 2022/0196(COD), 22 Nov 2023). OEIL calls it "Decision by Parliament".
    "PLENARY_ADOPT_POSITION": (EventKind.ep_position, "Parliament took its decision"),
    "PLENARY_AMEND_PROPOSAL": (
        EventKind.ep_position,
        "Parliament adopted its position, amending the proposal",
    ),
    "PLENARY_DECISION": (EventKind.ep_position, "Parliament took its decision"),
    "PLENARY_REJECT_PROPOSAL": (EventKind.rejection, "Parliament rejected the proposal"),
    "PLENARY_APPROVE_COUNCIL_POSITION": (
        EventKind.ep_position,
        "Parliament approved the Council's position at second reading",
    ),
    "PLENARY_AMEND_COUNCIL_POSITION": (
        EventKind.ep_position,
        "Parliament amended the Council's position at second reading",
    ),
    "PLENARY_REJECT_COUNCIL_POSITION": (
        EventKind.rejection,
        "Parliament rejected the Council's position at second reading",
    ),
    "PLENARY_ADOPT_JOINT_TEXT": (
        EventKind.ep_position,
        "Parliament approved the joint text agreed in conciliation (third reading)",
    ),
    "PLENARY_REJECT_JOINT_TEXT": (
        EventKind.rejection,
        "Parliament rejected the joint text agreed in conciliation (third reading)",
    ),
    "PLENARY_OUTCOME": (EventKind.other, "Outcome of a plenary item"),
    # final act
    "SIGNATURE": (EventKind.signature, "Final act signed"),
    "PUBLICATION_OFFICIAL_JOURNAL": (EventKind.publication, "Final act published in the Official Journal"),
    # national parliaments (rarely attached to procedures)
    "NATIONAL_CHAMBER_SUBMIT_CONTRIBUTION": (EventKind.other, "Contribution from a national parliament"),
    "NATIONAL_CHAMBER_SUBMIT_OPINION": (
        EventKind.other,
        "Reasoned opinion from a national parliament (subsidiarity)",
    ),
}

# Activities whose actor is not the EP. Signature is joint (EP + Council); publication is
# done by the Publications Office (EUR-Lex / Official Journal).
ACTIVITY_INSTITUTION: dict[str, Institution] = {"PUBLICATION_OFFICIAL_JOURNAL": "EUR-Lex"}

READING = {"RDG1": "first reading", "RDG2": "second reading", "RDG3": "third reading"}
# Activity types whose title gets the reading appended when the source states it.
READING_QUALIFIED = {"PLENARY_ADOPT_POSITION", "PLENARY_AMEND_PROPOSAL", "PLENARY_DECISION", "REFERRAL"}

# Vote-record activities that duplicate a same-day plenary decision; their documents
# (minutes, verbatim report, vote results) are folded into that decision event.
VOTE_RECORD_TYPES = {"PLENARY_VOTE", "PLENARY_VOTE_RESULTS"}
PLENARY_DECISION_TYPES = {
    "PLENARY_AMEND",
    "PLENARY_ADOPT_POSITION",
    "PLENARY_AMEND_PROPOSAL",
    "PLENARY_DECISION",
    "PLENARY_REJECT_PROPOSAL",
    "PLENARY_APPROVE_COUNCIL_POSITION",
    "PLENARY_AMEND_COUNCIL_POSITION",
    "PLENARY_REJECT_COUNCIL_POSITION",
    "PLENARY_ADOPT_JOINT_TEXT",
    "PLENARY_REJECT_JOINT_TEXT",
}

# --------------------------------------------------------------------------------------
# OEIL key events that the EP API does not record. Only these are added (others are EP
# activities already present from the API). Matching is on the exact OEIL label; labels
# not listed here are ignored.  label -> (kind, institution, title)
# --------------------------------------------------------------------------------------
OEIL_EVENT_MAP: dict[str, tuple[EventKind, Institution, str]] = {
    "Legislative proposal published": (
        EventKind.proposal,
        "Commission",
        "Commission published its legislative proposal",
    ),
    "Initial legislative proposal published": (
        EventKind.proposal,
        "Commission",
        "Commission published its legislative proposal",
    ),
    "Amended legislative proposal published": (
        EventKind.proposal,
        "Commission",
        "Commission published an amended legislative proposal",
    ),
    "Amended legislative proposal for reconsultation published": (
        EventKind.proposal,
        "Commission",
        "Commission published an amended proposal for reconsultation of Parliament",
    ),
    "Modified legislative proposal published": (
        EventKind.proposal,
        "Commission",
        "Commission published a modified legislative proposal",
    ),
    "Preparatory document": (EventKind.other, "Council", "Council preparatory document published"),
    "Proposal withdrawn by Commission": (
        EventKind.withdrawal,
        "Commission",
        "Commission withdrew the proposal",
    ),
    "Debate in Council": (EventKind.other, "Council", "Debate in Council"),
    "Council position published": (
        EventKind.council_position,
        "Council",
        "Council adopted its first-reading position",
    ),
    "Act adopted by Council after Parliament's 1st reading": (
        EventKind.council_adoption,
        "Council",
        "Council adopted the act after Parliament's first reading",
    ),
    "Act adopted by Council after consultation of Parliament": (
        EventKind.council_adoption,
        "Council",
        "Council adopted the act after consulting Parliament",
    ),
    "Act adopted by Council after Parliament's consent": (
        EventKind.council_adoption,
        "Council",
        "Council adopted the act after Parliament's consent",
    ),
    "Act approved by Council, 2nd reading": (
        EventKind.council_adoption,
        "Council",
        "Council approved Parliament's second-reading position",
    ),
    "Act adopted by Council, 3rd reading": (
        EventKind.council_adoption,
        "Council",
        "Council adopted the act at third reading",
    ),
    "Decision by Council, 3rd reading": (
        EventKind.council_adoption,
        "Council",
        "Council adopted the act at third reading",
    ),
    "Commission response to text adopted in plenary": (
        EventKind.other,
        "Commission",
        "Commission responded to the text adopted by Parliament",
    ),
    "Resumption of business from the previous parliamentary term": (
        EventKind.other,
        "EP",
        "Parliament resumed work on the file in the new parliamentary term",
    ),
    "Committee decision to open interinstitutional negotiations with report adopted in committee": (
        EventKind.negotiation_mandate,
        "EP",
        "Parliament committee decided to open negotiations with the Council",
    ),
    "Committee decision to open interinstitutional negotiations at 2nd reading": (
        EventKind.negotiation_mandate,
        "EP",
        "Parliament committee decided to open second-reading negotiations with the Council",
    ),
    "Committee decision to enter into interinstitutional negotiations announced in plenary (Rule 72)": (
        EventKind.negotiation_mandate,
        "EP",
        "Committee decision to negotiate with the Council announced in Parliament",
    ),
    "Committee decision to enter into interinstitutional negotiations announced in plenary (Rule 71)": (
        EventKind.negotiation_mandate,
        "EP",
        "Committee decision to negotiate with the Council announced in Parliament",
    ),
    "Committee decision to enter into interinstitutional negotiations announced in plenary (Rule 73)": (
        EventKind.negotiation_mandate,
        "EP",
        "Committee decision to negotiate with the Council announced in Parliament",
    ),
    "Final act signed": (EventKind.signature, "EP", "Final act signed"),
    "Final act published in Official Journal": (
        EventKind.publication,
        "EUR-Lex",
        "Final act published in the Official Journal",
    ),
    "Procedure lapsed": (EventKind.lapsed, "EP", "Procedure lapsed"),
    # EP activities that the EP API does not always carry (e.g. some 2021 "Fit for 55" files).
    # Added only when no EP API event of the same kind exists on the same day.
    "Vote in committee, 1st reading": (
        EventKind.committee_report,
        "EP",
        "Parliament committee voted on its report",
    ),
    "Vote in committee": (EventKind.committee_report, "EP", "Parliament committee voted on its report"),
    "Vote in committee, 2nd reading": (
        EventKind.committee_report,
        "EP",
        "Parliament committee voted on its second-reading recommendation",
    ),
    "Approval in committee of the text agreed at 1st reading interinstitutional negotiations": (
        EventKind.provisional_agreement,
        "EP",
        "Parliament committee approved the provisional agreement with the Council",
    ),
    "Approval in committee of the text agreed at early 2nd reading interinstitutional negotiations": (
        EventKind.provisional_agreement,
        "EP",
        "Parliament committee approved the agreement reached with the Council for an early second reading",
    ),
    "Debate in Parliament": (EventKind.plenary_debate, "EP", "Debate in Parliament"),
    "Committee decision to open interinstitutional negotiations after 1st reading in Parliament": (
        EventKind.negotiation_mandate,
        "EP",
        "Parliament committee decided to open second-reading negotiations with the Council",
    ),
}

COMMITTEE_ROLE: dict[str, str] = {
    "COMMITTEE_LEAD": "responsible",
    "COMMITTEE_LEAD_JOINT": "joint",
    "COMMITTEE_OPINION": "opinion",
    "COMMITTEE_OPINION_ASSOCIATED": "opinion",
    "COMMITTEE_OPINION_LEGAL_BASIS": "opinion",
    "COMMITTEE_OPINION_RECAST": "opinion",
    "COMMITTEE_OPINION_DA_AI": "opinion",
    "COMMITTEE_OPINION_HUMAN_RIGHTS": "opinion",
    "COMMITTEE_BUDGETARY_ASSESSMENT": "other",
}
RAPPORTEUR_ROLE: dict[str, str] = {
    "RAPPORTEUR": "rapporteur",
    "RAPPORTEUR_CO": "rapporteur",
    "RAPPORTEUR_CHAIR": "rapporteur",
    "RAPPORTEUR_SHADOW": "shadow",
    "RAPPORTEUR_SHADOW_REPORT": "shadow",
    "RAPPORTEUR_OPINION": "opinion_rapporteur",
    "RAPPORTEUR_CHAIR_OPINION": "opinion_rapporteur",
    "RAPPORTEUR_SHADOW_OPINION": "other",
}

CORRIGENDUM_CELEX = re.compile(r"R\(\d+\)$", re.I)  # e.g. 32016R0679R(02) is a corrigendum
COM_RE = re.compile(r"\bCOM\((\d{4})\)\s?(\d{3,4})\b")
CELEX_IN_URL = re.compile(r"(?:numdoc=|CELEX[:%3A]+)([0-9][0-9A-Z()]{6,})", re.I)
DATE_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
PROC_ID_RE = re.compile(r"^(\d{4})-(\d{4}[A-Z]?)$")
PROC_REF_RE = re.compile(r"^(\d{4})/(\d{4}[A-Z]?)\(([A-Z]{3})\)$")


# ====================================================================== small helpers
def as_list(x: Any) -> list[Any]:
    """JSON-LD framing collapses single-item arrays; normalize to a list."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def last_segment(uri: str | None) -> str:
    return (uri or "").rstrip("/").rsplit("/", 1)[-1]


# Broader concepts that some events carry next to their specific type.
GENERIC_ACTIVITY_TYPES = {"PLENARY_ACTIVITY", "COMMITTEE_ACTIVITY", "PROCEEDING_ACTIVITY", "MEETING_ACTIVITY"}


def activity_type(e: dict[str, Any]) -> str:
    """The event's activity type URI; when several are given, the most specific one."""
    types = [t for t in as_list(e.get("had_activity_type")) if isinstance(t, str)]
    specific = [t for t in types if last_segment(t) not in GENERIC_ACTIVITY_TYPES]
    known = [t for t in specific if last_segment(t) in ACTIVITY_MAP]
    return (known or specific or types or [""])[0]


def reading_stage(e: dict[str, Any]) -> str | None:
    """The procedure phase of an event, only when exactly one is given."""
    stages = [x for x in as_list(e.get("occured_at_stage")) if isinstance(x, str)]
    return stages[0] if len(stages) == 1 else None


def oeil_url(reference: str) -> str:
    return f"{OEIL_FILE}?reference={reference}"


def api_procedure_url(pid: str) -> str:
    return f"{EP_API}/procedures/{pid}?format=application/ld+json"


def dmy_to_iso(s: str) -> str | None:
    m = DATE_DMY.match(s.strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def humanize_type(raw: str) -> str:
    return raw.replace("_", " ").lower().capitalize()


def activity_title(raw: str, stage: str | None = None) -> tuple[EventKind, str]:
    """Deterministic (kind, title) for an EP activity type (with or without the def/ prefix)."""
    code = last_segment(raw)
    if code in ACTIVITY_MAP:
        kind, title = ACTIVITY_MAP[code]
    else:
        kind, title = EventKind.other, f"Parliament activity: {humanize_type(code)}"
    reading = READING.get(last_segment(stage)) if stage else None
    if reading and code in READING_QUALIFIED:
        title = f"{title} ({reading})"
    return kind, title


def normalize_proc_id(value: str) -> str | None:
    """'2012-0011' or '2012/0011(COD)' -> '2012-0011'."""
    v = str(value).strip()
    if PROC_ID_RE.match(v):
        return v
    m = PROC_REF_RE.match(v)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^(\d{4})/(\d{4}[A-Z]?)$", v)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def com_ref(year: str, num: str) -> str:
    return f"COM({year}){int(num):04d}"


# ---------------------------------------------------------------- EP document references
def ep_docref(doc_uri: str, date: str | None = None) -> DocRef:
    """Official EP document id -> DocRef with label/kind and a doceo URL where the pattern is
    the one OEIL itself links to (reports, adopted texts, committee documents)."""
    did = last_segment(doc_uri)
    label: str | None = None
    kind = "other"
    url: str | None = None
    if m := re.fullmatch(r"A-(\d+)-(\d{4})-(\d{4})", did):
        label, kind, url = f"A{m[1]}-{m[3]}/{m[2]}", "report", DOCEO.format(id=did)
    elif m := re.fullmatch(r"TA-(\d+)-(\d{4})-(\d{4})", did):
        label, kind, url = f"T{m[1]}-{m[3]}/{m[2]}", "adopted_text", DOCEO.format(id=did)
    elif m := re.fullmatch(r"C-(\d+)-(\d{4})-(\d{4})", did):
        # EP registration number of a document received from another institution (proposal,
        # Council position, corrigendum...): the API does not say which, so kind stays "other".
        label = f"C{m[1]}-{m[3]}/{m[2]}"
    elif m := re.fullmatch(r"([A-Z]{4}|CJ\d{2})-(AD|PA|PR|AM|AG|AL)-(\d{6})", did):
        pe = f"PE{m[3][:3]}.{m[3][3:]}"
        kinds = {"AD": "opinion", "AL": "opinion", "AG": "agreement"}
        kind = kinds.get(m[2], "other")
        names = {
            "AD": "Committee opinion",
            "AL": "Committee opinion (letter)",
            "PA": "Draft opinion",
            "PR": "Draft report",
            "AM": "Amendments tabled in committee",
            "AG": "Provisional agreement text",
        }
        label = f"{names[m[2]]} {m[1]} {pe}"
        if m[2] in ("AD", "PA", "PR", "AM"):
            url = DOCEO.format(id=did)
    elif m := re.fullmatch(r"A-(\d+)-(\d{4})-(\d{4})-AM-(\d+)-(\d+)", did):
        label = f"Plenary amendments {m[4]}-{m[5]} to A{m[1]}-{m[3]}/{m[2]}"
    elif m := re.fullmatch(r"SP-(\d{4})-(\d+)-.*", did):
        label = f"SP({m[1]}){m[2]}"
    elif did.startswith("PV-"):
        label = "Minutes of the sitting"
    elif did.startswith("CRE-"):
        label = "Verbatim report of proceedings"
    return DocRef(id=did, label=label, kind=kind, date=date, url=url)


def is_key_document(d: DocRef) -> bool:
    """Documents listed at procedure level (event-level docs keep everything)."""
    return d.kind in ("proposal", "report", "opinion", "adopted_text", "agreement")


# ====================================================================== OEIL parsing
@dataclass
class OeilEvent:
    date: str
    label: str
    refs: list[tuple[str, str | None]] = field(default_factory=list)  # (reference text, url)


@dataclass
class OeilPlayer:
    code: str
    role: str  # CommitteeRole.role
    rapporteurs: list[str] = field(default_factory=list)  # EP person ids
    shadows: list[str] = field(default_factory=list)


# OEIL key-players table headers -> CommitteeRole.role
# ("Former ..." = committee of a previous parliamentary term; same role.)
OEIL_COMMITTEE_HEADER = {
    "Committee responsible": "responsible",
    "Former committee responsible": "responsible",
    "Joint committee responsible": "joint",
    "Former joint committee responsible": "joint",
    "Committee for opinion": "opinion",
    "Former committee for opinion": "opinion",
    "Committee for opinion on the legal basis": "opinion",
    "Former committee for opinion on the legal basis": "opinion",
    "Committee for opinion on the recast technique": "opinion",
    "Former committee for opinion on the recast technique": "opinion",
    "Committee for budgetary assessment": "other",
}


@dataclass
class OeilInfo:
    title: str | None = None  # procedure title shown on the OEIL page (often the short title)
    status: str | None = None
    instrument: str | None = None
    subjects: list[Subject] = field(default_factory=list)
    committee_names: dict[str, str] = field(default_factory=dict)
    mep_names: dict[str, str] = field(default_factory=dict)  # EP person id -> "SURNAME Given"
    events: list[OeilEvent] = field(default_factory=list)
    com_docs: list[DocRef] = field(default_factory=list)
    final_acts: list[DocRef] = field(default_factory=list)  # id = CELEX
    players: list[OeilPlayer] = field(default_factory=list)  # EP committees + rapporteurs
    has_basic_info: bool = False  # the page has the procedure file's "Basic information" section
    reference: str | None = None  # procedure reference shown in that section


class OeilPageError(ValueError):
    """An OEIL answer (HTTP 200) that is not the procedure file asked for (error/maintenance/WAF page)."""


def check_oeil_page(info: OeilInfo, reference: str) -> None:
    """Raise OeilPageError unless the parsed page is the procedure file of `reference`."""
    if not info.has_basic_info:
        raise OeilPageError(f"OEIL page for {reference} has no procedure file (no 'Basic information')")
    wanted = normalize_proc_id(reference)
    if info.reference and wanted and normalize_proc_id(info.reference) != wanted:
        raise OeilPageError(f"OEIL page for {reference} shows procedure {info.reference}")


def _text(el: Any) -> str:
    return " ".join(el.text_content().split())


def parse_oeil(body: bytes | str) -> OeilInfo:
    """Parse an OEIL procedure-file page. Missing sections simply leave fields empty."""
    if isinstance(body, bytes):  # OEIL serves UTF-8; do not let lxml guess (it defaults to latin-1)
        body = body.decode("utf-8", errors="replace")
    doc = lxml_html.fromstring(body)
    info = OeilInfo()
    # page header: <h2 class="es_title-h1">reference</h2> ... <h2 class="es_title-h2 mb-3">title</h2>
    head = doc.xpath('//h2[contains(@class,"es_title-h2") and contains(@class,"mb-3")]')
    if head:
        info.title = _text(head[0]) or None

    sec1 = doc.xpath('//*[@id="section1"]')
    if sec1:
        s1 = sec1[0]
        info.has_basic_info = True
        for p in s1.xpath('.//p[contains(@class,"font-weight-bold")]'):
            if PROC_REF_RE.match(_text(p)):
                info.reference = _text(p)
                break
        st = s1.xpath('.//p[normalize-space()="Status"]/following-sibling::p[1]')
        if st:
            info.status = _text(st[0]) or None
        subj = s1.xpath('.//p[normalize-space()="Subject"]/following-sibling::p[1]')
        if subj:
            lines = [" ".join(t.split()) for t in subj[0].itertext()]
            for line in lines:
                if m := re.match(r"^(\d+(?:\.\d+)*)\s+(.+)$", line):
                    info.subjects.append(Subject(code=m[1], label=m[2], scheme="ep"))
    for tr in doc.xpath('//*[@id="section5"]//tr'):
        th, td = tr.xpath("./th"), tr.xpath("./td")
        if not th or not td:
            continue
        key = _text(th[0])
        if key == "Legislative instrument":
            info.instrument = _text(td[0]) or None
        elif key == "Stage reached in procedure" and not info.status:
            info.status = _text(td[0]) or None

    for badge in doc.xpath('//*[@id="section2"]//span[contains(@class,"es_badge-committee")]'):
        code = _text(badge)
        name_el = badge.xpath("./following-sibling::div[1]//span")
        if code and name_el and code not in info.committee_names:
            info.committee_names[code] = _text(name_el[0])
    for tbl in doc.xpath('//*[@id="es_accordion-committee"]//table'):
        hdr = tbl.xpath("./thead//th")
        role = OEIL_COMMITTEE_HEADER.get(_text(hdr[0]) if hdr else "", "other")
        current: OeilPlayer | None = None
        for tr in tbl.xpath("./tbody/tr"):
            badge = tr.xpath('./th//span[contains(@class,"es_badge-committee")]')
            ids = [
                m[1]
                for a in tr.xpath('./td//a[contains(@href,"/meps/en/")]')
                if (m := re.search(r"/meps/en/(\d+)", a.get("href", "")))
            ]
            if badge:
                current = OeilPlayer(code=_text(badge[0]), role=role, rapporteurs=ids)
                info.players.append(current)
            elif current is not None:
                current.shadows.extend(ids)
    for a in doc.xpath('//*[@id="section2"]//a[contains(@href,"/meps/en/")]'):
        m = re.search(r"/meps/en/(\d+)", a.get("href", ""))
        name = _text(a)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # drop "(S&D)" group suffix
        if m and name:
            info.mep_names.setdefault(m[1], name)

    for tr in doc.xpath('//*[@id="section3"]//tbody/tr'):
        tds = tr.xpath("./td")
        if len(tds) < 2:
            continue
        date = dmy_to_iso(_text(tds[0]))
        label = _text(tds[1])
        if not date or not label:
            continue
        refs: list[tuple[str, str | None]] = []
        if len(tds) > 2:
            for a in tds[2].xpath(".//a"):
                t = _text(a)
                if t:
                    refs.append((t, a.get("href")))
        info.events.append(OeilEvent(date=date, label=label, refs=refs))

    # Commission documents in the documentation gateway (legislative proposals)
    seen: set[str] = set()
    for tr in doc.xpath('//*[@id="es_accordion-item-doc-gateway-EC"]//tbody/tr'):
        cells = tr.xpath("./th|./td")
        if len(cells) < 3:
            continue
        dtype = _text(cells[0])
        ref_a = cells[1].xpath(".//a")
        ref_text = _text(ref_a[0]) if ref_a else _text(cells[1])
        m = COM_RE.search(ref_text)
        if not m or "proposal" not in dtype.lower():
            continue
        cid = com_ref(m[1], m[2])
        if cid in seen:
            continue
        seen.add(cid)
        date = dmy_to_iso(_text(cells[2])) if len(cells) > 2 else None
        url = ref_a[0].get("href") if ref_a else None
        info.com_docs.append(DocRef(id=cid, label=dtype, kind="proposal", date=date, url=url))
    # COM references also appear on key events (e.g. when the gateway is empty)
    for ev in info.events:
        if ev.label in OEIL_EVENT_MAP and OEIL_EVENT_MAP[ev.label][0] == EventKind.proposal:
            for t, url in ev.refs:
                m = COM_RE.search(t)
                if m and com_ref(m[1], m[2]) not in seen:
                    cid = com_ref(m[1], m[2])
                    seen.add(cid)
                    info.com_docs.append(
                        DocRef(id=cid, label="Legislative proposal", kind="proposal", date=ev.date, url=url)
                    )

    for a in doc.xpath('//*[@id="section9"]//a[@href]'):
        m = CELEX_IN_URL.search(a.get("href", ""))
        # OEIL also lists "Corrigendum to final act <CELEX>" entries, some of them other acts altogether (for
        # 2021/0426(COD): Commission Implementing Regulation 32025R1328); they are not the procedure's final act
        if m and not CORRIGENDUM_CELEX.search(m[1]) and not _text(a).lower().startswith("corrigendum"):
            celex = m[1].upper()
            if not any(f.id == celex for f in info.final_acts):
                info.final_acts.append(
                    DocRef(
                        id=celex,
                        label=_text(a) or None,
                        kind="other",
                        url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
                    )
                )
    return info


# ====================================================================== building records
def _src(
    institution: Institution, url: str, label: str | None, identifier: str, retrieved_at: str
) -> SourceRef:
    # Event-level sources carry no label (the procedure record has one): keeps the snapshot small.
    return SourceRef(
        institution=institution, url=url, label=label, identifier=identifier, retrieved_at=retrieved_at
    )


def build_events(
    proc: dict[str, Any], retrieved_at: str, oeil: OeilInfo | None, reference: str
) -> list[Event]:
    """EP API activities -> Events (+ OEIL-only key events). Sorted by (date, id)."""
    pid = proc["process_id"]
    raw_events: list[dict[str, Any]] = []
    for e in as_list(proc.get("consists_of")):
        if not isinstance(e, dict) or not isinstance(e.get("activity_date"), str):
            continue
        aid = e.get("activity_id") or (last_segment(e["id"]) if isinstance(e.get("id"), str) else None)
        if aid:
            raw_events.append({**e, "activity_id": str(aid)})

    def docs_of(e: dict[str, Any]) -> list[DocRef]:
        out: list[DocRef] = []
        for k in ("decided_on_a_realization_of", "based_on_a_realization_of", "recorded_in_a_realization_of"):
            for d in as_list(e.get(k)):
                if isinstance(d, str):
                    out.append(ep_docref(d))
        return out

    # 1) fold vote records into the same-day plenary decision event
    decisions_by_date: dict[str, list[dict[str, Any]]] = {}
    for e in raw_events:
        if last_segment(activity_type(e)) in PLENARY_DECISION_TYPES:
            decisions_by_date.setdefault(e["activity_date"][:10], []).append(e)
    folded_docs: dict[str, list[DocRef]] = {}
    keep: list[dict[str, Any]] = []
    for e in raw_events:
        code = last_segment(activity_type(e))
        day = e["activity_date"][:10]
        if code in VOTE_RECORD_TYPES and day in decisions_by_date:
            target = sorted(decisions_by_date[day], key=lambda x: x["activity_id"])[-1]
            folded_docs.setdefault(target["activity_id"], []).extend(docs_of(e))
            continue
        keep.append(e)

    # 2) group amendment tablings (committee or plenary) per day into one event
    events: list[Event] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in keep:
        code = last_segment(activity_type(e))
        day = e["activity_date"][:10]
        is_plenary_am = code == "TABLING_PLENARY" and any(
            "-AM-" in last_segment(d) for d in as_list(e.get("based_on_a_realization_of"))
        )
        if code == "COMMITTEE_TABLING_AMENDMENT" or is_plenary_am:
            groups.setdefault(
                (day, "committee" if code == "COMMITTEE_TABLING_AMENDMENT" else "plenary"), []
            ).append(e)
            continue
        kind, title = activity_title(activity_type(e), reading_stage(e))
        code_inst = ACTIVITY_INSTITUTION.get(code, "EP")
        docs = docs_of(e) + folded_docs.get(e["activity_id"], [])
        detail = None
        if m := re.search(r"-ADCP-([A-Z]{4}|CJ\d{2})-", e["activity_id"]):
            detail = f"Committee: {m[1]}"
        events.append(
            Event(
                id=e["activity_id"],
                date=day,
                kind=kind,
                raw_type=activity_type(e) or None,
                institution=code_inst,
                title=title,
                detail=detail,
                docs=_dedupe_docs(docs),
                source=_src(
                    "EP",
                    f"{EP_API}/events/{e['activity_id']}",  # JSON-LD is the API's default format
                    None,
                    e["activity_id"],
                    retrieved_at,
                ),
            )
        )
    for (day, where), items in sorted(groups.items()):
        items = sorted(items, key=lambda x: x["activity_id"])
        raw = activity_type(items[0]) or None
        title = (
            "Amendments tabled in Parliament committee"
            if where == "committee"
            else "Amendments tabled for the plenary"
        )
        docs = [d for it in items for d in docs_of(it)]
        first = items[0]["activity_id"]
        events.append(
            Event(
                id=first if len(items) == 1 else f"{first}+{len(items) - 1}",
                date=day,
                kind=EventKind.other,
                raw_type=raw,
                institution="EP",
                title=title,
                detail=None if len(items) == 1 else f"{len(items)} amendment documents",
                docs=_dedupe_docs(docs),
                source=_src(
                    "EP",
                    api_procedure_url(pid),
                    None,
                    first,
                    retrieved_at,
                ),
            )
        )

    # 3) OEIL key events not recorded by the EP API
    if oeil:
        have = {(ev.date, ev.kind, ev.institution) for ev in events}
        counter: dict[str, int] = {}
        for oe in oeil.events:
            mapped = OEIL_EVENT_MAP.get(oe.label)
            if not mapped:
                continue
            kind, inst, title = mapped
            if (oe.date, kind, inst) in have:
                continue  # already recorded by the EP API on the same day
            if kind in (EventKind.signature, EventKind.publication) and any(ev.kind == kind for ev in events):
                continue
            docs = []
            for t, url in oe.refs:
                m = COM_RE.search(t)
                docs.append(
                    DocRef(
                        id=com_ref(m[1], m[2]) if m else t,
                        label=None,
                        kind="proposal" if m else "other",
                        date=oe.date,
                        url=url if url and url.startswith("http") else None,
                    )
                )
            slug = re.sub(r"[^a-z0-9]+", "-", oe.label.lower()).strip("-")[:40]
            base = f"OEIL-{pid}-{oe.date}-{slug}"
            n = counter.get(base, 0)
            counter[base] = n + 1
            events.append(
                Event(
                    id=base if n == 0 else f"{base}-{n + 1}",
                    date=oe.date,
                    kind=kind,
                    raw_type=f"oeil:{oe.label}",
                    institution=inst,
                    title=title,
                    docs=_dedupe_docs(docs),
                    source=_src(
                        "OEIL",
                        oeil_url(reference),
                        "Legislative Observatory (OEIL) key events",
                        reference,
                        retrieved_at,
                    ),
                )
            )
            have.add((oe.date, kind, inst))
    events.sort(key=lambda ev: (ev.date, _kind_order(ev.kind), ev.id))
    return events


_KIND_ORDER = {k: i for i, k in enumerate(EventKind)}


def _kind_order(k: EventKind) -> int:
    return _KIND_ORDER[k]


def _dedupe_docs(docs: Iterable[DocRef]) -> list[DocRef]:
    out: dict[str, DocRef] = {}
    for d in docs:
        if d.id not in out:
            out[d.id] = d
    return list(out.values())


def build_participants(
    proc: dict[str, Any], names: Callable[[str], str | None], committee_names: dict[str, str]
) -> tuple[list[CommitteeRole], list[Rapporteur]]:
    committees: dict[tuple[str, str], CommitteeRole] = {}
    leads = [
        p
        for p in as_list(proc.get("had_participation"))
        if isinstance(p, dict)
        and "COMMITTEE_LEAD" in [last_segment(r) for r in as_list(p.get("participation_role"))]
    ]
    joint = len(leads) > 1
    rapps: dict[tuple[str, str, str | None], Rapporteur] = {}
    for p in as_list(proc.get("had_participation")):
        if not isinstance(p, dict):
            continue
        for role_uri in as_list(p.get("participation_role")):
            role = last_segment(role_uri)
            if role in COMMITTEE_ROLE:
                for org in as_list(p.get("had_participant_organization")):
                    code = last_segment(org)
                    r = COMMITTEE_ROLE[role]
                    if role == "COMMITTEE_LEAD" and joint:
                        r = "joint"
                    committees.setdefault(
                        (code, r), CommitteeRole(code=code, name=committee_names.get(code), role=r)
                    )
            elif role in RAPPORTEUR_ROLE:
                committee = last_segment(p.get("participation_in_name_of")) or None
                for person in as_list(p.get("had_participant_person")):
                    mep_id = last_segment(person)
                    name = names(mep_id)
                    if not name:
                        log.debug("no name for EP person %s (%s); skipped", mep_id, proc.get("process_id"))
                        continue
                    key = (mep_id, RAPPORTEUR_ROLE[role], committee)
                    rapps.setdefault(
                        key,
                        Rapporteur(mep_id=mep_id, name=name, committee=committee, role=RAPPORTEUR_ROLE[role]),
                    )
    return _sorted_participants(committees.values(), rapps.values())


def oeil_participants(
    oeil: OeilInfo, names: Callable[[str], str | None], committee_names: dict[str, str]
) -> tuple[list[CommitteeRole], list[Rapporteur]]:
    """Fallback for procedures without participations in the EP API (mostly older files)."""
    committees: dict[tuple[str, str], CommitteeRole] = {}
    rapps: dict[tuple[str, str, str | None], Rapporteur] = {}
    for pl in oeil.players:
        committees.setdefault(
            (pl.code, pl.role), CommitteeRole(code=pl.code, name=committee_names.get(pl.code), role=pl.role)
        )
        main = pl.role in ("responsible", "joint")
        groups = (
            (pl.rapporteurs, "rapporteur" if main else "opinion_rapporteur"),
            (pl.shadows, "shadow" if main else "other"),
        )
        for ids, role in groups:
            for mep_id in ids:
                name = names(mep_id)
                if name:
                    rapps.setdefault(
                        (mep_id, role, pl.code),
                        Rapporteur(mep_id=mep_id, name=name, committee=pl.code, role=role),
                    )
    return _sorted_participants(committees.values(), rapps.values())


def _sorted_participants(
    committees: Iterable[CommitteeRole], rapps: Iterable[Rapporteur]
) -> tuple[list[CommitteeRole], list[Rapporteur]]:
    role_order = {"responsible": 0, "joint": 1, "opinion": 2, "other": 3}
    rrole_order = {"rapporteur": 0, "shadow": 1, "opinion_rapporteur": 2, "other": 3}
    cs = sorted(committees, key=lambda c: (role_order[c.role], c.code))
    rs = sorted(rapps, key=lambda r: (rrole_order[r.role], r.committee or "", r.name, r.mep_id or ""))
    return cs, rs


class InvalidRecord(ValueError):
    """The EP record cannot be turned into a Procedure without guessing (it is skipped)."""


def _single(value: Any, what: str, pid: str) -> str | None:
    values = sorted({v for v in as_list(value) if isinstance(v, str) and v})
    if len(values) > 1:
        raise InvalidRecord(f"EP record {pid} merges several procedures ({what}: {', '.join(values)})")
    return values[0] if values else None


def build_procedure(
    proc: dict[str, Any],
    retrieved_at: str,
    oeil: OeilInfo | None,
    names: Callable[[str], str | None],
    committee_names: dict[str, str] | None = None,
    reference: str | None = None,
) -> Procedure:
    """`reference` = the procedure reference under which the id was discovered (used only when
    the EP record itself has none, and only if it matches the id)."""
    pid = proc.get("process_id") or ""
    label = _single(proc.get("label"), "labels", pid)
    if not label and reference and normalize_proc_id(reference) == pid and PROC_REF_RE.match(reference):
        label = reference
    if not label:
        raise InvalidRecord(f"EP record {pid} has no procedure reference")
    reference = label
    ptype = last_segment(_single(proc.get("process_type"), "types", pid)) or (
        PROC_REF_RE.match(reference)[3] if PROC_REF_RE.match(reference) else ""
    )
    titles = proc.get("process_title")
    if isinstance(titles, list):
        raise InvalidRecord(f"EP record {pid} has several titles")
    title = titles.get("en") if isinstance(titles, dict) else None
    if not title and oeil and oeil.title:
        title = oeil.title  # OEIL procedure-file title (official EP page); never translated or invented
    if not title:
        raise InvalidRecord(f"no English title for {reference} in the EP record or OEIL")
    events = build_events(proc, retrieved_at, oeil, reference)
    committee_names = {**(committee_names or {}), **(oeil.committee_names if oeil else {})}

    def name_of(mep_id: str) -> str | None:
        return names(mep_id) or (oeil.mep_names.get(mep_id) if oeil else None)

    committees, rapporteurs = build_participants(proc, name_of, committee_names)
    if oeil and (not committees or not rapporteurs):
        o_committees, o_rapporteurs = oeil_participants(oeil, name_of, committee_names)
        committees = committees or o_committees
        rapporteurs = rapporteurs or o_rapporteurs

    documents: dict[str, DocRef] = {}
    if oeil:
        for d in oeil.com_docs:
            documents.setdefault(d.id, d)
    for ev in events:
        for d in ev.docs:
            if is_key_document(d) and d.id not in documents:
                documents[d.id] = d.model_copy(update={"date": d.date or ev.date})
    for d in as_list(proc.get("created_a_realization_of")):
        if isinstance(d, str):
            ref = ep_docref(d)
            if is_key_document(ref):
                documents.setdefault(ref.id, ref)
    docs = sorted(documents.values(), key=lambda d: (d.date or "9999", d.id))

    com_refs = sorted({d.id for d in docs if COM_RE.fullmatch(d.id)}, key=lambda c: (c[4:8], c))
    proposal_dates = [e.date for e in events if e.kind == EventKind.proposal]
    started = min(proposal_dates) if proposal_dates else (events[0].date if events else None)
    return Procedure(
        id=pid,
        reference=reference,
        type=ptype,
        title=title,
        subjects=list(oeil.subjects) if oeil else [],
        stage_raw=oeil.status if oeil else None,
        started=started,
        committees=committees,
        rapporteurs=rapporteurs,
        events=events,
        documents=docs,
        com_refs=com_refs,
        celex_refs=[f.id for f in oeil.final_acts] if oeil else [],
        oeil_url=oeil_url(reference),
        source=SourceRef(
            institution="EP",
            url=api_procedure_url(pid),
            label=f"EP Open Data API – procedure {reference}"
            + ("; Legislative Observatory (OEIL) procedure file" if oeil else ""),
            identifier=pid,
            retrieved_at=retrieved_at,
        ),
    )


# ====================================================================== network
class _Pacer:
    """Spaces out *network* requests to one host across threads. Cached responses return in
    well under `fast_s`, so they do not consume the budget."""

    def __init__(self, gap_s: float, fast_s: float = 0.03):
        self.gap_s = gap_s
        self.fast_s = fast_s
        self._next = 0.0
        self._lock = threading.Lock()

    def call(self, fn: Callable[[], bytes]) -> bytes:
        with self._lock:
            wait = self._next - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        t0 = time.monotonic()
        try:
            return fn()
        finally:
            if time.monotonic() - t0 > self.fast_s:
                with self._lock:
                    self._next = max(self._next, time.monotonic()) + self.gap_s


# The list endpoint answered HTTP 500 to limit=1000 (2026-10-22) and, for COD, to 500 and 250 (2026-10-23,
# after about 20 s each); limit=125 worked.
LIST_PAGE = 500
MIN_LIST_PAGE = 125
SMALLER_PAGE_STATUSES = (500, 502, 503, 504, None)  # server errors and timeouts: try a smaller page


def list_procedure_ids(
    http: Http, ptype: str, page: int = LIST_PAGE, sizes: dict[str, int] | None = None
) -> list[tuple[str, str]]:
    """(process id, label) pairs of one procedure type. While the page can still be halved, a request gets a
    single attempt, and a server error or timeout halves the page size (down to MIN_LIST_PAGE, where Http's
    usual retries apply) before giving up with HttpError. `sizes` (process type -> page size) receives the
    size that worked, so the next run starts with it."""
    out: list[tuple[str, str]] = []
    offset = 0
    while True:
        params = {"process-type": ptype, "format": "application/ld+json", "offset": offset, "limit": page}
        smaller = page // 2 >= MIN_LIST_PAGE
        try:
            d = http.get_json(f"{EP_API}/procedures", params=params, **({"retries": 0} if smaller else {}))
        except HttpError as e:
            if not smaller:
                raise
            if e.status in SMALLER_PAGE_STATUSES:
                page //= 2
                log.warning("ep_procedures: list %s failed (%s); retrying with limit=%d", ptype, e, page)
                continue
            d = http.get_json(f"{EP_API}/procedures", params=params)  # e.g. 429: the usual retries, same page
        items = as_list(d.get("data"))
        for x in items:
            if isinstance(x, dict) and x.get("process_id"):
                out.append((x["process_id"], x.get("label") or x["process_id"]))
        total = (d.get("meta") or {}).get("total")
        offset += len(items)
        if not items or len(items) < page or (total is not None and offset >= total):
            break
    if sizes is not None:
        sizes[ptype] = page
    return out


def featured_ids() -> list[str]:
    path = CURATED / "featured.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get("procedures") or raw.get("featured") or []
    out: list[str] = []
    for entry in raw if isinstance(raw, list) else []:
        value = entry.get("id") if isinstance(entry, dict) else entry
        if value is None:
            continue
        pid = normalize_proc_id(str(value))
        if pid:
            out.append(pid)
        else:
            log.warning("featured.yaml: unrecognized procedure id %r", value)
    return out


class MepNames:
    """EP person id -> display name. Prefers the ep_people snapshot; for persons it lacks, the
    EP API MEP list of the parliamentary term(s) in which they took part (givenName +
    familyName as published). Term lists are downloaded at most once per run."""

    def __init__(self, http: Http):
        self.http = http
        self.names: dict[str, str] = {}
        self.fetched_terms: set[int] = set()
        try:
            for m in read_records("ep_people", "meps", Mep):
                self.names[m.id] = m.name
        except Exception as e:  # noqa: BLE001 - snapshot of another source may be absent/invalid
            log.info("ep_people snapshot not usable (%s); using EP API MEP lists", e)

    def ensure(self, people: Iterable[tuple[str, int | None]]) -> None:
        """`people` = (person id, term or None) pairs; None = known only from OEIL (any term)."""
        missing = {(pid, t) for pid, t in people if pid not in self.names}
        terms = {t for _, t in missing if t is not None} | (
            set(FALLBACK_TERMS) if any(t is None for _, t in missing) else set()
        )
        for term in sorted(terms - self.fetched_terms):
            self.fetched_terms.add(term)
            try:
                offset = 0
                while True:
                    d = self.http.get_json(
                        f"{EP_API}/meps",
                        params={
                            "parliamentary-term": term,
                            "format": "application/ld+json",
                            "offset": offset,
                            "limit": 1000,
                        },
                    )
                    items = as_list(d.get("data"))
                    for x in items:
                        if not isinstance(x, dict) or not x.get("identifier"):
                            continue
                        given, family = x.get("givenName"), x.get("familyName")
                        name = f"{given} {family}".strip() if given and family else x.get("label")
                        if name:
                            self.names.setdefault(str(x["identifier"]), name)
                    offset += len(items)
                    if len(items) < 1000:
                        break
            except HttpError as e:
                log.warning("MEP list for term %s unavailable: %s", term, e)

    def get(self, mep_id: str) -> str | None:
        return self.names.get(mep_id)


def mep_name_resolver(http: Http, people: Iterable[tuple[str, int | None]]) -> Callable[[str], str | None]:
    names = MepNames(http)
    names.ensure(people)
    return names.get


def _people_from(procs: Iterable[dict[str, Any]]) -> set[tuple[str, int | None]]:
    out: set[tuple[str, int | None]] = set()
    for p in procs:
        for part in as_list(p.get("had_participation")):
            if not isinstance(part, dict):
                continue
            m = re.search(r"ep-(\d+)$", str(part.get("parliamentary_term") or ""))
            for person in as_list(part.get("had_participant_person")):
                if isinstance(person, str):
                    out.add((last_segment(person), int(m[1]) if m else None))
    return out


# ====================================================================== incremental fetch
def _today() -> date:  # monkeypatched in tests
    return datetime.now(UTC).date()


def needs_refresh(
    rec: Procedure, acts: list[LegalAct], today: date, recent_days: int = RECENT_DAYS
) -> str | None:
    """Why an existing snapshot record must be re-fetched in incremental mode (None = reuse it)."""
    from pipeline.analysis.status import classify  # local import: analysis depends on models only

    if rec.stage_raw is None:
        return "no OEIL data"
    cutoff = (today - timedelta(days=recent_days)).isoformat()
    if any(e.date >= cutoff for e in rec.events):
        return "recent event"
    stage = classify(rec, acts, [], today).stage
    if stage not in TERMINAL_STAGES:
        return f"open ({stage})"
    return None


def select_ids(
    wanted: dict[str, str],
    existing: dict[str, Procedure],
    featured: list[str],
    acts_by_ref: dict[str, list[LegalAct]],
    today: date,
    full: bool,
) -> tuple[list[str], Counter[str]]:
    """Ids to fetch this run (newest first) and the reasons, for the manifest note."""
    reasons: Counter[str] = Counter()
    out: list[str] = []
    for pid in sorted(wanted, reverse=True):
        if full:
            why: str | None = "full refresh"
        elif pid not in existing:
            why = "new"
        elif pid in featured:
            why = "featured"
        else:
            rec = existing[pid]
            why = needs_refresh(rec, acts_by_ref.get(rec.reference, []), today)
            why = why.split(" (")[0] if why else None
        if why:
            reasons[why] += 1
            out.append(pid)
    return out, reasons


def in_scope_ref(ref: str, any_year: bool = False) -> str | None:
    """'2016/0224A(COD)' -> '2016-0224A' if the reference is in scope (type, year), else None.
    any_year: the procedure of an act in the EUR-Lex snapshot (acts since 2014, whatever the year the
    procedure started, e.g. 2013/0025(COD) -> Directive 2015/849)."""
    m = PROC_REF_RE.match(ref.strip())
    if not m or m[3] not in PROCEDURE_TYPES or (int(m[1]) < MIN_YEAR and not any_year):
        return None
    return f"{m[1]}-{m[2]}"


DISCOVERY_SOURCES: tuple[tuple[str, str, type[Any]], ...] = (
    ("eurlex", "acts", LegalAct),
    ("ep_votes", "votes", EpVote),
)


def discover_refs() -> dict[str, tuple[str, str]]:
    """In-scope procedure ids referenced by other snapshots: id -> (reference, source).

    The paged EP list endpoint repeats some rows and omits others, so ids are also taken from the
    procedure references of EUR-Lex acts and EP plenary votes."""
    out: dict[str, tuple[str, str]] = {}
    for source, name, model in DISCOVERY_SOURCES:
        try:
            records = read_records(source, name, model)
        except Exception as e:  # noqa: BLE001 - another source's snapshot may be absent/invalid
            log.info("%s snapshot not usable for id discovery (%s)", source, e)
            continue
        for r in records:
            for ref in r.procedure_refs:
                pid = in_scope_ref(ref, any_year=source == "eurlex")
                if pid:
                    out.setdefault(pid, (ref, source))
    return out


def split_parts(pid: str, ids: Iterable[str]) -> list[str]:
    """'2021-0211' -> ['2021-0211A', '2021-0211B'] if those split procedures are known."""
    return sorted(i for i in ids if re.fullmatch(re.escape(pid) + r"[A-Z]", i))


def has_oeil_data(p: Procedure) -> bool:
    """The record carries data taken from its OEIL procedure file."""
    return (
        p.stage_raw is not None
        or bool(p.subjects)
        or bool(p.celex_refs)
        or any(e.source.institution == "OEIL" for e in p.events)
    )


SEQUENTIAL_RETRY_STOP = 3  # consecutive failed one-by-one retries that end a chunk's retry pass (outage)
# Ids failing one after the other (EP API, or OEIL other than 404) after which no new id is started in this run:
# an outage (with slow failures, up to Http's 240 s per call, it would otherwise use the whole run window).
OUTAGE_STOP = 8
# Runs in a row in which OEIL answered 404 for a file whose record has OEIL data, after which the id is no longer
# kept pending: the stored record (as last read) stays, and the manifest note says so.
OEIL_GONE_RUNS = 3


class _Run:
    """State shared by the chunks of one fetch run."""

    def __init__(
        self,
        http: Http,
        wanted: dict[str, str],
        committees: dict[str, str],
        enriched: Iterable[str] = (),
        deadline: float | None = None,
        hard_deadline: float | None = None,
        min_progress: int = CHUNK_SIZE,
    ):
        self.http = http
        self.wanted = wanted
        self.ep_pacer, self.oeil_pacer = _Pacer(EP_API_GAP_S), _Pacer(OEIL_GAP_S)
        self.names = MepNames(http)
        self.committees = committees  # code -> name, grows with every OEIL page seen
        self.enriched = set(enriched)  # ids whose snapshot record has OEIL data
        # No new id is started after `hard_deadline` (run-wide), nor after `deadline` (this source's budget)
        # once `min_progress` ids were started (a run always makes some progress).
        self.deadline, self.hard_deadline, self.min_progress = deadline, hard_deadline, min_progress
        self.started = 0
        self.errors: dict[str, str] = {}  # transient/unexpected failures (stay pending)
        self.not_found: list[str] = []  # GET /procedures/{id} answers 404
        self.invalid: dict[str, str] = {}  # records that cannot be built without guessing
        self.oeil_errors: list[str] = []
        self.oeil_missing: list[str] = []  # OEIL answers 404 (no procedure file)
        # previously enriched ids whose OEIL page could not be read: record kept as is, id stays pending
        self.oeil_kept: dict[str, str] = {}
        self.deferred: set[str] = set()  # not started: time budget reached (stay pending)
        self.degraded: set[str] = set()  # recorded this run with EP API data only because OEIL failed (not 404)
        self.build_errors: list[str] = []
        self.requests = 0
        self.failing = 0  # ids that failed one after the other (see note_result)
        self.outage = False  # OUTAGE_STOP ids failed in a row: no new id is started
        self.lock = threading.Lock()

    def out_of_time(self) -> bool:
        if self.outage or past(self.hard_deadline):
            return True
        # the first chunk always makes some progress, unless its ids keep failing (a slow outage)
        return past(self.deadline) and (self.started >= self.min_progress or self.failing >= SEQUENTIAL_RETRY_STOP)

    def note_result(self, ok: bool) -> None:
        """An id was answered (ok: the EP record, and the OEIL page or its 404) or failed."""
        with self.lock:
            self.failing = 0 if ok else self.failing + 1
            if self.failing >= OUTAGE_STOP and not self.outage:
                self.outage = True
                log.warning("ep_procedures: %d ids failed in a row; no new id is started", self.failing)


def _fetch_one(run: _Run, pid: str) -> tuple[dict[str, Any], str, OeilInfo | None, str | None] | None:
    """(EP record, retrieved_at, OEIL info, OEIL failure or None), or None if the EP record could not be
    fetched (the reason is in run.errors / run.not_found / run.deferred)."""
    with run.lock:
        if run.out_of_time():
            run.deferred.add(pid)
            return None
        run.started += 1
        run.deferred.discard(pid)
    try:
        with run.lock:
            run.requests += 1
        body = run.ep_pacer.call(lambda: run.http.get(f"{EP_API}/procedures/{pid}", params=JSONLD))
        data = json.loads(body)
        procs = [p for p in as_list(data.get("data")) if isinstance(p, dict)]
        for p in procs:  # some records lack process_id but carry it in their id "eli/dl/proc/<id>"
            if not p.get("process_id") and isinstance(p.get("id"), str) and "/proc/" in p["id"]:
                p["process_id"] = last_segment(p["id"])
        procs = [p for p in procs if p.get("process_id")]
        if not procs:
            raise ValueError("empty response")
        proc = procs[0]
    except HttpError as e:
        with run.lock:
            if e.status == 404:
                run.not_found.append(pid)
            else:
                run.errors[pid] = str(e)[:120]
        run.note_result(e.status == 404)
        return None
    except Exception as e:  # noqa: BLE001
        with run.lock:
            run.errors[pid] = str(e)[:120]
        run.note_result(False)
        return None
    retrieved = now_iso()
    label = proc.get("label")
    reference = (label if isinstance(label, str) else None) or run.wanted.get(pid) or pid
    info: OeilInfo | None = None
    oeil_failure: str | None = None
    try:
        with run.lock:
            run.requests += 1
        page = run.oeil_pacer.call(lambda: run.http.get(OEIL_FILE, params={"reference": reference}))
        info = parse_oeil(page)
        check_oeil_page(info, reference)
    except HttpError as e:  # keep the EP API record without OEIL enrichment
        info = None
        if e.status == 404:
            oeil_failure = "no OEIL procedure file (404)"
            with run.lock:
                run.oeil_missing.append(reference)  # no OEIL page for this reference
        else:
            oeil_failure = str(e)[:120]
    except Exception as e:  # noqa: BLE001 - unreadable/foreign page: treated like an unavailable OEIL
        info = None
        oeil_failure = str(e)[:120]
    with run.lock:
        run.errors.pop(pid, None)
    run.note_result(oeil_failure is None or "(404)" in oeil_failure)
    return proc, retrieved, info, oeil_failure


def _fetch_chunk(run: _Run, ids: list[str]) -> list[Procedure]:
    """Fetch and build one chunk. Failed ids are left in run.errors / run.oeil_kept / run.deferred (they
    stay pending). A record that had OEIL data is never replaced by one without it: if its OEIL page cannot
    be read now, the stored record is kept unchanged and the id is retried next run."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        got = dict(zip(ids, ex.map(lambda i: _fetch_one(run, i), ids), strict=True))

    def failed(pid: str) -> bool:
        """EP API failed transiently, or OEIL failed for another reason than 404."""
        r = got[pid]
        if r is None:
            return pid in run.errors
        return r[3] is not None and "(404)" not in r[3]

    # One sequential retry (e.g. after an HTTP 429 burst), within the time budget; consecutive failures
    # mean an outage, so the pass stops early instead of spending the budget one id at a time.
    misses = 0
    for pid in [i for i in ids if failed(i)]:
        if misses >= SEQUENTIAL_RETRY_STOP or run.outage or past(run.deadline) or past(run.hard_deadline):
            break
        retry = _fetch_one(run, pid)
        if retry is not None and (got[pid] is None or retry[3] is None):
            got[pid] = retry
        if got[pid] is not None:  # the first answer still stands if the retry did worse
            run.errors.pop(pid, None)
            run.deferred.discard(pid)
        misses = misses + 1 if failed(pid) else 0
    fetched = [(pid, r) for pid, r in got.items() if r is not None]
    people = _people_from(proc for _, (proc, _, _, _) in fetched)
    for _, (_, _, info, _) in fetched:
        if info:
            people |= {(i, None) for pl in info.players for i in pl.rapporteurs + pl.shadows}
            for code, name in info.committee_names.items():
                run.committees.setdefault(code, name)
    run.names.ensure(people)
    out: list[Procedure] = []
    for pid, (proc, retrieved, info, oeil_failure) in fetched:
        if oeil_failure is not None:
            if pid in run.enriched:  # never replace an enriched record by a stripped one
                run.oeil_kept[pid] = oeil_failure
                continue
            if "(404)" not in oeil_failure:
                run.oeil_errors.append(f"{pid}: {oeil_failure}")
                run.degraded.add(pid)
        try:
            out.append(
                build_procedure(proc, retrieved, info, run.names.get, run.committees, run.wanted.get(pid))
            )
        except InvalidRecord as e:
            if oeil_failure is not None and "(404)" not in oeil_failure:
                run.errors[pid] = f"OEIL unavailable and EP record incomplete: {e}"[:160]  # retry
            else:
                run.invalid[pid] = str(e)
        except Exception as e:  # noqa: BLE001
            run.build_errors.append(f"{pid}: {e!r}"[:160])
    return out


def fetch(http: Http) -> SourceStatus:
    """Incremental, chunked and resumable; the committed snapshot is the checkpoint.

    - Default (incremental): list ids (3 cheap requests), then fetch only ids that are new, open
      (status not terminal), had an event in the last RECENT_DAYS days, lack OEIL data, or are
      featured; all other records are reused unchanged from the snapshot.
    - EU_INTEL_FULL_REFRESH=1: fetch every id in scope.
    - Work is done in chunks of CHUNK_SIZE; after each chunk the records are upserted into the
      snapshot and data/snapshot/ep_procedures/_state.json lists the ids still pending. A new
      run continues pending ids first. No new chunk (and, after the first chunk, no new id) starts after
      fetch_deadline() (EU_INTEL_FETCH_BUDGET_S / EU_INTEL_FETCH_DEADLINE); nothing at all starts after
      the run-wide EU_INTEL_FETCH_DEADLINE. The run then reports "partial".
    - A record that has OEIL data is only replaced by one that has it too (see _fetch_chunk).
    - If the EP list endpoint fails, the run works from the snapshot's ids, the pending ids and the ids
      referenced by other snapshots ("partial"). The page size that worked is kept in _state.json.
    - Once OUTAGE_STOP ids failed one after the other, no new id is started (an outage); the rest stays pending.
    - _state.json `unsettled` lists the ids whose record this run did not refresh completely (pending, kept, or
      recorded without OEIL data because OEIL failed), for change detection (pipeline/analysis/activity.py).
    """
    attempted = now_iso()
    deadline = fetch_deadline()
    hard_deadline = global_deadline()
    today = _today()
    state = read_state(SOURCE_ID)
    full = os.environ.get("EU_INTEL_FULL_REFRESH") == "1"
    existing = {p.id: p for p in read_records(SOURCE_ID, "procedures", Procedure)}

    wanted: dict[str, str] = {}  # pid -> reference (label)
    by_type: dict[str, int] = {}
    listing_error: str | None = None
    list_page = {  # process type -> page size that worked in the last run
        k: v for k, v in (state.get("list_page") or {}).items() if isinstance(v, int) and MIN_LIST_PAGE <= v
    }
    try:
        for ptype in PROCEDURE_TYPES:
            items = list_procedure_ids(http, ptype, list_page.get(ptype, LIST_PAGE), list_page)
            by_type[ptype] = len(items)
            for pid, label in items:
                if int(pid[:4]) >= MIN_YEAR:
                    wanted[pid] = label
    except HttpError as e:
        if not existing and not state.get("pending"):
            raise
        # The list is unavailable: keep working on what is known (snapshot ids, pending ids, ids referenced
        # by other snapshots) instead of blocking every pending id for the whole outage.
        listing_error = str(e)[:200]
        log.warning("ep_procedures: procedure list unavailable (%s); using the snapshot and pending ids", e)
        wanted = {pid: p.reference for pid, p in existing.items()}
        for pid in state.get("pending", []):
            wanted.setdefault(pid, "")
        by_type = {}
    listed = len(wanted)
    # The paged list is incomplete: add in-scope ids referenced by EUR-Lex acts and EP votes.
    discovered: Counter[str] = Counter()
    for pid, (ref, origin) in sorted(discover_refs().items()):
        if pid not in wanted:
            wanted[pid] = ref
            discovered[origin] += 1
    featured = featured_ids()
    for pid in featured:
        wanted.setdefault(pid, "")
    # ids known to be unusable: structural cases (split procedure, merged record) are retried
    # only by a full refresh; others (404, missing title) are retried by every run.
    unavailable: dict[str, str] = {} if full else dict(state.get("unavailable", {}))
    skip = {k for k, v in unavailable.items() if "split procedure" in v or "merges several" in v}
    # enriched files whose OEIL page answers 404: {id: {"since": first run date, "runs": runs in a row}}
    oeil_gone: dict[str, dict] = dict(state.get("oeil_gone", {}))

    acts_by_ref: dict[str, list[LegalAct]] = {}
    try:
        for a in read_records("eurlex", "acts", LegalAct):
            for ref in a.procedure_refs:
                acts_by_ref.setdefault(ref, []).append(a)
    except Exception as e:  # noqa: BLE001 - optional input for the terminal-state check
        log.info("eurlex snapshot not usable (%s)", e)

    # Ids left over by an interrupted run come first (an interrupted full refresh stays "full").
    resumed = [i for i in state.get("pending", []) if i in wanted]
    mode = "full" if full or (resumed and state.get("mode") == "full") else "incremental"
    selected, reasons = select_ids(
        {k: v for k, v in wanted.items() if k not in skip},
        existing,
        featured,
        acts_by_ref,
        today,
        full,
    )
    todo = list(dict.fromkeys(resumed + selected))
    if resumed:
        reasons["resumed"] += len(resumed)
    log.info(
        "ep_procedures: %d in scope, %d in snapshot, %d to fetch (%s, %s)",
        len(wanted),
        len(existing),
        len(todo),
        mode,
        dict(reasons),
    )

    committees = {c.code: c.name for p in existing.values() for c in p.committees if c.name}
    enriched = [pid for pid, p in existing.items() if has_oeil_data(p)]
    run = _Run(http, wanted, committees, enriched, deadline, hard_deadline, min_progress=CHUNK_SIZE)
    started_at = state.get("started_at") if resumed else attempted
    done: list[str] = []
    built: set[str] = set()
    stopped_early = False

    def note_unavailable() -> None:
        known = set(existing) | set(wanted) | built
        for pid in run.not_found:
            parts = split_parts(pid, known)
            unavailable[pid] = (
                f"404; split procedure, parts: {', '.join(parts)}" if parts else "404 at /procedures/{id}"
            )
        for pid, reason in run.invalid.items():
            parts = split_parts(pid, known)
            unavailable[pid] = reason + (f"; split procedure, parts: {', '.join(parts)}" if parts else "")
        for pid in built:
            unavailable.pop(pid, None)

    def save_state(pending: list[str]) -> None:
        base = {
            "unavailable": dict(sorted(unavailable.items())),
            "list_page": dict(sorted(list_page.items())),
            "oeil_gone": dict(sorted(oeil_gone.items())),
            "unsettled": {"attempted_at": attempted, "ids": sorted(set(pending) | run.degraded)},
        }
        if pending:
            write_state(SOURCE_ID, {**base, "mode": mode, "pending": pending, "started_at": started_at})
        else:
            write_state(
                SOURCE_ID,
                {
                    **base,
                    "mode": None,
                    "pending": [],
                    "started_at": None,
                    "last_complete": now_iso(),
                    "last_mode": mode,
                },
            )

    for i in range(0, len(todo), CHUNK_SIZE):
        # at least one chunk per run (progress even with a tiny budget), then respect the budget;
        # nothing starts after the run-wide deadline
        if (i and past(deadline)) or past(hard_deadline) or run.outage:
            stopped_early = True
            break
        chunk = todo[i : i + CHUNK_SIZE]
        records = _fetch_chunk(run, chunk)
        for pid in chunk:  # an enriched file whose OEIL page keeps answering 404: kept, no longer pending
            if "(404)" in run.oeil_kept.get(pid, ""):
                gone = oeil_gone.setdefault(pid, {"since": today.isoformat(), "runs": 0})
                gone["runs"] += 1
                if gone["runs"] >= OEIL_GONE_RUNS:
                    del run.oeil_kept[pid]
        if records:
            upsert_records(SOURCE_ID, "procedures", Procedure, records, id_of=lambda r: r.id)
        built |= {r.id for r in records}
        for r in records:
            oeil_gone.pop(r.id, None)
        dropped = set(run.invalid) & set(existing)
        if dropped:  # a stored record that no longer passes validation is removed, not kept stale
            keep = [r for r in read_records(SOURCE_ID, "procedures", Procedure) if r.id not in dropped]
            write_records(SOURCE_ID, "procedures", keep, key=lambda r: r.id)
            for pid in dropped:
                existing.pop(pid, None)
        done += [
            pid
            for pid in chunk
            if pid not in run.errors and pid not in run.oeil_kept and pid not in run.deferred
        ]
        stopped_early = stopped_early or bool(run.deferred)
        note_unavailable()
        save_state([pid for pid in todo if pid not in done])
        log.info("ep_procedures: %d/%d fetched (%d requests)", len(done), len(todo), run.requests)
    pending = [pid for pid in todo if pid not in done]
    save_state(pending)

    final = read_records(SOURCE_ID, "procedures", Procedure)
    kept_note = (
        f" {len(run.oeil_kept)} files that had OEIL data were kept unchanged because their OEIL page could "
        "not be read (retried next run): "
        + "; ".join(f"{k}: {v}" for k, v in sorted(run.oeil_kept.items())[:5])
        + "."
        if run.oeil_kept
        else ""
    )
    listing_note = (
        f" The EP procedure list was unavailable ({listing_error}); worked from the snapshot, pending and "
        "referenced ids, so new files may be missing."
        if listing_error
        else ""
    )
    gone = {k: v for k, v in sorted(oeil_gone.items()) if v["runs"] >= OEIL_GONE_RUNS}
    gone_note = (
        f" OEIL no longer has a procedure file (404 in {OEIL_GONE_RUNS} runs or more) for {len(gone)} files whose "
        "record has OEIL data; their stored records are kept as last read and are no longer retried as pending: "
        + "; ".join(f"{k} (since {v['since']})" for k, v in gone.items())[:600]
        + "."
        if gone
        else ""
    )
    outage_note = (
        f" Stopped after {OUTAGE_STOP} ids in a row failed (EP API or OEIL outage); the rest resumes next run."
        if run.outage
        else ""
    )
    if todo and not done and (not stopped_early or run.outage):
        return SourceStatus(
            source=SOURCE_ID,
            status="failed",
            attempted_at=attempted,
            note=f"0/{len(todo)} procedures fetched; snapshot unchanged; {len(pending)} pending."
            + outage_note
            + listing_note
            + kept_note
            + " "
            + "; ".join(f"{k}: {v}" for k, v in sorted(run.errors.items())[:5]),
        )
    counts: dict[str, int] = {"procedures": len(final)}
    for r in final:
        counts[f"type_{r.type}"] = counts.get(f"type_{r.type}", 0) + 1
    counts["with_oeil"] = sum(1 for r in final if r.stage_raw is not None)
    counts["events"] = sum(len(r.events) for r in final)
    counts["fetched_this_run"] = len(built)
    counts["unavailable"] = len(unavailable)
    counts["requests_this_run"] = run.requests + len(PROCEDURE_TYPES) + len(run.names.fetched_terms)
    counts["pending"] = len(pending)
    note = (
        f"Scope: {', '.join(PROCEDURE_TYPES)} with reference year >= {MIN_YEAR}: {listed} ids from the "
        f"paged list (API totals all years, with repeats: {by_type}) + {sum(discovered.values())} more "
        f"referenced by other snapshots ({dict(discovered)}) + {len(featured)} featured. Mode {mode}: "
        f"fetched {len(built)} ({dict(reasons)}), reused {len(final) - len(built)} from the snapshot. "
        f"OEIL enrichment for {counts['with_oeil']}/{len(final)}."
    )
    if pending:
        note += f" {len(pending)} pending; resumes next run" + (
            " (time budget reached)." if stopped_early else "."
        )
    if unavailable:
        note += (
            f" {len(unavailable)} ids skipped (no usable EP record; split/merged ones are retried on "
            "full refresh, others every run): "
            + "; ".join(f"{k} ({v})" for k, v in sorted(unavailable.items()))[:1500]
            + "."
        )
    problems = [f"{k}: {v}" for k, v in sorted(run.errors.items())] + run.build_errors
    if run.oeil_missing:
        note += f" No OEIL procedure file (404) for: {', '.join(sorted(run.oeil_missing))}."
    if problems or run.oeil_errors:
        note += (
            f" Failures: {len(run.errors)} EP API, {len(run.build_errors)} build, {len(run.oeil_errors)} OEIL. "
            + "; ".join((problems + run.oeil_errors)[:5])
        )
    note += outage_note + kept_note + gone_note + listing_note
    # "partial" whenever a previously enriched record could not be re-enriched (run.oeil_kept, pending)
    partial = bool(
        pending
        or problems
        or run.oeil_kept
        or listing_error
        or len(run.oeil_errors) > 0.02 * max(len(done), 1)
    )
    return SourceStatus(
        source=SOURCE_ID,
        status="partial" if partial else "ok",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records=counts,
        note=note,
    )
