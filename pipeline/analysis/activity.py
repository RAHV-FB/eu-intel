"""Change detection between snapshots, and the public activity list.

State (committed, data/state/):
    digest.json    {version, classifier, sources: {source: seen?}, dossiers: {dossier_id: {stage, label,
                   title, events[], votes[], council[], acts[]}}}
                   ids are the union of everything ever seen, so a temporarily missing source
                   never makes old records look "new" when it comes back; records of a source seen
                   for the first time are a baseline, not changes.
    activity.json  append-only list of verified changes, each with `detected_at`.

What counts as a change (substantive only — never a metadata refresh such as a new retrieved_at): an activity item
the snapshot lists (the same selection and wording, any date; see _entries) that rests on no record of the file seen
before, a status change, and a new file:
    new_dossier     a procedure id not seen before, when none of its recent items is its proposal
    status_change   the derived lifecycle stage changed. Recorded only when procedure AND act data are
                    present, the manifest says this snapshot's ep_procedures and eurlex fetches were
                    complete ("ok"; a failed or partial fetch may carry degraded records, so the stored
                    stages are kept until a complete one), and the stored stages were computed by the
                    same CLASSIFIER_VERSION (otherwise the stages are re-baselined silently).
                    A fetch that records which files it did not refresh completely (`unsettled` in
                    data/snapshot/<source>/_state.json, stamped with the manifest entry's attempted_at:
                    pending, kept or degraded records) is trusted for every other dossier: only the
                    dossiers it names keep their stored stage ("held") until a later run refreshes them
    milestone       a listed procedural step whose event id (or item key, see event_keys) was not seen before
    publication     a listed step (signature, publication, entry into force) of a legal act newly linked to the dossier
    ep_vote         a final vote, motion or discharge decision not seen before that no listed step records
    council_vote    a Council vote not seen before that no listed step records

Without recorded history, the public activity.json lists recent dated events from the snapshot
itself, with detected_at = null (we did not observe *when* they appeared).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pipeline.snapshot import now_iso

log = logging.getLogger("pipeline.analysis.activity")

RECENT_DAYS = 120
PUBLIC_LIMIT = 400
# Version of the lifecycle-stage logic (pipeline/analysis/status.py and the inputs build.py gives it).
# Bump it whenever the status logic changes: the next recorded run then re-baselines every stored stage
# instead of reporting the reclassification as status changes.
CLASSIFIER_VERSION = "2026-10-23.2"
# Sources whose fetch must have been complete ("ok") for a stage difference to count as a change.
STAGE_SOURCES = ("ep_procedures", "eurlex")
SNAPSHOT_EVENT_KINDS = {
    "proposal",
    "committee_report",
    "negotiation_mandate",
    "ep_position",
    "provisional_agreement",
    "council_position",
    "council_adoption",
    "signature",
    "publication",
    "entry_into_force",
    "withdrawal",
    "rejection",
    "lapsed",
}
# A final vote in a consultation or consent procedure is Parliament's opinion or its consent, not the adoption of
# the act: the procedure type says which (CNS, APP), or else the procedure symbol that ends the vote's published
# subject, "*" for consultation and "***" for consent ("Guidelines for the employment policies of the Member
# States *", 2026/0137(NLE); "EU–Mexico Interim Agreement on Trade ***", 2025/0271(NLE))
VOTE_STEP_TITLES = {
    ("opinion", "adopted"): "Parliament delivered its opinion",
    ("opinion", "rejected"): "Parliament delivered a negative opinion",
    ("consent", "adopted"): "Parliament gave its consent",
    ("consent", "rejected"): "Parliament did not give its consent",
}
_PROCEDURE_TYPE = re.compile(r"\(([A-Z]{3})\)$")
_PROCEDURE_SYMBOL = re.compile(r"(?<![*])(\*{1,3})\s*$")
# A motion to reject the proposal or the Council's position: what its outcome meant for that text (a rejected
# motion is not a rejection by Parliament; see build.VOTE_OUTCOME_NOTES)
REJECT_MOTION_TITLES = {
    ("reject_proposal", "rejected"): "Parliament did not reject the Commission proposal",
    ("reject_proposal", "adopted"): "Parliament rejected the Commission proposal",
    ("reject_council_position", "rejected"): "Parliament did not reject the Council's position",
    ("reject_council_position", "adopted"): "Parliament rejected the Council's position",
}
_KIND_TAIL = re.compile(r"\s+—\s+(?:motion to reject|final vote on the text)\b.*$")
# what a motion's title adds after its kind to tell it apart from another vote of the day (build.distinguish_vote_titles)
_MOTION_TAIL = re.compile(r"\s+—\s+motion to reject the (?:Commission proposal|Council's position \(second reading\))(.*)$")
# "Discharge 2020: European Border and Coast Guard Agency", "2019 Discharge: …"
_DISCHARGE_TITLE = re.compile(r"^(?:discharge\s+\d{4}|\d{4}\s+discharge)\b", re.I)
# A consent decision as the timeline titles it when it does not state the outcome (build: Builder.procedure_event)
CONSENT_DECISION_TITLE = "Parliament voted on consent"


def is_discharge_vote(v: dict) -> bool:
    """A vote on a discharge decision (procedure type DEC, or a title "Discharge 2020: …"): Parliament grants,
    postpones or refuses discharge to an EU body for implementing its budget. It is not a law, and the vote's
    "adopted" or "rejected" does not say which of these Parliament decided without the proposal voted on."""
    if "discharge" in (v.get("kind"), v.get("kind_detail"), v.get("final_role")):
        return True
    ref = v.get("procedure_ref") or v.get("dossier_ref") or ""
    return ref.endswith("(DEC)") or bool(_DISCHARGE_TITLE.match(v.get("display_title") or v.get("title") or ""))


def vote_headline(v: dict, step: str | None, dossier_title: str | None = None) -> str:
    """Activity and feed headline for a Parliament vote: what it decided, then what it was on. A motion to reject
    says what became of the proposal or the Council's position, then names the file."""
    title = v["display_title"]
    if (v.get("kind_detail"), v["outcome"]) in REJECT_MOTION_TITLES:
        what = short_title(dossier_title) if dossier_title else _KIND_TAIL.sub("", title)
        # with what tells it apart from another motion on the file that day, as its title gives it: 195775 "(amendments
        # 1, 2 and 7)" and 195807, both on 2025/0429(COD) on 9 July 2026, were headlined alike
        tail = m.group(1) if (m := _MOTION_TAIL.search(title)) else ""
        return f"{REJECT_MOTION_TITLES[(v['kind_detail'], v['outcome'])]}: {what}{tail}"
    if is_discharge_vote(v):
        return f"Parliament voted on a discharge decision: {_KIND_TAIL.sub('', title)}"
    res = {"adopted": "adopted", "rejected": "rejected", "lapsed": "lapsed"}.get(v["outcome"], "voted on")
    head = VOTE_STEP_TITLES.get((step or "", v["outcome"])) or f"Parliament {res}"
    return f"{head}: {title}"


def event_title(e: dict, b: Any) -> str:
    """A timeline step's title for activity. A consent decision says whether Parliament gave its consent when the
    final vote linked to it records the outcome officially (published, or in the minutes)."""
    v = b.vote_summary.get(e["vote_id"]) if e.get("vote_id") else None
    if e["title"] == CONSENT_DECISION_TITLE and v and v.get("outcome_basis") in ("published", "minutes"):
        return VOTE_STEP_TITLES.get(("consent", v["outcome"]), e["title"])
    return e["title"]


def council_vote_title(cv: dict) -> str:
    """A Council vote's list title (build: council_vote_label), else its official title."""
    return cv.get("display_title") or cv["title"]


def vote_step(v: dict, ptype: str | None, subject: str | None) -> str | None:
    """What a final vote in a consultation or consent procedure gave: "opinion" or "consent"; else None."""
    if v["kind"] != "final":
        return None
    if ptype is None and v.get("procedure_ref"):
        m = _PROCEDURE_TYPE.search(v["procedure_ref"])
        ptype = m.group(1) if m else None
    if ptype in ("CNS", "APP"):
        return "opinion" if ptype == "CNS" else "consent"
    symbol = _PROCEDURE_SYMBOL.search(subject or "")
    return {"*": "opinion", "***": "consent"}.get(symbol.group(1)) if symbol else None


def short_title(t: str, n: int = 110) -> str:
    """Dossier titles can be very long official titles; keep activity/feeds lines readable."""
    if len(t) <= n:
        return t
    return t[: n - 1].rsplit(" ", 1)[0].rstrip(",;:(") + "…"


def _item(
    id: str,
    date_: str,
    kind: str,
    title: str,
    dossier_id: str | None = None,
    vote_id: str | None = None,
    source: dict | None = None,
    detected_at: str | None = None,
) -> dict:
    return {
        "id": id,
        "date": date_,
        "detected_at": detected_at,
        "kind": kind,
        "title": title,
        "dossier_id": dossier_id,
        "vote_id": vote_id,
        "source": source,
    }


def _event_kind(kind: str) -> str:
    if kind == "proposal":
        return "new_dossier"
    if kind in ("publication", "entry_into_force", "signature"):
        return "publication"
    return "milestone"


# --------------------------------------------------------------------------------------- snapshot items
# Parliament's decisions that build.with_recorded_events also builds from the vote that decided them ("vote-<id>-<kind>")
# while its procedure record (EP API, OEIL) lacks them: the kind of vote that decides each
DECISION_VOTE_KINDS = {"ep_position": "final", "negotiation_mandate": "mandate"}
_VOTE_KEY = re.compile(r"^vote-(\d+)-")  # a step built from a vote, or keyed by it (event_keys)
_ACT_EVENT = re.compile(r"^act-([^-]+)-")  # a step of a legal act (build: "act-<celex>-<kind>-<date>")
# the digest list, and the source, of the record an item id names ("ev:<event id or key>", "vote:<id>", ...)
REF_LISTS = {"ev": "events", "vote": "votes", "council": "council", "act": "acts"}
REF_SOURCES = {"ev": "ep_procedures", "vote": "ep_votes", "council": "council", "act": "eurlex"}


def is_listed(e: dict) -> bool:
    """A timeline step that is an activity item: done, of a kind in SNAPSHOT_EVENT_KINDS, not recorded for after the
    act's validity ended, and for a negotiating mandate the decision, not its announcement in plenary."""
    return (
        e["state"] == "done"
        and e["kind"] in SNAPSHOT_EVENT_KINDS
        and not e.get("after_end_of_validity")
        and not (e["kind"] == "negotiation_mandate" and not e["key"])
    )


def event_keys(det: dict, today: str) -> dict[str, str]:
    """Event id -> the id of its activity item, for a file's listed steps: the step's own id, except that Parliament's
    decision on a day when an officially adopted vote of the deciding kind was held (outcome published or in the
    minutes) is keyed by that vote, "vote-<id>-<kind>", the id of the step built from it, whichever record supplies the
    step. The official event that replaces that step when the EP API or OEIL catch up is then the same item, not a new
    one (2025/0258(COD), 21 October 2026: vote 198325, then 2025-0258-DEC-REFBAK-2026-10-21)."""
    decided: dict[tuple[str, str], str] = {}
    for v in sorted(det.get("ep_votes") or [], key=lambda v: (v["date"], v["id"])):  # the last vote of the day wins
        if v["outcome"] == "adopted" and v["date"] <= today and v.get("outcome_basis") in ("published", "minutes"):
            for kind, vkind in DECISION_VOTE_KINDS.items():
                if v["kind"] == vkind:
                    decided[(kind, v["date"])] = v["id"]
    out: dict[str, str] = {}
    for e in det["timeline"]:
        if is_listed(e):
            vid = decided.get((e["kind"], e["date"]))
            key = f"vote-{vid}-{e['kind']}" if vid else e["id"]
            out[e["id"]] = e["id"] if key in out.values() else key  # a second such step that day keeps its own id
    return out


def item_refs(raw: str) -> list[str]:
    """The records an item id rests on, as item ids: itself, a Council vote and its step, and the vote a step was
    built from or is keyed by."""
    out = [raw]
    if raw.startswith("ev:council-"):
        out.append(f"council:{raw[len('ev:council-'):]}")
    elif raw.startswith("council:"):
        out.append(f"ev:council-{raw[len('council:'):]}")
    if raw.startswith("ev:") and (m := _VOTE_KEY.match(raw[3:])):
        out.append(f"vote:{m.group(1)}")
    return out


def _event_refs(e: dict, key: str) -> list[str]:
    """What a step's item rests on: the act it is a step of (digest `acts`), else the step (its id and key), its
    Council vote and the vote it links."""
    if m := _ACT_EVENT.match(e["id"]):
        return [f"act:{m.group(1)}"]
    refs = item_refs(f"ev:{e['id']}") + (item_refs(f"ev:{key}") if key != e["id"] else [])
    if e.get("vote_id"):
        refs.append(f"vote:{e['vote_id']}")
    return list(dict.fromkeys(refs))


def _counts(v: dict) -> str:
    n = v.get("abstain")
    return f"{v.get('for')} in favour, {v.get('against')} against, {n} abstention{'' if n == 1 else 's'}"


def _entries(b: Any, cut: str | None) -> list[tuple[dict, list[str]]]:
    """The activity items the snapshot gives for the steps, Parliament votes and Council votes dated from `cut` (any
    date when None) to today, each with the records it rests on (item ids, see item_refs). The snapshot list and the
    changes a recorded refresh detects (diff) are both drawn from these, so that each is listed once and in the same
    words, however it was found."""
    today, lo = b.today, cut or ""
    out: list[tuple[dict, list[str]]] = []
    for pid in b.dossier_ids:
        det = b.dossier_detail[pid]
        title = short_title(det["title"])
        keys = event_keys(det, today)
        for e in det["timeline"]:
            if e["id"] not in keys or not (lo <= e["date"] <= today):
                continue
            key = keys[e["id"]]
            out.append((
                _item(f"ev:{key}", e["date"], _event_kind(e["kind"]), f"{title}: {event_title(e, b)}", pid,
                      e.get("vote_id"), e.get("source")),
                _event_refs(e, key),
            ))  # fmt: skip
    # a vote that is already a dossier milestone (its timeline event, or the step keyed by it) is listed once, as that
    # milestone; so is a Council vote that its own step records
    covered = {r for _, refs in out for r in refs}
    subjects = {v.id: v.subject for v in getattr(b, "indexed_votes", [])}
    votes: list[tuple[dict, list[str]]] = []
    for v in b.vote_summary.values():
        if v["kind"] in ("final", "motion", "discharge") and lo <= v["date"] <= today and f"vote:{v['id']}" not in covered:
            d = b.dossier_summary.get(v["dossier_id"]) if v.get("dossier_id") else None
            step = vote_step(v, d["type"] if d else None, subjects.get(v["id"]))
            votes.append((_item(f"vote:{v['id']}", v["date"], "ep_vote", vote_headline(v, step, d["title"] if d else None),
                                v.get("dossier_id"), v["id"], v.get("source")), [f"vote:{v['id']}"]))  # fmt: skip
    # votes of one day on a file still headlined alike (their titles tell them apart by nothing) say how each went
    same = Counter((it["dossier_id"], it["date"], it["title"]) for it, _ in votes)
    for it, _ in votes:
        v = b.vote_summary[it["vote_id"]]
        if same[(it["dossier_id"], it["date"], it["title"])] > 1 and v.get("for") is not None:
            it["title"] += f" ({_counts(v)})"
    out += votes
    for cv in b.council_public:
        if lo <= cv["date"] <= today and f"council:{cv['id']}" not in covered:
            out.append((_item(f"council:{cv['id']}", cv["date"], "council_vote", f"Council vote: {council_vote_title(cv)}",
                              cv.get("dossier_id"), None, cv.get("source")), item_refs(f"council:{cv['id']}")))  # fmt: skip
    return out


def snapshot_entries(b: Any, days: int = RECENT_DAYS) -> list[tuple[dict, list[str]]]:
    """Recent dated activity present in the current snapshot (detected_at = None), with the records each item rests
    on (for merge)."""
    return _entries(b, (date.fromisoformat(b.today) - timedelta(days=days)).isoformat())


def snapshot_items(b: Any, days: int = RECENT_DAYS) -> list[dict]:
    """Recent dated events present in the current snapshot (detected_at = None)."""
    return [it for it, _ in snapshot_entries(b, days)]


# --------------------------------------------------------------------------------------- digest + diff
def digest(b: Any) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pid in b.dossier_ids:
        det = b.dossier_detail[pid]
        keys = event_keys(det, b.today)
        ids = [e["id"] for e in det["timeline"] if not e["id"].startswith("act-")]
        out[pid] = {
            "stage": det["stage"],
            "label": det["status_label"],
            "title": det["title"],
            # with the keys of the steps' activity items (event_keys): a step keyed by its vote is not new when the
            # official event replaces the step built from the vote, nor when the vote arrives after the official event
            "events": sorted(set(ids) | {keys[i] for i in ids if i in keys}),
            "votes": sorted(v["id"] for v in det["ep_votes"]),
            "council": sorted(c["id"] for c in det["council_votes"]),
            "acts": sorted(a["celex"] for a in det["acts"]),
        }
    return out


def sources_present(b: Any) -> dict[str, bool]:
    """Which inputs were present in this snapshot (ids from an absent source are never 'new')."""
    s = b.s
    return {
        "ep_procedures": bool(s.procedures),
        "eurlex": bool(s.acts),
        "ep_votes": bool(s.votes),
        "council": bool(s.council),
        "stage_reliable": bool(s.procedures) and bool(s.acts),
    }


def unsettled_record(b: Any, source: str) -> dict | None:
    """What the source's last fetch did not refresh completely (`unsettled` in data/snapshot/<source>/_state.json:
    procedure ids, CELEX ids, procedure references), if it was written by the fetch the manifest describes (same
    attempted_at; a restored or older state file does not count)."""
    st = (getattr(b.s, "manifest", None) or {}).get(source)
    root = getattr(b.s, "root", None)
    if st is None or root is None:
        return None
    state = _read(Path(root) / source / "_state.json", {})
    u = state.get("unsettled") if isinstance(state, dict) else None
    if isinstance(u, dict) and u.get("attempted_at") and u["attempted_at"] == getattr(st, "attempted_at", None):
        return u
    return None


def incomplete_stage_sources(b: Any) -> list[str]:
    """STAGE_SOURCES whose last fetch (manifest) was not complete ("ok"), e.g. a run in which OEIL or
    EUR-Lex failed for some records, and did not record which files it left unsettled (then nothing it wrote
    is trusted). A snapshot without a manifest (tests, local builds) is trusted."""
    manifest = getattr(b.s, "manifest", None) or {}
    if not manifest:
        return []
    out = []
    for source in STAGE_SOURCES:
        st = manifest.get(source)
        if st is None or (getattr(st, "status", None) != "ok" and unsettled_record(b, source) is None):
            out.append(source)
    return out


def _norm_ref(ref: str) -> str:
    return re.sub(r"\s+", "", ref or "").upper()


def unsettled_dossiers(b: Any, old: dict[str, dict] | None = None) -> dict[str, str]:
    """Dossier id -> source, for the dossiers whose procedure or act data this snapshot's fetches did not refresh
    completely (see unsettled_record): their stage is neither compared nor stored in this run."""
    out: dict[str, str] = {}
    u = unsettled_record(b, "ep_procedures")
    for pid in u.get("ids", []) if u else []:
        if pid in b.dossier_detail:
            out.setdefault(pid, "ep_procedures")
    u = unsettled_record(b, "eurlex")
    if u and (u.get("acts") or u.get("procedures")):
        acts = set(u.get("acts", []))
        refs = {_norm_ref(r) for r in u.get("procedures", [])}
        for pid in b.dossier_ids:
            det = b.dossier_detail[pid]
            celex = {a["celex"] for a in det["acts"]} | set((old or {}).get(pid, {}).get("acts", []))
            if celex & acts or _norm_ref(det.get("ref") or "") in refs:
                out.setdefault(pid, "eurlex")
    return out


def _warn(msg: str) -> None:
    log.warning(msg)
    if os.environ.get("GITHUB_ACTIONS"):  # an annotation on the workflow run
        print(f"::warning::{msg}")


def diff(
    old: dict[str, dict],
    new: dict[str, dict],
    b: Any,
    detected_at: str,
    stage_reliable: bool,
    seen: dict[str, bool] | None = None,
    held: set[str] | frozenset[str] = frozenset(),
) -> list[dict]:
    """Verified substantive changes from `old` to `new` digests: the activity items the snapshot gives (_entries, any
    date), as it gives them, that rest on no record of their file seen before; status changes; new files (with their
    recent items, as the snapshot lists them, and a "New file" item when none of them is the file's proposal).

    `seen` says which sources were already present when `old` was recorded: records of a source that
    was absent then are the first observation of that source (a baseline), not changes. Dossiers in `held`
    (see unsettled_dossiers) get no status change in this run.
    """
    seen = seen or dict.fromkeys(("ep_procedures", "eurlex", "ep_votes", "council", "stage_reliable"), True)
    stubs = getattr(b, "stub_ids", set())
    items: list[dict] = []
    today = b.today
    cut = (date.fromisoformat(today) - timedelta(days=RECENT_DAYS)).isoformat()
    of: dict[str, list[tuple[dict, list[str]]]] = {}
    for it, refs in _entries(b, None):
        if it["dossier_id"] in new and all(seen.get(REF_SOURCES[r.split(":", 1)[0]]) for r in refs):
            of.setdefault(it["dossier_id"], []).append((it, refs))

    def recorded(it: dict) -> dict:
        return {**it, "id": f"chg:{it['dossier_id']}:{it['id']}", "detected_at": detected_at}

    for pid in sorted(new):
        n = new[pid]
        det = b.dossier_detail[pid]
        title = short_title(det["title"])
        src = det["sources"][0] if det.get("sources") else None
        o = old.get(pid)
        if o is None:
            if seen["eurlex" if pid in stubs else "ep_procedures"]:
                fresh = [it for it, _ in of.get(pid, []) if it["date"] >= cut]
                if not any(it["kind"] == "new_dossier" for it in fresh):
                    items.append(_item(f"chg:{pid}:new", det.get("started") or det.get("last_event") or today,
                                       "new_dossier", f"New file: {title}", pid, None, src, detected_at))  # fmt: skip
                items += [recorded(it) for it in fresh]
            continue
        # a stored stage of None was recorded from incomplete inputs: the first stage seen is a baseline
        if (
            stage_reliable
            and seen["stage_reliable"]
            and pid not in held
            and o.get("stage") is not None
            and n["stage"] != o["stage"]
        ):
            since = (det.get("status") or {}).get("since") or today
            items.append(_item(f"chg:{pid}:stage:{n['stage']}:{since}", since, "status_change",
                               f"{title}: status now “{n['label']}” (previously “{o.get('label', o.get('stage'))}”)",
                               pid, None, src, detected_at))  # fmt: skip
        known = {f"{ns}:{x}" for ns, k in REF_LISTS.items() for x in o.get(k, [])}
        items += [recorded(it) for it, refs in of.get(pid, []) if not known.intersection(refs)]
    return items


def _merge_digest(
    old: dict[str, dict],
    new: dict[str, dict],
    stage_reliable: bool = True,
    held: set[str] | frozenset[str] = frozenset(),
    rebaseline: bool = False,
    detected_at: str | None = None,
) -> dict[str, dict]:
    """Union of ids ever seen; the stage is only updated when it was computed from complete inputs
    (otherwise a known dossier keeps its stored stage and a new one is stored without a stage). A held
    dossier keeps its stored stage too, with the time it was first held (`held_since`); when the status logic
    changed (`rebaseline`) its stage is dropped instead, so its next trusted stage is a baseline."""
    out = dict(old)
    for pid, n in new.items():
        o = old.get(pid, {})
        merged = {
            **n,
            **{k: sorted(set(o.get(k, [])) | set(n[k])) for k in ("events", "votes", "council", "acts")},
        }
        if not stage_reliable or pid in held:
            merged["stage"], merged["label"] = o.get("stage"), o.get("label")
        if stage_reliable and pid in held:
            merged["held_since"] = o.get("held_since") or detected_at
            if rebaseline:
                merged["stage"] = merged["label"] = None
        out[pid] = merged
    return dict(sorted(out.items()))


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_state(b: Any, state_dir: Path, record: bool = False) -> list[dict]:
    """Return recorded change items; with record=True, detect and append new ones first."""
    act_path, dig_path = state_dir / "activity.json", state_dir / "digest.json"
    recorded: list[dict] = _read(act_path, [])
    if not record:
        return recorded
    if not b.dossier_ids:  # procedures unavailable: nothing reliable to compare
        return recorded
    new = digest(b)
    stored = _read(dig_path, None)
    detected_at = os.environ.get("EU_INTEL_NOW") or now_iso()
    present = sources_present(b)
    # Stages computed from this snapshot are stored only if its procedure and act fetches were complete, or
    # recorded which files they did not refresh completely (those dossiers are held: their stage waits).
    untrusted = incomplete_stage_sources(b)
    stages_trusted = present["stage_reliable"] and not untrusted
    old: dict[str, dict] | None = None
    seen = dict.fromkeys(present, False)
    classifier: str | None = None
    suspended_since: str | None = None
    if isinstance(stored, dict):
        if "dossiers" in stored:
            old, seen = stored["dossiers"], {**seen, **stored.get("sources", {})}
            classifier = stored.get("classifier")
            suspended_since = stored.get("status_suspended_since")
        else:  # plain {dossier_id: entry} map
            old, seen = stored, dict.fromkeys(present, True)
    held = set(unsettled_dossiers(b, old)) & set(new) if stages_trusted else set()
    # Status changes need trusted stages on both sides, computed by the same classifier; after a change of
    # the status logic the stored stages are re-baselined (updated without recording changes).
    record_status = stages_trusted and classifier == CLASSIFIER_VERSION
    if old is not None:
        known = {it["id"] for it in recorded}
        fresh = [it for it in diff(old, new, b, detected_at, record_status, seen, held) if it["id"] not in known]
        recorded = recorded + fresh
        _write(act_path, recorded)
    elif not act_path.exists():
        _write(act_path, [])
    dossiers = _merge_digest(old or {}, new, stages_trusted, held, classifier != CLASSIFIER_VERSION, detected_at)
    suspended_since = None if stages_trusted else suspended_since or detected_at
    _write(dig_path, {
        "version": 1,
        "classifier": CLASSIFIER_VERSION if stages_trusted else classifier,
        "status_suspended_since": suspended_since,
        "sources": {k: bool(seen.get(k)) or v for k, v in present.items()},
        "dossiers": dossiers,
    })  # fmt: skip
    if untrusted and present["stage_reliable"]:
        manifest = getattr(b.s, "manifest", None) or {}
        how = ", ".join(f"{s} {getattr(manifest.get(s), 'status', 'missing')}" for s in untrusted)
        _warn(f"Status changes not recorded (suspended since {suspended_since}): the last fetch of {how} was not "
              "complete and did not record which files it left unsettled.")  # fmt: skip
    if held:
        since = min(dossiers[pid]["held_since"] for pid in held)
        _warn(f"Status changes held for {len(held)} files whose procedure or act data this run did not refresh "
              f"completely (the earliest held since {since}): {', '.join(sorted(held)[:20])}"
              + (" …" if len(held) > 20 else ""))  # fmt: skip
    return recorded


def merge(
    recorded: list[dict], snapshot: list[tuple[dict, list[str]]], today: str, limit: int = PUBLIC_LIMIT
) -> list[dict]:
    """Recorded changes first-class; the snapshot's items (snapshot_entries) fill in, except those resting on a record
    that a recorded change names: its step (by id or key), its vote or its Council vote."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in recorded:
        key = it["id"].split(":", 2)[-1] if it["id"].startswith("chg:") else it["id"]
        seen.update(item_refs(key), [it["id"]], [f"vote:{it['vote_id']}"] if it.get("vote_id") else [])
        out.append(it)
    for it, refs in snapshot:
        if it["id"] in seen or seen.intersection(refs):
            continue
        out.append(it)
    out = [it for it in out if it["date"] <= today]
    out.sort(key=lambda x: (x["date"], x.get("detected_at") or "", x["id"]), reverse=True)
    return out[:limit]
