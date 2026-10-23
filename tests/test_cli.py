"""python -m pipeline: fetch time limits and interrupts, per-source validation, manifest restore."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time
import types
from pathlib import Path

import pytest

import pipeline.__main__ as cli
from pipeline import snapshot
from pipeline.models.entities import SourceStatus

FIX = Path(__file__).parent / "fixtures" / "build" / "snapshot"


class DummyHttp:
    def __init__(self):
        self.aborted = False

    def abort(self):
        self.aborted = True


@pytest.fixture
def snap(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_DEADLINE", raising=False)
    return tmp_path


def fake_sources(monkeypatch, http, **fetchers):
    sources = {}
    for name, fn in fetchers.items():
        mod = types.ModuleType(f"fake_source_{name}")
        mod.fetch = fn  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
        sources[name] = mod.__name__
    monkeypatch.setattr(cli, "SOURCES", sources)
    monkeypatch.setattr(cli, "default_http", lambda: http)


def ok(name):
    def fetch(http):
        return SourceStatus(source=name, status="ok", attempted_at="t", fetched_at="t", records={"n": 1})

    return fetch


def manifest(root: Path) -> dict:
    return json.loads((root / "_manifest.json").read_text())


def test_sources_are_not_started_after_the_run_deadline(snap, monkeypatch):
    http = DummyHttp()
    fake_sources(monkeypatch, http, a=ok("a"), b=ok("b"))
    assert cli.cmd_fetch([]) == 0
    monkeypatch.setenv("EU_INTEL_FETCH_DEADLINE", str(time.time() - 1))
    called = []

    def never(h):
        called.append(1)
        raise AssertionError("must not start")

    fake_sources(monkeypatch, http, a=never, b=never)
    assert cli.cmd_fetch([]) == 1
    assert called == []
    m = manifest(snap)
    assert m["a"]["status"] == "partial" and m["a"]["records"] == {"n": 1} and m["a"]["fetched_at"] == "t"
    assert "fetch deadline passed" in m["a"]["note"]


def test_interrupt_records_the_source_and_stops(snap, monkeypatch):
    http = DummyHttp()
    fake_sources(monkeypatch, http, a=ok("a"), b=ok("b"), c=ok("c"))
    cli.cmd_fetch([])
    after = []

    def interrupted(h):
        os.kill(os.getpid(), signal.SIGINT)  # as `timeout --signal=INT` does
        time.sleep(5)
        raise AssertionError("SIGINT was not delivered")

    def later(h):
        after.append(1)
        return ok("c")(h)

    previous = signal.getsignal(signal.SIGINT)
    fake_sources(monkeypatch, http, a=ok("a"), b=interrupted, c=later)
    assert cli.cmd_fetch([]) == 130
    assert http.aborted and after == []
    assert signal.getsignal(signal.SIGINT) == previous
    m = manifest(snap)
    assert m["b"]["status"] == "partial" and "Interrupted" in m["b"]["note"] and m["b"]["records"] == {"n": 1}


def test_unknown_source_is_rejected_before_any_fetch(snap, monkeypatch):
    http = DummyHttp()
    called = []
    fake_sources(monkeypatch, http, a=lambda h: called.append(1))
    assert cli.cmd_fetch(["a", "nope"]) == 2 and called == []


def test_manifest_is_written_atomically(snap):
    snapshot.update_manifest(SourceStatus(source="a", status="ok", attempted_at="t"))
    assert manifest(snap)["a"]["status"] == "ok"
    assert not list(snap.glob("*.tmp"))


def test_restore_manifest_entries(snap):
    (snap / "_manifest.json").write_text(
        json.dumps(
            {
                "train": {"source": "train", "status": "bogus", "attempted_at": "2026-10-26T06:00:00Z"},
                "council": {"source": "council", "status": "ok", "attempted_at": "x", "records": {"votes": 9}},
                "newsrc": {"source": "newsrc", "status": "ok", "attempted_at": "x"},
            }
        )
    )
    prev = snap / "prev.json"
    prev.write_text(
        json.dumps(
            {
                "train": {
                    "source": "train",
                    "status": "ok",
                    "attempted_at": "2026-10-19T06:00:00Z",
                    "fetched_at": "2026-10-19T06:30:00Z",
                    "records": {"files": 1492},
                    "note": "statuses: ...",
                }
            }
        )
    )
    assert cli.main(["restore-manifest", "--previous", str(prev), "train", "newsrc"]) == 0
    m = manifest(snap)
    assert m["train"]["status"] == "partial" and m["train"]["records"] == {"files": 1492}
    assert m["train"]["fetched_at"] == "2026-10-19T06:30:00Z"
    assert m["train"]["attempted_at"] == "2026-10-26T06:00:00Z"
    assert "failed validation" in m["train"]["note"] and "statuses: ..." in m["train"]["note"]
    assert "newsrc" not in m  # no committed entry: removed
    assert m["council"]["records"] == {"votes": 9}  # other sources untouched
    assert cli.main(["restore-manifest", "--previous", str(prev), "../x"]) == 2


def test_validate_list_failing(snap, monkeypatch, capsys):
    shutil.copytree(FIX, snap, dirs_exist_ok=True)
    assert cli.main(["validate", "--list-failing"]) == 0
    assert capsys.readouterr().out == ""
    (snap / "council" / "votes.json").write_text("[{", encoding="utf-8")
    assert cli.main(["validate", "--list-failing"]) == 0
    captured = capsys.readouterr()
    assert captured.out.split() == ["council"]
    assert "council/votes.json: unreadable" in captured.err


def test_validate_built_needs_the_built_output_and_fails_on_its_contradictions(snap, monkeypatch, tmp_path_factory, capsys):
    # The workflows validated only before `pipeline build`, when public/data (not committed) is missing, so the
    # built-output checks were skipped without a word. `--built` (run after the build) fails without it, and on a
    # contradiction: vote 156022 (AI Act mandate, 14 Jun 2023) as built, then with its outcome turned to "rejected".
    import pipeline.validate as val

    shutil.copytree(FIX, snap, dirs_exist_ok=True)
    root = tmp_path_factory.mktemp("root")
    monkeypatch.setattr(val, "ROOT", root)
    assert cli.main(["validate"]) == 0
    assert "built output not checked" in capsys.readouterr().out
    assert cli.main(["validate", "--built"]) == 1
    assert f"ERROR no built output in {root / 'public' / 'data'}" in capsys.readouterr().out
    votes = root / "public" / "data" / "votes"
    votes.mkdir(parents=True)
    margin = {"rule": "votes_cast", "threshold": 264, "distance": 235, "relative": 0.4459,
              "label": "Majority reached: 235 votes more than needed"}  # fmt: skip
    (votes / "156022.json").write_text(json.dumps({"id": "156022", "outcome": "adopted", "margin": margin}))
    assert cli.main(["validate", "--built"]) == 0
    out = capsys.readouterr().out
    assert "validate: OK" in out and "not checked" not in out
    (votes / "156022.json").write_text(json.dumps({"id": "156022", "outcome": "rejected", "margin": margin}))
    assert cli.main(["validate", "--built"]) == 1
    assert "ERROR public votes/156022.json: vote 156022: margin distance 235 contradicts outcome 'rejected'" in (
        capsys.readouterr().out
    )
    with pytest.raises(SystemExit):  # the refresh's per-source check reads the snapshot only
        cli.main(["validate", "--built", "--list-failing"])
