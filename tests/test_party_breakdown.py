"""The national-party breakdown (pipeline/build.py party_breakdown) on the TEST-ONLY build fixture (tests/fixtures/build)
with a few invented records added: the MEPs in office with no recorded vote, by party record, group and country, in
each vote file (`no_vote`); the party records whose MEPs are listed outside the record's own period
(`parties_outside_period`); and each party page's votes on whole texts (PartyDetail.votes)."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

import pytest

from pipeline.build import build
from pipeline.contract import Contract, check_public
from tests.test_build import DATA_TS, FIX, TODAY, _vote, load

SRC = {"institution": "EP", "published": None, "retrieved_at": "2099-01-01T00:00:00Z"}


def _source(rid: str) -> dict:
    return {**SRC, "identifier": rid, "label": f"TEST ONLY {rid}", "url": f"https://example.invalid/{rid}"}


def _mep(mid: str, country: str, memberships: list[tuple[str, str, str, str | None]]) -> dict:
    return {
        "active": True, "country": country, "family_name": mid, "given_name": None, "id": mid,
        "memberships": [{"end": end, "kind": kind, "org_id": org, "role": "MEMBER", "start": start, "term": 10}
                        for kind, org, start, end in memberships],
        "name": f"Test {mid}", "official_url": f"https://example.invalid/meps/{mid}", "photo_url": None,
        "sort_label": mid, "source": _source(mid), "terms": [10],
    }  # fmt: skip


def _ballots(vid: str, favor=(), against=(), abstain=()) -> dict:
    return {"abstain": list(abstain), "against": list(against), "favor": list(favor), "intended_abstain": [],
            "intended_against": [], "intended_favor": [], "vote_id": vid}  # fmt: skip


@pytest.fixture(scope="module")
def parties_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The build fixture (T1 P1 Spain, T2 P2 Germany, T3 P2 until 15 Jul 2024, T4 P1 from 16 Jul 2024) plus:
    T5 (Czechia, S&D) with no party recorded, and T6 (Romania, S&D) whom the membership data lists in party record P3
    from 16 Jul 2024 although P3's own period ended on 15 Jul 2024 (as corporate body 5320 and Dan Nica); and votes
    V20 (final) and V21 (mandate) of June 2025, V22 (a resolution: not on the party pages) and V23 (final, 23 Oct 2019:
    a day the membership records do not give the Members in office, MEMBERS_COUNT_UNKNOWN)."""
    import pipeline.build as B

    base = tmp_path_factory.mktemp("build-parties")
    shutil.copytree(FIX / "snapshot", base / "snapshot")
    snap = base / "snapshot"
    meps = json.loads((snap / "ep_people/meps.json").read_text(encoding="utf-8"))
    meps += [
        _mep("T5", "CZ", [("group", "G10SD", "2024-07-16", None)]),
        _mep("T6", "RO", [("group", "G10SD", "2024-07-16", None), ("party", "P3", "2024-07-16", None)]),
    ]
    (snap / "ep_people/meps.json").write_text(json.dumps(meps), encoding="utf-8")
    orgs = json.loads((snap / "ep_people/orgs.json").read_text(encoding="utf-8"))
    orgs.append({"code": "TPC", "country": "RO", "end": "2024-07-15", "id": "P3", "kind": "party",
                 "label": "Test Party C", "source": _source("P3"), "start": "2019-07-02"})  # fmt: skip
    (snap / "ep_people/orgs.json").write_text(json.dumps(orgs), encoding="utf-8")
    votes = json.loads((snap / "ep_votes/votes.json").read_text(encoding="utf-8"))
    ballots = json.loads((snap / "ep_votes/ballots.json").read_text(encoding="utf-8"))
    votes += [
        _vote("V20", "2025-06-18", "final", "adopted", (1, 1, 1), ["2099/0003(COD)"], has_ballots=True),
        _vote("V21", "2025-06-19", "mandate", "adopted", (2, 0, 0), ["2099/0003(COD)"], has_ballots=True),
        _vote("V22", "2025-06-19", "resolution", "adopted", (1, 0, 0), [], has_ballots=True),
        _vote("V23", "2019-10-23", "final", "adopted", (1, 1, 0), [], has_ballots=True),
    ]
    ballots += [
        _ballots("V20", favor=["T1"], against=["T6"], abstain=["T4"]),  # T2 and T5 in office, no recorded vote
        _ballots("V21", favor=["T2", "T4"]),  # T1, T5 and T6 in office, no recorded vote
        _ballots("V22", favor=["T1"]),
        _ballots("V23", favor=["T1"], against=["T2"]),  # T3 also sat, but the day's Members are not known
    ]
    (snap / "ep_votes/votes.json").write_text(json.dumps(votes), encoding="utf-8")
    (snap / "ep_votes/ballots.json").write_text(json.dumps(ballots), encoding="utf-8")
    o = base / "public"
    mp = pytest.MonkeyPatch()
    # the fixture has six MEPs; stand in for a plausible count of Parliament's Members in office (720 seats)
    mp.setattr(B.Builder, "members_in_office", lambda self, d: 719)
    try:
        assert build(out=o, snapshot=snap, curated=FIX / "curated", state=base / "state", today=TODAY) == 0
    finally:
        mp.undo()
    return o


def test_vote_file_counts_the_mps_in_office_without_a_recorded_vote(parties_out: Path):
    v20 = load(parties_out, "votes/V20.json")
    # T2 (P2, EPP, Germany) and T5 (no party, S&D, Czechia) sat that day and have no recorded vote
    assert v20["no_vote"] == [[None, "s-d", "CZ", 1], ["P2", "epp", "DE", 1]]
    # the ballots give the same for those who voted: T6 under P3, the record Parliament's data lists T6 in
    assert {b["mep"]: (b.get("party"), b["group"], b["country"]) for b in v20["ballots"]} == {
        "T1": ("P1", "s-d", "ES"), "T4": ("P1", "epp", "ES"), "T6": ("P3", "s-d", "RO"),
    }  # fmt: skip
    # P3's own period ended on 15 Jul 2024: said as the party page says it
    assert v20["parties_outside_period"] == [{"party": "P3", "start": "2019-07-02", "end": "2024-07-15"}]
    v21 = load(parties_out, "votes/V21.json")
    assert v21["no_vote"] == [[None, "s-d", "CZ", 1], ["P1", "s-d", "ES", 1], ["P3", "s-d", "RO", 1]]
    # every MEP in office is counted once: a recorded vote, or none
    for v in (v20, v21):
        assert len(v["ballots"]) + sum(n for *_, n in v["no_vote"]) == 5
    assert "parties_outside_period" not in load(parties_out, "votes/V1.json")


def test_no_one_is_said_not_to_have_voted_on_a_day_the_members_in_office_are_not_known(parties_out: Path):
    v23 = load(parties_out, "votes/V23.json")  # 23 Oct 2019 (MEMBERS_COUNT_UNKNOWN): T3 sat, but that is not known
    assert v23["no_vote"] is None and len(v23["ballots"]) == 2
    # nor on a day the records give an implausible number of Members (V1: 719 in office against 705 seats)
    assert load(parties_out, "votes/V1.json")["no_vote"] is None
    # a vote without individual votes has nothing to break down
    assert "no_vote" not in load(parties_out, "votes/V4.json")


def test_party_pages_list_their_mps_votes_on_whole_texts_newest_first(parties_out: Path):
    p1, p2, p3 = (load(parties_out, f"people/parties/{p}.json")["votes"] for p in ("P1", "P2", "P3"))
    # [vote, for, against, abstained, did not vote]; final and mandate votes only (V22, a resolution, and V3 are not)
    assert p1 == [["V21", 1, 0, 0, 1], ["V20", 1, 0, 1, 0], ["V1", 1, 0, 0, None], ["V23", 1, 0, 0, None]]
    assert p2 == [["V21", 1, 0, 0, 0], ["V20", 0, 0, 0, 1], ["V1", 1, 1, 0, None], ["V23", 0, 1, 0, None]]
    # a party whose MEPs all did not vote is listed with them; P3's votes after its period count T6, as its page says
    assert p3 == [["V21", 0, 0, 0, 1], ["V20", 0, 1, 0, 0]]
    assert [x["id"] for x in load(parties_out, "people/parties/P3.json")["outside_period"]] == ["T6"]


def test_party_pages_agree_with_the_vote_files(parties_out: Path):
    """What the vote page adds up from a vote file (ballots by party, and no_vote) is what the party pages list."""
    index = {v["id"]: v for v in load(parties_out, "votes/index.json")}
    from_votes: dict[tuple[str, str], list] = {}
    for vid, v in index.items():
        if not v["has_ballots"] or v["kind"] not in ("final", "mandate"):
            continue
        d = load(parties_out, f"votes/{vid}.json")
        none = 0 if d["no_vote"] is not None else None
        rows: dict[str, list] = defaultdict(lambda none=none: [0, 0, 0, none])
        for b in d["ballots"]:
            if b.get("party"):
                rows[b["party"]][("for", "against", "abstain").index(b["pos"])] += 1
        for party, _group, _country, n in d["no_vote"] or []:
            if party:
                rows[party][3] += n
        from_votes |= {(party, vid): [vid, *c] for party, c in rows.items()}
    from_parties = {
        (pid, r[0]): r for pid in ("P1", "P2", "P3") for r in load(parties_out, f"people/parties/{pid}.json")["votes"]
    }
    assert from_parties == from_votes


def test_vote_titles_name_the_file_for_the_party_pages_link(parties_out: Path):
    titles = {t["id"]: t for t in load(parties_out, "votes/titles.json")}
    assert titles["V20"]["dossier_id"] == "2099-0003" and "dossier_id" not in titles["V23"]


def test_party_breakdown_matches_the_contract(parties_out: Path, tmp_path: Path):
    contract = Contract.load(DATA_TS)
    assert check_public(parties_out, contract).lines() == []
    # the contract checks the shapes: a count that is not a number, a tuple of the wrong length
    pub = tmp_path / "public"
    shutil.copytree(parties_out, pub)
    v20 = load(pub, "votes/V20.json")
    v20["no_vote"][0][3] = "1"
    (pub / "votes/V20.json").write_text(json.dumps(v20), encoding="utf-8")
    p1 = load(pub, "people/parties/P1.json")
    p1["votes"][0] = p1["votes"][0][:4]
    (pub / "people/parties/P1.json").write_text(json.dumps(p1), encoding="utf-8")
    assert check_public(pub, contract).lines() == [
        "people/parties/<id>.json: PartyDetail.votes[]: array where a tuple of 5 expected (1 time, e.g. "
        "people/parties/P1.json)",
        'votes/<id>.json: EpVoteDetail.no_vote[][3]: "1" where number expected (1 time, e.g. votes/V20.json)',
    ]
