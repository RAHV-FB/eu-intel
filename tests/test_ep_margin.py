"""Tests for pipeline.analysis.ep_margin on real vote records (tests/fixtures/ep_votes/)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.analysis.ep_margin import margin, statutory_seats, threshold
from tests.test_ep_votes import assemble


@pytest.fixture(scope="module")
def votes():
    out = {}
    for day in ("2024-03-13", "2024-09-19", "2025-07-10", "2025-10-07", "2026-07-08", "2026-07-09"):
        out.update(assemble(day)[0])
    return out


def test_statutory_seats():
    assert statutory_seats("2019-07-02") == 751
    assert statutory_seats("2020-01-31") == 751  # until the UK's withdrawal became legally effective
    assert statutory_seats("2020-02-01") == 705
    assert statutory_seats("2024-07-15") == 705
    assert statutory_seats("2024-07-16") == 720
    assert statutory_seats("2019-06-30") is None


def test_ai_act_majority_of_votes_cast(votes):
    m = margin(votes["166051"])  # 523 for, 46 against, 49 abstentions (abstentions are not votes cast)
    assert (m.rule, m.votes_cast, m.threshold, m.distance) == ("votes_cast", 569, 285, 238)
    assert m.relative == round(238 / 569, 4)
    assert m.label == "Majority reached: 238 votes more than needed"


def test_rejected_amendment(votes):
    m = margin(votes["166377"])  # 262 for, 351 against
    assert (m.threshold, m.distance, m.label) == (307, -45, "Majority not reached: 45 votes short")


def test_one_vote_majority(votes):
    v = votes["179413"]  # immunity decision, secret ballot: 306 for, 305 against, 17 abstentions, adopted
    assert (v.kind, v.method, v.procedure_refs) == ("final", "VOTE_ELECTRONIC_SECRET", ["2024/2086(IMM)"])
    m = margin(v)
    assert (m.threshold, m.distance) == (306, 0)
    assert m.label == "Majority reached with exactly the votes needed"


def test_budget_guidelines_rule_unknown(votes):
    v = votes[
        "166487"
    ]  # 272 for, 271 against in budget guidelines (BUI): not a type with an established rule
    assert v.majority_rule == "unknown" and margin(v) is None


def test_motion_of_censure_needs_component_members(votes):
    v = votes["178149"]  # 175 for, 360 against, 18 abstentions
    assert margin(v) is None  # the number of component Members is required
    m = margin(v, statutory_seats(v.date))
    # two-thirds of 535 votes cast = 357; majority of 720 Members = 361 -> 361 needed
    assert (m.rule, m.threshold, m.distance, m.label) == (
        "two_thirds_cast",
        361,
        -186,
        "Majority not reached: 186 votes short",
    )


def test_second_reading_amendment(votes):
    v = votes["195783"]  # 345 for, 237 against: rejected — more for than against, but below 361
    assert v.n_for > v.n_against and v.outcome == "rejected"
    m = margin(v, 720)
    assert (m.rule, m.threshold, m.distance) == ("component_members", 361, -16)


def test_objection_to_delegated_act(votes):
    m = margin(votes["195361"], 720)  # 388 for: adopted
    assert (m.rule, m.threshold, m.distance) == ("component_members", 361, 27)
    assert m.label == "Majority reached: 27 votes more than needed"


def test_unknown_rule_or_counts(votes):
    assert votes["166530"].outcome == "lapsed" and margin(votes["166530"]) is None  # no vote held
    assert margin(votes["166044"]) is None  # show of hands: no counts


SNAP_VOTES = Path(__file__).resolve().parent.parent / "data" / "snapshot" / "ep_votes" / "votes.json"


@pytest.mark.skipif(not SNAP_VOTES.exists(), reason="no snapshot")
def test_no_margin_for_an_outcome_that_is_not_established():
    from tests.test_build_real_records import votes as snapshot_votes

    # 116204 (8 Jul 2020, motion to reject the Council's position, 218 for, 469 against): the open data gives no
    # outcome and the sitting has no minutes XML; while no outcome is established (the snapshot now derives it from
    # the counts), "Majority not reached" would state a result not established
    v = snapshot_votes("116204")["116204"].model_copy(update={"outcome": "unknown"})
    assert v.majority_rule == "component_members"
    assert margin(v, 705) is None
    assert margin(v.model_copy(update={"outcome": "lapsed"}), 705) is None
    m = margin(v.model_copy(update={"outcome": "rejected"}), 705)  # the same counts with an established outcome
    assert m is not None and (m.threshold, m.distance) == (353, -135)


def test_contradiction_with_official_result_gives_none(votes):
    v = votes["169607"]  # split vote, 299 for, 299 against, published as ADOPTED
    assert (v.n_for, v.n_against, v.outcome, v.majority_rule) == (299, 299, "adopted", "votes_cast")
    assert margin(v) is None


def test_threshold_arithmetic():
    assert threshold("votes_cast", 300, 300, None) == 301  # a tie is not a majority
    assert threshold("votes_cast", 0, 0, None) is None
    assert threshold("component_members", 1, 1, 705) == 353
    assert threshold("two_thirds_cast", 600, 0, 720) == 400  # ceil(2/3 x 600)
    assert threshold("two_thirds_cast", 100, 10, 720) == 361
    assert threshold("unknown", 1, 1, 720) is None
