"""pipeline/validate.py on the TEST-ONLY fixture (tests/fixtures/build/) and broken copies of it."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

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


def test_dates_and_links_that_cellars_own_record_contradicts_are_warnings(tmp_path: Path):
    """PRIMA, Decision (EU) 2017/1324: Cellar's rule "DATPUB +20" and its date (8 August 2017, publication 18.7.2017)
    disagree. ETIAS, Regulation (EU) 2018/1240: the date from which it applies in general is "1001-01-01" ("V ART 96").
    AI Act: linked to Implementing Regulation (EU) No 90/2014 (32014R0090) though its title cites Directive
    2014/90/EU. Each is reported until checked (data/curated/act_dates.yaml, act_relations.yaml)."""
    clean = check(FIX, today=TODAY).warnings
    assert not clean["entry-into-force-rule"] and not clean["application-not-recorded"] and not clean["amends-link-type"]
    snap = _copy(tmp_path)

    def edit(r):
        r[0].update(entry_into_force_after_publication=20)  # published 2024-12-01, in force 2024-12-21: agrees
        r[1].update(entry_into_force_after_publication=20, date_publication="2023-02-01", entry_into_force="2023-02-22")
        r[0].update(in_force=True, application_unrecorded=[{"partial": False, "articles": ["96"]}])
        r[2].update(in_force=True, application_unrecorded=[{"partial": True, "articles": ["120.2"]}])  # some only
        r[0].update(title=r[0]["title"] + " amending Directive 2014/90/EU", amends=["32014R0090"])

    _edit(snap / "eurlex" / "acts.json", edit)
    w = check(snap, today=TODAY).warnings
    assert w["entry-into-force-rule"] == [
        "32099L0003: enters into force 2023-02-22, but EUR-Lex's rule (publication 2023-02-01 + 20 days) gives "
        "2023-02-21; check the act's text"
    ]
    assert w["application-not-recorded"] == [
        "32099R0001: EUR-Lex records no date from which it applies in general (it refers to Art. 96); check the act's text"
    ]
    assert w["amends-link-type"] == [
        "32099R0001: EUR-Lex links it as amending 32014R0090, but its title cites Directive 2014/90, not a regulation"
    ]


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


def test_sitting_meps_must_match_the_open_group_memberships(tmp_path: Path):
    """An MEP list in which no Member is marked as sitting (a short /meps/show-current answer) used to pass, and
    the site showed 0 current MEPs; it is now an error of ep_people, so a refresh restores that source."""
    from pipeline.validate import validate_by_source

    snap = _copy(tmp_path)
    _edit(snap / "ep_people" / "meps.json", lambda r: [m.update(active=False) for m in r])
    rep = check(snap, today=TODAY)
    assert any("0 MEPs marked as sitting, but 3 of the 3 holding an open political-group" in e for e in rep.errors)
    assert validate_by_source(snap, out=io.StringIO(), today=TODAY) == ["ep_people"]


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


def test_public_timeline_of_an_ordinary_procedure_adopting_its_act_twice_or_before_the_second_reading():
    # as published before the fix: 2014-0174 (OEIL's "Act adopted by Council after Parliament's 1st reading" on
    # 13 July 2015 next to the one moved to 18 September 2015, the act's date), 2018-0202 (the same OEIL step on
    # 21 April 2021, before Parliament approved the Council's position at second reading on 27 April 2021)
    from pipeline.validate import dossier_contradictions

    adopted = "Council adopted the act after Parliament's first reading"
    twice = {"id": "2014-0174", "type": "COD", "celex": ["32015R1843"],
             "timeline": [{"kind": "council_adoption", "date": "2015-07-13", "title": adopted},
                          {"kind": "council_adoption", "date": "2015-09-18", "title": adopted}]}  # fmt: skip
    assert dossier_contradictions(twice) == ["Council adoption steps on 2 days: 2015-07-13, 2015-09-18"]
    early = {"id": "2018-0202", "type": "COD", "celex": ["32021R0691"],
             "timeline": [{"kind": "council_position", "date": "2021-04-19", "title": "Council adopted its position at "
                           "first reading (written procedure)"},
                          {"kind": "council_adoption", "date": "2021-04-21", "title": adopted},
                          {"kind": "ep_position", "date": "2021-04-27",
                           "title": "Parliament approved the Council's position at second reading"}]}  # fmt: skip
    assert dossier_contradictions(early) == [
        "Council adoption step of 2021-04-21, before Parliament's second reading of 2021-04-27"
    ]
    # Parliament's second-reading amendments, then the Council's approval of them (Art. 294(9) TFEU): one adoption
    early["timeline"][1:] = [{"kind": "ep_position", "date": "2021-04-27",
                              "title": "Parliament amended the Council's position at second reading"},
                             {"kind": "council_adoption", "date": "2021-05-20",
                              "title": "Council approved Parliament's second-reading position"}]  # fmt: skip
    assert dossier_contradictions(early) == []
    # a consultation file's Council acts are not checked this way (2013/0400(CNS) adopted two directives)
    assert dossier_contradictions({**twice, "type": "CNS"}) == []


def test_public_timeline_with_a_trilogue_or_second_reading_step_before_what_it_follows():
    # as published before the fix: 2025-0132 (the first trilogue listed before Parliament confirmed the mandate on
    # 17 Dec 2025), 2018-0136 (the second-reading referral before the Council's first-reading position, 14 Dec 2020)
    from pipeline.validate import dossier_contradictions

    tri = {"kind": "other", "date": "2025-12-17", "title": "Negotiation meeting with the Council (trilogue)"}
    mandate = {"kind": "negotiation_mandate", "date": "2025-12-17",
               "title": "Parliament confirmed the committee's mandate to negotiate with the Council"}  # fmt: skip
    assert dossier_contradictions({"timeline": [tri, mandate]}) == [
        "trilogue listed before Parliament's decision of 2025-12-17"
    ]
    assert dossier_contradictions({"timeline": [mandate, tri]}) == []
    ref = {"kind": "referral", "date": "2020-12-14",
           "title": "Announced in Parliament and referred to committee (second reading)"}  # fmt: skip
    pos = {"kind": "council_position", "date": "2020-12-14", "title": "Council adopted its position at first reading"}
    assert dossier_contradictions({"timeline": [ref, pos]}) == [
        "second-reading step listed before the Council's position of 2020-12-14"
    ]
    assert dossier_contradictions({"timeline": [pos, ref]}) == []


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


# ------------------------------------------------------------------------------ emptied or missing data
def _records(snap: Path) -> None:
    """Give the fixture manifest the record counts a refresh writes (the committed manifest's `records`)."""
    m = json.loads((snap / "_manifest.json").read_text())
    for source, name in [("ep_votes", "votes"), ("ep_votes", "ballots"), ("ep_procedures", "procedures")]:
        m[source]["records"] = {**m[source]["records"], name: len(json.loads((snap / source / f"{name}.json").read_text()))}
    (snap / "_manifest.json").write_text(json.dumps(m), encoding="utf-8")


def test_a_file_emptied_below_its_manifest_count_is_an_error_of_its_source(tmp_path: Path):
    """In a copy of the committed snapshot, ep_votes votes.json and ballots.json set to [] gave `validate`, `build` and
    `validate --built` exit 0, and a site with 0 plenary votes would have been deployed."""
    from pipeline.validate import validate_by_source

    snap = _copy(tmp_path)
    _records(snap)
    assert check(snap, today=TODAY).errors == []
    _edit(snap / "ep_votes" / "votes.json", lambda r: r.clear())
    _edit(snap / "ep_votes" / "ballots.json", lambda r: r.clear())
    rep = check(snap, today=TODAY)
    assert rep.errors == [
        "ep_votes/votes.json: 0 records, but _manifest.json records 4 (more than 5% fewer): an emptied or truncated file",
        "ep_votes/ballots.json: 0 records, but _manifest.json records 3 (more than 5% fewer): an emptied or truncated file",
    ]
    assert list(rep.errors_by_source) == ["ep_votes"]  # so a refresh restores that source and keeps the others
    assert validate_by_source(snap, out=io.StringIO(), today=TODAY) == ["ep_votes"]


def test_a_shrink_of_up_to_five_percent_of_the_manifest_count_is_not_an_error(tmp_path: Path):
    snap = _copy(tmp_path)
    m = json.loads((snap / "_manifest.json").read_text())
    m["ep_votes"]["records"] = {"votes": 100}
    (snap / "_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    votes = snap / "ep_votes" / "votes.json"
    _edit(votes, lambda r: r.extend(dict(r[0], id=f"X{i}") for i in range(97)))  # 100 records
    assert check(snap, today=TODAY).errors == []
    _edit(votes, lambda r: r.__delitem__(slice(95, None)))  # 95: the limit
    assert check(snap, today=TODAY).errors == []
    _edit(votes, lambda r: r.pop())  # 94 of 100
    assert any("94 records, but _manifest.json records 100" in e for e in check(snap, today=TODAY).errors)


def test_a_missing_file_is_an_error_only_where_the_manifest_or_the_floor_expects_it(tmp_path: Path):
    """ep_procedures/procedures.json deleted: `_load` returned None without a word and `validate` exit 0, and a build
    with 1238 dossiers instead of 1577 was made. implementation/indicators is absent in the committed snapshot and
    nothing records it, so its absence is not an error."""
    snap = _copy(tmp_path)
    assert not (snap / "implementation" / "indicators.json").exists()
    assert check(snap, today=TODAY).errors == []
    _records(snap)
    (snap / "ep_procedures" / "procedures.json").unlink()
    assert check(snap, today=TODAY).errors == [
        "ep_procedures/procedures.json: file missing, but _manifest.json records 3 records"
    ]
    m = json.loads((snap / "_manifest.json").read_text())
    m["ep_procedures"]["records"] = {}
    (snap / "_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert check(snap, today=TODAY).errors == []  # nothing says it should be there
    floors = {("ep_procedures", "procedures"): 800, ("implementation", "indicators"): 10}
    assert check(snap, today=TODAY, min_records=floors).errors == [
        "ep_procedures/procedures.json: file missing, but a complete snapshot has at least 800",
        "implementation/indicators.json: file missing, but a complete snapshot has at least 10",
    ]


def test_the_committed_snapshot_is_held_to_floors_a_fixture_is_not(tmp_path: Path):
    """A source module that wrote an emptied file and the manifest with it passes the comparison with the manifest:
    the floors (about half of today's counts) stop it. They apply to the committed snapshot only."""
    from pipeline import validate as val

    assert val._floors(val.SNAPSHOT) is val.MIN_RECORDS and val._floors(tmp_path) is None
    snap = _copy(tmp_path)
    m = json.loads((snap / "_manifest.json").read_text())
    m["council"]["records"] = {"votes": 0}
    (snap / "_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    _edit(snap / "council" / "votes.json", lambda r: r.clear())
    assert check(snap, today=TODAY).errors == []  # consistent with its manifest, and no floor in a fixture
    errors = check(snap, today=TODAY, min_records=val.MIN_RECORDS).errors
    assert "council/votes.json: 0 records, fewer than the 350 a complete snapshot has" in errors


def test_the_floors_are_well_below_what_the_committed_snapshot_holds():
    from pipeline import validate as val

    for (source, name), floor in val.MIN_RECORDS.items():
        n = len(json.loads((val.SNAPSHOT / source / f"{name}.json").read_text(encoding="utf-8")))
        assert 0 < floor <= 0.6 * n, (source, name, floor, n)


# ------------------------------------------------------------------------------ the built output must be complete
@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from pipeline.build import build

    base = tmp_path_factory.mktemp("built")
    curated = FIX.parent / "curated"
    assert build(out=base / "public", snapshot=FIX, curated=curated, state=base / "state", today=TODAY) == 0
    return base / "public"


def _built_copy(built: Path, tmp_path: Path) -> Path:
    pub = tmp_path / "public"
    shutil.copytree(built, pub)
    return pub


def test_a_complete_build_passes_with_built(built: Path):
    assert check(FIX, public=built, today=TODAY, built=True).errors == []


def test_built_files_that_are_missing_or_unreadable_are_errors_only_with_built(built: Path, tmp_path: Path):
    """After a build, deleting public/data/home.json and dossiers/index.json, or truncating home.json, still gave
    `validate --built` exit 0 (two warnings); home.json was never parsed."""
    pub = _built_copy(built, tmp_path)
    (pub / "home.json").unlink()
    (pub / "dossiers" / "index.json").unlink()
    (pub / "topics.json").write_text('{"truncat', encoding="utf-8")
    (pub / "feeds" / "updates.xml").write_text("<feed><entry>", encoding="utf-8")
    loose = check(FIX, public=pub, today=TODAY)
    assert loose.errors == [] and len(loose.warnings["public-missing"]) == 2  # without --built: as before
    errors = check(FIX, public=pub, today=TODAY, built=True).errors
    assert "public/data/home.json is missing (run `python -m pipeline build`)" in errors
    assert "public/data/dossiers/index.json is missing (run `python -m pipeline build`)" in errors
    assert any(e.startswith("public topics.json: unreadable JSON") for e in errors)
    assert any(e.startswith("public feeds/updates.xml: unreadable XML") for e in errors)
    assert len(errors) == 4


def test_a_build_from_an_emptied_snapshot_is_an_error_with_built(built: Path, tmp_path: Path):
    """ep_votes votes.json and ballots.json set to [] built 3445 files instead of 6445 with meta count ep_votes 0, and
    `validate --built` said OK, 0 errors."""
    pub = _built_copy(built, tmp_path)
    (pub / "votes" / "index.json").write_text("[]", encoding="utf-8")
    meta = json.loads((pub / "meta.json").read_text())
    meta["counts"]["ep_votes"] = 0
    (pub / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errors = check(FIX, public=pub, today=TODAY, built=True).errors
    assert errors == [
        "public votes/index.json: not a list with records (the build found none; check data/snapshot)",
        "public meta.json: count 'ep_votes' is 0, but ep_votes/votes.json has 4 records",
    ]
    assert check(FIX, public=pub, today=TODAY).errors == []  # not checked without --built


def test_built_counts_below_the_snapshot_and_unwritten_files_are_errors(built: Path, tmp_path: Path):
    pub = _built_copy(built, tmp_path)
    meta = json.loads((pub / "meta.json").read_text())
    meta["counts"]["meps"] = 2  # of the snapshot's 4
    meta["counts"]["dossiers"] = 0
    (pub / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    ids = [d["id"] for d in json.loads((pub / "dossiers" / "index.json").read_text())]
    (pub / "dossiers" / f"{ids[0]}.json").unlink()
    errors = check(FIX, public=pub, today=TODAY, built=True).errors
    assert errors == [
        "public meta.json: count 'meps' is 2, but ep_people/meps.json has 4 records",
        "public meta.json: count 'dossiers' is 0, but ep_procedures/procedures.json has 3 records",
        f"public dossiers/index.json: 1 of {len(ids)} listed files not written (e.g. ['{ids[0]}'])",
    ]


def test_an_unreadable_built_file_is_an_error_not_a_crash(built: Path, tmp_path: Path):
    pub = _built_copy(built, tmp_path)
    some = next(p for p in (pub / "dossiers").glob("*.json") if p.name != "index.json")
    some.write_text("{", encoding="utf-8")
    (pub / "council" / "index.json").write_text("[{", encoding="utf-8")
    errors = check(FIX, public=pub, today=TODAY, built=True).errors
    assert sum(e.startswith(f"public dossiers/{some.name}: unreadable JSON") for e in errors) == 1
    assert sum(e.startswith("public council/index.json: unreadable JSON") for e in errors) == 1  # reported once
