"""The law in context on a file's page: EUR-Lex's official summaries of its acts, the court cases on them, their
consolidated versions and the advisory opinions on the file (data/snapshot/lawcontext, pipeline/sources/lawcontext.py).

Joined to a file only through official identifiers: the CELEX numbers of the file's acts and its procedure reference.
Each field is left out when the snapshot holds nothing for the file (or the source was never retrieved), so a page
without this data is built exactly as before.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable

from pipeline.models.entities import (
    ActContext,
    AdvisoryOpinion,
    LegalAct,
    OfficialSummary,
    ProcedureCase,
)

EURLEX = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
DECISION_RE = re.compile(r"^6\d{4}([CT])([JO])\d{4}")  # court (C: Court of Justice, T: General Court), J/O
COURTS = {"C": "Court of Justice", "T": "General Court"}


def _case_label(case: str | None, celex: str) -> str:
    """"Case C-312/24" -> "C-312/24"; joined cases as published; else the number the CELEX gives."""
    if case:
        return re.sub(r"^Case\s+", "", " ".join(case.split()))
    m = re.fullmatch(r"6(\d{4})([CT])[A-Z]0*(\d+)", celex)
    return f"{m[2]}-{m[3]}/{m[1][2:]}" if m else celex


def _court(celex: str) -> str:
    m = re.match(r"6\d{4}([CT])", celex)
    return COURTS.get(m[1], "Court of Justice") if m else "Court of Justice"


class LawContext:
    """The lawcontext snapshot indexed by act and by procedure reference."""

    def __init__(
        self,
        contexts: Iterable[ActContext],
        summaries: Iterable[OfficialSummary],
        opinions: Iterable[AdvisoryOpinion],
        procedure_cases: Iterable[ProcedureCase],
        acts: dict[str, LegalAct],
    ) -> None:
        self.ctx = {c.celex: c for c in contexts}
        self.summaries: dict[str, list[OfficialSummary]] = defaultdict(list)
        for s in summaries:
            if s.obsolete:  # EUR-Lex marks it obsolete: not shown
                continue
            for c in s.acts:
                self.summaries[c].append(s)
        self.opinions: dict[str, list[AdvisoryOpinion]] = defaultdict(list)
        for o in opinions:
            for r in o.procedure_refs:
                self.opinions[r].append(o)
        self.cases: dict[str, list[ProcedureCase]] = defaultdict(list)
        for k in procedure_cases:
            self.cases[k.reference].append(k)
        self.acts = acts
        # the acts amending each act, from both directions of the recorded link
        self.amended_by: dict[str, set[str]] = defaultdict(set)
        for a in acts.values():
            self.amended_by[a.celex] |= set(a.amended_by)
            for c in a.amends:
                self.amended_by[c].add(a.celex)

    def __bool__(self) -> bool:
        return bool(self.ctx or self.summaries or self.opinions or self.cases)

    # ------------------------------------------------------------------------------------------- summaries
    def latest_amendment(self, celexes: Iterable[str]) -> LegalAct | None:
        """The most recently published act amending one of `celexes` that our EUR-Lex data dates."""
        dated = [a for c in celexes for x in self.amended_by.get(c, ()) if (a := self.acts.get(x))
                 and (a.date_publication or a.date_document)]  # fmt: skip
        return max(dated, key=lambda a: (a.date_publication or a.date_document or "", a.celex), default=None)

    def official_summaries(self, acts: list[LegalAct], label: Callable[[LegalAct], str]) -> list[dict]:
        mine = {a.celex for a in acts}
        seen: dict[str, OfficialSummary] = {}
        for a in acts:
            for s in self.summaries.get(a.celex, []):
                seen.setdefault(s.id, s)
        out = []
        for s in seen.values():
            read = s.text_status == "ok"
            date = s.text_date if read else s.date  # the version whose text is quoted
            covers = sorted(c for c in s.acts if c in mine)
            latest = self.latest_amendment(covers)
            when = (latest.date_publication or latest.date_document) if latest else None
            item = {
                "id": s.id, "title": s.title, "date": date, "acts": covers,
                "aim": list(s.aim) if read else [], "aim_items": list(s.aim_items) if read else [],
                "aim_heading": s.aim_heading if read else None,
                "aim_complete": bool(s.aim_complete) if read else False, "url": s.url,
            }  # fmt: skip
            if latest and when and date and date < when:
                item["predates"] = {"celex": latest.celex, "label": label(latest), "date": when}
            out.append(item)
        return sorted(out, key=lambda x: (x["date"] or "", x["id"]), reverse=True)

    # --------------------------------------------------------------------------------------------------- court
    def court(self, reference: str, acts: list[LegalAct]) -> dict | None:
        decisions: dict[str, dict] = {}
        pending: dict[str, dict] = {}
        for a in acts:
            ctx = self.ctx.get(a.celex)
            if not ctx:
                continue
            for d in ctx.interpreted_by:
                m = DECISION_RE.match(d.celex)
                if not m:
                    continue
                item = decisions.setdefault(d.celex, {
                    "celex": d.celex, "case": _case_label(d.case, d.celex), "date": d.date, "ecli": d.ecli,
                    "kind": "judgment" if m[2] == "J" else "order", "court": COURTS[m[1]], "acts": [],
                    "url": EURLEX.format(celex=d.celex),
                })  # fmt: skip
                item["acts"] = sorted({*item["acts"], a.celex})
            for k in ctx.cases:
                if k.state != "pending":
                    continue
                item = pending.setdefault(k.celex, {
                    "celex": k.celex, "case": _case_label(k.case, k.celex), "kind": k.kind, "lodged": k.lodged,
                    "court": _court(k.celex), "acts": [], "url": EURLEX.format(celex=k.celex),
                })  # fmt: skip
                item["acts"] = sorted({*item["acts"], a.celex})
        for k in self.cases.get(reference, []):  # an action against the withdrawal of the file's proposal
            if k.state == "pending":
                pending.setdefault(k.celex, {
                    "celex": k.celex, "case": _case_label(k.case, k.celex), "kind": "annulment_of_withdrawal",
                    "lodged": k.lodged, "court": _court(k.celex), "acts": [], "applicants": k.applicants,
                    "url": EURLEX.format(celex=k.celex), "annulled": k.annulled,
                })  # fmt: skip
        if not decisions and not pending:
            return None

        def newest(x: dict, at: str) -> tuple[str, str]:
            return (x.get(at) or "", x["celex"])

        return {
            "interpreted_by": sorted(decisions.values(), key=lambda x: newest(x, "date"), reverse=True),
            "pending": sorted(pending.values(), key=lambda x: newest(x, "lodged"), reverse=True),
        }

    # ------------------------------------------------------------------------------------------ consolidated
    def consolidated(self, acts: list[LegalAct], label: Callable[[LegalAct], str]) -> list[dict]:
        out = []
        for a in acts:
            ctx = self.ctx.get(a.celex)
            if ctx and ctx.consolidated:
                out.append({"act": a.celex, "act_label": label(a),
                            "versions": [{"celex": v.celex, "date": v.date} for v in ctx.consolidated]})  # fmt: skip
        return out

    # -------------------------------------------------------------------------------------------- opinions
    def advisory_opinions(self, reference: str) -> list[dict]:
        return [
            {"celex": o.celex, "body": o.body, "date": o.date, "title": o.title, "url": o.url}
            for o in sorted(self.opinions.get(reference, []), key=lambda o: (o.date or "", o.celex))
        ]

    def for_dossier(self, reference: str, acts: list[LegalAct], label: Callable[[LegalAct], str]) -> dict:
        """The DossierDetail fields of the law context, each only when the snapshot holds something for the file."""
        out: dict = {}
        if s := self.official_summaries(acts, label):
            out["official_summaries"] = s
        if c := self.court(reference, acts):
            out["court"] = c
        if v := self.consolidated(acts, label):
            out["consolidated"] = v
        if o := self.advisory_opinions(reference):
            out["advisory_opinions"] = o
        return out
