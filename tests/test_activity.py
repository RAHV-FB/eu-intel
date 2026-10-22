"""Change detection (pipeline/analysis/activity.py) on the TEST-ONLY fixture in tests/fixtures/build/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pipeline.build import build

FIX = Path(__file__).parent / "fixtures" / "build"
TODAY = "2026-10-22"


def _run(base: Path, monkeypatch: pytest.MonkeyPatch, record: bool, now: str) -> list[dict]:
    monkeypatch.setenv("EU_INTEL_RECORD_ACTIVITY", "1" if record else "0")
    monkeypatch.setenv("EU_INTEL_NOW", now)
    out = base / "public"
    build(out=out, snapshot=base / "snapshot", curated=FIX / "curated", state=base / "state", today=TODAY)
    return json.loads((out / "activity.json").read_text(encoding="utf-8"))


def _edit(path: Path, fn) -> None:
    recs = json.loads(path.read_text(encoding="utf-8"))
    fn(recs)
    path.write_text(json.dumps(recs), encoding="utf-8")


@pytest.fixture
def base(tmp_path: Path) -> Path:
    shutil.copytree(FIX / "snapshot", tmp_path / "snapshot")
    return tmp_path


def test_without_history_lists_snapshot_events(base: Path, monkeypatch: pytest.MonkeyPatch):
    items = _run(base, monkeypatch, record=False, now="2099-01-01T00:00:00Z")
    assert not (base / "state").exists()  # nothing written without --record
    assert all(i["detected_at"] is None for i in items)
    assert [i["date"] for i in items] == sorted((i["date"] for i in items), reverse=True)
    assert all(i["date"] <= TODAY for i in items)


def test_first_record_sets_baseline_without_changes(base: Path, monkeypatch: pytest.MonkeyPatch):
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    assert (base / "state" / "digest.json").exists()
    assert json.loads((base / "state" / "activity.json").read_text()) == []


def test_metadata_refresh_is_not_a_change(base: Path, monkeypatch: pytest.MonkeyPatch):
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")

    def touch(recs):
        for r in recs:
            r["source"]["retrieved_at"] = "2099-12-31T00:00:00Z"

    for f in ("ep_procedures/procedures.json", "eurlex/acts.json", "ep_votes/votes.json"):
        _edit(base / "snapshot" / f, touch)
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert json.loads((base / "state" / "activity.json").read_text()) == []


def test_new_records_are_detected_once(base: Path, monkeypatch: pytest.MonkeyPatch):
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")

    def add_event(recs):
        p = next(r for r in recs if r["id"] == "2099-0003")
        e = dict(p["events"][-1])
        e.update(
            id="2099-0003-ev9", date="2026-10-20", kind="council_position", title="TEST Council position"
        )
        p["events"].append(e)

    _edit(base / "snapshot" / "ep_procedures" / "procedures.json", add_event)
    items = _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    rec = json.loads((base / "state" / "activity.json").read_text())
    assert [r["id"] for r in rec] == ["chg:2099-0003:ev:2099-0003-ev9"]
    assert rec[0]["detected_at"] == "2026-10-23T10:00:00Z" and rec[0]["date"] == "2026-10-20"
    assert items[0]["id"] == rec[0]["id"]
    # the same snapshot again: nothing new is appended
    _run(base, monkeypatch, record=True, now="2026-10-24T10:00:00Z")
    assert len(json.loads((base / "state" / "activity.json").read_text())) == 1
    # recorded changes show up on the dossier
    det = json.loads((base / "public" / "dossiers" / "2099-0003.json").read_text())
    assert [c["id"] for c in det["changes"]] == [rec[0]["id"]]


def test_missing_source_does_not_create_false_changes(base: Path, monkeypatch: pytest.MonkeyPatch):
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    acts = base / "snapshot" / "eurlex" / "acts.json"
    saved = acts.read_bytes()
    acts.unlink()  # EUR-Lex temporarily unavailable
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert json.loads((base / "state" / "activity.json").read_text()) == []
    acts.write_bytes(saved)  # ... and back: still nothing changed
    _run(base, monkeypatch, record=True, now="2026-10-24T10:00:00Z")
    assert json.loads((base / "state" / "activity.json").read_text()) == []


def test_first_appearance_of_a_source_is_a_baseline(base: Path, monkeypatch: pytest.MonkeyPatch):
    votes = base / "snapshot" / "ep_votes"
    saved = {f.name: f.read_bytes() for f in votes.iterdir()}
    procs = base / "snapshot" / "ep_procedures" / "procedures.json"
    saved_procs = procs.read_bytes()
    for f in votes.iterdir():
        f.unlink()
    procs.unlink()
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")  # only EUR-Lex-derived dossiers
    for name, data in saved.items():
        (votes / name).write_bytes(data)
    procs.write_bytes(saved_procs)
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")  # procedures + votes arrive
    assert json.loads((base / "state" / "activity.json").read_text()) == []
    dig = json.loads((base / "state" / "digest.json").read_text())
    assert dig["sources"]["ep_procedures"] and dig["sources"]["ep_votes"]
