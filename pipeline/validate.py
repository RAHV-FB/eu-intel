"""Offline checks of the normalized snapshot (data/snapshot/**) and, once built, of public/data.

    python -m pipeline validate            # the snapshot, and the built output if there is one
    python -m pipeline validate --built    # the same, but a missing built output is an error (CI, deploy, refresh)
    python -m pipeline validate --built --update-baseline
                                           # the same, then record its warnings in validate_baseline.json (refused
                                           # while there are errors)

Exit code 1 on any error or ratchet breach. Errors are structural problems of the snapshot (unreadable files, records
that do not match the schema in pipeline/models/entities.py, duplicate ids, malformed dates, a file missing or holding
fewer records than the manifest records for it or than a complete snapshot can, a count of sitting MEPs that a
complete list of current Members cannot give, an act linked to a procedure that cannot have adopted it), and claims in
the built output that contradict the rules or the files' own records (ERROR_CHECKS: an act shown on two files, a file
past adoption without Parliament's position, a file published or in force without an act, an adoption date on a file
shown before adoption, a transposition deadline before its act, a veto outside unanimity, a vote margin against its
outcome, one step reported twice in the activity feed, an activity item not citing the record it reports, ...); with
--built, also a built output that is incomplete or does not match the public data contract (src/types/data.ts,
pipeline/contract.py).

Every other finding has a class, and each class is one of three kinds:
- by design (BY_DESIGN): what the dataset's scope makes expected, e.g. votes on procedures outside it. Printed as
  INFO and not counted as warnings.
- integrity (INTEGRITY, and any class not classified): a fact on the site attached to the wrong record, or a join or
  checked correction the build relies on that no longer holds. A ratchet: validate fails on any integrity finding
  that pipeline/validate_baseline.json does not accept (`accepted`), whatever the count of its class.
- backlog (BACKLOG): gaps and anomalies of the sources, shown as recorded, that curation works through (dates to
  check against an act's text, official totals that differ from the recorded votes, ...). Counted against the
  baseline, never failing.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from pipeline.models import entities as E
from pipeline.models.countries import FORMER_MEMBER_STATES, MEMBER_STATES
from pipeline.snapshot import ROOT, SNAPSHOT

COUNTRIES = set(MEMBER_STATES) | set(FORMER_MEMBER_STATES)
# National measures notified as transposing a directive can be old national laws (e.g. a 19th-century code).
MIN_DATE = {("implementation", "measures"): "1800-01-01"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REF_RE = re.compile(r"^(\d{4})/(\d{4})\(([A-Z]{3})\)$")
CELEX_TYPE = {"R": "regulation", "L": "directive", "D": "decision", "H": "recommendation"}
# an act cited in a title by its type and number: "Directive 2014/90/EU", "Regulation (EU) 2024/1689", "Regulations
# (EC) No 300/2008, (EU) No 167/2013 and ...", "Council Framework Decisions 2002/584/JHA, 2003/577/JHA" (each number
# takes the type word before it)
CITED_TYPE_RE = re.compile(r"\b(Framework Decision|Regulation|Directive|Decision)s?\b")
CITED_NUMBER_RE = re.compile(
    r"\bNo (?P<n1>\d{1,4})/(?P<y1>\d{4})\b|\b(?P<y2>\d{4})/(?P<n2>\d{1,4})/(?:EU|EC|EEC|JHA|CFSP)\b|\) (?P<y3>\d{4})/(?P<n3>\d{1,4})\b"
)
CELEX_CITED_TYPE = {"R": "Regulation", "L": "Directive", "D": "Decision", "F": "Framework Decision"}
MAX_SITTING = 751  # Members of the European Parliament (Article 14(2) TEU)
MAX_NOT_SITTING = 0.05  # share of MEPs with an open political-group membership allowed not to be marked sitting
MAX_SHRINK = 0.05  # share of the records the manifest records for a file that the file may lack (as the fetch guards)
# Fewest records in each file of the committed snapshot, about half of what it holds today: a source module that wrote
# an emptied or truncated file and the manifest with it would pass the comparison with the manifest. Applied to the
# committed snapshot only (check's min_records); a file without an entry here has no floor.
MIN_RECORDS: dict[tuple[str, str], int] = {
    ("ep_people", "meps"): 600, ("ep_people", "orgs"): 300,
    ("ep_procedures", "procedures"): 800,
    ("ep_votes", "votes"): 15000, ("ep_votes", "ballots"): 1500,
    ("eurlex", "acts"): 600,
    ("council", "votes"): 350,
    ("implementation", "measures"): 30000, ("implementation", "infringements"): 3500,
    ("implementation", "coverage"): 250,
    ("train", "files"): 700,
    ("optouts", "directives"): 150, ("optouts", "regulations"): 8,
}  # fmt: skip
# Built lists that are never empty (activity.json can be, before the first recorded change).
BUILT_LISTS = [
    "dossiers/index.json", "votes/index.json", "votes/titles.json", "council/index.json", "people/meps.json",
    "people/groups.json", "people/parties.json", "countries/index.json", "topics.json", "search.json",
]  # fmt: skip
# meta.json counts and the snapshot file each is counted from: a count of zero is an error when that file has records;
# the first four are the file's own size, so they may not fall below it (the others are derived and can differ).
BUILT_COUNTS = {
    "legal_acts": ("eurlex", "acts"), "meps": ("ep_people", "meps"),
    "national_measures": ("implementation", "measures"), "infringements": ("implementation", "infringements"),
    "dossiers": ("ep_procedures", "procedures"), "ep_votes": ("ep_votes", "votes"),
    "council_votes": ("council", "votes"),
}  # fmt: skip
SAME_SIZE_COUNTS = ("legal_acts", "meps", "national_measures", "infringements")
PUBLIC_FILES = [
    "meta.json", "home.json", "dossiers/index.json", "votes/index.json", "votes/titles.json", "council/index.json",
    "people/meps.json", "people/groups.json", "people/parties.json", "countries/index.json",
    "topics.json", "search.json", "activity.json", "feeds/updates.xml", "open/datapackage.json",
]  # fmt: skip

# (source, file, model name, id function)
FILES: list[tuple[str, str, str, Callable[[Any], Any] | None]] = [
    ("ep_people", "meps", "Mep", lambda r: r.id),
    ("ep_people", "orgs", "Organization", lambda r: r.id),
    ("ep_procedures", "procedures", "Procedure", lambda r: r.id),
    ("ep_votes", "votes", "EpVote", lambda r: r.id),
    ("ep_votes", "ballots", "EpBallots", lambda r: r.vote_id),
    ("eurlex", "acts", "LegalAct", lambda r: r.celex),
    ("council", "votes", "CouncilVote", lambda r: r.id),
    ("implementation", "measures", "NationalMeasure", lambda r: r.id),
    ("implementation", "infringements", "InfringementCase", lambda r: r.id),
    ("implementation", "indicators", "CountryIndicator", lambda r: (r.country, r.indicator, r.period)),
    ("implementation", "coverage", "ImplementationCoverage", lambda r: r.celex),
    ("train", "files", "TrainFile", lambda r: r.url),
    ("optouts", "directives", "DirectiveOptOut", lambda r: r.celex),
    ("optouts", "regulations", "RegulationOptIn", lambda r: r.decision),
]


MANIFEST_KEY = "_manifest"  # errors_by_source key for an unreadable _manifest.json as a whole
BASELINE = Path(__file__).with_name("validate_baseline.json")  # warning counts the ratchet compares with

# The errors of the built output, by check: what each means (printed with the result).
ERROR_CHECKS = {
    "act-on-two-dossiers": "one act shown on two files: EUR-Lex and the EP give it different procedures (one law, "
    "one page)",
    "stage-without-parliament": "a file of the ordinary or consent procedure shown as adopted or later, with no "
    "position or decision of Parliament recorded (the act cannot be adopted without one)",
    "adopted-stage-behind": "a file with an adoption date shown at a stage before adoption",
    "deadline-before-act": "a transposition deadline shown that is earlier than the adoption of its act",
    "dossier-dates": "a file's claims that its own dates or steps contradict",
    "rapporteur": "a rapporteur linked to an MEP page that is not written, or listed twice in one role",
    "vote-margin": "a vote margin that the vote's outcome contradicts",
    "council-veto": "a single-state veto outside unanimity",
    "built-incomplete": "the built output is incomplete: a file missing or unreadable, a list empty, a count of zero "
    "or below the snapshot's",
    "contract": "built JSON that does not match the public data contract (src/types/data.ts)",
    "activity-duplicate": "one step of a file reported twice in the activity feed (the same day and title, or the same "
    "day and kind of step from another source's record)",
    "activity-source": "an activity item that does not cite the record it reports: a status change to a stage that an "
    "act establishes without the act's EUR-Lex record, a current status change without the record that gave the "
    "status, a step without the record of that step",
    "stage-without-act": "a file shown as published, in force or no longer in force with no act linked to it",
    "act-procedure-mismatch": "an act linked to a procedure of another kind or a number range no legislative "
    "procedure uses: the file would show it as its law (Cellar tags Council Decision (EU) 2020/2059 with 2020/3521(COD); "
    "drop such a link in data/curated/act_links.yaml, quoting the act's legal basis)",
    "open-data": "the open dataset (public/data/open) does not match its datapackage.json: a table's size or hash, its "
    "header, a value's type, a required value or an enumeration, a primary or foreign key, or a crosswalk identifier "
    "that its table does not list",
}
# Findings that the dataset's scope makes expected: printed as INFO, not counted as warnings.
BY_DESIGN = {
    "ref-procedure": "votes on procedures outside the dataset (own-initiative reports, resolutions, budget, discharge, "
    "non-legislative files), listed without a file page",
    "ref-mep": "rapporteurs of earlier parliamentary terms, not in meps.json: shown by name and group, without a page",
    "procedure-ref": "references that are not YYYY/NNNN(TYPE): split parts (2016/0224A), Parliament reports on a file "
    "(R, M) and Legislative Train files without a procedure type (NA)",
}
# Warning classes that gate (the ratchet): each means a fact on the site attached to the wrong record, or a join or a
# checked correction that the build relies on no longer holding. Any class not classified here or in BACKLOG gates too.
INTEGRITY = {
    "act-type": "an act whose type differs from its CELEX type letter: the site names the wrong kind of act",
    "amends-link-type": "an amendment link to an act that the title cites under another type (correct it in "
    "data/curated/act_relations.yaml)",
    "transposition-non-directive": "transposition deadlines or national measures on an act that is not a directive",
    "procedure-type": "a procedure whose type differs from its reference",
    "event-order": "a procedure's steps not in date order (the snapshot writes them sorted)",
    "future-event": "a step or vote dated after today, which the site would show as done",
    "ref-vote": "ballots of a vote that votes.json does not have",
    "ballots-missing": "a vote marked as having ballots, without them: its MEPs' positions are missing",
    "ballot-duplicate": "an MEP recorded with two positions in one vote",
    "ballot-mep": "ballots of MEPs that meps.json does not have: positions without their MEP",
    "ref-org": "memberships of a group, party or committee that orgs.json does not have",
    "country-code": "a country code that is not a Member State's",
    "act-relation-stale": "a checked correction (data/curated/act_relations.yaml) that no longer matches EUR-Lex, so it "
    "is not applied and the link it corrected is shown again",
    "act-link-stale": "a procedure link dropped in data/curated/act_links.yaml that EUR-Lex no longer records: the entry "
    "has nothing left to correct",
    "transposition-check-stale": "a checked transposition deadline (data/curated/transposition.yaml) that EUR-Lex no "
    "longer records, so it is not applied",
    "denmark-schengen-stale": "a recorded decision of Denmark (data/curated/denmark_schengen.yaml) on a directive whose "
    "recitals no longer say that Denmark decides",
    "report-off-timeline": "a key report of a file that no step of its built timeline carries",
    "contract-unlisted": "a built JSON file that src/types/data.ts gives no type, so the contract check skips it",
    "index-unlisted": "a built detail file that its folder's index does not list, which the site reaches only by a link "
    "(checked against its type all the same)",
    "schema": "a snapshot file whose model is not defined",
}
# Warning classes counted against the baseline but never failing: gaps and anomalies of the sources, shown as recorded,
# that curation works through.
BACKLOG = {
    "application-not-recorded": "acts whose general application date EUR-Lex does not record (curation: "
    "data/curated/act_dates.yaml)",
    "application-before-act": "application dates a year or more before the act: retroactive, or a Cellar error "
    "(curation: data/curated/act_dates.yaml)",
    "entry-into-force-before-act": "entry into force before the act or its publication (curation: act_dates.yaml)",
    "entry-into-force-rule": "entry into force that EUR-Lex's own rule contradicts (curation: act_dates.yaml)",
    "transposition-date-order": "a general transposition deadline taken by date order (curation: transposition.yaml)",
    "denmark-schengen-unchecked": "Denmark's decisions to record (curation: data/curated/denmark_schengen.yaml)",
    "ballot-totals": "official totals that differ from the recorded votes: facts, shown with a reconciliation note",
    "veto-wording": "'veto' in a Council vote's own text outside unanimity",
    "date-order": "dates of one record out of order, as the source records them",
    "date-range": "dates outside the plausible range, as the source records them",
    "group-overlap": "overlapping political-group memberships, as the EP records them",
    "manifest-count": "a file's record count differs from the manifest's (records re-derived offline)",
    "manifest": "no data/snapshot/_manifest.json",
    "public-missing": "built files missing without --built (an error with --built)",
}


def warning_kind(check: str) -> str:
    """'by design', 'backlog' or 'integrity' (also for a class not classified: it gates until classified)."""
    return "by design" if check in BY_DESIGN else "backlog" if check in BACKLOG else "integrity"


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        # source directory (or MANIFEST_KEY / "public") -> its structural errors; a manifest entry's
        # error counts for that entry's source
        self.errors_by_source: dict[str, list[str]] = defaultdict(list)
        self.errors_by_check: Counter[str] = Counter()  # ERROR_CHECKS name, or "snapshot (<source>)"
        self.warnings: dict[str, list[str]] = defaultdict(list)
        self.by_design: dict[str, list[str]] = defaultdict(list)  # BY_DESIGN findings, not counted as warnings
        self.info: list[str] = []
        self.unreadable: set[str] = set()  # built files reported as unreadable (once each)
        self.baseline: dict[str, int] | None = None  # set by apply_baseline
        self.breaches: list[str] = []  # integrity classes above their baseline
        self.ratchet_notes: list[str] = []  # classes below their baseline; integrity findings that replaced others

    def error(self, msg: str, source: str = "?", check: str | None = None) -> None:
        self.errors.append(msg)
        self.errors_by_source[source].append(msg)
        self.errors_by_check[check or f"snapshot ({source})"] += 1

    def warn(self, check: str, msg: str) -> None:
        (self.by_design if check in BY_DESIGN else self.warnings)[check].append(msg)

    def print(self, out=sys.stdout, examples: int = 5) -> None:
        for line in self.info:
            print(f"  {line}", file=out)
        for check in sorted(self.by_design):
            items = self.by_design[check]
            print(f"INFO [{check}] {len(items)} by design: {BY_DESIGN[check]}", file=out)
            for m in items[:2]:
                print(f"    - {m}", file=out)
        for check in sorted(self.warnings):
            items = self.warnings[check]
            base = "" if self.baseline is None else f", baseline {self.baseline.get(check, 0)}"
            print(f"WARNING [{check}] {len(items)} ({warning_kind(check)}{base})", file=out)
            for m in items[:examples]:
                print(f"    - {m}", file=out)
            if len(items) > examples:
                print(f"    … {len(items) - examples} more", file=out)
        for m in self.errors[:50]:
            print(f"ERROR {m}", file=out)
        if len(self.errors) > 50:
            print(f"ERROR … {len(self.errors) - 50} more errors", file=out)
        for m in self.breaches:
            print(f"RATCHET {m}", file=out)
        self.print_summary(out)

    def print_summary(self, out=sys.stdout) -> None:
        """The result, and what failed and why."""
        n_warn = sum(len(v) for v in self.warnings.values())
        n_integrity = sum(len(v) for k, v in self.warnings.items() if warning_kind(k) == "integrity")
        n_design = sum(len(v) for v in self.by_design.values())
        status = "FAILED" if self.errors or self.breaches else "OK"
        ratchet = "" if self.baseline is None else f", {len(self.breaches)} ratchet breaches"
        print(f"validate: {status} — {len(self.errors)} errors{ratchet}, {n_warn} warnings ({n_integrity} integrity, "
              f"{n_warn - n_integrity} backlog); {n_design} by-design findings not counted", file=out)  # fmt: skip
        for check, n in sorted(self.errors_by_check.items()):
            why = ERROR_CHECKS.get(check, "a structural problem of the snapshot")
            print(f"  failed: [{check}] {n} error{'s' if n > 1 else ''}: {why}", file=out)
        for m in self.breaches:
            print(f"  failed: ratchet {m}", file=out)
        for m in self.ratchet_notes:
            print(f"  note: {m}", file=out)


def cited_acts(title: str) -> dict[tuple[int, int], set[str]]:
    """(year, number) -> the types under which a title cites an act with that number."""
    marks = sorted([(m.start(), m) for m in CITED_TYPE_RE.finditer(title)] +
                   [(m.start(), m) for m in CITED_NUMBER_RE.finditer(title)], key=lambda x: x[0])  # fmt: skip
    out: dict[tuple[int, int], set[str]] = defaultdict(set)
    kind = None
    for _, m in marks:
        if m.re is CITED_TYPE_RE:
            kind = m.group(1)
        elif kind:
            y, n = next((m.group(f"y{i}"), m.group(f"n{i}")) for i in (1, 2, 3) if m.group(f"y{i}"))
            out[(int(y), int(n))].add(kind)
    return out


def _valid_date(s: str) -> bool:
    if not DATE_RE.match(s):
        return False
    try:
        date.fromisoformat(s)
    except ValueError:
        return False
    return True


def _load(snapshot: Path, source: str, name: str, model_name: str, rep: Report) -> list[BaseModel] | None:
    path = snapshot / source / f"{name}.json"
    if not path.exists():
        return None
    model: type[BaseModel] | None = getattr(E, model_name, None)
    if model is None:
        rep.warn("schema", f"{source}/{name}.json present but model {model_name} is not defined")
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        rep.error(f"{source}/{name}.json: unreadable JSON ({e})", source)
        return None
    if not isinstance(raw, list):
        rep.error(f"{source}/{name}.json: expected a JSON array", source)
        return None
    out: list[BaseModel] = []
    bad = 0
    for i, x in enumerate(raw):
        try:
            out.append(model.model_validate(x))
        except ValidationError as e:
            bad += 1
            if bad <= 5:
                first = e.errors()[0]
                rep.error(
                    f"{source}/{name}.json[{i}]: {'.'.join(map(str, first['loc']))}: {first['msg']}", source
                )
    if bad > 5:
        rep.error(f"{source}/{name}.json: {bad} invalid records in total", source)
    rep.info.append(f"{source}/{name}.json: {len(out)} records")
    return out


def check_size(
    snapshot: Path,
    source: str,
    name: str,
    n: int | None,
    recorded: dict[str, dict[str, int]],
    floors: dict[tuple[str, str], int],
    rep: Report,
) -> None:
    """A file that is missing, or holds more than MAX_SHRINK fewer records than its manifest entry records for it, or
    fewer than the floor for a complete snapshot, is an error of its source (an emptied or truncated file would
    otherwise be built and deployed as an empty section). `n` is None when `_load` read nothing."""
    count = recorded.get(source, {}).get(name) or 0
    floor = floors.get((source, name)) or 0
    if n is None:
        if (count or floor) and not (snapshot / source / f"{name}.json").exists():
            what = f"_manifest.json records {count} records" if count else f"a complete snapshot has at least {floor}"
            rep.error(f"{source}/{name}.json: file missing, but {what}", source)
    elif n < (1 - MAX_SHRINK) * count:
        rep.error(
            f"{source}/{name}.json: {n} records, but _manifest.json records {count} "
            f"(more than {MAX_SHRINK:.0%} fewer): an emptied or truncated file",
            source,
        )
    elif n < floor:
        rep.error(f"{source}/{name}.json: {n} records, fewer than the {floor} a complete snapshot has", source)
    if n is not None and count and n != count:  # e.g. records re-derived offline without rewriting the manifest
        rep.warn("manifest-count", f"{source}/{name}.json: {n} records, but _manifest.json records {count}")


def _dates(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """All (field path, value) pairs for date-like fields of a model dump."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, str) and (k in ("date", "start", "end", "started", "published", "last_updated",
                                             "notified", "latest_decision_date")
                                       or k.startswith("date_") or k in ("entry_into_force", "end_of_validity")):  # fmt: skip
                out.append((p, v))
            elif isinstance(v, list) and k in ("other_application_dates", "transposition_deadlines"):
                out += [(p, x) for x in v if isinstance(x, str)]
            elif isinstance(v, (dict, list)) and k != "source":
                out += _dates(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _dates(v, f"{path}[{i}]")
    return out


def check(
    snapshot: Path = SNAPSHOT,
    public: Path | None = None,
    today: str | None = None,
    built: bool = False,
    min_records: dict[tuple[str, str], int] | None = None,
) -> Report:
    """`built`: the built output must be complete (see check_built). `min_records`: the fewest records per
    (source, file); MIN_RECORDS for the committed snapshot, none for a test fixture."""
    rep = Report()
    today = today or date.today().isoformat()
    data: dict[tuple[str, str], list[Any]] = {}
    recorded: dict[str, dict[str, int]] = {}  # source -> the record counts its manifest entry gives
    # manifest
    man = snapshot / "_manifest.json"
    if man.exists():
        try:
            raw = json.loads(man.read_text(encoding="utf-8"))
            for k, v in raw.items():
                try:
                    recorded[str(k)] = E.SourceStatus.model_validate(v).records
                except ValidationError as e:
                    rep.error(f"_manifest.json[{k}]: {e.errors()[0]['msg']}", str(k))
        except (OSError, json.JSONDecodeError, AttributeError) as e:
            rep.error(f"_manifest.json unreadable ({e})", MANIFEST_KEY)
    else:
        rep.warn("manifest", "data/snapshot/_manifest.json missing")
    # schema + duplicates + date format
    for source, name, model_name, key in FILES:
        recs = _load(snapshot, source, name, model_name, rep)
        check_size(snapshot, source, name, None if recs is None else len(recs), recorded, min_records or {}, rep)
        if recs is None:
            continue
        data[(source, name)] = recs
        if key:
            dup = [k for k, n in Counter(key(r) for r in recs).items() if n > 1]
            for k in dup[:20]:
                rep.error(f"{source}/{name}.json: duplicate id {k!r}", source)
            if len(dup) > 20:
                rep.error(f"{source}/{name}.json: {len(dup)} duplicate ids in total", source)
        for r in recs:
            for p, v in _dates(r.model_dump(mode="json")):
                if not _valid_date(v[:10]) or (len(v) > 10 and not v[10] == "T"):
                    rep.error(
                        f"{source}/{name}.json {key(r) if key else '?'}: malformed date {p}={v!r}", source
                    )
                elif not ((MIN_DATE.get((source, name), "1950-01-01")) <= v[:10] <= "2100-12-31"):
                    rep.warn("date-range", f"{source}/{name} {key(r) if key else '?'}: {p}={v}")

    meps = {m.id: m for m in data.get(("ep_people", "meps"), [])}
    orgs = {o.id: o for o in data.get(("ep_people", "orgs"), [])}
    procs = data.get(("ep_procedures", "procedures"), [])
    proc_refs = {p.reference for p in procs}
    proc_by_ref = {p.reference: p for p in procs}
    votes = {v.id: v for v in data.get(("ep_votes", "votes"), [])}
    ballots = data.get(("ep_votes", "ballots"), [])
    acts = {a.celex: a for a in data.get(("eurlex", "acts"), [])}
    from pipeline.analysis.transposition import article_label, general_deadline_basis
    from pipeline.analysis.transposition import classify as classify_transposition
    from pipeline.build import (
        apply_transposition_checks,
        load_act_dates,
        load_act_links,
        load_act_relations,
        load_denmark_schengen,
        load_transposition_checks,
    )

    act_dates = load_act_dates()  # curated, checked corrections of act dates
    tr_checks = load_transposition_checks()  # curated, checked general transposition deadlines

    # people
    for m in meps.values():
        if m.country not in COUNTRIES:
            rep.warn("country-code", f"MEP {m.id}: country {m.country!r}")
        for ms in m.memberships:
            if orgs and ms.org_id not in orgs and ms.kind in ("group", "party", "committee"):
                rep.warn("ref-org", f"MEP {m.id}: membership org {ms.org_id} not in orgs.json")
            if ms.start and ms.end and ms.end < ms.start:
                rep.warn(
                    "date-order", f"MEP {m.id}: membership {ms.org_id} ends {ms.end} before start {ms.start}"
                )
        spans = sorted((x.start or "", x.end or "9999-12-31") for x in m.memberships if x.kind == "group")
        for (_s1, e1), (s2, _e2) in zip(spans, spans[1:], strict=False):
            if s2 <= e1:
                rep.warn("group-overlap", f"MEP {m.id}: overlapping political-group memberships around {s2}")
                break
    # Sitting MEPs (`active`, from the EP's list of current Members): a short list would show the Members it
    # lacks as no longer sitting. Members holding an open political-group membership are sitting, and no more
    # than 751 can sit (Article 14(2) TEU: "seven hundred and fifty in number, plus the President").
    in_group = [m for m in meps.values() if any(x.kind == "group" and x.end is None for x in m.memberships)]
    not_sitting = [m.id for m in in_group if not m.active]
    sitting = sum(1 for m in meps.values() if m.active)
    if len(not_sitting) > MAX_NOT_SITTING * len(in_group) or sitting > MAX_SITTING:
        rep.error(
            f"ep_people/meps.json: {sitting} MEPs marked as sitting (at most {MAX_SITTING} seats)"
            if sitting > MAX_SITTING
            else f"ep_people/meps.json: {sitting} MEPs marked as sitting, but {len(not_sitting)} of the "
            f"{len(in_group)} holding an open political-group membership are not (e.g. {not_sitting[:3]})",
            "ep_people",
        )
    # procedures
    for p in procs:
        if not REF_RE.match(p.reference):
            rep.warn("procedure-ref", f"procedure {p.id}: unusual reference {p.reference!r}")
        elif REF_RE.match(p.reference).group(3) != p.type:  # type: ignore[union-attr]
            rep.warn(
                "procedure-type", f"procedure {p.id}: type {p.type} differs from reference {p.reference}"
            )
        dates = [e.date for e in p.events]
        if dates != sorted(dates):
            rep.warn("event-order", f"procedure {p.id}: events not sorted by date")
        for e in p.events:
            if e.date > today:
                rep.warn("future-event", f"procedure {p.id}: event {e.id} dated {e.date} (after today)")
        for r in p.rapporteurs:
            if r.mep_id and meps and r.mep_id not in meps:
                rep.warn("ref-mep", f"procedure {p.id}: rapporteur {r.mep_id} not in meps.json")
    # votes + ballots
    ballot_ids = set()
    for b in ballots:
        ballot_ids.add(b.vote_id)
        v = votes.get(b.vote_id)
        if v is None:
            rep.warn("ref-vote", f"ballots for unknown vote {b.vote_id}")
            continue
        recorded = b.favor + b.against + b.abstain
        dup = [k for k, n in Counter(recorded).items() if n > 1]
        if dup:
            rep.warn("ballot-duplicate", f"vote {v.id}: {len(dup)} MEPs recorded with more than one position")
        missing = [i for i in recorded if meps and i not in meps]
        if missing:  # not ref-mep (by design, for rapporteurs of earlier terms): ballots are of the terms covered
            rep.warn(
                "ballot-mep", f"vote {v.id}: {len(missing)} ballot MEP ids not in meps.json (e.g. {missing[0]})"
            )
        if v.n_for is not None and (len(b.favor), len(b.against), len(b.abstain)) != (
            v.n_for,
            v.n_against,
            v.n_abstain,
        ):
            rep.warn("ballot-totals", f"vote {v.id} {v.date}: recorded {len(b.favor)}/{len(b.against)}/"
                     f"{len(b.abstain)} vs official {v.n_for}/{v.n_against}/{v.n_abstain}")  # fmt: skip
    for v in votes.values():
        if v.has_ballots and ballots and v.id not in ballot_ids:
            rep.warn("ballots-missing", f"vote {v.id}: has_ballots but no ballots record")
        if v.date > today:
            rep.warn("future-event", f"vote {v.id} dated {v.date}")
        for r in v.procedure_refs:
            if procs and r not in proc_refs:
                rep.warn("ref-procedure", f"vote {v.id}: procedure {r} not in procedures.json")
    # acts
    relation_fixes = {(f["act"], f["replace"]) for f in load_act_relations()}  # curated, checked amendment links
    for f in load_act_relations():
        if f["act"] in acts and f["replace"] not in acts[f["act"]].amends:
            rep.warn("act-relation-stale", f"{f['act']}: data/curated/act_relations.yaml replaces its link to "
                     f"{f['replace']}, which EUR-Lex no longer records")  # fmt: skip
    dropped_links = load_act_links()  # curated: procedure links that the act's own text rules out
    for c, refs in sorted(dropped_links.items()):
        for r in sorted(refs):
            if c in acts and r not in {re.sub(r"\s+", "", x).upper() for x in acts[c].procedure_refs}:
                rep.warn("act-link-stale", f"{c}: data/curated/act_links.yaml drops its link to {r}, which EUR-Lex no "
                         "longer records")  # fmt: skip
    # Denmark decides under Protocol No 22, Art. 4, whether to implement a directive building upon the Schengen acquis
    # (its recitals: optouts schengen_art4); its decision, notified to the Council, is recorded once checked
    optouts = {r.celex: r for r in data.get(("optouts", "directives"), [])}
    decisions = load_denmark_schengen()
    for c in sorted(decisions):
        if c in optouts and "DK" not in optouts[c].schengen_art4:
            rep.warn("denmark-schengen-stale", f"{c}: data/curated/denmark_schengen.yaml records Denmark's decision, "
                     "but the directive's recitals as read do not say that Denmark decides under Protocol No 22, Art. 4")  # fmt: skip
    for r in optouts.values():
        if "DK" in r.schengen_art4 and r.celex not in decisions:
            rep.warn("denmark-schengen-unchecked", f"{r.celex}: Denmark decides under Protocol No 22, Art. 4, whether to "
                     "implement it; record its decision, once notified, in data/curated/denmark_schengen.yaml")  # fmt: skip
    for a in acts.values():
        # Cellar links the act to an act whose number its title cites under another type only (the AI Act, 32024R1689,
        # to Implementing Regulation (EU) No 90/2014, 32014R0090, for Directive 2014/90/EU): check the text and
        # correct the link in data/curated/act_relations.yaml
        cited = cited_acts(a.title)
        for c in a.amends:
            cm = re.fullmatch(r"3(\d{4})([RLDF])(\d{4})", c)
            if not cm:
                continue
            kind, key = CELEX_CITED_TYPE[cm.group(2)], (int(cm.group(1)), int(cm.group(3)))
            if cited.get(key) and kind not in cited[key] and (a.celex, c) not in relation_fixes:
                rep.warn("amends-link-type", f"{a.celex}: EUR-Lex links it as amending {c}, but its title cites "
                         f"{'/'.join(sorted(cited[key]))} {key[0]}/{key[1]}, not a {kind.lower()}")  # fmt: skip
        m = re.match(r"^\d(\d{4})([A-Z])", a.celex)
        if m and CELEX_TYPE.get(m.group(2)) and CELEX_TYPE[m.group(2)] != a.act_type:
            rep.warn("act-type", f"{a.celex}: act_type {a.act_type} but CELEX type letter {m.group(2)}")
        if a.transposition_deadlines and a.act_type != "directive":
            rep.warn("transposition-non-directive", f"{a.celex} ({a.act_type}) has transposition deadlines")
        if a.date_publication and a.date_document and a.date_publication < a.date_document:
            rep.warn(
                "date-order",
                f"{a.celex}: published {a.date_publication} before document date {a.date_document}",
            )
        if a.other_application_dates != sorted(a.other_application_dates):
            rep.warn("date-order", f"{a.celex}: other_application_dates not ascending")
        # Retroactive application exists (e.g. from 1 January of a budget year), but a date a year or
        # more before the act is more often a Cellar error (DSA: 2022-02-17 for 2024-02-17): check the
        # act's text and, if wrong, correct it in data/curated/act_dates.yaml.
        signed = a.date_signature or a.date_document
        if signed and a.celex not in act_dates:
            for d in a.other_application_dates:
                if d < f"{int(signed[:4]) - 1}{signed[4:]}":
                    rep.warn("application-before-act", f"{a.celex}: applies from {d}, a year or more before "
                             f"the act ({signed}); check the act's text")  # fmt: skip
        # An act does not enter into force before it is adopted, and a regulation (published in the Official
        # Journal) normally not before its publication; a decision or directive addressed to the Member States
        # can take effect on adoption or notification, so those stay quiet. Cellar sometimes gives the date the
        # act applies from instead, or that of another act its entry into force is tied to (Regulation
        # 2021/768, Art. 9). Once checked, record the date in data/curated/act_dates.yaml.
        eif = a.entry_into_force
        if eif and a.celex not in act_dates and not a.entry_into_force_pending:
            if a.date_document and eif < a.date_document:
                rep.warn("entry-into-force-before-act", f"{a.celex}: enters into force {eif}, before the act "
                         f"({a.date_document}); check the act's text")  # fmt: skip
            elif a.act_type == "regulation" and a.date_publication and eif < a.date_publication:
                rep.warn("entry-into-force-before-act", f"{a.celex}: regulation enters into force {eif}, before "
                         f"its publication ({a.date_publication}); check the act's text")  # fmt: skip
        # Cellar's own rule for the date ("DATPUB +20": the twentieth day following publication) and the date it
        # records disagree: one of them is wrong (32017D1324: 2017-08-08 for 18.7.2017 + 20 days; 32019R0503: "+20"
        # where its Art. 8(1) says the day following publication). Check the act's text; record a wrong date, or
        # that the date is right, in data/curated/act_dates.yaml.
        n = a.entry_into_force_after_publication
        if eif and n is not None and a.date_publication and a.celex not in act_dates:
            expected = (date.fromisoformat(a.date_publication) + timedelta(days=n)).isoformat()
            if eif != expected:
                rep.warn("entry-into-force-rule", f"{a.celex}: enters into force {eif}, but EUR-Lex's rule (publication "
                         f"{a.date_publication} + {n} days) gives {expected}; check the act's text")  # fmt: skip
        # EUR-Lex gives the date from which the act in general applies as not recorded (1001-01-01): the act leaves it
        # to a later decision, notice or event. Once the act's text and that decision are checked, record the date
        # (or what the text provides) in data/curated/act_dates.yaml.
        general = next((x for x in a.application_unrecorded if not x.partial), None)
        if general and a.celex not in act_dates and a.in_force:
            refers = f" (it refers to {', '.join(article_label(r) for r in general.articles)})" if general.articles else ""
            rep.warn("application-not-recorded", f"{a.celex}: EUR-Lex records no date from which it applies in "
                     f"general{refers}; check the act's text")  # fmt: skip
        # Several transposition deadlines whose general one neither the article references nor a check of the
        # text decides: the earliest is taken, which is wrong when it is a derogation for a few provisions
        # (Directive (EU) 2024/1640). Check the act's text and record it in data/curated/transposition.yaml.
        if a.act_type == "directive" and a.transposition_deadlines:
            e = tr_checks.get(a.celex)
            checked = apply_transposition_checks(a, e)
            if e and checked.transposition_checked is None:
                rep.warn("transposition-check-stale", f"{a.celex}: data/curated/transposition.yaml names a date "
                         f"EUR-Lex does not record for the act ({', '.join(a.transposition_deadlines)})")  # fmt: skip
            for x in (e or {}).get("amends") or []:  # the deadlines covering its changes to another directive
                if not {x["deadline"], *(f["date"] for f in x.get("further") or [])} <= set(a.transposition_deadlines):
                    rep.warn("transposition-check-stale", f"{a.celex}: data/curated/transposition.yaml amends "
                             f"{x['celex']} names a date EUR-Lex does not record for the act")  # fmt: skip
            deadlines = [x.date for x in classify_transposition(checked) if x.kind in ("deadline", "further_deadline")]
            if general_deadline_basis(checked) == "date_order":
                rep.warn("transposition-date-order", f"{a.celex}: general deadline {deadlines[0]} taken by date "
                         f"order among {', '.join(deadlines)}; check the act's text")  # fmt: skip
        for r in a.procedure_refs:
            rm = REF_RE.match(r)
            if not rm:
                rep.warn("procedure-ref", f"{a.celex}: unusual procedure reference {r!r}")
                continue
            ptype, num = rm.group(3), int(rm.group(2))
            if re.sub(r"\s+", "", r).upper() in dropped_links.get(a.celex, set()):
                continue  # the build drops the link (data/curated/act_links.yaml)
            # an error of EUR-Lex's data: the refresh restores the source's last good files (validate --list-failing)
            if ptype in ("COD", "CNS") and num >= 2000:
                rep.error(f"eurlex/acts.json: {a.celex} ({a.act_type}) linked to {r}: number range is not used for "
                          "legislative procedures", "eurlex", "act-procedure-mismatch")  # fmt: skip
            p = proc_by_ref.get(r)
            if p is not None and p.type != ptype:
                rep.error(f"eurlex/acts.json: {a.celex} linked to {r} but the procedure type is {p.type}", "eurlex",
                          "act-procedure-mismatch")  # fmt: skip
    # council
    for cv in data.get(("council", "votes"), []):
        for c in cv.positions:
            if c not in COUNTRIES:
                rep.warn("country-code", f"council vote {cv.id}: position for {c!r}")
        text = " ".join([cv.title, *cv.statements]).lower()
        if cv.voting_rule != "unanimity" and re.search(r"\bveto", text):
            rep.warn("veto-wording", f"council vote {cv.id}: 'veto' wording but voting rule {cv.voting_rule}")
        for r in cv.procedure_refs:
            if procs and r not in proc_refs:
                rep.warn("ref-procedure", f"council vote {cv.id}: procedure {r} not in procedures.json")
    # implementation
    for nm in data.get(("implementation", "measures"), []):
        if nm.country not in COUNTRIES:
            rep.warn("country-code", f"measure {nm.id}: country {nm.country!r}")
        if not re.match(r"^3\d{4}L\d+", nm.directive_celex):
            rep.warn(
                "transposition-non-directive",
                f"measure {nm.id}: {nm.directive_celex} is not a directive CELEX",
            )
        a = acts.get(nm.directive_celex)
        if a is not None and a.act_type != "directive":
            rep.warn("transposition-non-directive", f"measure {nm.id}: act {a.celex} is a {a.act_type}")
    for ic in data.get(("implementation", "infringements"), []):
        if ic.country not in COUNTRIES:
            rep.warn("country-code", f"infringement {ic.id}: country {ic.country!r}")
    # train
    for t in data.get(("train", "files"), []):
        for r in t.procedure_refs:
            if not REF_RE.match(r):
                rep.warn("procedure-ref", f"train file {t.url}: unusual reference {r!r}")

    # built output (optional): derived claims must respect the rules too
    if public is not None and public.exists():
        docs: dict[str, Any] = {}  # the public files read so far (None: unreadable, reported once)
        if built:
            check_built(public, data, rep, docs)
        else:
            for f in PUBLIC_FILES:
                if not (public / f).exists():
                    rep.warn("public-missing", f"public/data/{f} missing (run `python -m pipeline build`)")
        if (public / "council" / "index.json").exists():
            for cv in _public_json(public, "council/index.json", rep, docs) or []:
                a = cv.get("assessment") or {}
                if a.get("single_state_veto_possible") and cv.get("voting_rule") != "unanimity":
                    rep.error(
                        f"public council/index.json {cv['id']}: single-state veto outside unanimity", "public",
                        "council-veto",
                    )  # fmt: skip
        if (public / "activity.json").exists():
            items = _public_json(public, "activity.json", rep, docs) or []
            dossier, kind_of = _activity_context(public, rep, docs, data, today)
            for msg in activity_duplicates(items, kind_of):
                rep.error(f"public activity.json: {msg}", "public", "activity-duplicate")
            for msg in activity_sources(items, dossier, today):
                rep.error(f"public activity.json: {msg}", "public", "activity-source")
        owners: dict[str, list[str]] = {}
        for f in sorted((public / "dossiers").glob("*.json")):
            if f.name != "index.json":
                d = _public_json(public, f"dossiers/{f.name}", rep)
                if d is None:
                    continue
                for msg in dossier_contradictions(d):
                    rep.error(f"public dossiers/{f.name}: {msg}", "public", "dossier-dates")
                for msg in rapporteur_problems(d, public):
                    rep.error(f"public dossiers/{f.name}: {msg}", "public", "rapporteur")
                for name, msg in dossier_invariants(d):
                    rep.error(f"public dossiers/{f.name}: {msg}", "public", name)
                # a key report that no step carries has no tabling or vote of its own on the timeline
                steps = {x["id"] for e in d.get("timeline", []) for x in e.get("docs", [])}
                for doc in d.get("documents") or []:
                    if doc.get("kind") == "report" and doc["id"] not in steps:
                        rep.warn("report-off-timeline", f"dossier {d['id']}: key document {doc['id']} is on no timeline step")
                for c in d.get("celex") or []:
                    owners.setdefault(c, []).append(d["id"])
                for v in d.get("ep_votes") or []:
                    for msg in margin_contradictions(v):
                        rep.error(f"public dossiers/{f.name}: {msg}", "public", "vote-margin")
        # one law, one page: an act shown on two files means EUR-Lex and the EP disagree on its procedure (2 Nov 2026:
        # Decision (EU) 2026/2402 of 2025/0380(COD) also shown on 2025/0177(COD))
        for c, ids in sorted(owners.items()):
            if len(ids) > 1:
                rep.error(f"public dossiers: {c} is shown on {', '.join(ids)}; check which procedure adopted it",
                          "public", "act-on-two-dossiers")  # fmt: skip
        for f in sorted((public / "votes").glob("*.json")):
            recs = _public_json(public, f"votes/{f.name}", rep)
            if recs is None:
                continue
            for v in recs if isinstance(recs, list) else [recs]:
                for msg in margin_contradictions(v):
                    rep.error(f"public votes/{f.name}: {msg}", "public", "vote-margin")
    return rep


def _activity_context(
    public: Path, rep: Report, docs: dict[str, Any], data: dict[tuple[str, str], list[Any]], today: str
) -> tuple[Callable[[str | None], dict | None], Callable[[dict], str | None]]:
    """For the activity checks: the built file of a dossier id, and the kind of the step an activity item reports (on
    the file's timeline, else as its id or its procedure's event of that id gives it: activity.step_kind)."""
    from pipeline.analysis.activity import step_key, step_kind

    events = {p.id: {e.id: e.kind.value for e in p.events} for p in data.get(("ep_procedures", "procedures"), [])}

    def dossier(pid: str | None) -> dict | None:
        rel = f"dossiers/{pid}.json"
        return _public_json(public, rel, rep, docs) if pid and (public / rel).exists() else None

    def kind_of(it: dict) -> str | None:
        key = step_key(it.get("id") or "")
        pid = it.get("dossier_id")
        return step_kind(key, dossier(pid), today, events.get(pid or "")) if key else None

    return dossier, kind_of


def _public_json(public: Path, rel: str, rep: Report, cache: dict[str, Any] | None = None) -> Any:
    """A built JSON file, or None if it cannot be read (reported as an error, once per file)."""
    if cache is not None and rel in cache:
        return cache[rel]
    try:
        doc = json.loads((public / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if rel not in rep.unreadable:
            rep.unreadable.add(rel)
            rep.error(f"public {rel}: unreadable JSON ({e})", "public", "built-incomplete")
        doc = None
    if cache is not None:
        cache[rel] = doc
    return doc


def check_built(public: Path, data: dict[tuple[str, str], list[Any]], rep: Report, docs: dict[str, Any]) -> None:
    """The built output of a complete build (`validate --built`, after `pipeline build`). Nothing in a build from an
    emptied or partial snapshot contradicts itself, so it is checked for what it must hold: every PUBLIC_FILES entry
    present and readable, the lists that are never empty not empty, the counts of meta.json not zero when the snapshot
    has records of that kind (nor below the snapshot's size, for the counts that are its size), and every detail file
    that the dossier and vote indexes list written. `data`: the snapshot records read by check()."""
    def incomplete(msg: str) -> None:
        rep.error(msg, "public", "built-incomplete")

    for f in PUBLIC_FILES:
        if not (public / f).exists():
            incomplete(f"public/data/{f} is missing (run `python -m pipeline build`)")
        elif f.endswith(".xml"):
            try:
                ET.parse(public / f)
            except (OSError, ET.ParseError) as e:
                incomplete(f"public {f}: unreadable XML ({e})")
        else:
            _public_json(public, f, rep, docs)
    for f in BUILT_LISTS:
        if docs.get(f) is not None and not (isinstance(docs[f], list) and docs[f]):
            incomplete(f"public {f}: not a list with records (the build found none; check data/snapshot)")
    if docs.get("home.json") is not None and not (isinstance(docs["home.json"], dict) and docs["home.json"]):
        incomplete("public home.json: empty")
    # the titles of the MEP and group vote tables are the index's votes, in its order (the pages look them up by id)
    index, titles = docs.get("votes/index.json"), docs.get("votes/titles.json")
    if isinstance(index, list) and isinstance(titles, list):
        listed = [e.get("id") if isinstance(e, dict) else None for e in index]
        titled = [e.get("id") if isinstance(e, dict) else None for e in titles]
        if listed != titled:
            absent, extra = set(listed) - set(titled), set(titled) - set(listed)
            how = f"{len(titled)} entries against {len(listed)}"
            if absent:
                how += f", {len(absent)} missing (e.g. {sorted(absent, key=str)[:3]})"
            if extra:
                how += f", {len(extra)} not in the index (e.g. {sorted(extra, key=str)[:3]})"
            if not (absent or extra) and len(titled) == len(listed):
                how += ", in another order"
            incomplete(f"public votes/titles.json: not the votes of votes/index.json in its order ({how})")
    meta = docs.get("meta.json")
    if meta is not None:
        counts = meta.get("counts") if isinstance(meta, dict) else None
        if not isinstance(counts, dict):
            incomplete("public meta.json: no counts")
        else:
            for key, (source, name) in BUILT_COUNTS.items():
                have, n = len(data.get((source, name), [])), counts.get(key)
                if not isinstance(n, int):
                    incomplete(f"public meta.json: count {key!r} is {n!r}")
                elif have and n == 0:
                    incomplete(f"public meta.json: count {key!r} is 0, but {source}/{name}.json has {have} records")
                elif key in SAME_SIZE_COUNTS and n < (1 - MAX_SHRINK) * have:
                    incomplete(f"public meta.json: count {key!r} is {n}, but {source}/{name}.json has {have} records")
    for index, folder, key in LISTED_FILES:
        entries = _public_json(public, index, rep, docs) if (public / index).exists() else None
        if isinstance(entries, list):
            missing = [e[key] for e in entries if isinstance(e, dict) and not (public / folder / f"{e.get(key)}.json").exists()]
            if missing:
                incomplete(f"public {index}: {len(missing)} of {len(entries)} listed files not written (e.g. {missing[:3]})")
    check_contract(public, rep, docs)
    if (public / "open" / "datapackage.json").exists():  # missing: reported above (PUBLIC_FILES)
        from pipeline.analysis.opendata import check as check_open_data

        for msg in check_open_data(public / "open"):
            rep.error(f"public open/{msg}", "public", "open-data")


# The detail files that an index lists: (index, folder, key of the file name)
LISTED_FILES = [
    ("dossiers/index.json", "dossiers", "id"), ("votes/index.json", "votes", "id"),
    ("people/meps.json", "people/meps", "id"), ("people/groups.json", "people/groups", "id"),
    ("people/parties.json", "people/parties", "id"), ("countries/index.json", "countries", "code"),
]  # fmt: skip


def check_contract(public: Path, rep: Report, docs: dict[str, Any]) -> None:
    """Every built file that src/types/data.ts gives a type, against that type (pipeline/contract.py): one error per
    kind of violation, with its count and a file that has it. A built JSON file it gives no type is a warning."""
    from pipeline.contract import Contract, ContractError, check_public

    try:
        contract = Contract.load()
    except (OSError, ContractError, KeyError) as e:
        rep.error(f"src/types/data.ts: cannot be read as the public data contract ({e!r})", "public", "contract")
        return

    def read(rel: str) -> Any:  # the files read before from the cache; the others read here, and not kept
        return _public_json(public, rel, rep, docs if rel in docs else None) if (public / rel).exists() else None

    try:
        problems = check_public(public, contract, read)
    except ContractError as e:
        rep.error(f"src/types/data.ts: cannot be read as the public data contract ({e})", "public", "contract")
        return
    for line in problems.lines():
        rep.error(f"public {line}", "public", "contract")
    for pattern in contract.files:  # checked against their type above, but which no index lists
        for rel in contract.unlisted(public, read, pattern):
            rep.warn("index-unlisted", f"public/data/{rel}: not listed in its folder's index ({pattern})")
    covered = re.compile("(?:" + "|".join(re.sub(r"<\w+>", "[^/]+", re.escape(p)) for p in contract.files) + ")")
    for f in sorted(public.rglob("*.json")):
        rel = f.relative_to(public).as_posix()
        if not covered.fullmatch(rel):
            rep.warn("contract-unlisted", f"public/data/{rel}: no type in the file list of src/types/data.ts")


ADOPTION_STEPS = ("council_adoption", "signature", "publication")
# Parliament's decision on the Council's position at second reading, as timelines title it (ep_procedures)
SECOND_READING_TITLE = re.compile(r"Parliament (?:approved|amended|rejected) the Council's position at second reading")


def dossier_contradictions(d: dict) -> list[str]:
    """Claims of a built dossier that its own dates contradict."""
    out = []
    since = (d.get("status") or {}).get("since")
    if d.get("stage") == "withdrawn":
        later = [e["date"] for e in d.get("timeline", []) if e.get("kind") in ADOPTION_STEPS and since and e["date"] > since]
        if d.get("celex") or d.get("adopted") or later:
            out.append(f"withdrawn since {since}, but an act is recorded (celex {d.get('celex')}, adopted "
                       f"{d.get('adopted')}, adoption steps on {', '.join(later) or 'none'})")  # fmt: skip
        if since and d.get("started") and since < d["started"]:
            out.append(f"withdrawn on {since}, before the proposal of {d['started']}")
    if d.get("adopted") and d.get("published") and d["adopted"] > d["published"]:
        out.append(f"adopted on {d['adopted']}, after its publication on {d['published']}")
    # one Council adoption of the act per day (a procedural vote of the same day is not one), and no signature
    # before it (2017/0329(COD): the EP's "Final act signed" of 11 Apr 2018, before the Council's adoption)
    adoptions = Counter(e["date"] for e in d.get("timeline", []) if e.get("kind") == "council_adoption")
    out += [f"{n} Council adoption steps on {day}" for day, n in sorted(adoptions.items()) if n > 1]
    signed = [e["date"] for e in d.get("timeline", []) if e.get("kind") == "signature"]
    if signed and adoptions and min(signed) < max(adoptions):
        out.append(f"signed on {min(signed)}, before the Council's adoption step of {max(adoptions)}")
    if d.get("type") == "COD" and len(d.get("celex") or []) <= 1:
        # the act of an ordinary procedure is adopted once (2014/0174(COD): OEIL's 13 July and 6 October 2015 for one
        # "decision of the Council of 18 September 2015"), and not by the Council before Parliament's second reading,
        # which is on the Council's first-reading position (2018/0202(COD): OEIL 21 April 2021, second reading 27 April)
        if len(adoptions) > 1:
            out.append(f"Council adoption steps on {len(adoptions)} days: {', '.join(sorted(adoptions))}")
        second = [e["date"] for e in d.get("timeline", []) if SECOND_READING_TITLE.fullmatch(e.get("title") or "")]
        early = sorted(day for day in adoptions if second and day < min(second))
        if early:
            out.append(f"Council adoption step of {early[0]}, before Parliament's second reading of {min(second)}")
    # steps of one day in procedural order (build.day_rank): a trilogue after Parliament's decisions of the day
    # (2025/0132(COD), 17 Dec 2025), a second-reading step after the Council's first-reading position (2018/0136(COD))
    tl = d.get("timeline", [])
    for i, e in enumerate(tl):
        later = {x.get("kind") for x in tl[i + 1 :] if x.get("date") == e.get("date")}
        if e.get("title") == "Negotiation meeting with the Council (trilogue)" and later & {
            "negotiation_mandate", "plenary_vote", "ep_position"}:  # fmt: skip
            out.append(f"trilogue listed before Parliament's decision of {e['date']}")
        if "council_position" in later and re.search(r"(?<!early )\bsecond[ -]reading\b", e.get("title") or ""):
            out.append(f"second-reading step listed before the Council's position of {e['date']}")
    return out


POST_ADOPTION = ("adopted", "published", "in_force", "takes_effect_on_notification", "no_longer_in_force")
# The stages that an act in our EUR-Lex data establishes (status._acts_stage; activity.ACT_STAGES)
ACT_ESTABLISHED = ("published", "in_force", "takes_effect_on_notification", "no_longer_in_force")
# Procedures whose act cannot be adopted without Parliament: its position (Art. 294 TFEU) or its consent. Consultation
# files are not held to it: OEIL lists as CNS some acts whose legal basis requires no opinion (2020/0209(CNS), tariff
# quotas under Art. 31 TFEU, adopted with none), and NLE files are shown only because EUR-Lex gives them as CNS/APP.
NEEDS_PARLIAMENT = ("COD", "APP")
DEADLINE_KINDS = ("deadline", "further_deadline")


def activity_duplicates(items: list[dict], kind_of: Callable[[dict], str | None] | None = None) -> list[str]:
    """Published activity items that report one step of a file twice: the same file, day and title (2025/0177(COD), 5
    Nov 2026: its signature on 21 October recorded with Decision (EU) 2026/2402, another file's act, and again with
    Directive (EU) 2026/2383), or the same file, day and kind of step (`kind_of`: the kind of the step a step item
    reports), the step reported again from another source's record (2025/0232(COD): the act's publication on 30
    October and the EP's record of it; 2023/0134(COD): OEIL's Council adoption on 26 October and the Council's voting
    result ST 14946/26). Never across files: twin files share their titles and move together (2021/0068 and
    2021/0071(COD), the EU Digital COVID Certificate for citizens and for third-country nationals). Checked on the data
    that is deployed; the data tests run on frozen data (tests/frozen-data.txt)."""
    from pipeline.analysis.activity import SNAPSHOT_EVENT_KINDS

    seen: dict[tuple[str, ...], str] = {}
    out: list[str] = []
    for it in items:
        pid, day = it.get("dossier_id") or "", it.get("date") or ""
        keys = [("title", pid, day, it.get("title") or "")]
        if kind_of is not None and pid and (kind := kind_of(it)) in SNAPSHOT_EVENT_KINDS:
            keys.append(("step", pid, day, kind))
        hit = next((k for k in keys if k in seen), None)
        if hit:
            out.append(f"{it.get('id')} repeats {seen[hit]} ({day}: {hit[3][:80]})")
        for k in keys:
            seen.setdefault(k, it.get("id") or "")
    return out


def activity_sources(items: list[dict], dossier: Callable[[str | None], dict | None], today: str) -> list[str]:
    """Activity items that do not cite the record they report (plan 1.2(d), docs/ASSESSMENT_2026-11.md): a status
    change to a stage that an act establishes (published, in force, ...) must cite the act's EUR-Lex record; a status
    change to the file's current status, the record that gave it (activity.status_source); a step on the file's
    timeline, that step's record. 2023/0421(COD), 2 Nov 2026: "status now Published in the Official Journal" cited the
    OEIL page, which gave "Awaiting committee decision". `dossier`: the built file of a dossier id."""
    from pipeline.analysis.activity import ACT_STAGES, event_keys, stage_item, status_source, step_key

    out: list[str] = []
    for it in items:
        det = dossier(it.get("dossier_id"))
        if det is None:
            continue
        src = it.get("source") or {}
        if (st := stage_item(it.get("id") or "")) is not None:
            _, stage, since = st
            if stage in ACT_STAGES and src.get("institution") != "EUR-Lex":
                out.append(f"{it['id']}: a status change to {stage!r} cites {src.get('institution')!r}, not the act's "
                           "EUR-Lex record")  # fmt: skip
            elif stage == det.get("stage") and since and since == (det.get("status") or {}).get("since"):
                want = status_source(det) or {}
                if src.get("url") != want.get("url"):
                    out.append(f"{it['id']}: cites {src.get('url')}, not the record that gave the status "
                               f"({want.get('url')})")  # fmt: skip
        elif (key := step_key(it.get("id") or "")) is not None:
            keys = event_keys(det, today)
            step = next((e for e in det.get("timeline") or [] if e["id"] == key or keys.get(e["id"]) == key), None)
            if step is not None and step.get("source") and src.get("url") != step["source"].get("url"):
                out.append(f"{it['id']}: cites {src.get('url')}, not the record of its step ({step['source'].get('url')})")
    return out


def dossier_invariants(d: dict) -> list[tuple[str, str]]:
    """(check, message) for each claim of a built dossier that its own records rule out:
    - stage-without-parliament: an ordinary or consent procedure shown as adopted or later with no position or decision
      of Parliament recorded (2023/0421(COD), 2 Nov 2026: "Published" from one EP publication event, with no Parliament
      position, Council adoption or act). Not for a file shown from its EUR-Lex record only (`eurlex_only`), whose steps
      are not in the data;
    - adopted-stage-behind: an adoption date on a file shown at an earlier stage (2025/0312(COD): adopted 26 Oct 2026
      by the Council, still "the Council must still formally approve it");
    - deadline-before-act: a transposition deadline shown that is earlier than the act's adoption (2010/0208(COD),
      Directive (EU) 2015/412: 17 October 2002, carried over by Cellar from Directive 2001/18/EC);
    - stage-without-act: a file shown as published, in force or no longer in force (a stage that the act establishes,
      status._acts_stage) with no act linked to it (2025/0177(COD), 2 Nov 2026: "Published in the Official Journal"
      from the EP's record of a publication on 28 October that the EP then deleted, no act in our EUR-Lex data)."""
    out: list[tuple[str, str]] = []
    stage, tl = d.get("stage"), d.get("timeline") or []
    if stage in ACT_ESTABLISHED and not d.get("celex"):
        out.append(("stage-without-act", f"shown as {stage!r} ({d.get('status_label')!r}), but no act is linked to the "
                    "file"))  # fmt: skip
    if stage in POST_ADOPTION and d.get("type") in NEEDS_PARLIAMENT and not d.get("eurlex_only"):
        decided = (
            any(e.get("kind") == "ep_position" for e in tl)
            or d.get("ep_approval_without_vote")
            or any(v.get("kind") == "final" and v.get("outcome") == "adopted" for v in d.get("ep_votes") or [])
        )
        if not decided:
            out.append(("stage-without-parliament", f"{d.get('type')} file shown as {stage!r} "
                        f"({d.get('status_label')!r}), but no position or decision of Parliament is recorded"))  # fmt: skip
    if d.get("adopted") and stage not in POST_ADOPTION and stage != "withdrawn":  # withdrawn: dossier_contradictions
        out.append(("adopted-stage-behind", f"adopted on {d['adopted']}, but shown at stage {stage!r} "
                    f"({d.get('status_label')!r})"))  # fmt: skip
    # each deadline shown, with the date of the act it belongs to (the file's adoption when the act has no date)
    acts = {a.get("celex"): a for a in d.get("acts") or [] if isinstance(a, dict)}
    directives = sorted(a["date_document"] for a in acts.values() if a.get("act_type") == "directive" and a.get("date_document"))
    first = directives[0] if directives else d.get("adopted")
    shown: list[tuple[str, str, str | None]] = []  # (deadline, where shown, adoption of its act)
    app = d.get("application") or {}
    rows = app.get("transposition")
    for t in [x.get("date") for x in rows if x.get("kind") in DEADLINE_KINDS] if isinstance(rows, list) else (
            app.get("transposition_deadlines") or []):  # fmt: skip
        shown.append((t, "application dates", first))
    for impl in [d.get("implementation"), *(d.get("implementation_more") or [])]:
        if isinstance(impl, dict) and impl.get("deadline"):
            own = (acts.get(impl.get("celex")) or {}).get("date_document") or first
            shown.append((impl["deadline"], f"implementation of {impl.get('celex')}", own))
    shown += [(e.get("date"), "timeline", first) for e in tl if e.get("kind") == "transposition_deadline"]
    early: dict[tuple[str, str], list[str]] = defaultdict(list)
    for t, where, adopted in shown:
        if isinstance(t, str) and adopted and t < adopted and where not in early[(t, adopted)]:
            early[(t, adopted)].append(where)
    for (t, adopted), where in sorted(early.items()):
        out.append(("deadline-before-act", f"transposition deadline {t} ({', '.join(where)}) is before the adoption "
                    f"of its act on {adopted}"))  # fmt: skip
    return out


def rapporteur_problems(d: dict, public: Path) -> list[str]:
    """A rapporteur linked to an MEP page that is not written, and an MEP listed twice in one role (2026/0172(COD):
    Marie-Sophie Christ under OEIL's person id and under EP Open Data's, as two shadow rapporteurs)."""
    out, seen = [], Counter()
    for r in d.get("rapporteurs") or []:
        if r.get("has_page") and not (public / "people" / "meps" / f"{r.get('mep_id')}.json").exists():
            out.append(f"rapporteur {r.get('name')} links people/meps/{r.get('mep_id')}.json, which is not written")
        if r.get("mep_id"):
            seen[(r["mep_id"], r.get("role"), r.get("committee"))] += 1
    out += [f"MEP {i} listed {n} times as {role}" + (f" ({c})" if c else "") for (i, role, c), n in seen.items() if n > 1]
    return out


def margin_contradictions(v: dict) -> list[str]:
    """A built vote's margin that its outcome contradicts. A margin is our calculation: it may stand only next to
    an established outcome (adopted or rejected), on the side of the threshold that outcome says."""
    m = v.get("margin")
    if not m:
        return []
    outcome, distance, label = v.get("outcome"), m.get("distance"), str(m.get("label") or "")
    if outcome not in ("adopted", "rejected"):
        return [f"vote {v.get('id')}: margin {label!r} with outcome {outcome!r}"]
    if not isinstance(distance, int) or (distance >= 0) != (outcome == "adopted"):
        return [f"vote {v.get('id')}: margin distance {distance} contradicts outcome {outcome!r}"]
    if label.startswith("Majority not reached") == (outcome == "adopted"):
        return [f"vote {v.get('id')}: margin label {label!r} contradicts outcome {outcome!r}"]
    return []


def _floors(snapshot: Path) -> dict[tuple[str, str], int] | None:
    """MIN_RECORDS for the committed snapshot; a snapshot somewhere else (a test fixture) has none. Compared with the
    repository's own data/snapshot (ROOT), not with the SNAPSHOT name bound when this module was imported: tests point
    pipeline.snapshot.SNAPSHOT at a fixture, and a first import inside such a test bound that fixture as "committed"."""
    return MIN_RECORDS if snapshot.resolve() == (ROOT / "data" / "snapshot").resolve() else None


def load_baseline(path: Path | None = None) -> tuple[dict[str, int], dict[str, list[str]]]:
    """pipeline/validate_baseline.json: warning class -> its count, and the integrity findings it accepted (an
    unreadable or missing file: none)."""
    try:
        doc = json.loads((path or BASELINE).read_text(encoding="utf-8"))
        counts, accepted = doc.get("counts"), doc.get("accepted")
    except (OSError, ValueError, AttributeError):
        return {}, {}
    counts = {str(k): v for k, v in counts.items() if type(v) is int} if isinstance(counts, dict) else {}
    accepted = {str(k): [str(m) for m in v] for k, v in accepted.items() if isinstance(v, list)} if isinstance(
        accepted, dict) else {}  # fmt: skip
    return counts, accepted


def write_baseline(rep: Report, path: Path | None = None) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Record the report's warning counts (every class not by design), and its integrity findings, as the baseline."""
    counts = {k: len(v) for k, v in sorted(rep.warnings.items()) if v}
    accepted = {k: sorted(v) for k, v in sorted(rep.warnings.items()) if v and warning_kind(k) == "integrity"}
    doc = {
        "about": "Warnings of `python -m pipeline validate --built` on the committed snapshot. `accepted`: the integrity "
        "findings checked and accepted (pipeline/validate.py INTEGRITY, and any class not classified); validate fails "
        "on any other integrity finding, whatever the count. `counts`: every class's count; backlog classes never "
        "fail. Rewrite with `python -m pipeline validate --built --update-baseline` once new findings are checked and "
        "accepted, or when a count fell (refused while validate reports errors).",
        "counts": counts,
        "accepted": accepted,
    }
    (path or BASELINE).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return counts, accepted


def apply_baseline(
    rep: Report, baseline: dict[str, int], complete: bool = True, accepted: dict[str, list[str]] | None = None
) -> None:
    """The ratchet: an integrity finding that the baseline does not accept (`accepted`: its integrity findings, by
    class) is a breach, also while its class has no more findings than the baseline counts: a new wrong link must not
    pass because another one was fixed. Backlog classes are counted (`baseline`) and never fail. `complete`: the built
    output was checked too, so a class below its baseline can be told (without it, the classes of the built output
    count none)."""
    rep.baseline = baseline
    for check, items in sorted(rep.warnings.items()):
        if warning_kind(check) != "integrity" or not items:
            continue
        why = INTEGRITY.get(check, "a warning class not classified in pipeline/validate.py: classify it")
        left = Counter((accepted or {}).get(check, []))
        new = []
        for m in items:
            if left[m] > 0:
                left[m] -= 1
            else:
                new.append(m)
        if new:
            rep.breaches.append(f"[{check}] {len(new)} finding{'s' if len(new) > 1 else ''} not in the baseline "
                                f"(e.g. {new[0][:160]}): {why}")  # fmt: skip
    if complete:
        for check, base in sorted(baseline.items()):
            n = len(rep.warnings.get(check, []))
            if n < base:
                rep.ratchet_notes.append(f"[{check}] {n}, below its baseline of {base}: lower it with --update-baseline")


def validate(built: bool = False, update_baseline: bool = False) -> int:
    """The snapshot checks and the built-output checks, and the ratchet on the warning counts (validate_baseline.json).
    The built output is checked only if it exists, so the workflows run this again after `python -m pipeline build`
    with built=True: without public/data that is an error instead of a silent skip. 1 on any error or ratchet breach.
    `update_baseline` (implies built): record this run's warning counts as the baseline first."""
    from pipeline import snapshot as snapshot_module

    built = built or update_baseline
    public = ROOT / "public" / "data"
    rep = check(snapshot_module.SNAPSHOT, public=public, built=built, min_records=_floors(snapshot_module.SNAPSHOT))
    if built and not public.exists():
        rep.error(f"no built output in {public}: run `python -m pipeline build` first", "public", "built-incomplete")
    old, accepted = load_baseline()
    if update_baseline and public.exists() and rep.errors:
        # the baseline accepts warnings only: errors are fixed, never recorded
        print(f"validate: baseline not written: {len(rep.errors)} error{'s' if len(rep.errors) > 1 else ''} (fix them "
              "first)")  # fmt: skip
    elif update_baseline and public.exists():
        new, accepted = write_baseline(rep)
        changed = [f"{k} {old.get(k, 0)} -> {new.get(k, 0)}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
        print(f"validate: baseline written to {BASELINE.relative_to(ROOT) if BASELINE.is_relative_to(ROOT) else BASELINE}"
              f" ({'; '.join(changed) or 'counts unchanged'})")  # fmt: skip
        old = new
    apply_baseline(rep, old, complete=public.exists(), accepted=accepted)
    rep.print(sys.stdout)
    if not built and not public.exists():
        print("validate: built output not checked (no public/data; run `python -m pipeline build` first)")
    return 1 if rep.errors or rep.breaches else 0


def validate_by_source(snapshot: Path | None = None, out=sys.stdout, today: str | None = None) -> list[str]:
    """Check the snapshot only (not the built output) and return the sources with structural errors,
    so that the refresh can restore just those sources' previous files instead of discarding the run."""
    from pipeline import snapshot as snapshot_module

    snapshot = snapshot or snapshot_module.SNAPSHOT
    rep = check(snapshot, today=today, min_records=_floors(snapshot))
    rep.print(out)
    for source, errs in sorted(rep.errors_by_source.items()):
        print(f"validate: {source}: {len(errs)} errors, e.g. {errs[0]}", file=out)
    return sorted(rep.errors_by_source)
