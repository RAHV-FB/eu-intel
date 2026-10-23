"""Offline checks of the normalized snapshot (data/snapshot/**) and, once built, of public/data.

    python -m pipeline validate            # the snapshot, and the built output if there is one
    python -m pipeline validate --built    # the same, but a missing built output is an error (CI, deploy, refresh)

Errors (exit code 1) are STRUCTURAL problems only: unreadable files, records that do not match
the schema in pipeline/models/entities.py, duplicate ids, malformed dates; and, in the built output,
claims that contradict the rules or the dossier's own dates (a veto outside unanimity, a withdrawn file
with an adopted act or withdrawn before its proposal, an adoption after publication, a vote margin next to an
outcome that is not established or on the other side of the threshold from it); and a count of sitting MEPs that
a complete list of current Members cannot give (see the people checks).
Everything else is reported as a warning: dangling references, official totals that differ from the
recorded individual votes (official discrepancies are facts, not bugs), implausible dates,
transposition data on non-directives, "veto" wording outside unanimity, odd act/procedure pairs.
"""

from __future__ import annotations

import json
import re
import sys
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
PUBLIC_FILES = [
    "meta.json", "home.json", "dossiers/index.json", "votes/index.json", "council/index.json",
    "people/meps.json", "people/groups.json", "people/parties.json", "countries/index.json",
    "topics.json", "search.json", "activity.json", "feeds/updates.xml",
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
]


MANIFEST_KEY = "_manifest"  # errors_by_source key for an unreadable _manifest.json as a whole


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        # source directory (or MANIFEST_KEY / "public") -> its structural errors; a manifest entry's
        # error counts for that entry's source
        self.errors_by_source: dict[str, list[str]] = defaultdict(list)
        self.warnings: dict[str, list[str]] = defaultdict(list)
        self.info: list[str] = []

    def error(self, msg: str, source: str = "?") -> None:
        self.errors.append(msg)
        self.errors_by_source[source].append(msg)

    def warn(self, check: str, msg: str) -> None:
        self.warnings[check].append(msg)

    def print(self, out=sys.stdout, examples: int = 5) -> None:
        for line in self.info:
            print(f"  {line}", file=out)
        for check in sorted(self.warnings):
            items = self.warnings[check]
            print(f"WARNING [{check}] {len(items)}", file=out)
            for m in items[:examples]:
                print(f"    - {m}", file=out)
            if len(items) > examples:
                print(f"    … {len(items) - examples} more", file=out)
        for m in self.errors[:50]:
            print(f"ERROR {m}", file=out)
        if len(self.errors) > 50:
            print(f"ERROR … {len(self.errors) - 50} more errors", file=out)
        status = "FAILED" if self.errors else "OK"
        n_warn = sum(len(v) for v in self.warnings.values())
        print(f"validate: {status} — {len(self.errors)} errors, {n_warn} warnings", file=out)


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


def check(snapshot: Path = SNAPSHOT, public: Path | None = None, today: str | None = None) -> Report:
    rep = Report()
    today = today or date.today().isoformat()
    data: dict[tuple[str, str], list[Any]] = {}
    # manifest
    man = snapshot / "_manifest.json"
    if man.exists():
        try:
            raw = json.loads(man.read_text(encoding="utf-8"))
            for k, v in raw.items():
                try:
                    E.SourceStatus.model_validate(v)
                except ValidationError as e:
                    rep.error(f"_manifest.json[{k}]: {e.errors()[0]['msg']}", str(k))
        except (OSError, json.JSONDecodeError, AttributeError) as e:
            rep.error(f"_manifest.json unreadable ({e})", MANIFEST_KEY)
    else:
        rep.warn("manifest", "data/snapshot/_manifest.json missing")
    # schema + duplicates + date format
    for source, name, model_name, key in FILES:
        recs = _load(snapshot, source, name, model_name, rep)
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
        if missing:
            rep.warn(
                "ref-mep", f"vote {v.id}: {len(missing)} ballot MEP ids not in meps.json (e.g. {missing[0]})"
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
            if ptype in ("COD", "CNS") and num >= 2000:
                rep.warn("act-procedure-mismatch", f"{a.celex} ({a.act_type}) linked to {r}: number range is "
                         "not used for legislative procedures")  # fmt: skip
            p = proc_by_ref.get(r)
            if p is not None and p.type != ptype:
                rep.warn(
                    "act-procedure-mismatch", f"{a.celex} linked to {r} but the procedure type is {p.type}"
                )
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
        for f in PUBLIC_FILES:
            if not (public / f).exists():
                rep.warn("public-missing", f"public/data/{f} missing (run `python -m pipeline build`)")
        cpath = public / "council" / "index.json"
        if cpath.exists():
            for cv in json.loads(cpath.read_text(encoding="utf-8")):
                a = cv.get("assessment") or {}
                if a.get("single_state_veto_possible") and cv.get("voting_rule") != "unanimity":
                    rep.error(
                        f"public council/index.json {cv['id']}: single-state veto outside unanimity", "public"
                    )
        owners: dict[str, list[str]] = {}
        for f in sorted((public / "dossiers").glob("*.json")):
            if f.name != "index.json":
                d = json.loads(f.read_text(encoding="utf-8"))
                for msg in dossier_contradictions(d):
                    rep.error(f"public dossiers/{f.name}: {msg}", "public")
                # a key report that no step carries has no tabling or vote of its own on the timeline
                steps = {x["id"] for e in d.get("timeline", []) for x in e.get("docs", [])}
                for doc in d.get("documents") or []:
                    if doc.get("kind") == "report" and doc["id"] not in steps:
                        rep.warn("report-off-timeline", f"dossier {d['id']}: key document {doc['id']} is on no timeline step")
                for c in d.get("celex") or []:
                    owners.setdefault(c, []).append(d["id"])
                for v in d.get("ep_votes") or []:
                    for msg in margin_contradictions(v):
                        rep.error(f"public dossiers/{f.name}: {msg}", "public")
        # one law, one page: an act shown on two files means EUR-Lex and the EP disagree on its procedure
        for c, ids in sorted(owners.items()):
            if len(ids) > 1:
                rep.warn("act-on-two-dossiers", f"{c} is shown on {', '.join(ids)}; check which procedure adopted it")
        for f in sorted((public / "votes").glob("*.json")):
            recs = json.loads(f.read_text(encoding="utf-8"))
            for v in recs if isinstance(recs, list) else [recs]:
                for msg in margin_contradictions(v):
                    rep.error(f"public votes/{f.name}: {msg}", "public")
    return rep


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


def validate(built: bool = False) -> int:
    """The snapshot checks and the built-output checks. The built output is checked only if it exists, so the
    workflows run this again after `python -m pipeline build` with built=True: without public/data that is an error
    instead of a silent skip."""
    from pipeline import snapshot as snapshot_module

    public = ROOT / "public" / "data"
    rep = check(snapshot_module.SNAPSHOT, public=public)
    if built and not public.exists():
        rep.error(f"no built output in {public}: run `python -m pipeline build` first", "public")
    rep.print(sys.stdout)
    if not built and not public.exists():
        print("validate: built output not checked (no public/data; run `python -m pipeline build` first)")
    return 1 if rep.errors else 0


def validate_by_source(snapshot: Path | None = None, out=sys.stdout, today: str | None = None) -> list[str]:
    """Check the snapshot only (not the built output) and return the sources with structural errors,
    so that the refresh can restore just those sources' previous files instead of discarding the run."""
    from pipeline import snapshot as snapshot_module

    rep = check(snapshot or snapshot_module.SNAPSHOT, today=today)
    rep.print(out)
    for source, errs in sorted(rep.errors_by_source.items()):
        print(f"validate: {source}: {len(errs)} errors, e.g. {errs[0]}", file=out)
    return sorted(rep.errors_by_source)
