"""European Parliament legislative procedures (COD / CNS / APP, reference year >= 2014).

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
   ``SourceRef(institution="OEIL")``. If an OEIL page cannot be fetched or parsed, the
   record is kept with EP API data only (stage_raw/subjects/com_refs/celex_refs empty).

Output: data/snapshot/ep_procedures/procedures.json (list[Procedure], sorted by id).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import yaml
from lxml import html as lxml_html

from pipeline.http import EP_API, Http, HttpError
from pipeline.models.entities import (
    CommitteeRole,
    DocRef,
    Event,
    EventKind,
    Institution,
    Mep,
    Procedure,
    Rapporteur,
    SourceRef,
    SourceStatus,
    Subject,
)
from pipeline.snapshot import CURATED, now_iso, read_records, write_records

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
MAX_FAILURE_RATIO = 0.2  # above this, do not overwrite the previous snapshot

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
OEIL_COMMITTEE_HEADER = {
    "Committee responsible": "responsible",
    "Joint committee responsible": "joint",
    "Committee for opinion": "opinion",
    "Committee for opinion on the legal basis": "opinion",
}


@dataclass
class OeilInfo:
    status: str | None = None
    instrument: str | None = None
    subjects: list[Subject] = field(default_factory=list)
    committee_names: dict[str, str] = field(default_factory=dict)
    mep_names: dict[str, str] = field(default_factory=dict)  # EP person id -> "SURNAME Given"
    events: list[OeilEvent] = field(default_factory=list)
    com_docs: list[DocRef] = field(default_factory=list)
    final_acts: list[DocRef] = field(default_factory=list)  # id = CELEX
    players: list[OeilPlayer] = field(default_factory=list)  # EP committees + rapporteurs


def _text(el: Any) -> str:
    return " ".join(el.text_content().split())


def parse_oeil(body: bytes | str) -> OeilInfo:
    """Parse an OEIL procedure-file page. Missing sections simply leave fields empty."""
    doc = lxml_html.fromstring(body)
    info = OeilInfo()

    sec1 = doc.xpath('//*[@id="section1"]')
    if sec1:
        s1 = sec1[0]
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
        if m and not CORRIGENDUM_CELEX.search(m[1]):
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
def _src(institution: Institution, url: str, label: str, identifier: str, retrieved_at: str) -> SourceRef:
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
                    f"{EP_API}/procedures/{pid}/events/{e['activity_id']}?format=application/ld+json",
                    f"EP Open Data API – event {e['activity_id']}",
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
                    f"EP Open Data API – procedure {reference}",
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
                        f"Legislative Observatory – {reference}",
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
                        log.warning("no name for EP person %s (%s); skipped", mep_id, proc.get("process_id"))
                        continue
                    key = (mep_id, RAPPORTEUR_ROLE[role], committee)
                    rapps.setdefault(
                        key,
                        Rapporteur(mep_id=mep_id, name=name, committee=committee, role=RAPPORTEUR_ROLE[role]),
                    )
    role_order = {"responsible": 0, "joint": 1, "opinion": 2, "other": 3}
    rrole_order = {"rapporteur": 0, "shadow": 1, "opinion_rapporteur": 2, "other": 3}
    cs = sorted(committees.values(), key=lambda c: (role_order[c.role], c.code))
    rs = sorted(
        rapps.values(), key=lambda r: (rrole_order[r.role], r.committee or "", r.name, r.mep_id or "")
    )
    return cs, rs


def build_procedure(
    proc: dict[str, Any],
    retrieved_at: str,
    oeil: OeilInfo | None,
    names: Callable[[str], str | None],
    committee_names: dict[str, str] | None = None,
) -> Procedure:
    pid = proc["process_id"]
    reference = proc.get("label") or pid
    ptype = last_segment(proc.get("process_type")) or (
        PROC_REF_RE.match(reference)[3] if PROC_REF_RE.match(reference) else ""
    )
    titles = proc.get("process_title") or {}
    title = titles.get("en") if isinstance(titles, dict) else None
    if not title:
        title = reference  # no English title in the source; never translate or invent one
    events = build_events(proc, retrieved_at, oeil, reference)
    committee_names = {**(committee_names or {}), **(oeil.committee_names if oeil else {})}

    def name_of(mep_id: str) -> str | None:
        return names(mep_id) or (oeil.mep_names.get(mep_id) if oeil else None)

    committees, rapporteurs = build_participants(proc, name_of, committee_names)

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


def list_procedure_ids(http: Http, ptype: str, page: int = 1000) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    offset = 0
    while True:
        d = http.get_json(
            f"{EP_API}/procedures",
            params={"process-type": ptype, "format": "application/ld+json", "offset": offset, "limit": page},
        )
        items = as_list(d.get("data"))
        for x in items:
            if isinstance(x, dict) and x.get("process_id"):
                out.append((x["process_id"], x.get("label") or x["process_id"]))
        total = (d.get("meta") or {}).get("total")
        offset += len(items)
        if not items or len(items) < page or (total is not None and offset >= total):
            break
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


def mep_name_resolver(http: Http, terms: Iterable[int]) -> Callable[[str], str | None]:
    """EP person id -> display name. Prefers the ep_people snapshot; otherwise the EP API MEP
    lists per parliamentary term (givenName + familyName as published)."""
    names: dict[str, str] = {}
    try:
        for m in read_records("ep_people", "meps", Mep):
            names[m.id] = m.name
    except Exception as e:  # noqa: BLE001 - snapshot of another source may be absent/invalid
        log.info("ep_people snapshot not usable (%s); using EP API MEP lists", e)
    for term in sorted(set(terms)):
        try:
            offset = 0
            while True:
                d = http.get_json(
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
                        names.setdefault(str(x["identifier"]), name)
                offset += len(items)
                if len(items) < 1000:
                    break
        except HttpError as e:
            log.warning("MEP list for term %s unavailable: %s", term, e)
    return names.get


def _terms_from(procs: Iterable[dict[str, Any]]) -> set[int]:
    terms: set[int] = set()
    for p in procs:
        for part in as_list(p.get("had_participation")):
            if isinstance(part, dict):
                m = re.search(r"ep-(\d+)$", str(part.get("parliamentary_term") or ""))
                if m:
                    terms.add(int(m[1]))
    return terms


def fetch(http: Http) -> SourceStatus:
    attempted = now_iso()
    ep_pacer, oeil_pacer = _Pacer(EP_API_GAP_S), _Pacer(OEIL_GAP_S)

    wanted: dict[str, str] = {}  # pid -> reference (label)
    by_type: dict[str, int] = {}
    for ptype in PROCEDURE_TYPES:
        items = list_procedure_ids(http, ptype)
        by_type[ptype] = len(items)
        for pid, label in items:
            if int(pid[:4]) >= MIN_YEAR:
                wanted[pid] = label
    featured = featured_ids()
    for pid in featured:
        wanted.setdefault(pid, "")
    ids = sorted(wanted, reverse=True)  # newest first: if interrupted, recent files are done
    log.info("ep_procedures: %d procedures in scope (%d featured)", len(ids), len(featured))

    raw: dict[str, tuple[dict[str, Any], str]] = {}
    oeil: dict[str, OeilInfo | None] = {}
    errors: list[str] = []
    oeil_errors: list[str] = []
    lock = threading.Lock()

    def work(pid: str) -> None:
        try:
            body = ep_pacer.call(lambda: http.get(f"{EP_API}/procedures/{pid}", params=JSONLD))
            data = json.loads(body)
            procs = [p for p in as_list(data.get("data")) if isinstance(p, dict) and p.get("process_id")]
            if not procs:
                raise ValueError("empty response")
            proc = procs[0]
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append(f"{pid}: {str(e)[:120]}")
            return
        retrieved = now_iso()
        reference = proc.get("label") or wanted.get(pid) or pid
        info: OeilInfo | None = None
        try:
            page = oeil_pacer.call(lambda: http.get(OEIL_FILE, params={"reference": reference}))
            info = parse_oeil(page)
        except Exception as e:  # noqa: BLE001
            with lock:
                oeil_errors.append(f"{reference}: {str(e)[:120]}")
        with lock:
            raw[pid] = (proc, retrieved)
            oeil[pid] = info
            n = len(raw)
        if n % 100 == 0:
            log.info("ep_procedures: %d/%d fetched", n, len(ids))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(ex.map(work, ids))

    if not raw or len(errors) > MAX_FAILURE_RATIO * len(ids):
        return SourceStatus(
            source=SOURCE_ID,
            status="failed",
            attempted_at=attempted,
            note=f"{len(errors)}/{len(ids)} procedure requests failed; snapshot not updated. "
            + "; ".join(errors[:5]),
        )

    names = mep_name_resolver(http, _terms_from(p for p, _ in raw.values()))
    # Committee code -> name, across all OEIL pages (closed files often omit key players).
    all_committees: dict[str, str] = {}
    for pid in sorted(oeil, reverse=True):  # newest first: current committee names win
        for code, name in (oeil[pid].committee_names if oeil[pid] else {}).items():
            all_committees.setdefault(code, name)
    records: list[Procedure] = []
    build_errors: list[str] = []
    for pid, (proc, retrieved) in raw.items():
        try:
            records.append(build_procedure(proc, retrieved, oeil.get(pid), names, all_committees))
        except Exception as e:  # noqa: BLE001
            build_errors.append(f"{pid}: {e!r}"[:160])
    write_records(SOURCE_ID, "procedures", records, key=lambda r: r.id)

    counts: dict[str, int] = {"procedures": len(records)}
    for r in records:
        counts[f"type_{r.type}"] = counts.get(f"type_{r.type}", 0) + 1
    counts["with_oeil"] = sum(1 for r in records if r.stage_raw is not None)
    counts["events"] = sum(len(r.events) for r in records)
    problems = errors + build_errors
    note = (
        f"Scope: {', '.join(PROCEDURE_TYPES)} with reference year >= {MIN_YEAR} "
        f"(API totals all years: {by_type}) + {len(featured)} featured. "
        f"OEIL enrichment for {counts['with_oeil']}/{len(records)}."
    )
    if problems or oeil_errors:
        note += (
            f" Failures: {len(errors)} EP API, {len(build_errors)} build, {len(oeil_errors)} OEIL. "
            + "; ".join((problems + oeil_errors)[:5])
        )
    return SourceStatus(
        source=SOURCE_ID,
        status="partial" if problems or len(oeil_errors) > 0.02 * len(ids) else "ok",
        fetched_at=now_iso(),
        attempted_at=attempted,
        records=counts,
        note=note,
    )
