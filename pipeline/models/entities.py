"""Normalized entity contract for the data snapshot (data/snapshot/**).

Source adapters (pipeline/sources/*) produce lists of these models. The build step
(pipeline/build.py) reads them and assembles the public site data (public/data/**),
whose shape is defined in src/types/data.ts.

Conventions
- Dates are ISO strings "YYYY-MM-DD"; timestamps are ISO 8601 UTC ("...Z").
- Missing information is `None` / empty list. Never fill gaps with guesses.
- Every record carries `source: SourceRef` (where the record came from, when retrieved).
- IDs:
    procedure id   "2021-0106"            (EP process_id; reference "2021/0106(COD)")
    legal act id   CELEX "32024R1689"
    MEP id         EP person identifier "197443"
    org id         EP corporate-body identifier, e.g. "5151" (groups/parties/committees)
    EP vote id     EP notation_votingId "166377"
    country        ISO 3166-1 alpha-2, upper case; Greece is "GR" (convert EU "EL" -> "GR")
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Institution = Literal[
    "EP",  # European Parliament (open data API, plenary, committees)
    "Council",  # Council of the European Union (NOT the European Council)
    "European Council",
    "Commission",
    "EUR-Lex",  # Publications Office: EUR-Lex / Cellar / Official Journal
    "OEIL",  # EP Legislative Observatory
    "LegislativeTrain",  # EP Legislative Train Schedule
    "CJEU",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class SourceRef(Model):
    institution: Institution
    url: str  # human-openable URL where possible (else the API URL)
    label: str | None = None  # e.g. "EP Open Data API – procedure 2021/0106(COD)"
    identifier: str | None = None  # official identifier of the record at the source
    retrieved_at: str  # ISO UTC timestamp of retrieval
    published: str | None = None  # source publication / last-modified date if provided


class DocRef(Model):
    id: str  # official reference, e.g. "COM(2021)0206", "A9-0188/2023", "TA-9-2024-0138"
    label: str | None = None
    kind: str | None = None  # proposal | report | opinion | adopted_text | agreement | other
    date: str | None = None
    url: str | None = None


class EventKind(StrEnum):
    proposal = "proposal"  # Commission (or other initiator) proposal adopted/published
    referral = "referral"  # announced in plenary / referred to committee
    committee_opinion = "committee_opinion"
    committee_report = "committee_report"  # responsible committee adopts its report
    negotiation_mandate = "negotiation_mandate"  # decision to enter interinstitutional negotiations
    plenary_debate = "plenary_debate"
    plenary_vote = "plenary_vote"  # a plenary decision (amendments, referral back, etc.)
    ep_position = "ep_position"  # EP adopts its (first/second reading) position
    provisional_agreement = "provisional_agreement"  # trilogue agreement / committee approves it
    council_position = "council_position"  # Council first-reading position / general approach
    council_adoption = "council_adoption"  # Council formally adopts the act
    signature = "signature"  # act signed by EP President + Council Presidency
    publication = "publication"  # published in the Official Journal
    entry_into_force = "entry_into_force"
    application = "application"  # start of application (incl. phased provisions)
    transposition_deadline = "transposition_deadline"
    withdrawal = "withdrawal"
    rejection = "rejection"
    lapsed = "lapsed"
    other = "other"


class Event(Model):
    id: str
    date: str
    kind: EventKind
    raw_type: str | None = None  # source activity type, e.g. "def/ep-activities/PLENARY_VOTE"
    institution: Institution
    title: str  # plain-English, deterministic from kind/raw_type (no free generation)
    detail: str | None = None
    docs: list[DocRef] = Field(default_factory=list)
    source: SourceRef


class Subject(Model):
    code: str  # e.g. EP subject "3.30.06" or EuroVoc / subject-matter code
    label: str | None = None
    scheme: Literal["ep", "eurovoc", "subject-matter", "directory"] = "ep"


class CommitteeRole(Model):
    code: str  # "ENVI"
    name: str | None = None
    role: Literal["responsible", "opinion", "joint", "other"] = "responsible"


class Rapporteur(Model):
    mep_id: str | None = None
    name: str
    committee: str | None = None
    role: Literal["rapporteur", "shadow", "opinion_rapporteur", "other"] = "rapporteur"


class Procedure(Model):
    """A legislative (or related) procedure ("dossier") as recorded by the European Parliament."""

    id: str  # "2021-0106"
    reference: str  # "2021/0106(COD)"
    type: str  # COD | CNS | APP | NLE | BUD | INI | ...
    title: str  # official English title as given by the source
    subjects: list[Subject] = Field(default_factory=list)
    stage_raw: str | None = None  # stage/status label exactly as given by the source, if any
    started: str | None = None  # date of the initiating document / first event
    committees: list[CommitteeRole] = Field(default_factory=list)
    rapporteurs: list[Rapporteur] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)  # sorted by date ascending
    documents: list[DocRef] = Field(default_factory=list)
    com_refs: list[str] = Field(default_factory=list)  # "COM(2021)0206"
    celex_refs: list[str] = Field(default_factory=list)  # final acts if the EP source links them
    oeil_url: str
    source: SourceRef


class LegalAct(Model):
    """An act in the EU legal corpus (EUR-Lex / Cellar)."""

    celex: str
    eli: str | None = None
    act_type: Literal["regulation", "directive", "decision", "recommendation", "other"]
    title: str
    date_document: str | None = None  # date of the act (adoption/signature date in the title)
    date_signature: str | None = None
    date_publication: str | None = None  # Official Journal publication
    oj_ref: str | None = None
    entry_into_force: str | None = None  # general entry-into-force date (earliest EIF value)
    # Further dates recorded by Cellar as entry-into-force/application of provisions, ascending.
    # Cellar does not say which provisions; label them neutrally in the UI.
    other_application_dates: list[str] = Field(default_factory=list)
    end_of_validity: str | None = None  # None if open-ended (Cellar "9999-12-31")
    in_force: bool | None = None
    transposition_deadlines: list[str] = Field(default_factory=list)  # directives only
    procedure_refs: list[str] = Field(default_factory=list)  # "2021/0106(COD)"
    subjects: list[Subject] = Field(default_factory=list)
    amends: list[str] = Field(default_factory=list)  # CELEX
    amended_by: list[str] = Field(default_factory=list)
    repeals: list[str] = Field(default_factory=list)
    repealed_by: list[str] = Field(default_factory=list)
    eurlex_url: str
    source: SourceRef


VoteKind = Literal[
    "final",  # vote on the whole text / legislative resolution / single vote on provisional agreement
    "amendment",
    "split_or_separate",  # split or separate vote on part of a text
    "resolution",  # non-legislative resolution (whole text)
    "motion",  # e.g. motion to reject, motion of censure, objection
    "procedural",  # e.g. referral back to committee, request for urgent procedure
    "other",
]


class EpVote(Model):
    """A recorded plenary vote of the European Parliament."""

    id: str  # EP notation_votingId
    event_id: str  # EP decision event id, e.g. "MTG-PL-2024-03-13-DEC-166377"
    date: str
    term: int  # parliamentary term (9, 10, ...)
    title: str  # English activity label as given by EP
    reference_text: str | None = None  # e.g. "Recital 29", "Proposal for a regulation"
    doc_ids: list[str] = Field(default_factory=list)  # decided_on_a_realization_of document ids
    procedure_refs: list[str] = Field(default_factory=list)  # linked only via official doc/procedure ids
    kind: VoteKind
    outcome: Literal["adopted", "rejected", "lapsed", "unknown"]
    method: str | None = None  # e.g. "VOTE_ELECTRONIC_ROLLCALL", "SHOW_OF_HANDS"
    n_for: int | None = None
    n_against: int | None = None
    n_abstain: int | None = None
    attendees: int | None = None
    # Majority rule that applied, ONLY if established from the vote's legal context.
    majority_rule: Literal["votes_cast", "component_members", "two_thirds_cast", "unknown"] = "unknown"
    committee: str | None = None
    has_ballots: bool = False
    source: SourceRef


class EpBallots(Model):
    """Individual roll-call positions for one EpVote (as recorded; 'intended' = later corrections)."""

    vote_id: str
    favor: list[str] = Field(default_factory=list)  # MEP ids
    against: list[str] = Field(default_factory=list)
    abstain: list[str] = Field(default_factory=list)
    intended_favor: list[str] = Field(default_factory=list)
    intended_against: list[str] = Field(default_factory=list)
    intended_abstain: list[str] = Field(default_factory=list)


class Membership(Model):
    org_id: str
    kind: Literal["group", "party", "committee", "delegation", "other"]
    role: str | None = None  # e.g. "MEMBER", "CHAIR", "SUBSTITUTE"
    start: str | None = None
    end: str | None = None  # None = ongoing
    term: int | None = None


class Mep(Model):
    id: str
    name: str  # display name, natural casing: "Elio Di Rupo"
    given_name: str | None = None
    family_name: str | None = None
    sort_label: str | None = None
    country: str  # ISO2 of country of representation (latest)
    active: bool  # currently sitting MEP
    terms: list[int] = Field(default_factory=list)
    memberships: list[Membership] = Field(default_factory=list)
    official_url: str  # https://www.europarl.europa.eu/meps/en/<id>
    photo_url: str | None = None  # only if use is permitted (EP portraits: see DATA_SOURCES.md)
    source: SourceRef


class Organization(Model):
    id: str
    kind: Literal["group", "party", "committee", "delegation", "other"]
    code: str | None = None  # "EPP", "S&D", "ENVI"; national party acronym if known
    label: str  # full name
    country: str | None = None  # parties only
    start: str | None = None
    end: str | None = None
    source: SourceRef


CouncilPosition = Literal["for", "against", "abstain", "not_participating"]


class CouncilVote(Model):
    """A recorded vote of the Council of the European Union (NOT the European Council)."""

    id: str
    date: str
    title: str
    procedure_refs: list[str] = Field(default_factory=list)  # "2021/0106(COD)" if officially given
    council_doc: str | None = None  # e.g. "PE-CONS 24/24"
    configuration: str | None = None  # e.g. "General Affairs Council"
    voting_rule: Literal["qmv", "unanimity", "simple_majority", "unknown"]
    act_type: str | None = None
    outcome: Literal["adopted", "not_adopted", "unknown"]
    positions: dict[str, CouncilPosition] = Field(default_factory=dict)  # ISO2 -> position
    statements: list[str] = Field(default_factory=list)  # titles/refs of statements, as published
    source: SourceRef


class NationalMeasure(Model):
    """A national measure notified as transposing a directive (EUR-Lex MNE / Cellar)."""

    id: str
    directive_celex: str
    country: str
    title: str | None = None
    date: str | None = None
    url: str | None = None
    source: SourceRef


class InfringementCase(Model):
    id: str  # e.g. "INFR(2023)0123"
    country: str
    celex: str | None = None  # only when the source links the case to an act
    title: str
    non_communication: bool | None = None  # "failure to notify transposition measures"
    latest_stage: str | None = None  # e.g. "Letter of formal notice", "Reasoned opinion", "Referral to Court"
    latest_decision_date: str | None = None
    status: Literal["open", "closed", "unknown"] = "unknown"
    source: SourceRef


class CountryIndicator(Model):
    country: str
    indicator: str  # machine id, e.g. "transposition_deficit"
    label: str
    value: float | None
    unit: str  # "%", "count"
    period: str  # reporting period as published
    definition: str
    source: SourceRef


class TrainFile(Model):
    """A file on the EP Legislative Train Schedule."""

    url: str
    title: str
    status: str  # exactly as published by the Legislative Train
    procedure_refs: list[str] = Field(default_factory=list)
    theme: str | None = None
    last_updated: str | None = None
    source: SourceRef


class SourceStatus(Model):
    """One entry of data/snapshot/_manifest.json."""

    source: str  # e.g. "ep_people"
    status: Literal["ok", "partial", "failed", "unavailable"]
    fetched_at: str | None = None  # time of the last successful fetch
    attempted_at: str
    records: dict[str, int] = Field(default_factory=dict)
    note: str | None = None
