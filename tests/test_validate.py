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


def test_general_deadline_by_date_order_is_reported(tmp_path: Path):
    # two deadlines under the same article reference, as Cellar records AMLD6 (Directive (EU) 2024/1640, Art. 78(1))
    snap = _copy(tmp_path)

    def two_deadlines(r):
        a = next(x for x in r if x["celex"] == "32099L0003")
        a["transposition_deadlines"] = ["2025-02-21", "2027-02-21"]
        a["transposition_dates"] = [{"date": d, "labels": [], "articles": ["9.1"]} for d in a["transposition_deadlines"]]

    _edit(snap / "eurlex" / "acts.json", two_deadlines)
    rep = check(snap, today=TODAY)
    assert rep.errors == []
    assert rep.warnings["transposition-date-order"] == [
        "32099L0003: general deadline 2025-02-21 taken by date order among 2025-02-21, 2027-02-21; check the act's text"
    ]
    assert "transposition-date-order" not in check(FIX, today=TODAY).warnings


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


def test_public_dossier_contradicting_its_own_dates(tmp_path: Path):
    # as published before the fix: 2010-0095 (in force since 2015, shown as withdrawn by a notice of 7 March 2015),
    # 2018-0213 (withdrawn three days before its proposal, as OEIL dates it), 2024-0016 (adopted after publication)
    pub = tmp_path / "public"
    (pub / "dossiers").mkdir(parents=True)
    dossiers = [
        {"id": "2010-0095", "stage": "withdrawn", "status": {"since": "2015-03-07"}, "started": "2010-04-23",
         "celex": ["32015L1535"], "adopted": "2015-07-13", "published": "2015-09-17",
         "timeline": [{"kind": "council_adoption", "date": "2015-07-13"}, {"kind": "publication", "date": "2015-09-17"}]},
        {"id": "2018-0213", "stage": "withdrawn", "status": {"since": "2018-05-28"}, "started": "2018-05-31",
         "celex": [], "adopted": None, "published": None, "timeline": []},
        {"id": "2024-0016", "stage": "in_force", "status": {"since": "2024-07-09"}, "started": "2024-01-24",
         "celex": ["32024R1732"], "adopted": "2024-07-17", "published": "2024-06-19", "timeline": []},
        {"id": "2018-0329", "stage": "withdrawn", "status": {"since": "2025-03-11"}, "started": "2018-09-12",
         "celex": [], "adopted": None, "published": None, "timeline": []},
    ]  # fmt: skip
    for d in dossiers:
        (pub / "dossiers" / f"{d['id']}.json").write_text(json.dumps(d), encoding="utf-8")
    errors = check(FIX, public=pub, today=TODAY).errors
    assert [e.split(":")[0] for e in errors] == [
        "public dossiers/2010-0095.json", "public dossiers/2018-0213.json", "public dossiers/2024-0016.json"]  # fmt: skip
    assert "before the proposal of 2018-05-31" in errors[1] and "after its publication" in errors[2]


def test_public_timeline_with_two_council_adoptions_or_a_signature_before_one(tmp_path: Path):
    # as published before the fix: 2020-0067 (ST 8159/20 and the derogation vote ST 8160/20 both "Council adopted
    # the act" on 20 May 2020), 2017-0329 (the EP's "Final act signed" of 11 Apr 2018 before the Council's 12 Apr)
    from pipeline.validate import dossier_contradictions

    two = {"id": "2020-0067", "timeline": [{"kind": "council_adoption", "date": "2020-05-20"}] * 2}
    early = {"id": "2017-0329", "timeline": [{"kind": "signature", "date": "2018-04-11"},
                                             {"kind": "council_adoption", "date": "2018-04-12"}]}  # fmt: skip
    assert dossier_contradictions(two) == ["2 Council adoption steps on 2020-05-20"]
    assert dossier_contradictions(early) == ["signed on 2018-04-11, before the Council's adoption step of 2018-04-12"]
    early["timeline"][0]["date"] = "2018-04-18"  # the act's date
    assert dossier_contradictions(early) == []


def test_public_vote_margin_must_agree_with_an_established_outcome(tmp_path: Path):
    # as published before the guard in build.py ep_vote_summary, 1,102 index entries with no established outcome
    # carried a margin label; a margin's sign or label can also disagree with the outcome (ids are illustrative)
    pub = tmp_path / "public"
    (pub / "votes").mkdir(parents=True)
    (pub / "dossiers").mkdir(parents=True)

    def margin(distance: int, label: str) -> dict:
        return {"rule": "votes_cast", "threshold": 300, "distance": distance, "relative": distance / 600, "label": label}

    ok = {"id": "162153", "outcome": "rejected", "margin": margin(-10, "Majority not reached: 10 votes short")}
    index = [
        ok,
        {"id": "114470", "outcome": "unknown", "margin": margin(5, "Majority reached: 5 votes more than needed")},
        {"id": "1", "outcome": "adopted", "margin": margin(-3, "Majority not reached: 3 votes short")},
        {"id": "2", "outcome": "rejected", "margin": margin(-3, "Majority reached: 3 votes more than needed")},
        {"id": "114367", "outcome": "unknown", "margin": None},
    ]
    (pub / "votes" / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (pub / "votes" / "162153.json").write_text(json.dumps(ok), encoding="utf-8")
    (pub / "dossiers" / "2099-0001.json").write_text(json.dumps({"id": "2099-0001", "ep_votes": [index[1]]}), encoding="utf-8")
    errors = check(FIX, public=pub, today=TODAY).errors
    assert errors == [
        "public dossiers/2099-0001.json: vote 114470: margin 'Majority reached: 5 votes more than needed' with outcome 'unknown'",
        "public votes/index.json: vote 114470: margin 'Majority reached: 5 votes more than needed' with outcome 'unknown'",
        "public votes/index.json: vote 1: margin distance -3 contradicts outcome 'adopted'",
        "public votes/index.json: vote 2: margin label 'Majority reached: 3 votes more than needed' contradicts outcome 'rejected'",
    ]
