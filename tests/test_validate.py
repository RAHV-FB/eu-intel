"""pipeline/validate.py on the TEST-ONLY fixture (tests/fixtures/build/) and broken copies of it."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

from pipeline.validate import check

FIX = Path(__file__).parent / "fixtures" / "build" / "snapshot"
TODAY = "2026-10-22"


def _copy(tmp_path: Path) -> Path:
    snap = tmp_path / "snapshot"
    shutil.copytree(FIX, snap)
    return snap


def _edit(path: Path, fn) -> None:
    recs = json.loads(path.read_text(encoding="utf-8"))
    fn(recs)
    path.write_text(json.dumps(recs), encoding="utf-8")


def test_fixture_is_structurally_valid():
    rep = check(FIX, today=TODAY)
    assert rep.errors == []
    # the fixture deliberately contains an official-total discrepancy (V3): reported, not an error
    assert any("V3" in m for m in rep.warnings["ballot-totals"])
    out = io.StringIO()
    rep.print(out)
    assert "validate: OK" in out.getvalue()


def test_schema_and_duplicate_errors(tmp_path: Path):
    snap = _copy(tmp_path)
    _edit(snap / "ep_votes" / "votes.json", lambda r: r.append(dict(r[0])))  # duplicate id
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].pop("eurlex_url"))  # schema violation
    rep = check(snap, today=TODAY)
    assert any("duplicate id 'V1'" in e for e in rep.errors)
    assert any("eurlex/acts.json" in e and "eurlex_url" in e for e in rep.errors)


def test_malformed_dates_are_errors(tmp_path: Path):
    snap = _copy(tmp_path)
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(date_publication="2024-13-01"))
    rep = check(snap, today=TODAY)
    assert any("malformed date" in e for e in rep.errors)


def test_unreadable_json_is_an_error(tmp_path: Path):
    snap = _copy(tmp_path)
    (snap / "council" / "votes.json").write_text("[{", encoding="utf-8")
    rep = check(snap, today=TODAY)
    assert any("council/votes.json: unreadable" in e for e in rep.errors)


def test_referential_and_semantic_issues_are_warnings(tmp_path: Path):
    snap = _copy(tmp_path)
    _edit(snap / "ep_votes" / "ballots.json", lambda r: r[0]["favor"].append("NOPE"))
    _edit(snap / "ep_votes" / "votes.json", lambda r: r[0]["procedure_refs"].append("2099/0777(COD)"))
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(transposition_deadlines=["2030-01-01"]))

    def veto(r):
        r[0]["statements"] = ["TEST statement mentioning a veto"]

    _edit(snap / "council" / "votes.json", veto)
    rep = check(snap, today=TODAY)
    assert rep.errors == []
    assert rep.warnings["ref-mep"] and rep.warnings["ref-procedure"]
    assert rep.warnings["transposition-non-directive"]
    assert rep.warnings["veto-wording"]


def test_act_procedure_mismatch_warning(tmp_path: Path):
    snap = _copy(tmp_path)
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(procedure_refs=["2099/3521(COD)"]))
    rep = check(snap, today=TODAY)
    assert rep.warnings["act-procedure-mismatch"]
    assert rep.errors == []


def test_entry_into_force_before_the_act_is_a_warning(tmp_path: Path):
    """Cellar dates Regulation 2021/768's entry into force 1 January 2021 (its application date), before its
    adoption on 30 April 2021; a Council decision or directive taking effect on adoption stays quiet."""
    assert not check(FIX, today=TODAY).warnings["entry-into-force-before-act"]
    snap = _copy(tmp_path)

    def dates(r):
        r[0].update(entry_into_force="2024-01-01")  # regulation adopted 2024-11-20
        r[1].update(entry_into_force="2023-01-15")  # directive: in force on the day of its adoption
        r[2].update(entry_into_force="2025-03-05")  # directive: before publication, after adoption

    _edit(snap / "eurlex" / "acts.json", dates)
    w = check(snap, today=TODAY).warnings["entry-into-force-before-act"]
    assert len(w) == 1 and w[0].startswith("32099R0001: enters into force 2024-01-01, before the act")
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(entry_into_force="2024-11-25"))  # published 12-01
    w = check(snap, today=TODAY).warnings["entry-into-force-before-act"]
    assert len(w) == 1 and "before its publication (2024-12-01)" in w[0]


def test_errors_are_attributed_to_their_source(tmp_path: Path):
    from pipeline.validate import validate_by_source

    snap = _copy(tmp_path)
    assert validate_by_source(snap, out=io.StringIO(), today=TODAY) == []
    _edit(snap / "ep_votes" / "votes.json", lambda r: r.append(dict(r[0])))  # duplicate id
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(date_publication="2024-13-01"))
    (snap / "council" / "votes.json").write_text("[{", encoding="utf-8")
    m = json.loads((snap / "_manifest.json").read_text())
    m["train"]["status"] = "bogus"
    (snap / "_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    out = io.StringIO()
    assert validate_by_source(snap, out=out, today=TODAY) == ["council", "ep_votes", "eurlex", "train"]
    assert "validate: council: 1 errors" in out.getvalue()


def test_unreadable_manifest_is_its_own_entry(tmp_path: Path):
    from pipeline.validate import MANIFEST_KEY, validate_by_source

    snap = _copy(tmp_path)
    (snap / "_manifest.json").write_text("{", encoding="utf-8")
    assert validate_by_source(snap, out=io.StringIO(), today=TODAY) == [MANIFEST_KEY]


def test_public_output_veto_rule(tmp_path: Path):
    pub = tmp_path / "public"
    (pub / "council").mkdir(parents=True)
    (pub / "council" / "index.json").write_text(json.dumps([
        {"id": "X", "voting_rule": "qmv", "assessment": {"single_state_veto_possible": True}}
    ]), encoding="utf-8")  # fmt: skip
    rep = check(FIX, public=pub, today=TODAY)
    assert any("single-state veto outside unanimity" in e for e in rep.errors)
