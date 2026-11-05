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
    assert rep.warnings["ballot-mep"] == ["vote V1: 1 ballot MEP ids not in meps.json (e.g. NOPE)"]
    assert "2099/0777(COD)" in " ".join(rep.by_design["ref-procedure"])  # by design: info, not a warning
    assert "ref-procedure" not in rep.warnings
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


def test_an_act_linked_to_a_procedure_that_cannot_have_adopted_it_is_an_error_of_eurlex(tmp_path: Path):
    """Cellar tags Council Decision (EU) 2020/2059 (Art. 207(4) with 218(9) TFEU) with 2020/3521(COD): the site showed
    it as an ordinary legislative procedure, "In force", and the validator only warned. An error of EUR-Lex's data
    (the refresh restores that source's last good files), unless data/curated/act_links.yaml drops the link."""
    snap = _copy(tmp_path)
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(procedure_refs=["2099/3521(COD)"]))
    rep = check(snap, today=TODAY)
    assert rep.errors_by_check == {"act-procedure-mismatch": 1} and list(rep.errors_by_source) == ["eurlex"]
    assert "act-procedure-mismatch" not in rep.warnings
    # the committed correction drops exactly that link: the act itself, under its own CELEX
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(celex="32020D2059", procedure_refs=["2020/3521(COD)"]))
    rep = check(snap, today=TODAY)
    assert "act-procedure-mismatch" not in rep.errors_by_check and "act-link-stale" not in rep.warnings
    # ... and an entry that EUR-Lex no longer needs is reported, so that it is removed
    _edit(snap / "eurlex" / "acts.json", lambda r: r[0].update(procedure_refs=[]))
    assert check(snap, today=TODAY).warnings["act-link-stale"] == [
        "32020D2059: data/curated/act_links.yaml drops its link to 2020/3521(COD), which EUR-Lex no longer records"]


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


def test_a_curated_entry_reviewed_before_an_act_amending_its_act_is_an_integrity_finding(tmp_path: Path):
    """docs/EDITORIAL.md, Re-review: a curated entry is re-read when the data show a new act amending its act. The AI
    Act's checked dates (data/curated/act_dates.yaml) replace EUR-Lex's in the build, so had they been reviewed before
    Regulation (EU) 2026/1744 moved the high-risk dates, the site would have kept the old ones. An entry reviewed before
    an act that EUR-Lex records as amending or repealing its act gates until it is re-read; an amending act the snapshot
    does not hold counts by its CELEX year only."""
    from pipeline.validate import warning_kind

    snap = _copy(tmp_path)
    cur = tmp_path / "curated"
    shutil.copytree(FIX.parent / "curated", cur)  # featured 2099/0001(COD): 32099R0001, reviewed 2099-01-01
    # 32099R0001 (of 2024-11-20, published 2024-12-01) amends 32099L0009; 32099R0077 (2099, not in the snapshot)
    # amends 32099R0001
    _edit(snap / "eurlex" / "acts.json", lambda r: r[2].update(amended_by=["32099R0001"]))
    entries = """
- celex: "32099L0009"
  reason: "Article 9 sets the dates."
  application: [{date: "2026-01-01", partial: false, provisions: "The Directive (Art. 9)"}]
  sources: [{label: "Directive 2099/9, Article 9", url: "https://eur-lex.europa.eu/eli/dir/2099/9/oj"}]
  reviewed: "{reviewed}"
"""
    (cur / "act_dates.yaml").write_text(entries.replace("{reviewed}", "2024-11-25"), encoding="utf-8")
    assert check(snap, today=TODAY, curated=cur).warnings["curated-review-stale"] == [
        "data/curated/act_dates.yaml 32099L0009: reviewed 2024-11-25, before 32099R0001 (2024-12-01), which amends "
        "32099L0009; re-read the entry against the act's current text and update `reviewed`"
    ]
    assert warning_kind("curated-review-stale") == "integrity"
    # re-read on the day the amending act was published: nothing to report
    (cur / "act_dates.yaml").write_text(entries.replace("{reviewed}", "2024-12-01"), encoding="utf-8")
    assert not check(snap, today=TODAY, curated=cur).warnings["curated-review-stale"]
    # an amending act outside the snapshot (a delegated act) is dated by its CELEX year: 32099R0077 counts from 2099
    featured = (cur / "featured.yaml").read_text(encoding="utf-8")
    (cur / "featured.yaml").write_text(featured.replace('reviewed: "2099-01-01"', 'reviewed: "2098-12-31"'), encoding="utf-8")
    assert check(snap, today=TODAY, curated=cur).warnings["curated-review-stale"] == [
        "data/curated/featured.yaml 2099/0001(COD): reviewed 2098-12-31, before 32099R0077 (2099-01-01), which amends "
        "32099R0001; re-read the entry against the act's current text and update `reviewed`"
    ]
    # an entry about an act with no valid review date cannot have been re-read
    (cur / "featured.yaml").write_text(featured.replace('  reviewed: "2099-01-01"\n', ""), encoding="utf-8")
    assert check(snap, today=TODAY, curated=cur).warnings["curated-review-stale"] == [
        "data/curated/featured.yaml 2099/0001(COD): no valid review date (None); review the entry and date it"
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


def test_public_rapporteur_linked_to_an_unwritten_mep_page_or_listed_twice(tmp_path: Path):
    # as published before the fix: 2026-0172 listed Marie-Sophie Christ as a shadow under EP Open Data's 277057 and
    # OEIL's 10006693, the second linked to a page that is not written
    pub = tmp_path / "public"
    (pub / "dossiers").mkdir(parents=True)
    (pub / "people" / "meps").mkdir(parents=True)
    (pub / "people" / "meps" / "277057.json").write_text("{}", encoding="utf-8")
    christ = {"mep_id": "277057", "name": "Marie-Sophie Christ", "role": "shadow", "committee": None, "has_page": True}
    d = {"id": "2026-0172", "timeline": [], "rapporteurs": [
        christ, {**christ, "mep_id": "10006693", "name": "CHRIST Marie-Sophie"}, {**christ, "role": "shadow_opinion"},
        {"mep_id": "4542", "name": "Timothy Kirkhope", "role": "rapporteur", "committee": "LIBE"}]}  # fmt: skip
    (pub / "dossiers" / "2026-0172.json").write_text(json.dumps(d), encoding="utf-8")
    assert check(FIX, public=pub, today=TODAY).errors == [
        "public dossiers/2026-0172.json: rapporteur CHRIST Marie-Sophie links people/meps/10006693.json, "
        "which is not written"]  # fmt: skip
    d["rapporteurs"][1] = christ
    (pub / "dossiers" / "2026-0172.json").write_text(json.dumps(d), encoding="utf-8")
    assert check(FIX, public=pub, today=TODAY).errors == [
        "public dossiers/2026-0172.json: MEP 277057 listed 2 times as shadow"]


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


def test_a_file_whose_count_differs_from_the_manifest_in_either_direction_is_a_warning(tmp_path: Path):
    # data/snapshot/ep_votes/ballots.json held 2,996 records after an offline re-derivation that left the manifest at
    # 2,995, so the About page's technical details gave 2,995 next to a summary of 2,996
    snap = _copy(tmp_path)
    votes = snap / "ep_votes" / "votes.json"
    _edit(votes, lambda r: r.extend(dict(r[0], id=f"X{i}") for i in range(100 - len(r))))
    n = 100
    m = json.loads((snap / "_manifest.json").read_text())
    m["ep_votes"]["records"] = {"votes": n}
    (snap / "_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert not check(snap, today=TODAY).warnings.get("manifest-count")
    for recorded in (n - 1, n + 1):  # more records than recorded, or (within the 5% allowed) fewer
        m["ep_votes"]["records"] = {"votes": recorded}
        (snap / "_manifest.json").write_text(json.dumps(m), encoding="utf-8")
        rep = check(snap, today=TODAY)
        assert rep.errors == []
        assert rep.warnings["manifest-count"] == [f"ep_votes/votes.json: {n} records, but _manifest.json records {recorded}"]


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
        path = val.SNAPSHOT / source / f"{name}.json"
        if source in val.FLOOR_ONCE_FETCHED and not path.exists():  # a newer source not retrieved in this snapshot
            continue
        n = len(json.loads(path.read_text(encoding="utf-8")))
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


def test_vote_titles_must_be_the_votes_of_the_index_in_its_order(built: Path, tmp_path: Path):
    """The MEP and group pages look their votes up in votes/titles.json by id instead of reading votes/index.json: a
    vote missing from it shows as "Vote <id>" with no date or result, one that the index lacks is never shown."""
    pub = _built_copy(built, tmp_path)
    path = pub / "votes" / "titles.json"
    titles = json.loads(path.read_text(encoding="utf-8"))
    ids = [t["id"] for t in titles]
    assert len(ids) == 3 and check(FIX, public=pub, today=TODAY, built=True).errors == []

    def errors_for(rows: list) -> list[str]:
        path.write_text(json.dumps(rows), encoding="utf-8")
        return check(FIX, public=pub, today=TODAY, built=True).errors

    head = "public votes/titles.json: not the votes of votes/index.json in its order"
    assert errors_for(titles[1:]) == [f"{head} (2 entries against 3, 1 missing (e.g. ['{ids[0]}']))"]
    assert errors_for([*titles, {**titles[0], "id": "V99"}]) == [f"{head} (4 entries against 3, 1 not in the index (e.g. ['V99']))"]
    assert errors_for([titles[1], titles[0], titles[2]]) == [f"{head} (3 entries against 3, in another order)"]
    assert errors_for([titles[0], titles[0], titles[2]]) == [f"{head} (3 entries against 3, 1 missing (e.g. ['{ids[1]}']))"]
    assert errors_for(titles) == []
    # the file itself is one of the built files that must exist
    path.unlink()
    assert check(FIX, public=pub, today=TODAY, built=True).errors == ["public/data/votes/titles.json is missing (run `python -m pipeline build`)"]
    assert len(check(FIX, public=pub, today=TODAY).warnings["public-missing"]) == 1  # a warning without --built


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
    (pub / "votes" / "titles.json").write_text("[]", encoding="utf-8")  # the build writes both from the same votes
    meta = json.loads((pub / "meta.json").read_text())
    meta["counts"]["ep_votes"] = 0
    (pub / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    errors = check(FIX, public=pub, today=TODAY, built=True).errors
    assert errors == [
        "public votes/index.json: not a list with records (the build found none; check data/snapshot)",
        "public votes/titles.json: not a list with records (the build found none; check data/snapshot)",
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


# ------------------------------------------------------------------------------ classes: by design, integrity, backlog
def test_every_warning_class_is_classified_once():
    """A class that is not classified gates as integrity (fail-safe); every class the checks use is classified."""
    import re

    from pipeline import validate as val

    used = set(re.findall(r'rep\.warn\(\s*"([\w-]+)"', Path(val.__file__).read_text(encoding="utf-8")))
    kinds = [set(val.BY_DESIGN), set(val.INTEGRITY), set(val.BACKLOG)]
    assert not (kinds[0] & kinds[1] or kinds[0] & kinds[2] or kinds[1] & kinds[2])
    assert used and used - set().union(*kinds) == set()
    assert {"ref-procedure", "ref-mep", "procedure-ref"} == kinds[0]
    assert "act-type" in kinds[1] and "application-not-recorded" in kinds[2]
    assert "act-procedure-mismatch" in val.ERROR_CHECKS and "act-procedure-mismatch" not in set().union(*kinds)
    assert val.warning_kind("a-new-check") == "integrity"


def test_by_design_findings_are_info_and_not_counted():
    rep = check(FIX, today=TODAY)
    assert rep.by_design["ref-procedure"] and "ref-procedure" not in rep.warnings
    out = io.StringIO()
    rep.print(out)
    text = out.getvalue()
    assert "INFO [ref-procedure] 1 by design: votes on procedures outside the dataset" in text
    assert "WARNING [ballot-totals] 1 (backlog)" in text
    assert "validate: OK — 0 errors, 1 warnings (0 integrity, 1 backlog); 1 by-design findings not counted" in text


def test_ratchet_fails_when_an_integrity_class_rises_or_appears_never_for_backlog():
    from pipeline.validate import Report, apply_baseline

    def run(warnings: dict[str, int], baseline: dict[str, int], accepted=None) -> Report:
        rep = Report()
        for k, n in warnings.items():
            for i in range(n):
                rep.warn(k, f"{k} finding {i}")
        apply_baseline(rep, baseline, accepted=accepted)
        return rep

    base = {"act-type": 1, "application-not-recorded": 19}
    ok = {"act-type": ["act-type finding 0"]}
    assert run({"act-type": 1, "application-not-recorded": 25}, base, ok).breaches == []  # backlog: never
    rose = run({"act-type": 2}, base, ok)
    assert rose.breaches == ["[act-type] 1 finding not in the baseline (e.g. act-type finding 1): an act whose type "
                             "differs from its CELEX type letter: the site names the wrong kind of act"]  # fmt: skip
    new = run({"amends-link-type": 1, "a-new-check": 1, "ref-mep": 9}, base, ok)  # by design: not a warning at all
    assert [b.split(" (")[0] for b in new.breaches] == [
        "[a-new-check] 1 finding not in the baseline", "[amends-link-type] 1 finding not in the baseline"]
    assert "classify it" in new.breaches[0]
    lower = run({}, base, ok)
    assert lower.breaches == [] and lower.ratchet_notes == [
        "[act-type] 0, below its baseline of 1: lower it with --update-baseline",
        "[application-not-recorded] 0, below its baseline of 19: lower it with --update-baseline",
    ]
    # the accepted finding fixed and a new one of the class appeared: a breach, although the count did not rise (the
    # count-only ratchet let a new wrong link replace 2020/3521's once that was fixed)
    swapped = run({"act-type": 1}, base, {"act-type": ["an older finding"]})
    assert swapped.breaches == ["[act-type] 1 finding not in the baseline (e.g. act-type finding 0): an act whose type "
                                "differs from its CELEX type letter: the site names the wrong kind of act"]  # fmt: skip
    assert run({"act-type": 1}, base).breaches  # no accepted findings: every integrity finding is new
    out = io.StringIO()
    rose.print(out)
    assert "validate: FAILED — 0 errors, 1 ratchet breaches" in out.getvalue()
    assert "  failed: ratchet [act-type] 1 finding not in the baseline (e.g. act-type finding 1)" in out.getvalue()


def test_the_committed_baseline_is_readable_and_accepts_only_known_classes():
    from pipeline import validate as val

    counts, accepted = val.load_baseline()
    assert counts and all(val.warning_kind(k) != "by design" for k in counts)
    assert "act-procedure-mismatch" not in counts  # an error now; 2020/3521's link is dropped in act_links.yaml
    assert accepted["index-unlisted"] == [  # the two party records the EP names "-" (build.unnamed_parties)
        f"public/data/people/parties/{p}.json: not listed in its folder's index (people/parties/<id>.json)"
        for p in ("5500", "5719")]  # fmt: skip
    assert set(accepted) == {k for k in counts if val.warning_kind(k) == "integrity"}
    assert all(len(accepted[k]) == counts[k] for k in accepted)


def test_validate_cli_ratchet_and_update_baseline(built: Path, tmp_path: Path, monkeypatch, capsys):
    import pipeline.__main__ as cli
    from pipeline import snapshot
    from pipeline import validate as val

    snap = _copy(tmp_path)
    root = tmp_path / "root"
    shutil.copytree(built, root / "public" / "data")
    monkeypatch.setattr(snapshot, "SNAPSHOT", snap)
    monkeypatch.setattr(val, "ROOT", root)
    monkeypatch.setattr(val, "BASELINE", tmp_path / "baseline.json")  # none yet: every integrity class is new
    assert cli.main(["validate", "--built"]) == 0  # the fixture: backlog and by-design findings only
    assert "0 ratchet breaches" in capsys.readouterr().out
    acts = snap / "eurlex" / "acts.json"
    first, first_type = (lambda a: (a["celex"], a["act_type"]))(json.loads(acts.read_text())[0])
    _edit(acts, lambda r: r[0].update(act_type="recommendation"))  # an integrity finding: act-type
    assert cli.main(["validate", "--built"]) == 1
    out = capsys.readouterr().out
    assert f"RATCHET [act-type] 1 finding not in the baseline (e.g. {first}: act_type recommendation" in out
    assert "validate: FAILED — 0 errors, 1 ratchet breaches" in out
    assert cli.main(["validate", "--built", "--update-baseline"]) == 0
    assert "(act-type 0 -> 1; ballot-totals 0 -> 1)" in capsys.readouterr().out
    counts, accepted = val.load_baseline()
    assert counts == {"act-type": 1, "ballot-totals": 1} and list(accepted) == ["act-type"]
    assert cli.main(["validate", "--built"]) == 0
    # the accepted finding fixed and another of the class in its place: the count is the same, but it is new
    _edit(acts, lambda r: (r[0].update(act_type=first_type), r[1].update(act_type="recommendation")))
    assert cli.main(["validate", "--built"]) == 1
    assert "failed: ratchet [act-type] 1 finding not in the baseline" in capsys.readouterr().out
    assert cli.main(["validate"]) == 1  # the gate holds without --built as well
    # the baseline accepts warnings, never errors: with an error it is not rewritten
    _edit(acts, lambda r: r[2].update(procedure_refs=["2099/3521(COD)"]))  # act-procedure-mismatch: an error
    before = val.BASELINE.read_text()
    assert cli.main(["validate", "--built", "--update-baseline"]) == 1
    assert "validate: baseline not written: 1 error (fix them first)" in capsys.readouterr().out
    assert val.BASELINE.read_text() == before
    with pytest.raises(SystemExit):
        cli.main(["validate", "--update-baseline"])  # needs --built


# ------------------------------------------------------------------------------ invariants of the built output
def _dossier(**kw) -> dict:
    return {"id": "2099-0001", "type": "COD", "stage": "in_force", "status_label": "In force", "celex": ["32099R0001"],
            "timeline": [], "acts": [], "ep_votes": [], **kw}  # fmt: skip


def test_an_act_shown_on_two_files_is_an_error(tmp_path: Path):
    """2 Nov 2026: `validate --built` warned "32026D2402 is shown on 2025-0177, 2025-0380", said OK and deployed."""
    pub = tmp_path / "public"
    (pub / "dossiers").mkdir(parents=True)
    for i in ("2025-0177", "2025-0380"):
        d = _dossier(id=i, celex=["32026D2402"], timeline=[{"kind": "ep_position", "date": "2026-10-08"}])
        (pub / "dossiers" / f"{i}.json").write_text(json.dumps(d), encoding="utf-8")
    rep = check(FIX, public=pub, today=TODAY)
    assert rep.errors == ["public dossiers: 32026D2402 is shown on 2025-0177, 2025-0380; check which procedure adopted it"]
    assert rep.errors_by_check == {"act-on-two-dossiers": 1} and "act-on-two-dossiers" not in rep.warnings


def test_a_file_past_adoption_needs_parliaments_position():
    """2023/0421(COD) on 2 Nov 2026: "Published in the Official Journal" from one EP publication event, with no
    Parliament position, Council adoption or act."""
    from pipeline.validate import dossier_invariants

    published = _dossier(id="2023-0421", stage="published", status_label="Published in the Official Journal", celex=[],
                         timeline=[{"kind": "proposal", "date": "2023-11-27"}, {"kind": "publication", "date": "2026-10-30"}])  # fmt: skip
    without = ("stage-without-parliament", "COD file shown as 'published' ('Published in the Official Journal'), but no "
               "position or decision of Parliament is recorded")  # fmt: skip
    assert dossier_invariants(published) == [
        ("stage-without-act", "shown as 'published' ('Published in the Official Journal'), but no act is linked to the "
         "file"), without]  # fmt: skip
    published["celex"] = ["32099L0421"]  # with an act, still without Parliament's position
    assert dossier_invariants(published) == [without]
    position = {"kind": "ep_position", "date": "2024-04-24"}
    assert dossier_invariants({**published, "timeline": [*published["timeline"], position]}) == []
    assert dossier_invariants({**published, "ep_approval_without_vote": {"date": "2026-01-20"}}) == []  # second reading
    assert dossier_invariants({**published, "ep_votes": [{"kind": "final", "outcome": "adopted"}]}) == []
    assert dossier_invariants({**published, "ep_votes": [{"kind": "amendment", "outcome": "adopted"}]}) != []
    assert dossier_invariants({**published, "type": "APP"}) != []  # consent is required too
    assert dossier_invariants({**published, "eurlex_only": True}) == []  # its steps are not in the data
    assert dossier_invariants({**published, "type": "CNS"}) == []  # 2020/0209(CNS): Art. 31 TFEU, no opinion needed
    assert dossier_invariants({**published, "stage": "provisional_agreement"}) == []


def test_an_adoption_date_needs_a_stage_of_adoption_or_later():
    """2025/0312(COD) on 2 Nov 2026: adopted 26 Oct by the Council (27-0-0), still "Approved by Parliament … the
    Council must still formally approve it"."""
    from pipeline.validate import dossier_invariants

    d = _dossier(id="2025-0312", stage="parliament_position", status_label="Approved by Parliament", adopted="2026-10-26",
                 timeline=[{"kind": "ep_position", "date": "2026-10-08"}])  # fmt: skip
    assert dossier_invariants(d) == [("adopted-stage-behind", "adopted on 2026-10-26, but shown at stage "
                                      "'parliament_position' ('Approved by Parliament')")]  # fmt: skip
    for stage in ("adopted", "published", "in_force", "no_longer_in_force", "withdrawn"):  # withdrawn: dossier-dates
        assert dossier_invariants({**d, "stage": stage}) == []
    assert dossier_invariants({**d, "adopted": None}) == []


def test_a_transposition_deadline_before_its_act_is_an_error():
    """2010/0208(COD), Directive (EU) 2015/412 of 11 March 2015: "the transposition deadline (17 October 2002) has
    passed", a date Cellar carried over from Directive 2001/18/EC, on the application dates, the timeline and the 27
    country rows of the implementation table."""
    from pipeline.validate import dossier_invariants

    act = {"celex": "32015L0412", "act_type": "directive", "date_document": "2015-03-11"}
    d = _dossier(id="2010-0208", adopted="2015-03-02", acts=[act], timeline=[
        {"kind": "ep_position", "date": "2015-01-13"}, {"kind": "transposition_deadline", "date": "2002-10-17"}],
        application={"transposition_deadlines": ["2002-10-17"], "transposition": [
            {"date": "2002-10-17", "kind": "deadline"}, {"date": "2014-01-01", "kind": "application"}]},
        implementation={"celex": "32015L0412", "deadline": "2002-10-17"})  # fmt: skip
    assert dossier_invariants(d) == [("deadline-before-act", "transposition deadline 2002-10-17 (application dates, "
                                      "implementation of 32015L0412, timeline) is before the adoption of its act on 2015-03-11")]  # fmt: skip
    # the fix: the date shown as another date, not as a deadline; an application date before the act is no deadline
    d["application"]["transposition"][0]["kind"] = "other"
    d["implementation"]["deadline"] = None
    d["timeline"] = d["timeline"][:1]
    assert dossier_invariants(d) == []
    d["application"] = {"transposition_deadlines": ["2015-01-01"]}  # no classified list: the deadlines themselves
    assert dossier_invariants(d)[0][1].startswith("transposition deadline 2015-01-01 (application dates)")


def test_the_contract_check_runs_with_built_and_reports_each_kind_of_drift_once(built: Path, tmp_path: Path):
    pub = _built_copy(built, tmp_path)
    council = json.loads((pub / "council" / "index.json").read_text())
    for cv in council:
        cv["voting_rule"] = "bogus"
    (pub / "council" / "index.json").write_text(json.dumps(council), encoding="utf-8")
    (pub / "extra.json").write_text("[]", encoding="utf-8")
    rep = check(FIX, public=pub, today=TODAY, built=True)
    n = len(council)
    assert rep.errors == [
        'public council/index.json: CouncilVote[].voting_rule: "bogus" where "qmv" | "simple_majority" | "unanimity" | '
        f'"unknown" expected ({n} time{"s" if n > 1 else ""}, e.g. council/index.json)'
    ]
    assert rep.errors_by_check == {"contract": 1}
    assert rep.warnings["contract-unlisted"] == ["public/data/extra.json: no type in the file list of src/types/data.ts"]
    assert check(FIX, public=pub, today=TODAY).errors == []  # without --built: not checked


def test_activity_duplicates_flags_a_step_reported_twice():
    from pipeline.validate import ERROR_CHECKS, activity_duplicates

    title = "Amending Directives 2009/43/EC and 2009/81/EC…: Signed by the Presidents of Parliament and Council"
    wrong = {"id": "chg:2025-0177:ev:act-32026D2402-signature-2026-10-21", "date": "2026-10-21", "title": title}
    right = {**wrong, "id": "chg:2025-0177:ev:act-32026L2383-signature-2026-10-21"}
    other = {**wrong, "id": "chg:2025-0177:ev:2025-0177-PUB-2026-11-03", "date": "2026-11-03"}
    assert activity_duplicates([right, other]) == []
    (msg,) = activity_duplicates([wrong, other, right])
    assert msg.startswith("chg:2025-0177:ev:act-32026L2383-signature-2026-10-21 repeats chg:2025-0177:ev:act-32026D2402")
    assert "activity-duplicate" in ERROR_CHECKS


# ------------------------------------------------------------------------------ activity: one step, its record (audit of #17)
COVID_CERT = ("Framework for the issuance, verification and acceptance of interoperable COVID-19 vaccination, test and "
              "recovery certificates (EU Digital COVID Certificate) to facilitate free movement during the COVID-19 "
              "pandemic")  # fmt: skip


def test_twin_files_moving_together_are_not_an_activity_duplicate():
    """2021/0068(COD) and 2021/0071(COD) (the EU Digital COVID Certificate for citizens and for third-country
    nationals) took every step on the same days under one 110-character short title: keyed on day and title only, a
    build as of 20 June 2021 gave 8 "activity-duplicate" errors, which would fail every refresh while they are listed.
    The same step of one file reported twice is still one."""
    from pipeline.analysis.activity import short_title
    from pipeline.validate import activity_duplicates

    title = f"{short_title(COVID_CERT)}: Council adopted the act"
    citizens = {"id": "ev:council-ST-9718-2021", "dossier_id": "2021-0068", "date": "2021-06-11", "title": title}
    others = {"id": "ev:council-ST-9720-2021", "dossier_id": "2021-0071", "date": "2021-06-11", "title": title}
    assert activity_duplicates([citizens, others]) == []
    again = {**citizens, "id": "chg:2021-0068:ev:council-ST-9718-2021"}
    assert activity_duplicates([citizens, again]) == [
        f"chg:2021-0068:ev:council-ST-9718-2021 repeats ev:council-ST-9718-2021 (2021-06-11: {title[:80]})"]


def test_one_step_reported_from_two_records_is_an_activity_duplicate():
    """2025/0232(COD), 9aba253: "…: Published in the Official Journal of the EU" (the act's step, recorded 2 Nov 2026)
    and "…: Final act published in the Official Journal" (the EP's record of the same day, recorded 5 Nov): different
    titles, one step (same file, day and kind)."""
    from pipeline.validate import activity_duplicates

    kinds = {"chg:2025-0232:ev:act-32026L2450-publication-2026-10-30": "publication",
             "chg:2025-0232:ev:2025-0232-PUB-2026-10-30": "publication"}  # fmt: skip
    items = [{"id": i, "dossier_id": "2025-0232", "date": "2026-10-30", "title": t} for i, t in zip(
        kinds, ("Carcinogens: Published in the Official Journal of the EU",
                "Carcinogens: Final act published in the Official Journal"), strict=True)]  # fmt: skip
    assert activity_duplicates(items) == []  # by title only: missed
    assert activity_duplicates(items, lambda it: kinds.get(it["id"])) == [
        "chg:2025-0232:ev:2025-0232-PUB-2026-10-30 repeats chg:2025-0232:ev:act-32026L2450-publication-2026-10-30 "
        "(2026-10-30: publication)"]  # fmt: skip


def test_an_activity_item_cites_the_record_it_reports():
    """Plan 1.2(d): 2023/0421(COD), 2 Nov 2026, "status now Published in the Official Journal" cited the OEIL page
    (which said "Awaiting committee decision"); a status change to a stage an act establishes cites the act's EUR-Lex
    record, a current one the record that gave the status, a step its own record."""
    from pipeline.validate import activity_sources

    oeil = {"institution": "OEIL", "url": "https://oeil.europarl.europa.eu/x"}
    act = {"institution": "EUR-Lex", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32099R0001",
           "identifier": "32099R0001"}  # fmt: skip
    council = {"institution": "Council", "url": "https://data.consilium.europa.eu/doc/document/ST-1-2099-INIT/EN/pdf"}
    det = {"id": "2099-0001", "stage": "adopted", "status": {"since": "2026-10-26"}, "sources": [oeil], "acts": [],
           "ep_votes": [], "timeline": [{"id": "council-ST-1-2099", "date": "2026-10-26", "kind": "council_adoption",
                                         "state": "done", "key": True, "source": council}]}  # fmt: skip
    dossier = {"2099-0001": det}.get
    item = {"dossier_id": "2099-0001", "kind": "status_change"}
    published = {**item, "id": "chg:2099-0001:stage:published:2026-10-30", "source": oeil}
    adopted = {**item, "id": "chg:2099-0001:stage:adopted:2026-10-26", "source": oeil}
    step = {**item, "id": "chg:2099-0001:ev:council-ST-1-2099", "kind": "milestone", "source": oeil}
    assert activity_sources([published, adopted, step], dossier, "2026-11-05") == [
        "chg:2099-0001:stage:published:2026-10-30: a status change to 'published' cites 'OEIL', not the act's EUR-Lex "
        "record",
        f"chg:2099-0001:stage:adopted:2026-10-26: cites {oeil['url']}, not the record that gave the status "
        f"({council['url']})",
        f"chg:2099-0001:ev:council-ST-1-2099: cites {oeil['url']}, not the record of its step ({council['url']})",
    ]
    assert activity_sources([{**published, "source": act}, {**adopted, "source": council}, {**step, "source": council}],
                            dossier, "2026-11-05") == []  # fmt: skip


def test_a_file_shown_published_needs_an_act():
    """2025/0177(COD) on 2 Nov 2026: "Published in the Official Journal" from the EP's record of a publication on 28
    October, which the EP then deleted; no act of the file in our EUR-Lex data."""
    from pipeline.validate import dossier_invariants

    d = _dossier(id="2025-0177", stage="published", status_label="Published in the Official Journal", celex=[],
                 timeline=[{"kind": "ep_position", "date": "2026-09-16"}])  # fmt: skip
    assert dossier_invariants(d) == [("stage-without-act", "shown as 'published' ('Published in the Official Journal'), "
                                      "but no act is linked to the file")]  # fmt: skip
    for stage in ("in_force", "no_longer_in_force", "takes_effect_on_notification"):
        assert [n for n, _ in dossier_invariants({**d, "stage": stage})] == ["stage-without-act"]
    assert dossier_invariants({**d, "celex": ["32026L2383"]}) == []
    assert dossier_invariants({**d, "stage": "adopted"}) == []  # signed, awaiting publication: no act yet


def test_a_built_file_no_index_lists_is_checked_and_reported(built: Path, tmp_path: Path):
    """people/parties/5500.json and 5719.json (the party records the EP names "-") are written but not listed in
    people/parties.json: the contract check, which went by the index, never read them."""
    pub = _built_copy(built, tmp_path)
    party = next((pub / "people" / "parties").glob("*.json"))
    (pub / "people" / "parties" / "9999.json").write_text(json.dumps({"id": "9999"}), encoding="utf-8")  # not listed
    rep = check(FIX, public=pub, built=True, today=TODAY)
    assert rep.warnings["index-unlisted"] == [
        "public/data/people/parties/9999.json: not listed in its folder's index (people/parties/<id>.json)"]
    assert any(e.startswith("public people/parties/<id>.json: PartyDetail.") and "people/parties/9999.json" in e
               for e in rep.errors)  # and checked against its type  # fmt: skip
    assert party.name != "9999.json"


def test_a_files_index_entry_that_its_own_file_contradicts_is_an_error(built: Path, tmp_path: Path):
    """The explorer reads a file's stage, status and dates from dossiers/index.json, its page from dossiers/<id>.json:
    the two must agree (titles only shortened in the index). Nothing checked it: on 5 Nov 2026 the files of 42
    entries lacked the entries' `names`."""
    from pipeline.validate import summary_mismatches

    pub = _built_copy(built, tmp_path)
    entry = json.loads((pub / "dossiers" / "index.json").read_text(encoding="utf-8"))[0]
    path = pub / "dossiers" / f"{entry['id']}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    assert summary_mismatches(entry, d) == [] and summary_mismatches({**entry, "title": d["title"][:4] + "…"}, d) == []
    assert summary_mismatches({**entry, "names": ["AI Act"]}, d) == ['names: the index gives ["AI Act"], the file null']
    path.write_text(json.dumps({**d, "status_label": "Proposal under examination"}), encoding="utf-8")
    errors = check(FIX, public=pub, today=TODAY, built=True).errors
    assert errors == [f'public dossiers/{entry["id"]}.json: status_label: the index gives "{entry["status_label"]}", '
                      'the file "Proposal under examination"']  # fmt: skip
