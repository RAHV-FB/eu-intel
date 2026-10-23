"""Change detection (pipeline/analysis/activity.py) on the TEST-ONLY fixture in tests/fixtures/build/."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pipeline.build import build

FIX = Path(__file__).parent / "fixtures" / "build"
TODAY = "2026-10-22"
ATOM = "{http://www.w3.org/2005/Atom}"


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


# ---------------------------------------------------------------- status changes and their safeguards
def _withdraw(recs, pid: str = "2099-0003"):
    """A Commission withdrawal recorded for `pid`: its derived stage changes."""
    p = next(r for r in recs if r["id"] == pid)
    e = dict(p["events"][-1])
    e.update(
        id=f"{pid}-ev9",
        date="2026-10-20",
        kind="withdrawal",
        institution="Commission",
        title="TEST Commission withdrew the proposal",
        source={**e["source"], "identifier": f"{pid}-ev9"},
    )
    p["events"].append(e)


def _set_status(base: Path, source: str, status: str) -> None:
    path = base / "snapshot" / "_manifest.json"
    m = json.loads(path.read_text(encoding="utf-8"))
    m[source]["status"] = status
    path.write_text(json.dumps(m), encoding="utf-8")


def _status_changes(base: Path) -> list[dict]:
    return [r for r in json.loads((base / "state" / "activity.json").read_text()) if r["kind"] == "status_change"]


def _stage(base: Path, pid: str) -> str | None:
    return json.loads((base / "state" / "digest.json").read_text())["dossiers"][pid]["stage"]


def test_stage_change_is_recorded_after_a_complete_fetch(base: Path, monkeypatch: pytest.MonkeyPatch):
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    before = _stage(base, "2099-0003")
    _edit(base / "snapshot" / "ep_procedures" / "procedures.json", _withdraw)
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    changes = _status_changes(base)
    assert len(changes) == 1 and changes[0]["dossier_id"] == "2099-0003"
    assert _stage(base, "2099-0003") == "withdrawn" != before


@pytest.mark.parametrize("source", ["ep_procedures", "eurlex"])
@pytest.mark.parametrize("status", ["partial", "failed"])
def test_no_status_change_from_an_incomplete_fetch(
    base: Path, monkeypatch: pytest.MonkeyPatch, source: str, status: str
):
    """A run whose procedure or act fetch was incomplete may carry degraded records: no status change is
    recorded from it and the stored stage is kept; a real change is recorded by the next complete run."""
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    before = _stage(base, "2099-0003")
    _edit(base / "snapshot" / "ep_procedures" / "procedures.json", _withdraw)
    _set_status(base, source, status)
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert _status_changes(base) == []
    assert _stage(base, "2099-0003") == before
    rec = json.loads((base / "state" / "activity.json").read_text())
    assert [r["id"] for r in rec] == ["chg:2099-0003:ev:2099-0003-ev9"]  # other changes are still recorded
    _set_status(base, source, "ok")
    _run(base, monkeypatch, record=True, now="2026-10-30T10:00:00Z")
    changes = _status_changes(base)
    assert len(changes) == 1 and changes[0]["detected_at"] == "2026-10-30T10:00:00Z"


def test_degraded_run_then_recovery_leaves_no_false_changes(base: Path, monkeypatch: pytest.MonkeyPatch):
    """The audit replay: a partial run changes a stage, the next run restores the record. The append-only
    log must not keep a pair of false status changes."""
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    procs = base / "snapshot" / "ep_procedures" / "procedures.json"
    saved = procs.read_bytes()
    _edit(procs, _withdraw)
    _set_status(base, "ep_procedures", "partial")
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    procs.write_bytes(saved)
    _set_status(base, "ep_procedures", "ok")
    _run(base, monkeypatch, record=True, now="2026-10-30T10:00:00Z")
    assert _status_changes(base) == []


def test_new_dossier_from_an_incomplete_fetch_gets_its_stage_later(base: Path, monkeypatch: pytest.MonkeyPatch):
    pid = "2099-0002"  # a file without a legal act: it only exists through its procedure record
    procs = base / "snapshot" / "ep_procedures" / "procedures.json"
    saved = json.loads(procs.read_text())
    _edit(procs, lambda r: r.remove(next(x for x in r if x["id"] == pid)))
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    _edit(procs, lambda r: r.append(next(x for x in saved if x["id"] == pid)))
    _set_status(base, "ep_procedures", "partial")
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert _stage(base, pid) is None  # not trusted yet
    _set_status(base, "ep_procedures", "ok")
    _edit(procs, lambda r: _withdraw(r, pid))
    _run(base, monkeypatch, record=True, now="2026-10-30T10:00:00Z")
    assert _status_changes(base) == []  # the first trusted stage is a baseline
    assert _stage(base, pid) == "withdrawn"


def test_classifier_change_rebaselines_without_status_changes(base: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.analysis import activity

    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    assert json.loads((base / "state" / "digest.json").read_text())["classifier"] == activity.CLASSIFIER_VERSION
    monkeypatch.setattr(activity, "CLASSIFIER_VERSION", "test-next")  # new status logic ...
    _edit(base / "snapshot" / "ep_procedures" / "procedures.json", _withdraw)  # ... classifies differently
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert _status_changes(base) == []
    dig = json.loads((base / "state" / "digest.json").read_text())
    assert dig["classifier"] == "test-next" and dig["dossiers"]["2099-0003"]["stage"] == "withdrawn"
    _edit(base / "snapshot" / "ep_procedures" / "procedures.json", lambda r: None)
    _run(base, monkeypatch, record=True, now="2026-10-24T10:00:00Z")  # same logic again: nothing new
    assert _status_changes(base) == []


def test_classifier_is_stored_only_with_trusted_stages(base: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.analysis import activity

    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    monkeypatch.setattr(activity, "CLASSIFIER_VERSION", "test-next")
    _set_status(base, "eurlex", "partial")
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    # the stored stages are still those of the previous logic: they are re-baselined by a later trusted run
    assert json.loads((base / "state" / "digest.json").read_text())["classifier"] != "test-next"


# ---------------------------------------------------------------- per-dossier holds (unsettled files of a fetch)
def _set_unsettled(base: Path, source: str, status: str, stamp: str | None = None, **unsettled) -> None:
    """The source's fetch was `status` and recorded what it left unsettled (stamped with its manifest entry's
    attempted_at unless `stamp` says otherwise)."""
    _set_status(base, source, status)
    m = json.loads((base / "snapshot" / "_manifest.json").read_text(encoding="utf-8"))
    (base / "snapshot" / source).mkdir(exist_ok=True)
    state = {"unsettled": {"attempted_at": stamp or m[source]["attempted_at"], **unsettled}}
    (base / "snapshot" / source / "_state.json").write_text(json.dumps(state), encoding="utf-8")


def test_a_pending_file_no_longer_suspends_every_status_change(
    base: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """ep_procedures stays 'partial' while one file is pending (e.g. its OEIL page fails): the other dossiers'
    status changes are still recorded; the pending one keeps its stored stage, with a warning."""
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    before = _stage(base, "2099-0002")
    procs = base / "snapshot" / "ep_procedures" / "procedures.json"
    _edit(procs, _withdraw)  # 2099-0003: a real change
    _edit(procs, lambda r: _withdraw(r, "2099-0002"))  # 2099-0002: changed, but its fetch did not settle
    _set_unsettled(base, "ep_procedures", "partial", ids=["2099-0002"])
    with caplog.at_level("WARNING", logger="pipeline.analysis.activity"):
        _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert [c["dossier_id"] for c in _status_changes(base)] == ["2099-0003"]
    assert _stage(base, "2099-0002") == before
    dig = json.loads((base / "state" / "digest.json").read_text())
    assert dig["dossiers"]["2099-0002"]["held_since"] == "2026-10-23T10:00:00Z"
    assert "Status changes held for 1 files" in caplog.text and "2099-0002" in caplog.text
    # the next run refreshes it: its change is recorded then, once
    _set_unsettled(base, "ep_procedures", "ok", ids=[])
    _run(base, monkeypatch, record=True, now="2026-10-30T10:00:00Z")
    changes = _status_changes(base)
    assert [(c["dossier_id"], c["detected_at"]) for c in changes] == [
        ("2099-0003", "2026-10-23T10:00:00Z"),
        ("2099-0002", "2026-10-30T10:00:00Z"),
    ]
    assert "held_since" not in json.loads((base / "state" / "digest.json").read_text())["dossiers"]["2099-0002"]


def test_a_degraded_act_held_by_eurlex_leaves_no_false_changes(base: Path, monkeypatch: pytest.MonkeyPatch):
    """The audit replay for EUR-Lex: an act is missing from one run (e.g. a short answer) and back in the next.
    The fetch names it as unsettled, so neither the loss nor the recovery is logged as a status change."""
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    acts = base / "snapshot" / "eurlex" / "acts.json"
    saved = acts.read_bytes()
    before = _stage(base, "2099-0001")
    _edit(acts, lambda r: r.remove(next(a for a in r if a["celex"] == "32099R0001")))
    _set_unsettled(base, "eurlex", "partial", acts=["32099R0001"], procedures=[])
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert _stage(base, "2099-0001") == before  # held: the stage without the act was not stored
    acts.write_bytes(saved)
    _set_unsettled(base, "eurlex", "ok", acts=[], procedures=[])
    _run(base, monkeypatch, record=True, now="2026-10-30T10:00:00Z")
    assert _status_changes(base) == []
    # a notice or act change named by procedure reference is held the same way
    _edit(acts, lambda r: r.remove(next(a for a in r if a["celex"] == "32099R0001")))
    _set_unsettled(base, "eurlex", "partial", acts=[], procedures=["2099/0001(COD)"])
    _run(base, monkeypatch, record=True, now="2026-11-06T10:00:00Z")
    assert _status_changes(base) == []
    _set_unsettled(base, "eurlex", "ok", acts=[], procedures=[])  # still without the act: now a real change
    _run(base, monkeypatch, record=True, now="2026-11-13T10:00:00Z")
    assert [c["dossier_id"] for c in _status_changes(base)] == ["2099-0001"]


def test_an_unsettled_record_of_another_fetch_does_not_count(
    base: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """A state file from an earlier fetch (e.g. restored after a failed validation) says nothing about the
    current data: the partial source suspends status changes as before, and the build says since when."""
    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    _edit(base / "snapshot" / "ep_procedures" / "procedures.json", _withdraw)
    _set_unsettled(base, "ep_procedures", "partial", stamp="2026-10-15T00:00:00Z", ids=[])
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    with caplog.at_level("WARNING", logger="pipeline.analysis.activity"):
        _run(base, monkeypatch, record=True, now="2026-10-30T10:00:00Z")
    assert _status_changes(base) == []
    assert "Status changes not recorded (suspended since 2026-10-23T10:00:00Z)" in caplog.text
    assert "ep_procedures partial" in caplog.text
    _set_unsettled(base, "ep_procedures", "partial", ids=[])  # this fetch's own record: trusted again
    _run(base, monkeypatch, record=True, now="2026-11-06T10:00:00Z")
    assert len(_status_changes(base)) == 1
    assert json.loads((base / "state" / "digest.json").read_text())["status_suspended_since"] is None


def test_held_dossier_is_rebaselined_after_a_classifier_change(base: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.analysis import activity

    _run(base, monkeypatch, record=True, now="2026-10-22T10:00:00Z")
    monkeypatch.setattr(activity, "CLASSIFIER_VERSION", "test-next")
    _edit(base / "snapshot" / "ep_procedures" / "procedures.json", _withdraw)
    _set_unsettled(base, "ep_procedures", "partial", ids=["2099-0003"])
    _run(base, monkeypatch, record=True, now="2026-10-23T10:00:00Z")
    assert _stage(base, "2099-0003") is None  # stored by the previous logic: not compared with the new one
    _set_unsettled(base, "ep_procedures", "ok", ids=[])
    _run(base, monkeypatch, record=True, now="2026-10-30T10:00:00Z")
    assert _status_changes(base) == [] and _stage(base, "2099-0003") == "withdrawn"


SNAP_VOTES = Path(__file__).resolve().parent.parent / "data" / "snapshot" / "ep_votes" / "votes.json"


@pytest.mark.skipif(not SNAP_VOTES.exists(), reason="no snapshot")
def test_feed_names_parliaments_step_in_consultation_and_consent_files():
    from types import SimpleNamespace

    from pipeline.analysis.activity import snapshot_items
    from tests.test_build_real_records import votes

    # published as "Parliament adopted: …" although Parliament only gives an opinion (198386, 2026/0137(NLE),
    # subject "Guidelines for the employment policies of the Member States *"; 195831, 2025/0265(CNS)) or its
    # consent (195415, 2025/0271(NLE), "EU–Mexico Interim Agreement on Trade ***"; 197472, 2025/0313(APP)).
    # 166051 (AI Act, 2021/0106(COD) ***I) is Parliament's own decision on the text and keeps "adopted".
    v = votes("198386", "195831", "195415", "197472", "166051")
    refs = {"198386": "2026/0137(NLE)", "195831": "2025/0265(CNS)", "195415": "2025/0271(NLE)",
            "197472": "2025/0313(APP)", "166051": "2021/0106(COD)"}  # fmt: skip
    summary = {vid: {"id": vid, "date": "2026-10-01", "kind": x.kind, "outcome": x.outcome, "dossier_id": None,
                     "procedure_ref": refs[vid], "display_title": f"TEST {vid}", "source": None}
               for vid, x in v.items()}  # fmt: skip
    b = SimpleNamespace(today="2026-10-22", dossier_ids=[], dossier_detail={}, dossier_summary={},
                        council_public=[], vote_summary=summary, indexed_votes=list(v.values()))  # fmt: skip
    titles = {i["vote_id"]: i["title"] for i in snapshot_items(b)}
    assert titles == {
        "198386": "Parliament delivered its opinion: TEST 198386",
        "195831": "Parliament delivered its opinion: TEST 195831",
        "195415": "Parliament gave its consent: TEST 195415",
        "197472": "Parliament gave its consent: TEST 197472",
        "166051": "Parliament adopted: TEST 166051",
    }
    # a rejected consultation or consent vote says so in the same terms
    b.vote_summary = {"195415": {**summary["195415"], "outcome": "rejected"}}
    assert snapshot_items(b)[0]["title"] == "Parliament did not give its consent: TEST 195415"


@pytest.mark.skipif(not SNAP_VOTES.exists(), reason="no snapshot")
def test_feed_says_what_a_motion_to_reject_did_to_the_text():
    from types import SimpleNamespace

    from pipeline.analysis.activity import snapshot_items
    from tests.test_build_real_records import votes

    # 199567 (2026/0325(COD), rejected 123-374-41) was published as "Parliament rejected: Reduction of methane
    # emissions … — motion to reject the Commission proposal"; 195807 (2025/0429(COD), rejected 276-286-30) as
    # "Parliament rejected: Amending Regulation (EU) 2021/1232 …", although the act was then adopted; 179804
    # (2023/0413(COD), adopted 370-264-9) did reject the Commission proposal
    v = votes("199567", "195807", "179804")
    files = {"199567": ("2026-0325", "Reduction of methane emissions in the energy sector: postponement of certain obligations"),
             "195807": ("2025-0429", "Amending Regulation (EU) 2021/1232 as regards the extension of its period of application"),
             "179804": ("2023-0413", "Monitoring framework for resilient European forests")}  # fmt: skip
    summary = {vid: {"id": vid, "date": "2026-10-01", "kind": x.kind, "kind_detail": x.kind_detail,
                     "outcome": x.outcome, "dossier_id": files[vid][0], "procedure_ref": None,
                     "display_title": f"{files[vid][1]} — motion to reject …", "source": None}
               for vid, x in v.items()}  # fmt: skip
    b = SimpleNamespace(today="2026-10-22", dossier_ids=[], dossier_detail={}, council_public=[], vote_summary=summary,
                        dossier_summary={d: {"type": "COD", "title": t} for d, t in files.values()},
                        indexed_votes=list(v.values()))  # fmt: skip
    titles = {i["vote_id"]: i["title"] for i in snapshot_items(b)}
    assert titles == {
        "199567": "Parliament did not reject the Commission proposal: Reduction of methane emissions in the energy "
        "sector: postponement of certain obligations",
        "195807": "Parliament did not reject the Council's position: Amending Regulation (EU) 2021/1232 as regards "
        "the extension of its period of application",
        "179804": "Parliament rejected the Commission proposal: Monitoring framework for resilient European forests",
    }
    # an adopted motion to reject the Council's position; without a file, the vote's title without its kind
    b.vote_summary = {"195807": {**summary["195807"], "outcome": "adopted", "dossier_id": None}}
    assert snapshot_items(b)[0]["title"] == (
        "Parliament rejected the Council's position: Amending Regulation (EU) 2021/1232 as regards the extension of "
        "its period of application"
    )


def test_discharge_decisions_are_not_headlined_as_adopted_or_rejected():
    from types import SimpleNamespace

    from pipeline.analysis.activity import is_discharge_vote, snapshot_items

    # 149084 (2021/2146(DEC), adopted 345-284-8) refused discharge to Frontex; 142787 (2021/2110(DEC), rejected)
    # rejected a proposal to postpone, so discharge was granted. Titles as in votes/index.json.
    frontex = {"id": "149084", "date": "2026-10-01", "kind": "final", "outcome": "adopted", "dossier_id": None,
               "procedure_ref": "2021/2146(DEC)", "source": None,
               "display_title": "Discharge 2020: European Border and Coast Guard Agency — final vote on the text"}  # fmt: skip
    old = {**frontex, "id": "136221", "procedure_ref": None,
           "display_title": "2019 Discharge: European Border and Coast Guard Agency — final vote on the text"}  # fmt: skip
    law = {**frontex, "id": "1", "procedure_ref": "2021/0106(COD)", "display_title": "Artificial Intelligence Act"}
    assert is_discharge_vote(frontex) and is_discharge_vote(old) and not is_discharge_vote(law)
    assert is_discharge_vote({**law, "kind": "discharge"})  # a kind of its own, when votes carry one
    b = SimpleNamespace(today="2026-10-22", dossier_ids=[], dossier_detail={}, dossier_summary={}, council_public=[],
                        vote_summary={"149084": frontex}, indexed_votes=[])  # fmt: skip
    assert snapshot_items(b)[0]["title"] == (
        "Parliament voted on a discharge decision: Discharge 2020: European Border and Coast Guard Agency"
    )


def test_consent_milestone_says_whether_consent_was_given():
    from types import SimpleNamespace

    from pipeline.analysis.activity import snapshot_items

    # 2025/0313(APP): the timeline step "Parliament voted on consent" of 6 October 2026 links vote 197472,
    # adopted 462-121-75 (published); the same feed says "Parliament gave its consent" for other consent votes
    event = {"id": "2025-0313-DEC-DCPL-2026-10-06", "date": "2026-10-06", "kind": "ep_position", "state": "done",
             "key": True, "title": "Parliament voted on consent", "vote_id": "197472", "source": None}  # fmt: skip
    vote = {"id": "197472", "date": "2026-10-06", "kind": "final", "outcome": "adopted", "outcome_basis": "published",
            "dossier_id": "2025-0313", "display_title": "x", "source": None}  # fmt: skip
    b = SimpleNamespace(today="2026-10-22", dossier_ids=["2025-0313"],
                        dossier_detail={"2025-0313": {"title": "Amending Council Regulation (EC) No 332/2002",
                                                      "timeline": [event]}},
                        dossier_summary={"2025-0313": {"type": "APP", "title": "x"}}, council_public=[],
                        vote_summary={"197472": vote}, indexed_votes=[])  # fmt: skip
    items = snapshot_items(b)
    assert [i["title"] for i in items] == ["Amending Council Regulation (EC) No 332/2002: Parliament gave its consent"]
    # an outcome not officially recorded keeps the neutral wording
    b.vote_summary = {"197472": {**vote, "outcome_basis": "derived"}}
    assert snapshot_items(b)[0]["title"].endswith(": Parliament voted on consent")


def test_council_vote_feed_item_names_the_item_voted_on_and_links_its_document():
    from types import SimpleNamespace

    from pipeline.analysis.activity import snapshot_items
    from pipeline.analysis.feeds import atom

    # ST 14700/26: every Member State voted for the NON-approval of Parliament's amendments to the 2027 draft budget;
    # the item was titled "Council vote: Amendments of the European Parliament …" and linked to the site root
    url = "https://data.consilium.europa.eu/doc/document/ST-14700-2026-INIT/EN/pdf"
    cv = {"id": "ST-14700-2026", "date": "2026-10-19", "dossier_id": None, "source": {"url": url},
          "title": "Amendments of the European Parliament to the Council's position on the draft budget for 2027",
          "display_title": "Amendments of the European Parliament to the Council's position on the draft budget for "
          "2027 – Non-approval of the European Parliament's amendment(s)"}  # fmt: skip
    b = SimpleNamespace(today="2026-10-22", dossier_ids=[], dossier_detail={}, dossier_summary={}, council_public=[cv],
                        vote_summary={}, indexed_votes=[])  # fmt: skip
    (item,) = snapshot_items(b)
    assert item["title"].startswith("Council vote: ") and item["title"].endswith("Non-approval of the European Parliament's amendment(s)")
    xml = atom("t", "s", "feeds/updates.xml", [item], "https://example.org/eu-intel/", "2026-10-22T00:00:00Z")
    entry = ET.fromstring(xml).find(f"{ATOM}entry")
    assert entry.find(f"{ATOM}link[@rel='alternate']").get("href") == url
