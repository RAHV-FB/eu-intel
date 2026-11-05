"""The steps the Council and Parliament have scheduled, for the site: each file's `scheduled` list and the home page's
list of the next weeks (from data/snapshot/agenda, pipeline/sources/agenda.py).

A planned step is joined to a file by its full procedure reference only. Only steps dated after the build's date are given:
one planned for the day of the build or earlier may have taken place already, and the other sources show it once it is
recorded. The pages compare the dates with the reader's date, since the data is rebuilt weekly: a step whose date has
passed is left out of the home page's list and said to have been scheduled on the file's page
(src/features/legislation/dossier/ScheduledNext.tsx, src/lib/format.ts `stillAhead`).

The same step can be in both schedules: a vote of Parliament on its agenda and as a planned event in Cellar. Steps of
a file with the same date and event type are one step, with the sources and documents of both (Parliament's agenda
first). Steps that differ in date are each shown, with their own source: they are both published plans.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from pipeline.models.entities import PlannedStep

# The procedure phases given with a step: the readings ("Second reading"); "End of procedure", the phase of the Council's
# adoption of the act, is what the step's own label says
READINGS = {"RDG1", "RDG2", "RDG3"}
HOME_DAYS = 21  # the home page lists the steps of the next three weeks
HOME_LIMIT = 100  # a bound only: the list holds the whole window, so it never runs dry early
# the badge of the home page's planned steps (src/lib/format.ts PLANNED_BADGE: kept on their day)
HOME_BADGE = "Planned"
INSTITUTION_ORDER = {"Council": 0, "EP": 1}
_SMALL = {"of", "the", "and", "for", "on", "in", "to", "a", "an"}


def meeting_name(title: str | None) -> str | None:
    """A Council agenda's title as a name: the part set in capitals in sentence case, the rest as given.
    "COUNCIL OF THE EUROPEAN UNION (General Affairs)" -> "Council of the European Union (General Affairs)";
    "PERMANENT REPRESENTATIVES COMMITTEE (Part 1)" -> "Permanent Representatives Committee (Part 1)"."""
    if not title:
        return None
    title = " ".join(title.split())
    m = re.match(r"^([A-Z][A-Z ,'&-]*[A-Z])(?=\s*(?:\(|$))(.*)$", title)
    if not m:
        return title
    words = m[1].split(" ")
    head = " ".join(
        w.lower() if i and w.lower() in _SMALL else w[:1] + w[1:].lower() for i, w in enumerate(words)
    )
    return head + m[2]


def _step(s: PlannedStep) -> dict[str, Any]:
    out: dict[str, Any] = {"date": s.date, "institution": s.institution, "label": s.label}
    if s.phase and s.phase_code in READINGS:
        out["phase"] = s.phase
    if meeting := meeting_name(s.meeting):
        out["meeting"] = meeting
    out["documents"] = [d.model_dump(mode="json") for d in s.documents]
    out["sources"] = [s.source.model_dump(mode="json")]
    return out


def _merge(into: dict[str, Any], s: PlannedStep) -> None:
    """Add another schedule's record of the same step: its source, the documents not listed yet, the reading and the
    meeting if the first gives none."""
    extra = _step(s)
    into["sources"] += [x for x in extra["sources"] if x not in into["sources"]]
    have = {d["id"] for d in into["documents"]}
    into["documents"] += [d for d in extra["documents"] if d["id"] not in have]
    for key in ("phase", "meeting"):
        if key in extra and key not in into:
            into[key] = extra[key]


def scheduled_by_dossier(
    steps: Iterable[PlannedStep], dossier_of: Callable[[str], str | None], today: str
) -> dict[str, list[dict[str, Any]]]:
    """{dossier id: its steps dated after `today`, by date}. `dossier_of`: a procedure reference -> the file of the site
    it is (None: not in the site's scope, the step is left out)."""
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    # Parliament's own agenda first, so that its record leads a step both schedules give
    for s in sorted(steps, key=lambda s: (s.source.institution != "EP", s.date, s.id)):
        if s.date <= today:
            continue
        pid = dossier_of(s.reference)
        if pid is None:
            continue
        key = (pid, s.date, s.event_type)
        if key in merged:
            _merge(merged[key], s)
        else:
            merged[key] = _step(s)
    out: dict[str, list[dict[str, Any]]] = {}
    for (pid, _d, _t), x in sorted(
        merged.items(),
        key=lambda kv: (kv[0][0], kv[0][1], INSTITUTION_ORDER.get(kv[1]["institution"], 9), kv[1]["label"]),
    ):
        out.setdefault(pid, []).append(x)
    return out


def home_subtitle(step: dict[str, Any]) -> str:
    """ "Vote in EP plenary (second reading)"; "Approval of … (adoption of the legislative act) – Council of the European
    Union (General Affairs)"."""
    text = step["label"] + (f" ({step['phase'].lower()})" if step.get("phase") else "")
    return f"{text} – {step['meeting']}" if step.get("meeting") else text


def home_items(
    scheduled: dict[str, list[dict[str, Any]]],
    summaries: dict[str, dict[str, Any]],
    today: str,
    days: int = HOME_DAYS,
    limit: int = HOME_LIMIT,
) -> list[dict[str, Any]]:
    """The home page's planned steps: those of the next `days` days after `today`, by date (featured files first on a
    day), at most `limit`."""
    end = (date.fromisoformat(today) + timedelta(days=days)).isoformat()
    rows = [
        (s, pid)
        for pid, steps in scheduled.items()
        if pid in summaries
        for s in steps
        if today < s["date"] <= end
    ]
    rows.sort(key=lambda r: (r[0]["date"], not summaries[r[1]]["featured"], r[1], r[0]["label"]))
    return [
        {"dossier_id": pid, "title": summaries[pid]["title"], "subtitle": home_subtitle(s), "date": s["date"],
         "badge": HOME_BADGE}
        for s, pid in rows[:limit]
    ]  # fmt: skip
