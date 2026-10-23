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
    # the source's own date for the record, if provided: a last-modified date for EUR-Lex/Cellar
    # (cmr:lastModificationDate), national measures and Legislative Train pages; the document's date for a
    # Council register document. Not an Official Journal publication date (LegalAct.date_publication).
    published: str | None = None


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
    # shadow_opinion = shadow rapporteur for a committee opinion (EP role RAPPORTEUR_SHADOW_OPINION)
    role: Literal["rapporteur", "shadow", "opinion_rapporteur", "shadow_opinion"] = "rapporteur"
    date: str | None = None  # EP API participation activity_date (the appointment); latest if several
    group: str | None = None  # political group printed next to the name in the OEIL file, e.g. "The Left"


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
    # "Legislative instrument" in the OEIL procedure file, verbatim ("Regulation", "Directive", "Decision",
    # "Recommendation"): the type of act proposed, which the final act can differ from
    instrument: str | None = None
    oeil_url: str
    source: SourceRef


class CourtRuling(Model):
    """A judgment that Cellar records as annulling (in whole or in part) or declaring invalid a legal act."""

    celex: str  # judgment CELEX, e.g. "62023CJ0019"
    case_number: str | None = None  # as published, e.g. "C-19/23", "Joined Cases C-541/20 to C-555/20"
    ecli: str | None = None  # "ECLI:EU:C:2025:865"
    date: str | None = None  # date of the judgment
    title: str  # English title as published, e.g. "Judgment of the Court (Grand Chamber) of 11 November 2025. ..."
    # annulment: action for annulment (Art. 263 TFEU); invalidity: declared invalid in a preliminary ruling
    effect: Literal["annulment", "invalidity"]
    effect_text: str | None = None  # the judgment's published subject-matter keywords (headnote), verbatim
    provisions: list[str] = Field(default_factory=list)  # Cellar location codes, as recorded ("A05P1")
    url: str  # EUR-Lex page of the judgment


class ProcedureNotice(Model):
    """A Commission withdrawal of a proposal, or its replacement by a new proposal, as recorded by Cellar
    on the procedure (event types WDW_byCOM / WDW_PROPLEG_byCOM / RPL_byCOM)."""

    id: str  # "2016/0337(CNS):replaced:2023-09-12"
    reference: str  # "2016/0337(CNS)"
    kind: Literal["withdrawn", "replaced"]
    date: str
    document: str | None = None  # "COM(2023)0532" (the new proposal) or the OJ withdrawal notice
    source: SourceRef


class DirectiveOptOut(Model):
    """Which Member States a directive's own recitals declare not bound by it (Protocols 21 and 22:
    Denmark, Ireland), read from the EUR-Lex text (pipeline/sources/optouts.py)."""

    celex: str
    status: Literal["ok", "unavailable"]  # unavailable: the text could not be fetched (retried next run)
    not_bound: list[str] = Field(default_factory=list)  # "DK", "IE"
    quotes: list[str] = Field(default_factory=list)  # the recital sentences, verbatim (whitespace normalized)
    # countries that took part after adoption (Protocol No 21, Article 4): country -> CELEX of the Commission
    # decision confirming the participation, e.g. {"IE": "32024D2087"} for Directive (EU) 2024/1346
    opted_in: dict[str, str] = Field(default_factory=dict)
    parser: int = 1  # version of the recital matcher that read the text; older records are read again
    url: str
    source: SourceRef


class TranspositionDate(Model):
    """One `directive_date_transposition` value with Cellar's annotation of what it is."""

    date: str
    # comment_on_date codes: ADOPTION ("adopt and publish by"), APPLICATION ("apply from"),
    # AU+TARD ("at the latest"); empty when Cellar does not annotate the date
    labels: list[str] = Field(default_factory=list)
    articles: list[str] = Field(default_factory=list)  # article of the directive setting it, e.g. "48.1"


class CheckedTransposition(Model):
    """What a directive's transposition dates are, checked against its text where Cellar's annotations
    cannot tell (data/curated/transposition.yaml). Set by the build only; never part of the snapshot."""

    deadline: str  # the general transposition deadline (one of the act's transposition dates)
    applies_from: str | None = None  # the general date from which the national measures apply
    # recorded dates that are neither a deadline nor a firm application date (e.g. conditional or optional)
    other: list[str] = Field(default_factory=list)
    # what the directive's own text provides for some Member States beside the general deadline (an extension of the
    # transposition period, an exemption), in plain words naming each provision
    exceptions: str | None = None


class ValidityNote(Model):
    """One `resource_legal_date_end-of-validity` value with Cellar's comment on it (authority table fd_330)."""

    date: str
    partial: bool = False  # FIN/VAL/PART: partial end of validity (some provisions only)
    # fd_330 codes in the comment, in order: A/PAR "Repealed by", AR/PAR "Repealed and replaced by",
    # AI/PAR "Implicitly repealed by", R/PAR "Replaced by", P/PAR "Ext. valid. by", V "see", ART, ANN...
    codes: list[str] = Field(default_factory=list)
    acts: list[str] = Field(default_factory=list)  # CELEX ids of the acts the comment names


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
    # Cellar gives the entry-into-force date (type EV) as the placeholder 1001-01-01: the act enters into
    # force on a condition it sets that is not yet recorded as met (e.g. approval by every Member State)
    entry_into_force_pending: bool = False
    # the article(s) of the act that Cellar's comment on that placeholder refers to ("V ART 2.2" -> "2.2")
    entry_into_force_articles: list[str] = Field(default_factory=list)
    # Cellar gives the date of effect (type PE) as 1001-01-01 with comment DATNOT (date of notification): a
    # decision that takes effect on notification to its addressee, notification date not recorded
    effect_on_notification: bool = False
    # Further dates recorded by Cellar as entry-into-force/application of provisions, ascending.
    # Cellar does not say which provisions; label them neutrally in the UI.
    other_application_dates: list[str] = Field(default_factory=list)
    # those of other_application_dates that Cellar marks as partial application (MA/PART, PE/PART)
    partial_application_dates: list[str] = Field(default_factory=list)
    # Cellar marks the entry-into-force date as a partial application date too: some provisions apply from the entry
    # into force (DMA, Regulation (EU) 2022/1925, Art. 54: "Article 3(6) and (7) and Articles 40, 46, 47, 48, 49 and
    # 50 shall apply from 1 November 2022")
    partial_on_entry_into_force: bool = False
    end_of_validity: str | None = None  # None if open-ended (Cellar "9999-12-31")
    validity_notes: list[ValidityNote] = Field(default_factory=list)  # end-of-validity values Cellar comments on
    in_force: bool | None = None
    transposition_deadlines: list[str] = Field(default_factory=list)  # directives only: every value
    transposition_dates: list[TranspositionDate] = Field(default_factory=list)  # the same, annotated
    # build only (excluded from the snapshot): the dates checked against the act's text, if curated
    transposition_checked: CheckedTransposition | None = Field(default=None, exclude=True)
    procedure_refs: list[str] = Field(default_factory=list)  # "2021/0106(COD)"
    subjects: list[Subject] = Field(default_factory=list)
    amends: list[str] = Field(default_factory=list)  # CELEX
    amended_by: list[str] = Field(default_factory=list)
    repeals: list[str] = Field(default_factory=list)
    repealed_by: list[str] = Field(default_factory=list)
    # partial repeals: repeal links that every Cellar annotation limits to a provision or marks as partial (role AP)
    partly_repeals: list[str] = Field(default_factory=list)
    partly_repealed_by: list[str] = Field(default_factory=list)
    court_rulings: list[CourtRuling] = Field(default_factory=list)  # annulment / invalidity, by date
    eurlex_url: str
    source: SourceRef


VoteKind = Literal[
    "final",  # vote on the whole text / legislative resolution / single vote on provisional agreement
    "amendment",
    "split_or_separate",  # split or separate vote on part of a text
    "resolution",  # non-legislative resolution (whole text)
    "motion",  # e.g. motion to reject, motion of censure, objection
    "procedural",  # e.g. referral back to committee, request for urgent procedure
    # vote on the (amended) proposal as a whole after which Parliament referred the matter back to committee
    # for interinstitutional negotiations (Rule 59(4)): its negotiating mandate, not its position
    "mandate",
    "other",  # incl. a whole-text vote that lapsed without being held
]
# What a motion or procedural vote decides, where the published texts say so (see ep_votes.kind_detail)
KindDetail = Literal[
    "reject_proposal",  # motion to reject the Commission proposal (adopted = proposal rejected)
    "reject_council_position",  # second reading: motion to reject the Council's position
    "censure",  # motion of censure on the Commission
    "objection",  # objection to a delegated or implementing act (adopted = Parliament objects)
    "no_objection",  # recommendation to raise no objections to one (adopted = Parliament does not object)
    "negotiation_decision",  # vote on a committee's decision to enter into interinstitutional negotiations
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
    # What was voted, as published in English: the vote item title (from 2024-01-15) or the block title of
    # the sitting's English minutes (before), else the English title of the vote's only linked procedure;
    # None when no English title is published or it is ambiguous.
    subject: str | None = None
    kind: VoteKind
    kind_detail: KindDetail | None = None
    outcome: Literal["adopted", "rejected", "lapsed", "unknown"]
    # How `outcome` was established: "published" = decision_outcome of the API decision;
    # "minutes" = the sitting's official "Results of votes" minutes (PV-…-VOT), matched by document and
    # counts (also the French minutes of the 2020 remote-voting sittings); "derived" = from the counts, when
    # they settle the result under the established majority_rule, or under every rule when it is unknown.
    outcome_basis: Literal["published", "minutes", "derived"] | None = None
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
CouncilVoteOn = Literal["act", "first_reading_position", "other"]


class CouncilVote(Model):
    """A recorded vote of the Council of the European Union (NOT the European Council)."""

    id: str
    date: str
    title: str
    procedure_refs: list[str] = Field(default_factory=list)  # "2021/0106(COD)" if officially given
    council_doc: str | None = None  # e.g. "PE-CONS 24/24"
    configuration: str | None = None  # e.g. "General Affairs Council"
    # Item(s) voted on as listed in the note's subject, "; "-separated, e.g. "Adoption of the legislative act",
    # "Adoption of the Council's position at first reading and of the statement of the Council's reasons"
    stage: str | None = None
    # What was voted on, normalised from the subject (see pipeline.sources.council.vote_subject):
    # the act itself, the Council's first-reading position (the act is NOT adopted by that vote), or other.
    vote_on: CouncilVoteOn | None = None
    meeting: str | None = None  # meeting reference as published, e.g. "3999th meeting of the Council"
    written_procedure: bool | None = None  # adopted by written procedure rather than at a meeting
    voting_rule: Literal["qmv", "unanimity", "simple_majority", "unknown"]
    act_type: str | None = None
    outcome: Literal["adopted", "not_adopted", "unknown"]
    positions: dict[str, CouncilPosition] = Field(default_factory=dict)  # ISO2 -> position
    # Only when `positions` is empty: why the positions could not be read from the published voting sheet
    # (plain language, specific). The Council does publish them; this records our reading failure.
    positions_note: str | None = None
    statements: list[str] = Field(default_factory=list)  # titles/refs of statements, as published
    source: SourceRef


class NationalMeasure(Model):
    """A national measure notified as transposing a directive (EUR-Lex MNE / Cellar)."""

    id: str
    directive_celex: str
    country: str
    title: str | None = None
    date: str | None = None  # publication date in the national official journal, if known
    commission_ref: str | None = None  # e.g. "MNE(2025)04528"
    national_ref: str | None = None
    journal: str | None = None  # national official journal name
    notified: str | None = None  # date notified to the Commission, if provided
    url: str | None = None
    source: SourceRef


class ImplementationCoverage(Model):
    """A directive whose national measures were queried (distinguishes 'none found' from 'not queried')."""

    celex: str
    measures: int
    source: SourceRef


class InfringementCase(Model):
    id: str  # e.g. "INFR(2023)0123"
    country: str
    celex: str | None = None  # only when the source links the case to exactly one act
    legal_basis: list[str] = Field(default_factory=list)  # all CELEX ids named as legal basis by the register
    court_ref: str | None = None  # e.g. "C-123/24" when referred to the Court
    press_release_url: str | None = None
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
    blocking_institution: str | None = None  # institution the Train names as blocking, verbatim, if any
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
