"""Tests for pipeline.sources.ep_votes (EP plenary votes and roll-call ballots).

Offline tests run on real, trimmed API responses in tests/fixtures/ep_votes/ (see each file's `_note`).
Snapshot tests check invariants of data/snapshot/ep_votes/ when it exists. Live tests: `-m network`.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest

from pipeline.models.entities import EpBallots, EpVote
from pipeline.snapshot import SNAPSHOT, read_records
from pipeline.sources import ep_votes as ev

FIX = Path(__file__).parent / "fixtures" / "ep_votes"
RETRIEVED = "2026-10-22T00:00:00Z"


def _term(day: str) -> int:
    return 9 if day <= "2024-07-15" else 10


def load_sitting(day: str) -> ev.Sitting:
    raw = json.loads((FIX / f"sitting_{day}.json").read_text(encoding="utf-8"))
    sid = raw["sitting"]
    return ev.Sitting.build(
        {"id": sid, "date": sid[7:17], "term": _term(sid[7:17])},
        raw["decisions"]["data"],
        raw["vote_results"]["data"],
    )


def proc_labels() -> dict[str, str]:
    raw = json.loads((FIX / "procedures.json").read_text(encoding="utf-8"))
    return {r["process_id"]: r["label"] for r in raw["data"]}


def doc_links() -> dict[str, tuple[list[str], list[str]]]:
    """Recorded /plenary-documents/{doc}?language=en answers, parsed like fetch_document_links does."""
    raw = json.loads((FIX / "documents.json").read_text(encoding="utf-8"))
    out = {}
    for doc, resp in raw["responses"].items():
        rows = resp["data"]
        procs = sorted(
            {p.rsplit("/", 1)[-1] for r in rows for p in ev._ids(r.get("inverse_created_a_realization_of"))}
        )
        derived = sorted({ev._suffix(d) for r in rows for d in ev._ids(r.get("is_derivative_of"))})
        out[doc] = (procs, derived)
    return out


def assemble(*days: str, links: bool = True) -> tuple[dict[str, EpVote], dict[str, EpBallots]]:
    res = ev.assemble([load_sitting(d) for d in days], proc_labels(), doc_links() if links else {}, RETRIEVED)
    return {v.id: v for v in res.votes}, {b.vote_id: b for b in res.ballots}


# ------------------------------------------------------------------------------------------- helpers
def test_document_references():
    assert ev.doc_ref_to_id("A9-0188/2023") == "A-9-2023-0188"
    assert ev.doc_ref_to_id("RC-B9-0163/2024") == "RC-9-2024-0163"
    assert ev.doc_ref_to_id("B10-0424/2026") == "B-10-2026-0424"
    assert ev.doc_ref_to_id("A9-0088/202") is None  # a typo in a real label is not "repaired"
    assert ev.base_doc("A-9-2024-0042-AM-102") == "A-9-2024-0042"
    assert ev.base_doc("MTG-PL-2024-03-13-VOT-ITM-941749-SPLIT-1-2") is None


def test_old_labels():
    assert ev.clean_label("B9-0154/2019 - Am 52 24/10/2019 12:34:01.000") == "B9-0154/2019 - Am 52"
    assert ev.label_tail("A9-0050/2024 – Dragoş Pîslaru – § 9/2") == "§ 9/2"
    assert ev.label_tail("A9-0139/2021 - Angel Dzhambazki -Annex, Part B, indent 3/1") == "Annex, Part B, indent 3/1"
    assert ev.label_tail("Elissavet Vozemberg-Vrionidi - Am 3") == "Am 3"  # hyphenated names are kept


@pytest.mark.parametrize(
    "ref,kind",
    [  # referenceText / label tails exactly as published
        ("07 20 04 01", "amendment"),  # budget line
        ("Block 16", "amendment"),
        ("Ams 1-456", "amendment"),
        ("§ 11/2", "split_or_separate"),
        ("Recital K/2", "split_or_separate"),
        ("Recommendation 1, sub§ 2", "split_or_separate"),
        ("Single vote", "final"),
        ("Proposals for decisions", "final"),
        ("Draft Council decision", "final"),
        ("Proposition de résolution", "resolution"),
        ("B10-0441/2026", "resolution"),
        ("Request for referral back (Rule 60(4))", "procedural"),
        ("Motion for adjournment of the vote", "procedural"),
        ("Proposal to vote on amendments", "procedural"),
        ("Approval without vote", "other"),
    ],
)
def test_classify_reference_texts(ref, kind):
    assert ev.classify(ev.Signals(ref=ref, label=ref)) == kind


# --------------------------------------------------------------- new format (2024-01-15 onwards)
def test_ai_act_final_vote():
    votes, ballots = assemble("2024-03-13")
    v = votes["166051"]
    assert v.procedure_refs == ["2021/0106(COD)"]
    assert v.kind == "final"  # tabled as "Am 808" but referenceText is "Provisional agreement"
    assert v.doc_ids == ["A-9-2023-0188-AM-808"]
    assert (v.n_for, v.n_against, v.n_abstain, v.attendees) == (523, 46, 49, 618)
    assert v.outcome == "adopted" and v.method == "VOTE_ELECTRONIC_ROLLCALL"
    assert v.majority_rule == "votes_cast"  # ***I: Art. 294(3) TFEU, no special majority
    assert v.term == 9 and v.date == "2024-03-13" and v.event_id == "MTG-PL-2024-03-13-DEC-166051"
    assert v.has_ballots
    b = ballots["166051"]
    assert (len(b.favor), len(b.against), len(b.abstain)) == (523, 46, 49)
    assert b.intended_abstain == ["96780"] and b.intended_against == ["204733"]
    assert all(re.fullmatch(r"\d+", p) for p in b.favor + b.against + b.abstain)
    assert ev.ballot_issues(v, b) == []


EXPECTED_2024_03_13 = {
    "166377": ("amendment", "rejected", ["2023/0129(COD)"]),  # A9-0042/2024 – Recital 29 – Am 102, RCV
    "166044": ("amendment", "rejected", ["2023/0156(COD)"]),  # show of hands, AM-295
    "166493": ("split_or_separate", "adopted", ["2023/2220(BUI)"]),  # § 46/2 (SPLIT document, about "§")
    "166341": ("amendment", "adopted", ["2023/0290(COD)"]),  # committee amendments – separate votes
    "166202": ("final", "adopted", ["2023/0129(COD)"]),  # "Commission proposal"
    "166145": ("resolution", "rejected", ["2023/2116(INI)"]),  # motion for a resolution (text as a whole)
    "166566": ("resolution", "adopted", ["2024/2580(RSP)"]),  # RC-B9-0163/2024 as a whole (via document)
    "166656": ("procedural", "adopted", ["2024/0028(COD)"]),  # request for referral back (Rule 59(4))
    "166382": ("procedural", "rejected", ["2022/0277(COD)"]),  # vote on amendments instead of agreement
    "166530": ("resolution", "lapsed", ["2024/2580(RSP)"]),  # B9-0163/2024 ("other motions"), lapsed
    "166172": ("final", "adopted", ["2022/0131(COD)"]),  # provisional agreement tabled as Am 117
    "166487": ("amendment", "adopted", ["2023/2220(BUI)"]),  # 272 for, 271 against
}


@pytest.mark.parametrize("vid", sorted(EXPECTED_2024_03_13))
def test_new_format_kinds_and_links(vid):
    votes, _ = assemble("2024-03-13")
    kind, outcome, refs = EXPECTED_2024_03_13[vid]
    v = votes[vid]
    assert (v.kind, v.outcome, v.procedure_refs) == (kind, outcome, refs)


def test_rejected_amendment_is_not_a_rejected_law():
    votes, ballots = assemble("2024-03-13")
    amendment, whole = votes["166377"], votes["166202"]
    assert amendment.procedure_refs == whole.procedure_refs
    assert (amendment.kind, amendment.outcome) == ("amendment", "rejected")
    assert (whole.kind, whole.outcome) == ("final", "adopted")
    assert not amendment.has_ballots and "166377" not in ballots  # only whole-text roll-calls keep ballots


def test_no_link_without_official_identifier():
    votes, _ = assemble("2024-03-13", links=False)
    # the Armenia vote item names no procedure; without the document lookup the vote stays unlinked
    assert votes["166566"].procedure_refs == []
    assert votes["166051"].procedure_refs == ["2021/0106(COD)"]


# ---------------------------------------------------------------------- old format (before 2024)
def test_old_format_roll_calls():
    votes, ballots = assemble("2019-10-24")
    v = votes["109643"]
    assert v.title == "B9-0154/2019 - Am 52"  # timestamp suffix removed
    assert (v.kind, v.outcome, v.reference_text, v.doc_ids) == ("amendment", "unknown", None, [])
    assert v.procedure_refs == ["2019/2755(RSP)"]  # label document B9-0154/2019 = the vote item's document
    assert (v.n_for, v.n_against, v.n_abstain) == (164, 455, 10)
    objection = votes["109583"]  # "B9-0151/2019 - Resolution", item "Objection … article 112 …"
    assert objection.kind == "motion" and objection.procedure_refs == ["2019/2844(RSP)"]
    assert objection.majority_rule == "votes_cast"  # objection to an implementing act: no Treaty exception
    assert objection.has_ballots and len(ballots["109583"].favor) == objection.n_for == 301
    assert votes["109687"].kind == "amendment"  # RC-B9-0118/2019 - Am 8
    assert votes["109687"].procedure_refs == ["2019/2854(RSP)"]  # joint motion -> plenary document
    assert votes["109744"].kind == "resolution"  # RC-B9-0156/2019 - Resolution
    assert votes["109706"].kind == "split_or_separate"  # RC-B9-0134/2019 - § 4


# ------------------------------------------------------------------------------- majority rules
def test_second_reading_needs_component_members():
    # the 8 July 2020 vote item omits "***II"; the item for the same report on 9 July carries it
    votes, _ = assemble("2020-07-08", "2020-07-09")
    rejection = votes["116206"]  # A9-0116/2020 - Proposal for rejection (Rule 67(1))
    assert rejection.kind == "motion" and rejection.procedure_refs == ["2017/0123(COD)"]
    assert rejection.majority_rule == "component_members"
    assert votes["115855"].kind == "amendment" and votes["115855"].majority_rule == "component_members"
    alone, _ = assemble("2020-07-08")
    assert alone["116206"].majority_rule == "unknown"  # no symbol, no rule


def test_second_reading_symbol_without_procedure():
    votes, _ = assemble("2026-07-09")
    for vid in ("195775", "195783"):  # "Temporary derogation from the ePrivacy directive ***II"
        assert votes[vid].procedure_refs == [] and votes[vid].majority_rule == "component_members"
    assert votes["195775"].kind == "motion" and votes["195783"].kind == "amendment"


def test_motion_of_censure():
    votes, _ = assemble("2025-07-10")
    v = votes["178149"]
    assert (v.kind, v.majority_rule, v.outcome) == ("motion", "two_thirds_cast", "rejected")
    assert (v.n_for, v.n_against, v.n_abstain) == (175, 360, 18)
    assert v.has_ballots


def test_objection_to_delegated_act():
    votes, _ = assemble("2026-07-08")
    v = votes["195361"]
    assert v.procedure_refs == ["2026/2680(DEA)"]
    assert (v.kind, v.majority_rule, v.outcome) == ("motion", "component_members", "adopted")


# -------------------------------------------------------------------------------------- snapshot
def _snapshot() -> tuple[list[EpVote], list[EpBallots]]:
    votes = read_records(ev.SOURCE_ID, "votes", EpVote)
    if not votes:
        pytest.skip("no ep_votes snapshot")
    return votes, read_records(ev.SOURCE_ID, "ballots", EpBallots)


def test_snapshot_votes():
    votes, ballots = _snapshot()
    ids = [v.id for v in votes]
    assert len(ids) == len(set(ids))
    with_ballots = {b.vote_id for b in ballots}
    assert with_ballots == {v.id for v in votes if v.has_ballots}
    for v in votes:
        assert re.fullmatch(r"\d+", v.id) and v.event_id.startswith(f"MTG-PL-{v.date}-")
        assert v.term == (9 if v.date <= "2024-07-15" else 10) and v.date >= ev.FIRST_SITTING
        assert all(ev.PROC_REF_RE.fullmatch(r) for r in v.procedure_refs)
        if v.has_ballots:
            assert v.method == ev.ROLLCALL and v.kind in ev.BALLOT_KINDS


def test_snapshot_ballot_invariants():
    votes, ballots = _snapshot()
    by_id = {v.id: v for v in votes}
    mismatches = {}
    for b in ballots:
        everyone = b.favor + b.against + b.abstain
        assert len(everyone) == len(set(everyone)), f"vote {b.vote_id}: an MEP is listed twice"
        assert all(re.fullmatch(r"\d+", p) for p in everyone + b.intended_favor + b.intended_against)
        if problems := ev.ballot_issues(by_id[b.vote_id], b):
            mismatches[b.vote_id] = problems
    if mismatches:  # reported, never corrected: the published counts and lists are kept as they are
        warnings.warn(f"{len(mismatches)} votes whose voter lists differ from the counts: {mismatches}")
    assert len(mismatches) <= len(ballots) * 0.005


def test_snapshot_ai_act():
    votes, _ = _snapshot()
    final = [v for v in votes if "2021/0106(COD)" in v.procedure_refs and v.date == "2024-03-13"]
    assert [(v.id, v.kind, v.n_for, v.n_against, v.n_abstain) for v in final] == [
        ("166051", "final", 523, 46, 49)
    ]


def test_snapshot_size():
    path = SNAPSHOT / ev.SOURCE_ID / "ballots.json"
    if not path.exists():
        pytest.skip("no ep_votes snapshot")
    assert path.stat().st_size < 25_000_000


# ------------------------------------------------------------------------------------------ live
@pytest.mark.network
def test_live_ai_act_sitting():
    from pipeline.http import default_http

    http = default_http()
    sitting = {"id": "MTG-PL-2024-03-13", "date": "2024-03-13", "term": 9}
    decisions, items = ev.fetch_sitting(http, sitting)
    res = ev.assemble([ev.Sitting.build(sitting, decisions, items)], ev.fetch_procedure_labels(http), {}, RETRIEVED)
    v = {x.id: x for x in res.votes}["166051"]
    assert (v.kind, v.procedure_refs, v.n_for, v.n_against, v.n_abstain) == (
        "final",
        ["2021/0106(COD)"],
        523,
        46,
        49,
    )


@pytest.mark.network
def test_live_document_link():
    from pipeline.http import default_http

    assert ev.fetch_document_links(default_http(), "RC-9-2024-0163")[0] == ["2024-2580"]
