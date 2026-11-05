"""How the activity items read: what happened apart from the file's title, the file's full title in a headline, and a
status change told together with the step that gave the status.

An activity item's title (pipeline/analysis/activity.py) is its headline: "<file title>: <what happened>" for a step or a
status change, "New file: <file title>", or a Parliament or Council vote's own headline. The file title in it is shortened
(activity.short_title, 110 characters) and, for a recorded item, the one the file had when the item was recorded. These
helpers read the headlines for the What changed page (`event` and `step_id` of public/data/activity.json) and the Atom feeds
(full titles; one entry for a status change and its step). They never add, drop or re-date an item: which items are
published is activity.py's.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.analysis.activity import (
    CONSENT_DECISION_TITLE,
    REJECT_MOTION_TITLES,
    STAGE_STEP_KINDS,
    VOTE_STEP_TITLES,
    short_title,
)

# The kind of the act's own step that dates each stage an act establishes (activity.status_source).
ACT_STAGE_KINDS: dict[str, tuple[str, ...]] = {
    "published": ("publication",),
    "takes_effect_on_notification": ("publication",),
    "in_force": ("entry_into_force",),
    "no_longer_in_force": ("end_of_validity",),
}
# A status change's headline after the file's title (activity.diff)
STATUS_TEXT = re.compile(r"status now “(?P<now>.+?)”(?: \(previously “(?P<was>.+?)”\))?$")
_STAGE_ID = re.compile(r"^chg:[^:]+:stage:([^:]+):")
_VOTE_KEY = re.compile(r"^vote-\d+-(\w+)$")
_MOTIONS = tuple(REJECT_MOTION_TITLES.values())
# headlines that name what was voted on rather than the file (a vote's own title, a Council vote's)
VOTE_KINDS = ("ep_vote", "council_vote")
NEW_FILE = "New file: "


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _step(item: dict, timeline: list[dict] | None) -> dict | None:
    """The timeline step an item reports (its id is "ev:<step id>", or "ev:vote-<vote id>-<kind>" for Parliament's
    decision keyed by its vote: activity.event_keys), when the file's timeline has it."""
    raw = item["id"].split(":", 2)[2] if item["id"].startswith("chg:") and item["id"].count(":") >= 2 else item["id"]
    if not raw.startswith("ev:") or not timeline:
        return None
    key = raw[3:]
    if m := _VOTE_KEY.match(key):
        vid = key.split("-")[1]
        return next((e for e in timeline if e.get("vote_id") == vid and e["kind"] == m.group(1)), None)
    return next((e for e in timeline if e["id"] == key), None)


def _what(item: dict, title: str | None, timeline: list[dict] | None = None) -> str | None:
    """The headline without the file's title, as written in it ("status now …" in lower case); None when the headline
    does not name the file that way."""
    head = item.get("title") or ""
    kind = item.get("kind")
    if kind == "new_dossier" and head.startswith(NEW_FILE):
        return "New file"
    if title:
        short = short_title(title)
        if kind not in VOTE_KINDS and head.startswith(f"{short}: "):
            return head[len(short) + 2:]
        # a motion to reject: "<what became of the text>: <file title><what tells it apart>" (activity.vote_headline)
        if kind == "ep_vote" and head.startswith(_MOTIONS) and f": {short}" in head:
            what, _, tail = head.partition(f": {short}")
            return what + tail
    if kind in VOTE_KINDS:
        return None
    # recorded under an earlier title of the file: the title of the step it reports (a consent decision's, as
    # activity.event_title words it), what follows a shortened title ("<title…>: <what happened>"), a status change
    if (e := _step(item, timeline)) is not None:
        names = [e["title"], *VOTE_STEP_TITLES.values()] if e["title"] == CONSENT_DECISION_TITLE else [e["title"]]
        if name := next((n for n in names if head.endswith(f": {n}")), None):
            return name
    if head.count("…: ") == 1:
        return head.split("…: ", 1)[1]
    if kind == "status_change" and (i := head.rfind(": status now “")) >= 0:
        return head[i + 2:]
    return None


def event_of(item: dict, title: str | None, timeline: list[dict] | None = None) -> str | None:
    """What happened, without the file's title: "Council adopted the act", "Status now “In force” (previously …)",
    "New file", "Parliament did not reject the Commission proposal"; None for a headline that does not name the file
    (a vote on another text, a Council vote), which is then read whole. `timeline`: the file's, to read a headline
    recorded under an earlier title of the file."""
    what = _what(item, title, timeline)
    return _cap(what) if what else None


def full_headline(item: dict, title: str | None, timeline: list[dict] | None = None) -> str:
    """The item's headline with the file's full title (`title`, the file's current one) in place of its shortened
    form; a headline recorded under an earlier title of the file is given the current one."""
    head = item.get("title") or ""
    if not title:
        return head
    if item.get("kind") == "new_dossier" and head.startswith(NEW_FILE):
        return NEW_FILE + title
    short = short_title(title)
    if short in head:
        return head.replace(short, title, 1)
    what = _what(item, None, timeline)
    return f"{title}: {what}" if what is not None else head


def status_parts(item: dict) -> tuple[str, str | None] | None:
    """A status change's new status label and the previous one: ("In force", "Signed, awaiting publication")."""
    if item.get("kind") != "status_change":
        return None
    head = item.get("title") or ""
    i = head.rfind("status now “")
    m = STATUS_TEXT.match(head, i) if i >= 0 else None
    return (m.group("now"), m.group("was")) if m else None


def _step_kind(item: dict, det: dict | None) -> str | None:
    """The timeline kind of the step an item reports ("publication", "council_adoption"), when it reports one."""
    raw = item["id"].split(":", 2)[2] if item["id"].startswith("chg:") and item["id"].count(":") >= 2 else item["id"]
    if raw.startswith("ev:") and (m := _VOTE_KEY.match(raw[3:])):
        return m.group(1)
    e = _step(item, (det or {}).get("timeline"))
    return e["kind"] if e else None


def _url(item: dict) -> str | None:
    return (item.get("source") or {}).get("url") or None


def step_of(status: dict, items: list[dict], det: dict | None, taken: set[str] | frozenset[str] = frozenset()) -> dict | None:
    """The item of the step that gave a file the status a status change records: of the file's other items of that day
    (not in `taken`), the one citing the same record (activity.status_source), else one reporting a step of a kind that
    dates the new status (an act's publication or entry into force, the Council's adoption …; never "other"). On 4
    November 2026 2024/0098(COD) became "Published, not yet in force" citing the act's EUR-Lex record, while the day's
    item was the EP's record of the same publication."""
    pid = status.get("dossier_id")
    if not pid:
        return None
    same = [i for i in items if i is not status and i.get("dossier_id") == pid and i["date"] == status["date"]
            and i.get("kind") != "status_change" and i["id"] not in taken]  # fmt: skip
    url = _url(status)
    hit = next((i for i in same if url and _url(i) == url), None)
    if hit is not None:
        return hit
    stage = m.group(1) if (m := _STAGE_ID.match(status["id"])) else ""
    kinds = [k for k in ACT_STAGE_KINDS.get(stage) or STAGE_STEP_KINDS.get(stage, ()) if k != "other"]
    return next((i for i in same if _step_kind(i, det) in kinds), None) if kinds else None


def annotate(items: list[dict], b: Any) -> list[dict]:
    """Copies of activity items, in their order, with `event` (event_of) where the headline names the file, and on a
    status change told with the step that gave the status, that step's item id (`step_id`, see step_of)."""
    details = getattr(b, "dossier_detail", {}) or {}
    out = []
    for it in items:
        det = details.get(it.get("dossier_id") or "") or {}
        it = {**it}
        if (event := event_of(it, det.get("title"), det.get("timeline"))) is not None:
            it["event"] = event
        out.append(it)
    taken: set[str] = set()
    for s in out:
        if s.get("kind") == "status_change":
            step = step_of(s, out, details.get(s.get("dossier_id") or ""), taken)
            if step is not None:
                s["step_id"] = step["id"]
                taken.add(step["id"])
    return out


def told_together(items: list[dict]) -> list[tuple[dict, dict | None]]:
    """The items as told: a status change with the item of its step (`step_id`), in the status change's place, and
    that step not again; any other item alone."""
    by_id = {i["id"]: i for i in items}
    merged = {s["step_id"] for s in items if s.get("kind") == "status_change" and s.get("step_id") in by_id}
    out: list[tuple[dict, dict | None]] = []
    for it in items:
        if it["id"] in merged:
            continue
        step = by_id.get(it.get("step_id") or "") if it.get("kind") == "status_change" else None
        out.append((it, step))
    return out
