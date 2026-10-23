"""pipeline/build.py rules checked on the real records that showed each problem (data/snapshot/, read only).

Skipped when the snapshot is not present. Builder methods are called on a minimal stand-in holding only the
attributes they read.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.build import (
    Builder,
    commission_cod_proposal,
    rejection_title,
)
from pipeline.models.entities import CouncilVote, EpVote, LegalAct, Procedure

SNAP = Path(__file__).resolve().parent.parent / "data" / "snapshot"
pytestmark = pytest.mark.skipif(not (SNAP / "ep_procedures" / "procedures.json").exists(), reason="no snapshot")


def records(rel: str, ids: set[str], key: str = "id") -> dict[str, dict]:
    """Records of a snapshot file (one JSON record per line) whose `key` is in `ids`."""
    out = {}
    with (SNAP / rel).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip().rstrip(",")
            if line.startswith("{") and any(f'"{key}":"{i}"' in line for i in ids):
                r = json.loads(line)
                if r.get(key) in ids:
                    out[r[key]] = r
    assert set(out) == ids, ids - set(out)
    return out


def procs(*ids: str) -> dict[str, Procedure]:
    return {k: Procedure.model_validate(v) for k, v in records("ep_procedures/procedures.json", set(ids)).items()}


def council(*ids: str) -> dict[str, CouncilVote]:
    return {k: CouncilVote.model_validate(v) for k, v in records("council/votes.json", set(ids)).items()}


def acts(*celex: str) -> dict[str, LegalAct]:
    return {k: LegalAct.model_validate(v) for k, v in records("eurlex/acts.json", set(celex), "celex").items()}


def votes(*ids: str) -> dict[str, EpVote]:
    return {k: EpVote.model_validate(v) for k, v in records("ep_votes/votes.json", set(ids)).items()}


# ------------------------------------------------------------------------------- Council: split procedures
def test_council_votes_on_a_split_parent_go_to_the_part_whose_act_they_adopted():
    # ST 8688/23 and ST 8687/23 (25 Apr 2023) cite "2021/0211 (COD)"; the directive is 2021/0211A's act
    # (Directive (EU) 2023/959), the regulation 2021/0211B's (Regulation (EU) 2023/957). ST 10071/19 (14 Jun
    # 2019) adopted Regulation (EU) 2019/1243 of 2016/0400A; 2016/0400B was withdrawn and has no act.
    cv = council("ST-8688-2023", "ST-8687-2023", "ST-10071-2019")
    a = acts("32023L0959", "32023R0957", "32019R1243")
    me = SimpleNamespace(
        split_children={"2021-0211": ["2021-0211A", "2021-0211B"], "2016-0400": ["2016-0400A", "2016-0400B"]},
        acts_of={"2021-0211A": [a["32023L0959"]], "2021-0211B": [a["32023R0957"]], "2016-0400A": [a["32019R1243"]]},
    )
    part = lambda vid, pid: Builder.council_split_part(me, cv[vid], pid)  # type: ignore[arg-type]  # noqa: E731
    assert part("ST-8688-2023", "2021-0211") == "2021-0211A"
    assert part("ST-8687-2023", "2021-0211") == "2021-0211B"
    assert part("ST-10071-2019", "2016-0400") == "2016-0400A"
    assert part("ST-8688-2023", "2021-0211A") is None  # not a split parent: nothing to move
    # two parts with an act of the same type: the act title decides
    me.acts_of["2021-0211B"] = [a["32023R0957"], a["32023L0959"].model_copy(update={"celex": "X"})]
    assert part("ST-8688-2023", "2021-0211") is None  # both titles match: ambiguous, stays on the parent
    me.acts_of["2021-0211B"] = [a["32023R0957"]]
    me.acts_of["2021-0211A"] = [a["32023L0959"], a["32023R0957"].model_copy(update={"act_type": "directive"})]
    assert part("ST-8688-2023", "2021-0211") == "2021-0211A"


# --------------------------------------------------------------------------- Council: what was voted on
def test_early_second_reading_vote_on_the_council_position_is_not_the_act():
    # ST 12604/20 (written procedure, 4 Nov 2020) is headed "Adoption of the legislative act", but its
    # reference document 9890/20 is the Council's first-reading position (OEIL: 6 Nov 2020, 09890/2/2020);
    # Parliament approved that position at second reading on 23 Nov 2020 (Art. 294(7)(a) TFEU)
    cv = council("ST-12604-2020", "ST-12592-2020", "ST-13733-2020")
    p = procs("2018-0204", "2018-0203", "2018-0170")
    on, note = Builder.council_vote_on(None, cv["ST-12604-2020"], p["2018-0204"])  # type: ignore[arg-type]
    assert (cv["ST-12604-2020"].vote_on, on) == ("act", "first_reading_position")
    assert note and "ST 9890/20" in note and "09890/2/2020" in note and "23 November 2020" in note
    assert Builder.council_vote_on(None, cv["ST-12592-2020"], p["2018-0203"])[0] == "first_reading_position"  # type: ignore[arg-type]
    assert Builder.council_vote_on(None, cv["ST-13733-2020"], p["2018-0170"])[0] == "first_reading_position"  # type: ignore[arg-type]
    # the same vote without the later second-reading decision keeps the document's own label
    before = p["2018-0204"].model_copy(update={"events": [e for e in p["2018-0204"].events if e.date <= "2020-11-06"]})
    assert Builder.council_vote_on(None, cv["ST-12604-2020"], before) == ("act", None)  # type: ignore[arg-type]


def test_voting_result_naming_no_item_on_the_day_the_council_adopted_the_act():
    # ST 11980/21 (21 Sep 2021, PE-CONS 62/21) names no item; OEIL: "Act adopted by Council after
    # Parliament's 1st reading" on 21/09/2021
    cv = council("ST-11980-2021")["ST-11980-2021"]
    p = procs("2021-0228")["2021-0228"]
    on, note = Builder.council_vote_on(None, cv, p)  # type: ignore[arg-type]
    assert (cv.vote_on, on) == (None, "act") and note and "does not name the item" in note
    later = p.model_copy(update={"events": [e for e in p.events if e.kind.value != "council_adoption"]})
    assert Builder.council_vote_on(None, cv, later) == (None, None)  # type: ignore[arg-type]


def test_commission_proposal_of_an_ordinary_procedure_without_its_com_number():
    p = procs("2023-0052", "2010-0817", "2021-0106")
    assert not p["2023-0052"].com_refs and commission_cod_proposal(p["2023-0052"])
    assert not commission_cod_proposal(p["2010-0817"])  # initiative of Member States (09288/2010)
    assert commission_cod_proposal(p["2021-0106"])


def test_both_qmv_thresholds_are_given_when_the_legal_basis_is_not_established():
    from pipeline.analysis.council_qmv import assess

    cv = council("ST-7930-2022")["ST-7930-2022"]  # 2022/0077(COD): 25 of 25 taking part
    a = Builder.council_rule_assessment(None, assess, cv, None)  # type: ignore[arg-type]
    assert a and a["legal_basis"] is None and (a["states_required"], a["states_required_alt"]) == (14, 18)
    p = procs("2022-0077")["2022-0077"]
    b = Builder.council_rule_assessment(None, assess, cv, p)  # type: ignore[arg-type]
    # on a Commission proposal, with Denmark and Ireland not taking part: Art. 238(3)(a) TFEU
    assert b and b["legal_basis"] == "TFEU Art. 238(3)(a)" and b["states_required_alt"] is None


# ------------------------------------------------------------------- Parliament's decisions in the timeline
def test_first_reading_decision_whose_final_vote_was_rejected():
    # 2025/0429(COD), 26 Mar 2026: "Commission proposal" REJECTED 228-311-92 (EP API DEC-189270); OEIL summary
    # of T10-0095/2026: "the European Parliament rejected the proposal". 9 Jul 2026: two motions to reject the
    # Council's position, both rejected (314-276-17, 276-286-30), and the position amended (T10-0266/2026).
    p = procs("2025-0429")["2025-0429"]
    v = votes("189270", "195775", "195807", "186972")
    me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-22")
    tl = {e["date"]: e for e in Builder.timeline(me, p, [], list(v.values())) if e["kind"] == "ep_position"}  # type: ignore[arg-type]
    assert (tl["2026-03-26"]["title"], tl["2026-03-26"]["vote_id"]) == ("Parliament rejected the proposal at first reading", "189270")
    assert tl["2026-07-09"]["title"] == "Parliament amended the Council's position at second reading"
    assert tl["2026-07-09"]["vote_id"] == "195775"
    assert tl["2026-07-09"]["detail"].startswith("Parliament voted on 2 motions to reject the Council's position")
    # an adopted final vote on the same day: the event keeps its source title
    adopted = {**v, "189270": v["189270"].model_copy(update={"outcome": "adopted"})}
    tl2 = Builder.timeline(me, p, [], list(adopted.values()))  # type: ignore[arg-type]
    assert next(e for e in tl2 if e["date"] == "2026-03-26" and e["kind"] == "ep_position")["title"] == (
        "Parliament took its decision (first reading)"
    )


def test_rejection_titles_fit_the_procedure():
    p = procs("2019-0819", "2025-0580", "2022-0196")
    assert rejection_title(p["2019-0819"]) == "Parliament delivered its opinion: it rejected the Council's draft"
    assert rejection_title(p["2025-0580"]) == "Parliament delivered its opinion: it rejected the proposal"
    assert rejection_title(p["2022-0196"]) == "Parliament rejected the proposal at first reading"


def test_rejected_final_vote_on_a_file_that_later_became_law_says_so():
    p = procs("2025-0429")["2025-0429"]
    v = votes("189270")["189270"]
    me = SimpleNamespace(acts_of={"2025-0429": list(acts("32026R1881").values())})
    note = Builder.later_act_note(me, v, p)  # type: ignore[arg-type]
    assert note == (
        "Parliament rejected the text in this vote, but the procedure continued: it later produced "
        "Regulation (EU) 2026/1881."
    )
    assert Builder.later_act_note(SimpleNamespace(acts_of={}), v, p) is None  # type: ignore[arg-type]


def test_derived_rejection_is_not_repeated_next_to_the_decision_it_restates():
    # 2022/0196(COD), 22 Nov 2023: Parliament's decision (final vote 161821 REJECTED 207-299-121, minutes) is titled
    # as the rejection; the event derived from the vote for the status must not appear a second time
    from pipeline.models.entities import Event, EventKind

    p = procs("2022-0196")["2022-0196"]
    v = votes("161821")
    derived = Event(
        id="vote-161821-rejected", date="2023-11-22", kind=EventKind.rejection, raw_type="ep_vote:final:rejected",
        institution="EP", title="Parliament rejected the proposal in a plenary vote", source=v["161821"].source,
    )  # fmt: skip
    p = p.model_copy(update={"events": sorted([*p.events, derived], key=lambda e: (e.date, e.id))})
    me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-22")
    tl = Builder.timeline(me, p, [], list(v.values()))  # type: ignore[arg-type]
    day = [(e["kind"], e["title"]) for e in tl if e["date"] == "2023-11-22" and "reject" in e["title"]]
    assert day == [("ep_position", "Parliament rejected the proposal at first reading")]
