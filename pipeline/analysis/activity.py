"""Change detection between snapshots, and the public activity list.

State (committed, data/state/):
    digest.json    {version, classifier, sources: {source: seen?}, dossiers: {dossier_id: {stage, label,
                   title, events[], votes[], council[], acts[]}}}
                   ids are the union of everything ever seen, so a temporarily missing source
                   never makes old records look "new" when it comes back; records of a source seen
                   for the first time are a baseline, not changes.
    activity.json  append-only list of verified changes, each with `detected_at`.

What counts as a change (substantive only — never a metadata refresh such as a new retrieved_at):
    new_dossier     a procedure id not seen before
    status_change   the derived lifecycle stage changed. Recorded only when procedure AND act data are
                    present, the manifest says this snapshot's ep_procedures and eurlex fetches were
                    complete ("ok"; a failed or partial fetch may carry degraded records, so the stored
                    stages are kept until a complete one), and the stored stages were computed by the
                    same CLASSIFIER_VERSION (otherwise the stages are re-baselined silently)
    milestone       a new recorded procedural event id
    publication     a new legal act linked to the dossier
    ep_vote         a new indexed EP vote linked to the dossier
    council_vote    a new Council vote linked to the dossier

Without recorded history, the public activity.json lists recent dated events from the snapshot
itself, with detected_at = null (we did not observe *when* they appeared).
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pipeline.snapshot import now_iso

RECENT_DAYS = 120
PUBLIC_LIMIT = 400
# Version of the lifecycle-stage logic (pipeline/analysis/status.py and the inputs build.py gives it).
# Bump it whenever the status logic changes: the next recorded run then re-baselines every stored stage
# instead of reporting the reclassification as status changes.
CLASSIFIER_VERSION = "2026-10-23.1"
# Sources whose fetch must have been complete ("ok") for a stage difference to count as a change.
STAGE_SOURCES = ("ep_procedures", "eurlex")
SNAPSHOT_EVENT_KINDS = {
    "proposal",
    "committee_report",
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
def snapshot_items(b: Any, days: int = RECENT_DAYS) -> list[dict]:
    """Recent dated events present in the current snapshot (detected_at = None)."""
    today = b.today
    cut = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    out: list[dict] = []
    for pid in b.dossier_ids:
        det = b.dossier_detail[pid]
        title = short_title(det["title"])
        for e in det["timeline"]:
            if (
                e["state"] != "done"
                or not (cut <= e["date"] <= today)
                or e["kind"] not in SNAPSHOT_EVENT_KINDS
                or e.get("after_end_of_validity")  # recorded for after the act's validity ended
            ):
                continue
            out.append(
                _item(
                    f"ev:{e['id']}",
                    e["date"],
                    _event_kind(e["kind"]),
                    f"{title}: {e['title']}",
                    pid,
                    e.get("vote_id"),
                    e.get("source"),
                )  # fmt: skip
            )
    # a vote that is already a dossier milestone (its timeline event) is listed once, as that milestone
    milestone_votes = {i["vote_id"] for i in out if i.get("vote_id")}
    milestone_ids = {i["id"] for i in out}
    for v in b.vote_summary.values():
        if v["kind"] in ("final", "motion") and cut <= v["date"] <= today and v["id"] not in milestone_votes:
            res = {"adopted": "adopted", "rejected": "rejected", "lapsed": "lapsed"}.get(
                v["outcome"], "voted on"
            )
            out.append(_item(f"vote:{v['id']}", v["date"], "ep_vote", f"Parliament {res}: {v['display_title']}",
                             v.get("dossier_id"), v["id"], v.get("source")))  # fmt: skip
    for cv in b.council_public:
        if cut <= cv["date"] <= today and f"ev:council-{cv['id']}" not in milestone_ids:
            out.append(_item(f"council:{cv['id']}", cv["date"], "council_vote", f"Council vote: {cv['title']}",
                             cv.get("dossier_id"), None, cv.get("source")))  # fmt: skip
    return out


# --------------------------------------------------------------------------------------- digest + diff
def digest(b: Any) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pid in b.dossier_ids:
        det = b.dossier_detail[pid]
        out[pid] = {
            "stage": det["stage"],
            "label": det["status_label"],
            "title": det["title"],
            "events": sorted(e["id"] for e in det["timeline"] if not e["id"].startswith("act-")),
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


def incomplete_stage_sources(b: Any) -> list[str]:
    """STAGE_SOURCES whose last fetch (manifest) was not complete ("ok"), e.g. a run in which OEIL or
    EUR-Lex failed for some records. A snapshot without a manifest (tests, local builds) is trusted."""
    manifest = getattr(b.s, "manifest", None) or {}
    if not manifest:
        return []
    out = []
    for source in STAGE_SOURCES:
        st = manifest.get(source)
        if st is None or getattr(st, "status", None) != "ok":
            out.append(source)
    return out


def diff(
    old: dict[str, dict],
    new: dict[str, dict],
    b: Any,
    detected_at: str,
    stage_reliable: bool,
    seen: dict[str, bool] | None = None,
) -> list[dict]:
    """Verified substantive changes from `old` to `new` digests.

    `seen` says which sources were already present when `old` was recorded: records of a source that
    was absent then are the first observation of that source (a baseline), not changes.
    """
    seen = seen or dict.fromkeys(("ep_procedures", "eurlex", "ep_votes", "council", "stage_reliable"), True)
    stubs = getattr(b, "stub_ids", set())
    items: list[dict] = []
    today = b.today
    for pid in sorted(new):
        n = new[pid]
        det = b.dossier_detail[pid]
        title = short_title(det["title"])
        src = det["sources"][0] if det.get("sources") else None
        o = old.get(pid)
        if o is None:
            if seen["eurlex" if pid in stubs else "ep_procedures"]:
                items.append(_item(f"chg:{pid}:new", det.get("started") or det.get("last_event") or today,
                                   "new_dossier", f"New file: {title}", pid, None, src, detected_at))  # fmt: skip
            continue
        # a stored stage of None was recorded from incomplete inputs: the first stage seen is a baseline
        if stage_reliable and seen["stage_reliable"] and o.get("stage") is not None and n["stage"] != o["stage"]:
            since = (det.get("status") or {}).get("since") or today
            items.append(_item(f"chg:{pid}:stage:{n['stage']}:{since}", since, "status_change",
                               f"{title}: status now “{n['label']}” (previously “{o.get('label', o.get('stage'))}”)",
                               pid, None, src, detected_at))  # fmt: skip
        if seen["ep_procedures"]:
            ev_by_id = {e["id"]: e for e in det["timeline"]}
            for eid in sorted(set(n["events"]) - set(o.get("events", []))):
                e = ev_by_id.get(eid)
                if e:
                    kind = "milestone" if e["kind"] == "proposal" else _event_kind(e["kind"])
                    items.append(_item(f"chg:{pid}:ev:{eid}", e["date"], kind, f"{title}: {e['title']}", pid,
                                       e.get("vote_id"), e.get("source"), detected_at))  # fmt: skip
        if seen["ep_votes"]:
            votes = {v["id"]: v for v in det["ep_votes"]}
            for vid in sorted(set(n["votes"]) - set(o.get("votes", []))):
                v = votes[vid]
                items.append(_item(f"chg:{pid}:vote:{vid}", v["date"], "ep_vote",
                                   f"New Parliament vote: {v['display_title']}", pid, vid, v.get("source"),
                                   detected_at))  # fmt: skip
        if seen["council"]:
            cvs = {c["id"]: c for c in det["council_votes"]}
            for cid in sorted(set(n["council"]) - set(o.get("council", []))):
                c = cvs[cid]
                items.append(_item(f"chg:{pid}:council:{cid}", c["date"], "council_vote",
                                   f"Council vote: {c['title']}", pid, None, c.get("source"), detected_at))  # fmt: skip
        if seen["eurlex"]:
            acts = {a["celex"]: a for a in det["acts"]}
            for celex in sorted(set(n["acts"]) - set(o.get("acts", []))):
                a = acts[celex]
                items.append(_item(f"chg:{pid}:act:{celex}",
                                   a.get("date_publication") or a.get("date_document") or today, "publication",
                                   f"{title}: legal act {celex} recorded by EUR-Lex", pid, None, None,
                                   detected_at))  # fmt: skip
    return items


def _merge_digest(old: dict[str, dict], new: dict[str, dict], stage_reliable: bool = True) -> dict[str, dict]:
    """Union of ids ever seen; the stage is only updated when it was computed from complete inputs
    (otherwise a known dossier keeps its stored stage and a new one is stored without a stage)."""
    out = dict(old)
    for pid, n in new.items():
        o = old.get(pid, {})
        merged = {
            **n,
            **{k: sorted(set(o.get(k, [])) | set(n[k])) for k in ("events", "votes", "council", "acts")},
        }
        if not stage_reliable:
            merged["stage"], merged["label"] = o.get("stage"), o.get("label")
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
    # Stages computed from this snapshot are stored only if its procedure and act fetches were complete.
    stages_trusted = present["stage_reliable"] and not incomplete_stage_sources(b)
    old: dict[str, dict] | None = None
    seen = dict.fromkeys(present, False)
    classifier: str | None = None
    if isinstance(stored, dict):
        if "dossiers" in stored:
            old, seen = stored["dossiers"], {**seen, **stored.get("sources", {})}
            classifier = stored.get("classifier")
        else:  # plain {dossier_id: entry} map
            old, seen = stored, dict.fromkeys(present, True)
    # Status changes need trusted stages on both sides, computed by the same classifier; after a change of
    # the status logic the stored stages are re-baselined (updated without recording changes).
    record_status = stages_trusted and classifier == CLASSIFIER_VERSION
    if old is not None:
        known = {it["id"] for it in recorded}
        fresh = [it for it in diff(old, new, b, detected_at, record_status, seen) if it["id"] not in known]
        recorded = recorded + fresh
        _write(act_path, recorded)
    elif not act_path.exists():
        _write(act_path, [])
    _write(dig_path, {
        "version": 1,
        "classifier": CLASSIFIER_VERSION if stages_trusted else classifier,
        "sources": {k: bool(seen.get(k)) or v for k, v in present.items()},
        "dossiers": _merge_digest(old or {}, new, stages_trusted),
    })  # fmt: skip
    return recorded


def merge(recorded: list[dict], snapshot: list[dict], today: str, limit: int = PUBLIC_LIMIT) -> list[dict]:
    """Recorded changes first-class; snapshot-derived recent events fill in (dedup by underlying id)."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in recorded:
        key = it["id"].split(":", 2)[-1] if it["id"].startswith("chg:") else it["id"]
        seen.add(key)
        seen.add(it["id"])
        out.append(it)
    for it in snapshot:
        raw = it["id"].split(":", 1)[-1]
        if it["id"] in seen or f"ev:{raw}" in seen or raw in seen:
            continue
        out.append(it)
    out = [it for it in out if it["date"] <= today]
    out.sort(key=lambda x: (x["date"], x.get("detected_at") or "", x["id"]), reverse=True)
    return out[:limit]
