"""The open dataset: the site's data as documented CSV tables, for reuse and citation.

    public/data/open/README.md          what the tables hold, their identifiers, caveats, licence and citation
    public/data/open/datapackage.json   Frictionless Tabular Data Package 1.0: every table and field with its type and
                                        description, primary and foreign keys, the sources with their attribution
                                        and the licence
    public/data/open/<table>.csv        UTF-8, RFC 4180 (comma, double quotes, CRLF line ends), one header row

`build_open_data` makes them from the build's own output (pipeline/build.py calls it after Builder.run): the tables
say what the site says, with the same statuses, labels, links and checked corrections. The enumerations of the fields
are those of the public data contract (src/types/data.ts). Deterministic: rows are sorted by their key and nothing
depends on the time of the build. Statuses depend on the day they are computed for (`as_of`, the build's today), and
the sources on their retrieval: datapackage.json gives both, and `content_hash` leaves them out, so that the weekly
release (.github/workflows/release-data.yml) publishes a new version only when a row or the schema changed.

    python -m pipeline opendata content-hash            # the content hash of public/data/open
    python -m pipeline opendata package --tag TAG --out DIR [--commit SHA]
                                                        # DIR/eu-intel-TAG.zip, DIR/datapackage.json, DIR/notes.md
"""

from __future__ import annotations

import csv
import functools
import hashlib
import io
import json
import re
import sys
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline.analysis.transposition import classify as classify_transposition
from pipeline.analysis.transposition import general_deadline
from pipeline.models.countries import MEMBER_STATES

DIR = "open"  # under public/data
NAME = "eu-legislative-intelligence"
TITLE = "EU Legislative Intelligence – open dataset"
REPOSITORY = "https://github.com/RAHV-FB/eu-intel"
RELEASES = f"{REPOSITORY}/releases"
PUBLISHER = "RAHV-FB"
LICENSE = {
    "name": "CC-BY-4.0",
    "title": "Creative Commons Attribution 4.0 International",
    "path": "https://creativecommons.org/licenses/by/4.0/",
}
LIST_SEPARATOR = ";"  # between the values of a field that holds several (dates, identifiers, topics)
# A field of several dates is a string of this form (Frictionless 1.0 has no list type): ISO dates separated by ";"
DATE_LIST = r"\d{4}-\d{2}-\d{2}(;\d{4}-\d{2}-\d{2})*"
# The values that change without a change to any row or to the schema: the day statuses are computed for and the
# sources' retrieval times. Left out of the content hash (package fields; `retrieved_at` of each source).
VOLATILE = ("as_of", "snapshot_at", "core_data_at")
HASH_MARKER = "content-sha256"  # <!-- content-sha256: <hex> --> in the release notes

# What a Member State's Council position and a transposition status read as, on the site (src/features/votes/
# Breakdowns.tsx Pos, src/features/legislation/labels.ts TRANSPOSITION_LABEL; tests/test_opendata.py compares them)
POSITION_LABEL = {"for": "For", "against": "Against", "abstain": "Abstained", "not_participating": "Not participating"}
TRANSPOSITION_LABEL = {
    "measures_notified": "Measures notified",
    "none_found": "No measures found in the available dataset",
    "deadline_not_reached": "Deadline not yet reached",
    "no_deadline": "No transposition deadline recorded",
    "not_participating": "Not bound (did not take part in adoption)",
    "not_required": "Not required by the directive",
    "unavailable": "Data unavailable",
}


# ------------------------------------------------------------------------------------------------ schema
@dataclass(frozen=True)
class Field:
    name: str
    type: str  # string | integer | boolean | date | datetime
    description: str
    required: bool = False
    enum: tuple[str, ...] = ()
    unique: bool = False
    uri: bool = False  # a URL: type string, format uri
    many: bool = False  # several values separated by LIST_SEPARATOR

    def descriptor(self) -> dict[str, Any]:
        constraints: dict[str, Any] = {}
        if self.required:
            constraints["required"] = True
        if self.unique:
            constraints["unique"] = True
        if self.enum:
            constraints["enum"] = list(self.enum)
        dates = self.many and self.type == "date"
        if dates:
            constraints["pattern"] = DATE_LIST
        return {
            "name": self.name,
            "type": "string" if dates else self.type,
            **({"format": "uri"} if self.uri else {}),
            "description": self.description,
            **({"constraints": constraints} if constraints else {}),
        }


@dataclass(frozen=True)
class Table:
    name: str  # the resource name; the file is <name>.csv
    title: str
    description: str
    fields: tuple[Field, ...]
    key: tuple[str, ...]  # primary key
    references: tuple[tuple[str, str, str], ...] = ()  # foreign keys: (field, resource, its field)
    sources: tuple[str, ...] = ()  # ids of build.SOURCES the table's records come from

    @property
    def path(self) -> str:
        return f"{self.name}.csv"

    @property
    def columns(self) -> list[str]:
        return [f.name for f in self.fields]


@functools.cache
def _contract() -> Any:
    from pipeline.contract import Contract

    return Contract.load()


def _enum(type_name: str, field: str | None = None) -> tuple[str, ...]:
    """The string literals of a type of the public data contract (src/types/data.ts): a named union
    ("LifecycleStage") or one field of an interface ("CouncilVote", "voting_rule"), null left out."""
    contract = _contract()
    t: tuple = ("ref", type_name)
    if field is not None:
        t = contract.fields(t)[field][1]
    return tuple(x[1] for x in contract.alternatives(t) if x[0] == "lit" and isinstance(x[1], str))


@functools.cache
def tables() -> tuple[Table, ...]:
    """The tables of the open dataset, in the order of datapackage.json."""
    oeil = "The procedure file on Parliament's Legislative Observatory (OEIL); empty where OEIL has no file under this reference."
    files = Table(
        "files",
        "Legislative files",
        "One row per legislative file (procedure) of the dataset: the files of the site's legislation explorer. Their "
        "scope is in datapackage.json (description). Statuses are derived from the procedure's recorded events and its "
        "adopted act, as of `as_of` in datapackage.json.",
        (
            Field("id", "string", "The file's identifier on this site, which is also the European Parliament's process "
                  "id: the year and number of the procedure (2021-0106), followed by a letter for a part of a split "
                  "procedure (2016-0400A) or for a report of Parliament on a file (2025-0571R).", required=True,
                  unique=True),  # fmt: skip
            Field("ref", "string", "Procedure reference as Parliament's Legislative Observatory writes it: 2021/0106(COD). "
                  "The identifier of a procedure in crosswalk.csv.", required=True, unique=True),  # fmt: skip
            Field("type", "string", "Procedure type, the letters of the reference: COD ordinary legislative procedure, CNS "
                  "consultation, APP consent; NLE non-legislative (files EUR-Lex records under one of the three).",
                  required=True),  # fmt: skip
            Field("type_label", "string", "The procedure type in words, as the site shows it.", required=True),
            Field("title", "string", "The title the site shows: a curated short title, the act's official short name "
                  "(\"AI Act\"), or the official title without its legal-form boilerplate.", required=True),  # fmt: skip
            Field("official_title", "string", "The procedure's official title, or the official title of its adopted act "
                  "where the procedure's title does not describe it. Empty for a split procedure's parent known only "
                  "from EUR-Lex, which has no title of its own."),  # fmt: skip
            Field("stage", "string", "Stage of the file as of `as_of`, derived from its recorded events and its adopted "
                  "act. `unknown`: a proposal split into separate files, a report of Parliament, or a file whose final act "
                  "or stage the records do not give.", required=True, enum=_enum("LifecycleStage")),  # fmt: skip
            Field("status_label", "string", "The status as the site words it as of `as_of` (\"Approved by Parliament\" "
                  "is not \"adopted\" while the Council has not agreed).", required=True),  # fmt: skip
            Field("status_since", "date", "The date from which the status holds, where the records give it."),
            Field("status_basis", "string", "`source`: the status is recorded by an official source; `derived`: worked "
                  "out from the recorded events; `unknown`.", enum=_enum("Basis")),  # fmt: skip
            Field("started", "date", "Date of the proposal: the earliest recorded proposal or Commission document."),
            Field("last_event", "date", "Date of the latest recorded procedural step."),
            Field("adopted", "date", "Date of adoption: Parliament's approval at second reading, else the Council's "
                  "adoption as its voting result dates it; for an act Parliament adopts with the Council's consent, "
                  "Parliament's decision. Empty when not adopted or not recorded."),  # fmt: skip
            Field("published", "date", "Date the final act was published in the Official Journal."),
            Field("next_date", "date", "The earliest date after `as_of` that the file's acts fix (entry into force, "
                  "application, a transposition deadline); empty when there is none."),  # fmt: skip
            Field("instrument", "string", "Type of the adopted act linked from EUR-Lex; for a file without one (`celex` "
                  "empty), the type of act proposed, as the Legislative Observatory records it.",
                  enum=_enum("LegalInstrument")),  # fmt: skip
            Field("celex", "string", "CELEX numbers of the file's adopted acts (rows of acts.csv), separated by `;`. "
                  "The same links as crosswalk.csv `procedure_act`.", many=True),  # fmt: skip
            Field("topics", "string", "The site's topics (slugs, separated by `;`) from Parliament's subject codes; empty "
                  "when none of them covers the file. The slugs and their names are in datapackage.json (description).",
                  many=True),  # fmt: skip
            Field("featured", "boolean", "Whether the editors feature the file on the home page: an editorial selection, "
                  "not a ranking.", required=True),  # fmt: skip
            Field("officially_blocked", "boolean", "Whether Parliament's Legislative Train Schedule classifies the file "
                  "as \"Blocked\" (in the Train's own definition, no progress recorded for at least nine months). Empty "
                  "when the copy of the Train in the data is more than 42 days older than `as_of`: its classifications "
                  "are then not given, as on the site."),  # fmt: skip
            Field("blocked_label", "string", "The Legislative Train's status of the file, verbatim, when it is blocked."),
            Field("blocked_as_of", "date", "The Legislative Train's \"information updated as of\" date for that status."),
            Field("blocked_source_url", "string", "The file's page on the Legislative Train.", uri=True),
            Field("eurlex_only", "boolean", "Whether the file is known from its EUR-Lex act alone: the procedure's own "
                  "steps are not in the data.", required=True),  # fmt: skip
            Field("oeil_url", "string", oeil, uri=True),
            Field("url", "string", "The file's page on this site.", required=True, uri=True),
        ),
        ("id",),
        sources=("ep_procedures", "eurlex", "council", "train"),
    )
    acts = Table(
        "acts",
        "Adopted legal acts",
        "One row per adopted act linked to a file of files.csv (EUR-Lex / Cellar). Dates are EUR-Lex's, except where a "
        "check against the act's text corrected them (the site says so on the file's page; the corrections are listed "
        "in the repository's data/curated folder).",
        (
            Field("celex", "string", "CELEX number of the act: 32024R1689.", required=True, unique=True),
            Field("eli", "string", "European Legislation Identifier of the act.", uri=True),
            Field("act_type", "string", "Type of act, as EUR-Lex records it.", required=True, enum=_enum("LegalInstrument")),
            Field("title", "string", "Official title (EUR-Lex).", required=True),
            Field("date_document", "date", "Date of the act, as its title gives it (for an act of Parliament and the "
                  "Council, the day it was signed)."),  # fmt: skip
            Field("date_publication", "date", "Date of publication in the Official Journal."),
            Field("entry_into_force", "date", "Date of entry into force. Empty when EUR-Lex records none: the act "
                  "enters into force on a condition not yet met, or takes effect on notification."),  # fmt: skip
            Field("application_dates", "date", "Further dates from which the act, or some of its provisions, apply, "
                  "separated by `;`.", many=True),  # fmt: skip
            Field("transposition_deadline", "date", "Directives: the general deadline to transpose, from EUR-Lex's "
                  "annotations of its transposition dates (for some directives checked against the text)."),  # fmt: skip
            Field("further_transposition_deadlines", "date", "Directives: deadlines for specific provisions, earlier or "
                  "later than the general one, separated by `;`.", many=True),  # fmt: skip
            Field("in_force", "boolean", "Whether EUR-Lex records the act as in force."),
            Field("end_of_validity", "date", "End of validity, as EUR-Lex records it."),
            Field("file_id", "string", "The file of files.csv the act was adopted in.", required=True),
            Field("procedure", "string", "That file's procedure reference.", required=True),
            Field("eurlex_url", "string", "The act on EUR-Lex.", required=True, uri=True),
        ),
        ("celex",),
        (("file_id", "files", "id"),),
        sources=("eurlex",),
    )
    ep_votes = Table(
        "ep_votes",
        "European Parliament votes",
        "One row per plenary vote the site lists: roll-call votes on texts as a whole (final votes, resolutions, motions, "
        "negotiating mandates) and the final, mandate and negotiation-decision votes linked to a procedure. Votes on "
        "amendments and split or separate votes are not included, nor each MEP's vote (on the vote pages of the site). "
        "Results are Parliament's official ones.",
        (
            Field("id", "string", "Parliament's id of the vote in its open data (notation_votingId).", required=True,
                  unique=True),  # fmt: skip
            Field("date", "date", "Date of the plenary vote.", required=True),
            Field("title", "string", "What was voted, as the site titles it: the file's title and what the vote "
                  "decided.", required=True),  # fmt: skip
            Field("official_label", "string", "Parliament's own label of the vote (may be technical, or in French, English "
                  "and German).", required=True),  # fmt: skip
            Field("kind", "string", "Kind of vote, as the site classifies it from Parliament's records (this table "
                  "has no `amendment` or `split_or_separate` votes).", required=True, enum=_enum("VoteKind")),  # fmt: skip
            Field("kind_label", "string", "The kind of vote in words.", required=True),
            Field("kind_detail", "string", "What a motion or procedural vote (or a final vote on discharge) decides, where "
                  "Parliament's texts say so. For `reject_proposal`, `reject_council_position` and `objection` an adopted "
                  "motion means Parliament rejected or objected.", enum=_enum("VoteKindDetail")),  # fmt: skip
            Field("final_role", "string", "Final votes: what the vote decides, where the procedure establishes it.",
                  enum=_enum("FinalRole")),  # fmt: skip
            Field("outcome", "string", "Outcome of the text or motion voted on, not of a law: Parliament's vote alone does "
                  "not make a law.", required=True, enum=_enum("VoteOutcome")),  # fmt: skip
            Field("outcome_basis", "string", "How the outcome is established: `published` in Parliament's open data, "
                  "`minutes` of the sitting, or `derived`, calculated from the recorded counts.",
                  enum=_enum("EpVoteSummary", "outcome_basis")),  # fmt: skip
            Field("outcome_note", "string", "What the outcome means, where it needs saying (a motion to reject, an "
                  "objection)."),  # fmt: skip
            Field("for", "integer", "Votes in favour (official result)."),
            Field("against", "integer", "Votes against (official result)."),
            Field("abstain", "integer", "Abstentions (official result)."),
            Field("majority_rule", "string", "The majority the vote required, where established: of the votes cast, of "
                  "Parliament's component Members, or two thirds of the votes cast.", enum=_enum("VoteMargin", "rule")),  # fmt: skip
            Field("majority_threshold", "integer", "Votes in favour needed under that rule."),
            Field("margin", "integer", "Votes in favour minus the threshold (negative: short of it). Empty when the rule "
                  "is not established."),  # fmt: skip
            Field("has_ballots", "boolean", "Whether each MEP's vote is recorded (a roll-call vote).", required=True),
            Field("file_id", "string", "The file of files.csv the vote is on, when it names exactly one."),
            Field("procedure_ref", "string", "The procedure reference the vote names, also when that procedure is not a "
                  "file of this dataset."),  # fmt: skip
            Field("source_url", "string", "Parliament's record of the vote (the sitting's roll-call votes or minutes).",
                  required=True, uri=True),  # fmt: skip
            Field("url", "string", "The vote's page on this site.", required=True, uri=True),
        ),
        ("id",),
        (("file_id", "files", "id"),),
        sources=("ep_votes",),
    )
    council_votes = Table(
        "council_votes",
        "Council of the EU votes",
        "One row per Council vote from the Council's published voting results (and a few Council documents for records "
        "a voting result lacks). Member States' positions are in council_positions.csv.",
        (
            Field("id", "string", "This site's id of the vote: the voting-result document's number (ST-15154-2026), or "
                  "another Council document's for a record taken from it.", required=True, unique=True),  # fmt: skip
            Field("document", "string", "The voting-result document as the Council numbers it: ST 15154/26."),
            Field("date", "date", "Date of the vote (for a meeting over several days, the day the act's text gives for "
                  "the decision).", required=True),  # fmt: skip
            Field("title", "string", "The item's official title, as published.", required=True),
            Field("display_title", "string", "The title without legal-form boilerplate, with the item voted on when it is "
                  "neither the act nor the Council's first-reading position, as the site lists it."),  # fmt: skip
            Field("vote_on", "string", "`act`: the adoption of the act itself; `first_reading_position`: the Council's "
                  "position at first reading, which does not adopt the act (Parliament must still approve it); `other`: "
                  "another item. Empty when the document names no item.", enum=_enum("CouncilVoteOn")),  # fmt: skip
            Field("vote_on_label", "string", "For `other`: the item or items voted on."),
            Field("voting_rule", "string", "`qmv`: qualified majority. Where the act's legal basis requires unanimity but "
                  "the voting sheet prints \"qualified majority\", unanimity (see `notes`).", required=True,
                  enum=_enum("CouncilVote", "voting_rule")),  # fmt: skip
            Field("outcome", "string", "Outcome, as the voting result records it (or as the correction in `notes` "
                  "gives it).", required=True, enum=_enum("CouncilVote", "outcome")),  # fmt: skip
            Field("states_for", "integer", "Member States voting for (council_positions.csv); empty when the positions "
                  "are not given."),  # fmt: skip
            Field("states_against", "integer", "Member States voting against."),
            Field("states_abstain", "integer", "Member States abstaining."),
            Field("states_not_participating", "integer", "Member States not taking part under the Treaties' opt-outs "
                  "(not abstentions)."),  # fmt: skip
            Field("positions_note", "string", "Why the positions are not given, when they are not (the Council publishes "
                  "them)."),  # fmt: skip
            Field("notes", "string", "Where a value differs from the voting-result document, or the record comes from "
                  "another Council document: why, as checked against the act's text and the Council's documents."),  # fmt: skip
            Field("configuration", "string", "Council configuration that held the vote."),
            Field("meeting", "string", "The meeting, as published."),
            Field("written_procedure", "boolean", "Whether the vote was by written procedure rather than at a meeting."),
            Field("council_doc", "string", "The Council document voted on (PE-CONS 24/24, ST 8543/26). A "
                  "`council_document` of crosswalk.csv."),  # fmt: skip
            Field("file_id", "string", "The file of files.csv the vote is on, when it names exactly one."),
            Field("procedure", "string", "That file's procedure reference."),
            Field("source_url", "string", "The voting-result document (or other Council document).", required=True,
                  uri=True),  # fmt: skip
        ),
        ("id",),
        (("file_id", "files", "id"),),
        sources=("council",),
    )
    council_positions = Table(
        "council_positions",
        "Council of the EU votes: Member States' positions",
        "One row per Member State and Council vote whose positions are published (long form of the voting results' "
        "tables).",
        (
            Field("vote_id", "string", "The vote (council_votes.csv id).", required=True),
            Field("country", "string", "Member State at the time of the vote, ISO 3166-1 alpha-2 code (Greece GR, not "
                  "the EU's EL; GB, the United Kingdom, until its withdrawal on 31 January 2020).", required=True),  # fmt: skip
            Field("position", "string", "The Member State's recorded position. `not_participating`: not taking part "
                  "under the Treaties (an opt-out), which is not an abstention.", required=True,
                  enum=_enum("CouncilPosition")),  # fmt: skip
            Field("position_label", "string", "The position as the site words it.", required=True),
        ),
        ("vote_id", "country"),
        (("vote_id", "council_votes", "id"),),
        sources=("council",),
    )
    transposition = Table(
        "transposition",
        "Transposition of directives",
        "One row per directive of acts.csv and Member State. A count of notified measures says what the Member State "
        "notified to the Commission and EUR-Lex lists; it is not an assessment that transposition is complete or correct. "
        "\"No measures found\" means none in the available dataset, not that the country has not transposed the directive.",
        (
            Field("celex", "string", "The directive (acts.csv celex).", required=True),
            Field("act", "string", "The directive's number as its official title cites it: Directive (EU) 2022/2555."),
            Field("country", "string", "Member State, ISO 3166-1 alpha-2 code.", required=True),
            Field("deadline", "date", "The directive's general transposition deadline (acts.csv transposition_deadline)."),
            Field("status", "string", "Status, verbatim (`status_label` in words), as of `as_of`. `measures_notified`: at "
                  "least one national measure in the available dataset, which does not show that transposition is "
                  "complete or correct. `none_found`: no measures found in the available dataset after the deadline, which "
                  "is not proof of non-transposition or of non-compliance. `deadline_not_reached`: the deadline is after "
                  "`as_of`. `no_deadline`: EUR-Lex records no transposition deadline. `not_participating`: not bound "
                  "(did not take part in adopting it under a Treaty opt-out). `not_required`: the directive's own text "
                  "exempts the country (`status_note`). `unavailable`: national measures for this directive are not in "
                  "the data.", required=True, enum=_enum("TranspositionStatus")),  # fmt: skip
            Field("status_label", "string", "The status as the site words it.", required=True),
            Field("measures", "integer", "National measures notified to the Commission for this directive and country, "
                  "as EUR-Lex lists them (the rows of national_measures.csv). A count of notifications, not a measure "
                  "of transposition.", required=True),  # fmt: skip
            Field("latest_notification", "date", "The latest date a measure was notified to the Commission."),
            Field("status_note", "string", "For `not_required` and `not_participating` where it needs saying: the "
                  "provision or decision the status rests on."),  # fmt: skip
            Field("opted_in", "string", "CELEX number of the Commission decision confirming the country took part after "
                  "adoption (Protocol No 21, Article 4)."),  # fmt: skip
            Field("file_id", "string", "The file of files.csv the directive was adopted in.", required=True),
            Field("nim_url", "string", "The directive's national transposition measures on EUR-Lex.", required=True,
                  uri=True),  # fmt: skip
        ),
        ("celex", "country"),
        (("celex", "acts", "celex"), ("file_id", "files", "id")),
        sources=("implementation", "eurlex", "optouts", "council"),
    )
    measures = Table(
        "national_measures",
        "National transposition measures",
        "One row per national measure a Member State notified to the Commission as transposing a directive of acts.csv, "
        "as EUR-Lex lists them (current Member States). A notified measure is the Member State's statement that it "
        "transposes the directive, not an assessment of it.",
        (
            Field("id", "string", "EUR-Lex identifier of the national measure (a CELEX number of sector 7: "
                  "72014L0017AUT_233592).", required=True, unique=True),  # fmt: skip
            Field("directive", "string", "The directive transposed (acts.csv celex).", required=True),
            Field("country", "string", "Member State, ISO 3166-1 alpha-2 code.", required=True),
            Field("title", "string", "Title of the measure, in the national language, as notified."),
            Field("publication_date", "date", "Date of publication in the national official journal, where given."),
            Field("notified", "date", "Date the measure was notified to the Commission."),
            Field("commission_ref", "string", "The Commission's reference of the notification: MNE(2016)50267."),
            Field("national_ref", "string", "The measure's national reference, where given."),
            Field("journal", "string", "The national official journal, where given."),
            Field("url", "string", "The measure's own address, where EUR-Lex gives one.", uri=True),
        ),
        ("id",),
        (("directive", "acts", "celex"),),
        sources=("implementation",),
    )
    infringements = Table(
        "infringements",
        "Infringement cases",
        "One row per infringement case of the Commission's register of infringement decisions concerning a current "
        "Member State: all open cases and all cases with a Commission decision since 1 January 2019 (cases closed "
        "before then are not included). An open case is not a court ruling.",
        (
            Field("id", "string", "The Commission's case number: INFR(2023)0123.", required=True, unique=True),
            Field("country", "string", "Member State, ISO 3166-1 alpha-2 code.", required=True),
            Field("celex", "string", "The act the register names, when it names exactly one; it may be outside this "
                  "dataset. The links to acts of acts.csv are in crosswalk.csv (`infringement_act`)."),  # fmt: skip
            Field("title", "string", "Title of the case, as the register gives it (often in French).", required=True),
            Field("non_communication", "boolean", "Whether the case is about a failure to notify transposition measures."),
            Field("latest_stage", "string", "The latest decision's stage, as published."),
            Field("latest_decision_date", "date", "Date of the latest decision."),
            Field("status", "string", "Whether the register gives the case as open or closed.", required=True,
                  enum=_enum("InfringementInfo", "status")),  # fmt: skip
            Field("source_url", "string", "The case in the Commission's register.", required=True, uri=True),
        ),
        ("id",),
        sources=("implementation",),
    )
    kinds = tuple(CROSSWALK_IDS)
    where = "; ".join(f"`{k}`: {w}" for k, w in CROSSWALK_WHERE.items())
    crosswalk = Table(
        "crosswalk",
        "Identifier crosswalk",
        "One row per link between two official identifiers (procedure, CELEX, ELI, Parliament vote, Council vote and "
        "document, national measure, infringement case), with the kind of link and the record that establishes it. "
        "Only identifiers that each have a row in this dataset are linked.",
        (
            Field("from_type", "string", f"Kind of the first identifier, and where it is listed: {where}.",
                  required=True, enum=kinds),  # fmt: skip
            Field("from_id", "string", "The first identifier.", required=True),
            Field("link", "string", "Kind of link: " + "; ".join(f"`{k}`, {v}" for k, v in CROSSWALK_LINKS.items()) + ".",
                  required=True, enum=tuple(CROSSWALK_LINKS)),  # fmt: skip
            Field("to_type", "string", "Kind of the second identifier (as `from_type`).", required=True, enum=kinds),
            Field("to_id", "string", "The second identifier.", required=True),
            Field("source", "string", "The record that establishes the link: "
                  + "; ".join(f"`{k}`, {v}" for k, v in CROSSWALK_SOURCES.items())
                  + ". Two, separated by `;`, when both records establish it.", required=True),  # fmt: skip
        ),
        ("from_type", "from_id", "link", "to_type", "to_id"),
        sources=("ep_procedures", "ep_votes", "eurlex", "council", "implementation"),
    )
    return (files, acts, ep_votes, council_votes, council_positions, transposition, measures, infringements, crosswalk)


# Each kind of identifier in crosswalk.csv: the table and field that list it
CROSSWALK_IDS: dict[str, tuple[str, str]] = {
    "procedure": ("files", "ref"),
    "celex": ("acts", "celex"),
    "eli": ("acts", "eli"),
    "ep_vote": ("ep_votes", "id"),
    "council_vote": ("council_votes", "id"),
    "council_document": ("council_votes", "council_doc"),
    "national_measure": ("national_measures", "id"),
    "infringement": ("infringements", "id"),
}
CROSSWALK_WHERE = {k: f"{t}.csv {f}" for k, (t, f) in CROSSWALK_IDS.items()}
CROSSWALK_LINKS: dict[str, str] = {
    "procedure_act": "procedure → celex, the act adopted in the procedure",
    "act_eli": "celex → eli, the same act",
    "vote_procedure": "ep_vote → procedure, the procedure a Parliament vote is on",
    "council_vote_procedure": "council_vote → procedure, the procedure a Council vote is on",
    "council_vote_document": "council_vote → council_document, the document the Council voted on",
    "act_national_measure": "celex → national_measure, a measure notified as transposing the directive",
    "infringement_act": "infringement → celex, an act the case concerns (its legal basis in the register)",
}
# The record that establishes a link of the crosswalk (its `source`; a link two records establish names both, "; ")
CROSSWALK_SOURCES: dict[str, str] = {
    "EUR-Lex": "the act's own record in EUR-Lex (Cellar): its procedure reference, its ELI",
    "Legislative Observatory": "Parliament's procedure file, which lists the procedure's final act",
    "Parliament": "the vote's procedure reference in Parliament's open data",
    "Council": "the Council's voting result: the procedure reference it cites, the document voted on",
    "EUR-Lex national measures": "the national transposition measures EUR-Lex lists for the directive",
    "Commission register": "the case in the Commission's register of infringement decisions: its legal basis, or the "
    "one act it names",
    "derived": "worked out by the build: a vote on the decision to enter into negotiations on a proposal later split, "
    "which Parliament files under the proposal, on the part whose documents it voted",
}


# ------------------------------------------------------------------------------------------------ rows
def _site(site_url: str) -> str:
    return site_url if site_url.endswith("/") else site_url + "/"


def _url(src: dict | None) -> str | None:
    return (src or {}).get("url") or None


def _labels_current(meta: dict, source: str, as_of: str) -> bool:
    """Whether a source's official classifications (the Legislative Train's "Blocked") are given as current throughout
    the day `as_of`: its copy is at most `labels_expire_after_days` old at the end of that day (src/lib/freshness.ts
    classifications, on the reader's clock)."""
    s = next((x for x in meta.get("sources") or [] if x.get("id") == source), None)
    if not s or not s.get("fetched_at"):
        return False
    limit = s.get("labels_expire_after_days")
    if limit is None:
        return True
    fetched = datetime.fromisoformat(s["fetched_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(f"{as_of}T00:00:00+00:00") + timedelta(days=1)
    return (end - fetched).total_seconds() / 86400 <= limit


def _rows(b: Any, files: dict[str, Any], site_url: str) -> dict[str, list[dict[str, Any]]]:
    """The rows of each table, from the built files and the joins the build made (Builder `b`)."""
    site = _site(site_url)
    meta = files.get("meta.json") or {}
    as_of = b.today
    train_current = _labels_current(meta, "train", as_of)
    index = files.get("dossiers/index.json") or []
    details = [files[f"dossiers/{d['id']}.json"] for d in index if f"dossiers/{d['id']}.json" in files]
    details.sort(key=lambda d: d["id"])

    out: dict[str, list[dict[str, Any]]] = {t.name: [] for t in tables()}
    links: set[tuple[str, str, str, str, str, str]] = set()

    def link(from_type: str, from_id: str, kind: str, to_type: str, to_id: str, source: str) -> None:
        links.add((from_type, from_id, kind, to_type, to_id, source))

    acts: dict[str, dict] = {}
    impl: dict[str, tuple[dict, str]] = {}  # directive -> (its implementation table, file id)
    for d in details:
        stall = d.get("stall") or {}
        blocked = bool(d.get("officially_blocked")) if train_current else None
        status = d.get("status") or {}
        out["files"].append({
            "id": d["id"], "ref": d["ref"], "type": d["type"], "type_label": d["type_label"], "title": d["title"],
            "official_title": d.get("official_title"), "stage": d["stage"], "status_label": d["status_label"],
            "status_since": status.get("since"), "status_basis": status.get("basis"), "started": d.get("started"),
            "last_event": d.get("last_event"), "adopted": d.get("adopted"), "published": d.get("published"),
            "next_date": d.get("next_date"), "instrument": d.get("instrument"), "celex": d.get("celex") or [],
            "topics": d.get("topics") or [], "featured": bool(d.get("featured")), "officially_blocked": blocked,
            "blocked_label": stall.get("official_label") if blocked else None,
            "blocked_as_of": stall.get("official_label_date") if blocked else None,
            "blocked_source_url": stall.get("official_source_url") if blocked else None,
            "eurlex_only": bool(d.get("eurlex_only")), "oeil_url": d.get("oeil_url"),
            "url": f"{site}legislation/{d['id']}/",
        })  # fmt: skip
        p = b.proc.get(d["id"])
        for a in d.get("acts") or []:
            acts.setdefault(a["celex"], {**a, "file_id": d["id"], "procedure": d["ref"]})
            act = b.act.get(a["celex"])
            eurlex = act is not None and any(
                (q := b.resolve_ref(r)) is not None and q.id == d["id"] for r in act.procedure_refs
            )
            oeil = p is not None and a["celex"] in p.celex_refs
            for source, on in (("EUR-Lex", eurlex), ("Legislative Observatory", oeil), ("derived", not (eurlex or oeil))):
                if on:
                    link("procedure", d["ref"], "procedure_act", "celex", a["celex"], source)
        for v in d.get("ep_votes") or []:
            named = d["id"] in b.vote_dossier_map.get(v["id"], [])
            link("ep_vote", v["id"], "vote_procedure", "procedure", d["ref"], "Parliament" if named else "derived")
        for cv in d.get("council_votes") or []:
            link("council_vote", cv["id"], "council_vote_procedure", "procedure", d["ref"], "Council")
        tabs = ([d["implementation"]] if d.get("implementation") else []) + list(d.get("implementation_more") or [])
        for t in tabs:
            impl.setdefault(t["celex"], (t, d["id"]))

    for celex, a in sorted(acts.items()):
        act = b.act.get(celex)
        dated = classify_transposition(act) if act is not None and a["act_type"] == "directive" else []
        out["acts"].append({
            "celex": celex, "eli": a.get("eli"), "act_type": a["act_type"], "title": a["title"],
            "date_document": a.get("date_document"), "date_publication": a.get("date_publication"),
            "entry_into_force": a.get("entry_into_force"), "application_dates": a.get("other_application_dates") or [],
            "transposition_deadline": general_deadline(act) if dated else None,
            "further_transposition_deadlines": [x.date for x in dated if x.kind == "further_deadline"],
            "in_force": a.get("in_force"), "end_of_validity": a.get("end_of_validity"), "file_id": a["file_id"],
            "procedure": a["procedure"], "eurlex_url": a["eurlex_url"],
        })  # fmt: skip
        if a.get("eli"):
            link("celex", celex, "act_eli", "eli", a["eli"], "EUR-Lex")

    for v in files.get("votes/index.json") or []:
        m = v.get("margin") or {}
        out["ep_votes"].append({
            "id": v["id"], "date": v["date"], "title": v.get("display_title") or v["title"], "official_label": v["title"],
            "kind": v["kind"], "kind_label": v["kind_label"], "kind_detail": v.get("kind_detail"),
            "final_role": v.get("final_role"), "outcome": v["outcome"], "outcome_basis": v.get("outcome_basis"),
            "outcome_note": v.get("outcome_note"), "for": v.get("for"), "against": v.get("against"),
            "abstain": v.get("abstain"), "majority_rule": m.get("rule"), "majority_threshold": m.get("threshold"),
            "margin": m.get("distance"), "has_ballots": bool(v.get("has_ballots")), "file_id": v.get("dossier_id"),
            "procedure_ref": v.get("procedure_ref"), "source_url": _url(v.get("source")),
            "url": f"{site}votes/{v['id']}/",
        })  # fmt: skip
    out["ep_votes"].sort(key=lambda r: (r["date"], int(r["id"]) if r["id"].isdigit() else 0, r["id"]))

    for cv in files.get("council/index.json") or []:
        pos = cv.get("positions") or {}
        counted = {k: sum(1 for x in pos.values() if x == k) for k in POSITION_LABEL}
        notes = [cv.get(k) for k in ("vote_on_note", "date_note", "voting_rule_note", "outcome_note", "source_note")]
        out["council_votes"].append({
            "id": cv["id"], "document": (cv.get("source") or {}).get("identifier"), "date": cv["date"],
            "title": cv["title"], "display_title": cv.get("display_title"), "vote_on": cv.get("vote_on"),
            "vote_on_label": cv.get("vote_on_label"), "voting_rule": cv["voting_rule"], "outcome": cv["outcome"],
            **({f"states_{k}": counted[k] if pos else None for k in POSITION_LABEL}),
            "positions_note": cv.get("positions_note"), "notes": " ".join(n for n in notes if n) or None,
            "configuration": cv.get("configuration"), "meeting": cv.get("meeting"),
            "written_procedure": cv.get("written_procedure"), "council_doc": cv.get("council_doc"),
            "file_id": cv.get("dossier_id"), "procedure": cv.get("dossier_ref"), "source_url": _url(cv.get("source")),
        })  # fmt: skip
        for country, p in sorted(pos.items()):
            out["council_positions"].append(
                {"vote_id": cv["id"], "country": country, "position": p, "position_label": POSITION_LABEL.get(p, p)}
            )
        if cv.get("council_doc"):
            link("council_vote", cv["id"], "council_vote_document", "council_document", cv["council_doc"], "Council")
    out["council_votes"].sort(key=lambda r: (r["date"], r["id"]))
    out["council_positions"].sort(key=lambda r: (r["vote_id"], r["country"]))

    cases: dict[str, dict] = {}
    for code in sorted(MEMBER_STATES):
        for i in (files.get(f"countries/{code}.json") or {}).get("infringements") or []:
            cases.setdefault(i["id"], i)
    for celex, (t, file_id) in sorted(impl.items()):
        for r in t["countries"]:
            out["transposition"].append({
                "celex": celex, "act": t.get("act"), "country": r["country"], "deadline": t.get("deadline"),
                "status": r["status"], "status_label": TRANSPOSITION_LABEL.get(r["status"], r["status"]),
                "measures": r["measures"], "latest_notification": r.get("latest_notification"),
                "status_note": r.get("status_note"), "opted_in": r.get("opted_in"), "file_id": file_id,
                "nim_url": t["nim_url"],
            })  # fmt: skip
            for i in r.get("infringements") or []:
                if i["id"] in cases:
                    link("infringement", i["id"], "infringement_act", "celex", celex, "Commission register")
            for nm in sorted(b.measures_by.get((celex, r["country"]), []), key=lambda m: m.id):
                out["national_measures"].append({
                    "id": nm.id, "directive": celex, "country": nm.country, "title": nm.title,
                    "publication_date": nm.date, "notified": nm.notified, "commission_ref": nm.commission_ref,
                    "national_ref": nm.national_ref, "journal": nm.journal, "url": nm.url,
                })  # fmt: skip
                link("celex", celex, "act_national_measure", "national_measure", nm.id, "EUR-Lex national measures")
    out["transposition"].sort(key=lambda r: (r["celex"], r["country"]))
    out["national_measures"].sort(key=lambda r: r["id"])

    for cid, i in sorted(cases.items()):
        out["infringements"].append({
            "id": cid, "country": i["country"], "celex": i.get("celex"), "title": i["title"],
            "non_communication": i.get("non_communication"), "latest_stage": i.get("latest_stage"),
            "latest_decision_date": i.get("latest_decision_date"), "status": i["status"],
            "source_url": _url(i.get("source")),
        })  # fmt: skip
        if i.get("celex") in acts:
            link("infringement", cid, "infringement_act", "celex", i["celex"], "Commission register")

    # one row per link: a link two records establish names both, in the order of CROSSWALK_SOURCES
    merged: dict[tuple[str, ...], set[str]] = {}
    for *key, source in links:
        merged.setdefault(tuple(key), set()).add(source)
    order = list(CROSSWALK_SOURCES)
    out["crosswalk"] = [
        {"from_type": k[0], "from_id": k[1], "link": k[2], "to_type": k[3], "to_id": k[4],
         "source": LIST_SEPARATOR.join(sorted(s, key=order.index))}
        for k, s in sorted(merged.items())
    ]  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ files
def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return LIST_SEPARATOR.join(_cell(x) for x in v)
    return str(v)


def to_csv(columns: list[str], rows: Iterable[dict[str, Any]]) -> bytes:
    """RFC 4180: comma-separated, fields with a comma, a double quote or a line break in double quotes (a double quote
    doubled), CRLF line ends; one header row; UTF-8 without a byte-order mark."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(columns)
    for r in rows:
        if set(r) != set(columns):
            raise ValueError(f"row fields {sorted(set(r) ^ set(columns))} do not match the table's columns")
        w.writerow([_cell(r[c]) for c in columns])
    return buf.getvalue().encode("utf-8")


def _sources(meta: dict) -> dict[str, dict]:
    return {s["id"]: s for s in meta.get("sources") or [] if isinstance(s, dict) and s.get("id")}


def attribution(site_url: str) -> str:
    return (
        f"EU Legislative Intelligence ({PUBLISHER}), {_site(site_url)}, licensed CC BY 4.0. Contains information © "
        "European Union from the European Parliament, EUR-Lex (Publications Office of the European Union), the "
        "Council of the European Union and the European Commission, adapted: selected, combined and reformatted."
    )


def datapackage(b: Any, files: dict[str, Any], data: dict[str, bytes], counts: dict[str, int], site_url: str) -> dict:
    meta = files.get("meta.json") or {}
    sources = _sources(meta)
    topics = files.get("topics.json") or []
    scope = meta.get("scope") or {}
    types = ", ".join(scope.get("procedure_types") or [])
    described = (
        f"The data of EU Legislative Intelligence ({_site(site_url)}), an independent, nonpartisan site that explains EU "
        "legislation from official EU records only: legislative files with their status and dates, the acts adopted in "
        "them, Parliament and Council votes, the transposition of directives by Member State with the national measures "
        "notified, infringement cases, and a crosswalk of the official identifiers that join them (procedure reference, "
        "CELEX and ELI, Parliament vote, Council voting result and document, national measure, infringement case). "
        f"Scope: procedures of the types {types or 'COD, CNS and APP'}"
        + (f" from {scope['procedures_from_year']}" if scope.get("procedures_from_year") else "")
        + (f", acts dated from {scope['acts_from']}" if scope.get("acts_from") else "")
        + (f", Parliament votes from {scope['ep_votes_from']} to {scope['ep_votes_to']}" if scope.get("ep_votes_from") else "")
        + (f", Council votes from {scope['council_votes_from']} to {scope['council_votes_to']}"
           if scope.get("council_votes_from") else "")
        + f". Statuses are as of {b.today} (`as_of`). Not an official EU dataset: the official records remain "
        "authoritative. Topics: " + "; ".join(f"{t['slug']} = {t['label']}" for t in topics) + "."
    )  # fmt: skip
    resources = []
    for t in tables():
        raw = data[t.path]
        resources.append({
            "profile": "tabular-data-resource",
            "name": t.name,
            "path": t.path,
            "title": t.title,
            "description": t.description,
            "format": "csv",
            "mediatype": "text/csv",
            "encoding": "utf-8",
            "dialect": {"delimiter": ",", "lineTerminator": "\r\n", "quoteChar": '"', "doubleQuote": True, "header": True},
            "bytes": len(raw),
            "hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "rows": counts[t.name],
            "sources": [{"title": sources[s]["name"], "path": sources[s]["url"]} for s in t.sources if s in sources],
            "schema": {
                "fields": [f.descriptor() for f in t.fields],
                "primaryKey": list(t.key),
                "foreignKeys": [
                    {"fields": [f], "reference": {"resource": res, "fields": [rf]}} for f, res, rf in t.references
                ],
                "missingValues": [""],
            },
        })  # fmt: skip
    return {
        "profile": "tabular-data-package",
        "name": NAME,
        "title": TITLE,
        "description": described,
        "homepage": _site(site_url),
        "keywords": ["European Union", "legislation", "European Parliament", "Council of the European Union", "EUR-Lex",
                     "votes", "transposition", "infringements", "open data"],  # fmt: skip
        "as_of": b.today,
        "snapshot_at": meta.get("snapshot_at"),
        "core_data_at": meta.get("core_data_at"),
        "licenses": [LICENSE],
        "attribution": attribution(site_url),
        "contributors": [{"title": PUBLISHER, "path": f"https://github.com/{PUBLISHER}", "role": "author"}],
        "sources": [
            {"id": sid, "title": s["name"], "path": s["url"], "attribution": s["licence"], "retrieved_at": s.get("fetched_at")}
            for sid, s in sources.items()
        ],
        "resources": resources,
    }


def _day(ts: str | None) -> str:
    if not ts:
        return "not recorded"
    d = date.fromisoformat(ts[:10])
    return f"{d.day} {d:%B %Y}"


def readme(dp: dict) -> str:
    rows = "\n".join(
        f"| [`{r['path']}`]({r['path']}) | {r['rows']:,} | {r['title']}: {r['description']} |" for r in dp["resources"]
    )
    links = "\n".join(f"- `{k}`: {v}" for k, v in CROSSWALK_LINKS.items())
    ids = "\n".join(f"- `{k}`: {v}" for k, v in CROSSWALK_WHERE.items())
    sources = "\n".join(f"- **{s['title']}** ({s['path']}): {s['attribution']}" for s in dp["sources"])
    return f"""# {dp['title']}

{dp['description']}

- **Statuses as of** {_day(dp['as_of'])} (`as_of`): a file's stage and status label, the transposition statuses and
  the "next" dates are computed for that day.
- **Data current to** {_day(dp.get('core_data_at'))} for procedures, votes and acts (the oldest last successful
  retrieval of their sources); the latest retrieval of any source was on {_day(dp.get('snapshot_at'))}. Each source's
  retrieval is in `datapackage.json` (`sources`).
- **Site**: {dp['homepage']} · **Releases**: {RELEASES} (tags `data-YYYY-MM-DD`) · **Code and documentation**:
  {REPOSITORY}

## Files

All tables are CSV (UTF-8 without a byte-order mark, RFC 4180: comma-separated, double quotes, CRLF line ends) with
one header row. An empty cell means the value is not available in the official records used, or does not apply. A
field that holds several values separates them with `;`. Dates are ISO 8601 (YYYY-MM-DD). `datapackage.json` (a
[Frictionless](https://specs.frictionlessdata.io/tabular-data-package/) Tabular Data Package) gives every field's
type and description, the primary keys and the foreign keys between the tables.

| File | Rows | Contents |
| --- | ---: | --- |
{rows}

## Identifiers and the crosswalk

Records are joined only through official identifiers, never by title. `crosswalk.csv` lists each link between two
identifiers of this dataset, with the record that establishes it. Identifiers:

{ids}

Links:

{links}

## Read with care

- A **status** says where a file stands in the official records as of `as_of`; "Approved by Parliament" is not "adopted"
  while the Council has not agreed, and a vote's outcome is that of the text or motion voted on, not of a law.
- **Transposition**: `measures_notified` means at least one national measure is in the available dataset; a notified
  measure is the Member State's statement, not an assessment that transposition is complete or correct.
  `none_found` means no measures were found in the available dataset, not that the country has not transposed the
  directive. A count of measures is a count of notifications.
- **Council positions**: `not_participating` (a Treaty opt-out) is not an abstention. MEPs' votes grouped by country
  are not that country's position, which its government gives in the Council.
- **Blocked**: only the Legislative Train's own classification, given while its copy is at most 42 days old.
- Official records are sometimes late, incomplete or inconsistent; where they disagree the site follows the official
  result and notes the difference. A few values were corrected by hand against the official texts; each correction
  cites its provision in the repository's `data/curated` folder.

## Licence and attribution

The compilation (the selection, the structure, the derived fields and the checked corrections) is licensed under
[CC BY 4.0]({LICENSE['path']}). Credit it as:

> {dp['attribution']}

The official records it contains remain subject to their publishers' reuse terms, which also require
acknowledgement of the source; each row keeps the address of the record it comes from where the table has one:

{sources}

The site and this dataset are independent and not official: they are not endorsed by the European Union or its
institutions.

## Cite

Cite a release by its tag and address, e.g. "{PUBLISHER}. EU Legislative Intelligence – open dataset, release
data-YYYY-MM-DD. {RELEASES}". The repository's `CITATION.cff` gives the citation, with the DOI once releases are
archived on Zenodo.
"""


def build_open_data(b: Any, files: dict[str, Any], site_url: str) -> dict[str, bytes]:
    """public/data/open/: the CSV tables, datapackage.json and README.md (paths relative to public/data)."""
    rows = _rows(b, files, site_url)
    data = {t.path: to_csv(t.columns, rows[t.name]) for t in tables()}
    dp = datapackage(b, files, data, {k: len(v) for k, v in rows.items()}, site_url)
    out = {f"{DIR}/{path}": raw for path, raw in data.items()}
    out[f"{DIR}/datapackage.json"] = (json.dumps(dp, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    out[f"{DIR}/README.md"] = readme(dp).encode("utf-8")
    return out


# ------------------------------------------------------------------------------------------------ release
def content_hash(dp: dict) -> str:
    """SHA-256 of the descriptor without the values that change while no row or schema does (VOLATILE, the sources'
    retrieval times). The descriptor gives each table's SHA-256, so the hash covers every row."""
    stable = {k: v for k, v in dp.items() if k not in VOLATILE}
    stable["sources"] = [{k: v for k, v in s.items() if k != "retrieved_at"} for s in dp.get("sources") or []]
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def read_package(open_dir: Path) -> dict:
    return json.loads((open_dir / "datapackage.json").read_text(encoding="utf-8"))


def write_zip(open_dir: Path, path: Path, top: str) -> None:
    """The dataset's files in `top`/, in a fixed order with a fixed time: the same files give the same zip."""
    names = ["README.md", "datapackage.json", *(r["path"] for r in read_package(open_dir)["resources"])]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in names:
            info = zipfile.ZipInfo(f"{top}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (open_dir / name).read_bytes())


def release_notes(dp: dict, tag: str, commit: str | None = None) -> str:
    """The release's notes: the snapshot's dates, each table's rows, the caveats, the licence, and the content hash in
    a comment (HASH_MARKER) that the next run compares its own with (.github/workflows/release-data.yml)."""
    rows = "\n".join(f"| `{r['path']}` | {r['rows']:,} | {r['title']} |" for r in dp["resources"])
    built = f"\n- **Built from** commit {commit}." if commit else ""
    return f"""The open dataset of EU Legislative Intelligence, release `{tag}`: legislative files, adopted acts, \
Parliament and Council votes, the transposition of directives with the national measures notified, and infringement \
cases, as CSV tables with a schema (`datapackage.json`, a Frictionless Data Package) and a crosswalk of the official \
identifiers that join them.

- **Data current to** {_day(dp.get('core_data_at'))} for procedures, votes and acts (the oldest last successful retrieval \
of their sources); latest retrieval of any source {_day(dp.get('snapshot_at'))}.
- **Statuses as of** {_day(dp['as_of'])}.{built}

| File | Rows | Contents |
| --- | ---: | --- |
{rows}

The zip holds these files with `datapackage.json` and `README.md`, which describes every table, the identifiers and \
what the values do not say: a notified national measure is not an assessment of transposition, and "no measures \
found" (`none_found`) is not proof that a directive was not transposed.

**Licence**: the compilation is under [CC BY 4.0]({LICENSE['path']}); the official records keep their publishers' \
terms (README.md, "Licence and attribution"). Credit: {dp['attribution']}

<!-- {HASH_MARKER}: {content_hash(dp)} -->
"""


def package(open_dir: Path, out: Path, tag: str, commit: str | None = None) -> Path:
    """The release's files in `out`: eu-intel-<tag>.zip, datapackage.json and notes.md. Returns the zip."""
    if not re.fullmatch(r"data-\d{4}-\d{2}-\d{2}(?:\.\d+)?", tag):
        raise ValueError(f"not a data release tag: {tag!r} (data-YYYY-MM-DD, or data-YYYY-MM-DD.N)")
    out.mkdir(parents=True, exist_ok=True)
    dp = read_package(open_dir)
    zip_path = out / f"eu-intel-{tag}.zip"
    write_zip(open_dir, zip_path, f"eu-intel-{tag}")
    (out / "datapackage.json").write_bytes((open_dir / "datapackage.json").read_bytes())
    (out / "notes.md").write_text(release_notes(dp, tag, commit), encoding="utf-8")
    return zip_path


# ------------------------------------------------------------------------------------------------ checks
TYPE_CHECKS: dict[str, Callable[[str], bool]] = {
    "string": lambda s: True,
    "integer": lambda s: re.fullmatch(r"-?\d+", s) is not None,
    "boolean": lambda s: s in ("true", "false"),
    "date": lambda s: re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) is not None,
}
NO_CHECK: Callable[[str], bool] = lambda s: False  # noqa: E731 - a type this check does not know


def check(open_dir: Path) -> list[str]:
    """Problems of the open dataset in `open_dir` against its datapackage.json: each table's size and hash, header,
    field types, required values and enumerations, primary keys, foreign keys, and every identifier of the crosswalk
    present in its table. [] when it is consistent."""
    problems: list[str] = []
    try:
        dp = read_package(open_dir)
    except (OSError, ValueError) as e:
        return [f"datapackage.json: unreadable ({e})"]
    if not (open_dir / "README.md").is_file():
        problems.append("README.md is missing")
    expected = {t.name: t for t in tables()}
    names = [r.get("name") for r in dp.get("resources") or []]
    if names != list(expected):
        problems.append(f"datapackage.json lists the tables {names}, not {list(expected)}")
    columns: dict[str, dict[str, list[str]]] = {}
    for r in dp.get("resources") or []:
        name, path = r.get("name"), open_dir / str(r.get("path"))
        try:
            raw = path.read_bytes()
        except OSError as e:
            problems.append(f"{r.get('path')}: unreadable ({e})")
            continue
        if len(raw) != r.get("bytes") or "sha256:" + hashlib.sha256(raw).hexdigest() != r.get("hash"):
            problems.append(f"{r['path']}: its size or SHA-256 differs from datapackage.json")
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{r['path']}: starts with a byte-order mark")
        try:
            records = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
        except (UnicodeDecodeError, csv.Error) as e:
            problems.append(f"{r['path']}: not UTF-8 CSV ({e})")
            continue
        fields = r.get("schema", {}).get("fields") or []
        header = records[0] if records else []
        if header != [f["name"] for f in fields]:
            problems.append(f"{r['path']}: header {header} is not the fields of datapackage.json")
            continue
        if name in expected and header != expected[name].columns:
            problems.append(f"{r['path']}: header {header} is not the table's columns {expected[name].columns}")
        body = records[1:]
        if len(body) != r.get("rows"):
            problems.append(f"{r['path']}: {len(body)} rows, datapackage.json says {r.get('rows')}")
        cols: dict[str, list[str]] = {f["name"]: [] for f in fields}
        bad: dict[str, tuple[int, str]] = {}
        for n, rec in enumerate(body, start=2):
            if len(rec) != len(fields):
                bad.setdefault("cells", (n, f"{len(rec)} cells, not {len(fields)}"))
                continue
            for f, value in zip(fields, rec, strict=True):
                cols[f["name"]].append(value)
                cons = f.get("constraints") or {}
                if not value:
                    if cons.get("required"):
                        bad.setdefault(f["name"], (n, "required value missing"))
                    continue
                if not TYPE_CHECKS.get(f["type"], NO_CHECK)(value):
                    bad.setdefault(f["name"], (n, f"{value!r} is not a {f['type']}"))
                elif cons.get("pattern") and not re.fullmatch(cons["pattern"], value):
                    bad.setdefault(f["name"], (n, f"{value!r} does not match {cons['pattern']}"))
                elif cons.get("enum") and value not in cons["enum"]:
                    bad.setdefault(f["name"], (n, f"{value!r} is not one of its values"))
        for what, (n, msg) in sorted(bad.items()):
            problems.append(f"{r['path']} line {n}, {what}: {msg}")
        columns[name] = cols
        key = r.get("schema", {}).get("primaryKey") or []
        if key and not bad.get("cells"):
            keys = list(zip(*(cols[k] for k in key), strict=True))
            if len(set(keys)) != len(keys):
                dup = next(k for k in keys if keys.count(k) > 1)
                problems.append(f"{r['path']}: primary key {key} is not unique (e.g. {dup})")
        for f in fields:
            if (f.get("constraints") or {}).get("unique"):
                vals = [v for v in cols[f["name"]] if v]
                if len(set(vals)) != len(vals):
                    problems.append(f"{r['path']}: {f['name']} is not unique")
    for r in dp.get("resources") or []:
        for fk in r.get("schema", {}).get("foreignKeys") or []:
            (field,), ref = fk["fields"], fk["reference"]
            target = set(columns.get(ref["resource"], {}).get(ref["fields"][0], []))
            missing = sorted({v for v in columns.get(r.get("name"), {}).get(field, []) if v and v not in target})
            if missing:
                problems.append(f"{r['path']}: {field} {missing[:3]} not in {ref['resource']}.{ref['fields'][0]} "
                                f"({len(missing)} values)")  # fmt: skip
    cw = columns.get("crosswalk", {})
    listed = {kind: set(columns.get(t, {}).get(f, [])) for kind, (t, f) in CROSSWALK_IDS.items()}
    for side in ("from", "to"):
        pairs = zip(cw.get(f"{side}_type", []), cw.get(f"{side}_id", []), strict=True)
        missing = {(kind, ident) for kind, ident in pairs if ident not in listed.get(kind, ())}
        if missing:
            problems.append(f"crosswalk.csv: {len(missing)} {side}_id not in their table (e.g. {sorted(missing)[:3]})")
    return problems


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str], open_dir: Path) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="pipeline opendata")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("content-hash", help="print the content hash of the open dataset (its rows and schema)")
    pk = sub.add_parser("package", help="write the release's zip, datapackage.json and notes.md")
    pk.add_argument("--tag", required=True, help="data-YYYY-MM-DD (or data-YYYY-MM-DD.N)")
    pk.add_argument("--out", type=Path, required=True)
    pk.add_argument("--commit", default=None, help="the commit the dataset was built from")
    a = p.parse_args(argv)
    problems = check(open_dir)
    if problems:
        for m in problems[:20]:
            print(f"opendata: {m}", file=sys.stderr)
        return 1
    if a.cmd == "content-hash":
        print(content_hash(read_package(open_dir)))
        return 0
    zip_path = package(open_dir, a.out, a.tag, a.commit)
    print(zip_path)
    return 0
