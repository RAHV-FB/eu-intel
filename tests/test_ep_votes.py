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


def load_sitting(day: str, minutes: bool = True, base: Path = FIX) -> ev.Sitting:
    raw = json.loads((base / f"sitting_{day}.json").read_text(encoding="utf-8"))
    sid = raw["sitting"]
    xml = base / f"minutes_{day}.xml"
    return ev.Sitting.build(
        {"id": sid, "date": sid[7:17], "term": _term(sid[7:17])},
        raw["decisions"]["data"],
        raw["vote_results"]["data"],
        ev.parse_minutes(xml.read_bytes()) if minutes and xml.exists() else [],
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


def referrals() -> dict[str, list[str]]:
    raw = json.loads((FIX / "procedure_2021-0106.json").read_text(encoding="utf-8"))
    return ev.parse_procedures(raw["data"])[1]


def assemble(
    *days: str, links: bool = True, minutes: bool = True, refer: bool = True
) -> tuple[dict[str, EpVote], dict[str, EpBallots]]:
    res = ev.assemble(
        [load_sitting(d, minutes) for d in days],
        proc_labels(),
        doc_links() if links else {},
        RETRIEVED,
        referrals=referrals() if refer else None,
    )
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
    assert (
        ev.label_tail("A9-0139/2021 - Angel Dzhambazki -Annex, Part B, indent 3/1")
        == "Annex, Part B, indent 3/1"
    )
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
    assert (
        v.outcome == "adopted" and v.outcome_basis == "published" and v.method == "VOTE_ELECTRONIC_ROLLCALL"
    )
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
    assert (v.kind, v.reference_text, v.doc_ids) == ("amendment", None, [])
    assert (v.outcome, v.outcome_basis) == ("rejected", "minutes")  # the API has no outcome before 2024
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


def test_old_format_outcomes_from_minutes():
    votes, _ = assemble("2019-10-24")
    got = {vid: (votes[vid].outcome, votes[vid].outcome_basis) for vid in sorted(votes)}
    assert got == {
        "109582": ("adopted", "minutes"),  # B9-0117/2019 - Resolution (572, 42, 21)
        "109583": ("adopted", "minutes"),  # objection B9-0151/2019 (301, 295, 45)
        "109643": ("rejected", "minutes"),
        "109687": ("adopted", "minutes"),  # RC-B9-0118/2019 - Am 8 (474, 104, 49)
        "109706": ("adopted", "minutes"),
        "109744": ("adopted", "minutes"),
    }
    no_minutes, _ = assemble("2019-10-24", minutes=False)
    # without the minutes only votes under an established rule get an outcome, marked "derived"
    assert (no_minutes["109643"].outcome, no_minutes["109643"].outcome_basis) == ("rejected", "derived")
    assert all(v.outcome_basis in ("derived", None) for v in no_minutes.values())


def test_zero_against_left_out_by_the_api():
    # 12 Dec 2023, A9-0355/2023 (2023/0027(CNS)): the decision has 604 for and 5 abstentions but no
    # "against" count and no voter in that position; the minutes print "Commission proposal | RCV | + | 604
    # | 0 | 5" (PV-9-2023-12-12-VOT)
    raw = json.loads((FIX / "sitting_2023-12-12.json").read_text(encoding="utf-8"))["decisions"]["data"][0]
    assert "number_of_votes_against" not in raw and "had_voter_against" not in raw
    assert ev.vote_counts(raw) == (604, 0, 5)
    assert ev.vote_counts({"number_of_votes_favor": 3, "had_voter_against": ["person/1"]}) == (3, 1, 0)
    assert ev.vote_counts({"decision_method": "def/ep-decision-methods/VOTE_SHOW_OF_HANDS"}) == (None,) * 3
    votes, ballots = assemble("2023-12-12")
    v = votes["162156"]
    assert (v.n_for, v.n_against, v.n_abstain) == (604, 0, 5)
    assert (v.kind, v.outcome, v.outcome_basis, v.majority_rule) == ("final", "adopted", "minutes", "votes_cast")
    assert v.procedure_refs == ["2023/0027(CNS)"] and ballots["162156"].against == []
    no_minutes, _ = assemble("2023-12-12", minutes=False)
    assert (no_minutes["162156"].outcome, no_minutes["162156"].outcome_basis) == ("adopted", "derived")


# Votes that were not linked or not classed as Parliament's decision (fixtures in linking/: real API answers of
# one decision and its vote item each; the procedure references are the EP API's labels of those ids)
LINKING = FIX / "linking"
LINK_LABELS = {
    "2021-0211A": "2021/0211A(COD)", "2020-0036": "2020/0036(COD)", "2025-0045": "2025/0045(COD)",
    "2018-0108": "2018/0108(COD)",
}  # fmt: skip


def link(day: str, vid: str, **kw) -> EpVote:
    res = ev.assemble([load_sitting(day, base=LINKING)], LINK_LABELS, {}, RETRIEVED, **kw)
    return next(v for v in res.votes if v.id == vid)


def test_split_procedure_reference_keeps_its_letter():
    # 18 Apr 2023, ETS revision: the vote item lists eli/dl/proc/2021-0211A (the split part of 2021/0211(COD))
    v = link("2023-04-18", "154173")
    assert v.title == "A9-0162/2022 – Peter Liese – Provisional agreement – Am 680"
    assert (v.procedure_refs, v.kind) == (["2021/0211A(COD)"], "final")
    assert ev.ref_to_process_id("2021/0211A(COD)") == "2021-0211A"


def test_provisional_agreement_named_only_in_the_minutes():
    # 24 Jun 2021, European Climate Law: the label is "A9-0162/2020 - Jytte Guteland - Am 176"; the minutes
    # row reads "Provisional agreement | 176 | committee | RCV | + | 442 203 51" (PV-9-2021-06-24-VOT)
    # the 2021 vote item lists no procedure: the item of 7 Oct 2020 on the same report does (state index)
    known = {"A-9-2020-0162": {"procs": ["2020-0036"], "symbols": ["***I"]}}
    v = link("2021-06-24", "134029", known_docs=known)
    assert (v.n_for, v.n_against, v.n_abstain) == (442, 203, 51)
    assert (v.kind, v.outcome, v.outcome_basis) == ("final", "adopted", "minutes")
    assert (v.procedure_refs, v.majority_rule, v.has_ballots) == (["2020/0036(COD)"], "votes_cast", True)
    without = ev.assemble([load_sitting("2021-06-24", minutes=False, base=LINKING)], LINK_LABELS, {}, RETRIEVED)
    assert without.votes[0].kind == "amendment"  # nothing else says it was the agreement
    # a misspelt marker in the label (European Year of Youth, 14 Dec 2021, 137684)
    label = "European Year of Youth 2022 - A9-0322/2021 - Sabine Verheyen - Provisonal agreement - Am 2"
    assert ev.is_provisional_agreement("", "", label)


def test_referral_back_recorded_the_next_day_makes_a_mandate():
    # 7 Oct 2020 (remote voting), European Climate Law, "Proposition de la Commission" 392-161-142; the
    # referral back to committee (procedure event PLENARY_REFER_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS)
    # is dated 8 Oct 2020
    assert link("2020-10-07", "118521").kind == "final"
    assert link("2020-10-07", "118521", referrals={"2020-0036": ["2020-10-08"]}).kind == "mandate"
    assert link("2020-10-07", "118521", referrals={"2020-0036": ["2020-10-12"]}).kind == "final"
    assert not ev.referred_after("2020-10-07", ["2020-10-06"])


def test_document_number_with_a_non_breaking_hyphen():
    # 13 Jun 2023, e-evidence: "… – A9‑0256/2020 – Birgit Sippel – Provisional agreement – Am 2" (U+2011)
    v = link("2023-06-13", "155928")
    assert "A9‑0256/2020" in v.title
    assert (v.kind, v.procedure_refs) == ("final", ["2018/0108(COD)"])
    assert ev.doc_ref_to_id(ev.ascii_hyphens("A9‑0256/2020")) == "A-9-2020-0256"


def test_secret_ballot_item_named_only_by_its_report():
    # 22 Oct 2025, Omnibus I: the item of the secret ballot on the committee's negotiating mandate (309-318-34)
    # lists no procedure and no document; its structuredLabel names "Report: Jörgen Warborn (A10-0197/2025)",
    # the report other vote items (here: the state's document index) link to 2025/0045(COD)
    known = {"A-10-2025-0197": {"procs": ["2025-0045"], "symbols": ["***I"]}}
    assert link("2025-10-22", "180328").procedure_refs == []
    v = link("2025-10-22", "180328", known_docs=known)
    assert (v.procedure_refs, v.kind, v.kind_detail, v.outcome) == (
        ["2025/0045(COD)"], "procedural", "negotiation_decision", "rejected"
    )  # fmt: skip


def test_minutes_rows():
    rows = ev.parse_minutes((FIX / "minutes_2023-06-14.xml").read_bytes())
    ai = [r for r in rows if r.counts == (499, 28, 93)]
    assert [(r.item, r.outcome, "A-9-2023-0188" in r.docs) for r in ai] == [("6.", "adopted", True)]


def test_ai_act_2023_mandate_vote():
    # 14 June 2023: the amended Commission proposal was voted (499, 28, 93) and the file was referred back to
    # committee for negotiations (procedure event 2021-0106-DEC-REFBAK-2023-06-14): a mandate, not the position
    votes, _ = assemble("2023-06-14")
    v = votes["156022"]
    assert (v.n_for, v.n_against, v.n_abstain) == (499, 28, 93)
    assert v.procedure_refs == ["2021/0106(COD)"]
    assert (v.kind, v.outcome, v.outcome_basis, v.majority_rule) == (
        "mandate",
        "adopted",
        "minutes",
        "votes_cast",
    )
    assert v.has_ballots
    assert votes["156150"].kind == "split_or_separate"
    without_events, _ = assemble("2023-06-14", refer=False)
    assert without_events["156022"].kind == "final"  # no referral recorded -> the vote on the text


def test_referral_back_in_the_same_vote_item_makes_a_mandate():
    votes, _ = assemble("2024-03-13", refer=False)
    # Ukraine trade measures (A9-0077/2024): "Commission proposal" adopted, then referral back (166656) adopted
    assert votes["166656"].kind == "procedural" and votes["166656"].outcome == "adopted"
    assert votes["166551"].kind == "mandate" if "166551" in votes else True


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
    assert v.kind_detail == "objection"
    # the English vote item title says what was objected to (the label is only "B10-0337/2026 – Motion …")
    assert v.subject is not None and v.subject.startswith("Objection pursuant to Rule 114(3): Trajectory")
    assert v.title == "B10-0337/2026 – Motion for a resolution (as a whole)"


# ------------------------------------------------------------------- whole-text votes (audit regressions)
@pytest.mark.parametrize(
    "label,heading,ref,kind",
    [
        # old format: the agreement sits in the second-to-last segment, before its amendment number
        ("Digital Services Act - A9-0356/2021 - Christel Schaldemose - Provisional agreement - Am 564", None, None,
         "final"),
        ("Framework for ensuring a secure and sustainable supply of critical raw materials – A9-0260/2023 – Nicola "
         "Beer – Provisional agreement – Am 26", None, None, "final"),
        ("A9-0214/2020 - Eider Gardiazabal Rubial - Joint Statement - Am 3", None, None, "amendment"),
        # new format: a statement voted under the "Provisional agreement" heading is not the agreement
        ("A9-0220/2023 – César Luena – Commission statement – Am 138", "Provisional agreement",
         "Commission statement", "amendment"),
        ("A9-0220/2023 – César Luena – Provisional agreement – Am 137", "Provisional agreement",
         "Provisional agreement", "final"),
    ],
)  # fmt: skip
def test_provisional_agreement_is_the_whole_text(label, heading, ref, kind):
    docs = ["A-9-2023-0220-AM-138"] if ref == "Commission statement" else []
    signals = ev.Signals(ref=ref or ev.label_tail(label), label=label, heading=heading, docs=docs)
    assert ev.classify(signals) == kind


def test_old_format_provisional_agreements_dsa_dma():
    # 5 July 2022: Parliament's final votes on the DSA (Am 564) and the DMA (Am 256), old label format
    votes, ballots = assemble("2022-07-05")
    dsa, dma = votes["146649"], votes["146588"]
    assert (dsa.kind, dsa.outcome, dsa.outcome_basis) == ("final", "adopted", "minutes")
    assert (dsa.n_for, dsa.n_against, dsa.n_abstain) == (539, 54, 30)
    assert dsa.procedure_refs == ["2020/0361(COD)"] and dma.procedure_refs == ["2020/0374(COD)"]
    assert dma.kind == "final" and (dma.n_for, dma.n_against, dma.n_abstain) == (588, 11, 31)
    assert dsa.has_ballots and len(ballots["146649"].favor) == 539  # whole-text roll call keeps its ballots
    assert dsa.subject == "Digital Services Act ***I"  # block title of the English minutes


def test_statement_under_the_agreement_heading_and_the_lapsed_proposal():
    # Nature Restoration, 27 Feb 2024: the agreement (Am 137) is the final vote; the Commission statement
    # (Am 138, voted under the same heading) is not; the "Commission proposal" decision lapsed unheld
    votes, ballots = assemble("2024-02-27")
    agreement, statement, lapsed = votes["164499"], votes["164800"], votes["164513"]
    assert (agreement.kind, agreement.n_for, agreement.n_against) == ("final", 329, 275)
    assert statement.kind == "amendment" and not statement.has_ballots and "164800" not in ballots
    assert (lapsed.kind, lapsed.outcome, lapsed.n_for) == ("other", "lapsed", None)
    assert all(v.procedure_refs == ["2022/0195(COD)"] for v in (agreement, statement, lapsed))


def test_rejected_commission_proposal_stays_the_final_vote():
    # SIOFA, 11 July 2023: the minutes record "Commission proposal — 48/585/6"; adopted text
    # TA-9-2023-0265 reads "1. Rejects the Commission proposal; 2. Calls on the Commission to withdraw its
    # proposal". Parliament rejected the proposal: a final vote, outcome rejected (not lapsed, not an amendment)
    votes, _ = assemble("2023-07-11")
    v = votes["156775"]
    assert (v.kind, v.outcome, v.outcome_basis) == ("final", "rejected", "minutes")
    assert (v.n_for, v.n_against, v.n_abstain) == (48, 585, 6)
    assert v.procedure_refs == ["2022/0348(COD)"]
    assert v.subject is not None and "(SIOFA)" in v.subject


def test_urgent_procedure_items_link_through_their_structured_label():
    # Deforestation Regulation revision, 17 Dec 2025: the vote item names its procedure only in
    # structuredLabel "(COM(2025)0652 – C10-0263/2025 – 2025/0329(COD))"
    votes, _ = assemble("2025-12-17")
    agreement, rejection = votes["182886"], votes["182885"]
    assert agreement.procedure_refs == rejection.procedure_refs == ["2025/0329(COD)"]
    assert (agreement.kind, agreement.majority_rule) == ("final", "votes_cast")
    assert (rejection.kind, rejection.kind_detail, rejection.outcome) == (
        "motion",
        "reject_proposal",
        "rejected",
    )
    assert rejection.subject == "Deforestation Regulation: certain obligations of operators and traders ***I"
    item = {"structuredLabel": "<structuredLabel><title>T</title><label>Proposal (COM(2025)0652 – "
                               "C10-0263/2025 – 2025/0329(COD))</label></structuredLabel>"}  # fmt: skip
    assert ev.structured_label_refs(item) == ["2025/0329(COD)"]


def test_whole_text_amendment_is_an_amendment():
    # urgent procedure, 14 Mar 2024: "Text as a whole" with amendment number 1 (by ECON, show of hands) is an
    # amendment replacing the text; the vote on the "Commission proposal" is the final vote
    votes, _ = assemble("2024-03-14")
    assert votes["166652"].kind == "amendment"
    assert (votes["166653"].kind, votes["166653"].procedure_refs) == ("final", ["2024/0019(COD)"])


def test_motion_details():
    votes, ballots = assemble("2025-07-10", "2026-07-09")
    assert votes["178149"].kind_detail == "censure"
    assert (
        votes["195775"].kind_detail == "reject_council_position"
    )  # ***II, "Proposal to reject the Council position"
    assert votes["195783"].kind_detail is None  # an amendment
    # the roll call confirming the committee's decision to negotiate (digital euro) keeps its ballots
    neg = votes["195719"]
    assert (neg.kind, neg.kind_detail, neg.outcome) == ("procedural", "negotiation_decision", "adopted")
    assert (neg.n_for, neg.n_against, neg.n_abstain) == (416, 169, 22)
    assert neg.procedure_refs == ["2023/0212(COD)"] and neg.has_ballots and "195719" in ballots


def test_minutes_block_titles():
    rows = ev.parse_minutes((FIX / "minutes_2023-07-11.xml").read_bytes())
    siofa = [r for r in rows if r.counts == (48, 585, 6)]
    assert [(r.outcome, r.symbol) for r in siofa] == [("rejected", "***I")]
    assert siofa[0].title is not None and siofa[0].title.endswith("(SIOFA) ***I")


# ------------------------------------------------- kinds, outcomes and subjects (fixtures in kinds/, real records)
KINDS = FIX / "kinds"


def kinds(day: str, labels: dict[str, str], links: dict | None = None, **kw) -> dict[str, EpVote]:
    res = ev.assemble([load_sitting(day, base=KINDS)], labels, links or {}, RETRIEVED, **kw)
    return {v.id: v for v in res.votes}


def test_recommendation_to_raise_no_objections_is_not_an_objection():
    # 24 Nov 2022, B9-0490/2022, 2022/2899(DEA): vote item "Recommandation de décision de ne pas s'opposer à un
    # acte délégué: …"; minutes PV-9-2022-11-24-VOT item 7 "Decision to raise no objections pursuant to Rule
    # 111(6) | Recommendation for a decision | RCV | + | 445/102/24". Rule 111(6) only says the recommendation
    # "shall be put to the vote" (Rule 111(5) and Art. 290(2) TFEU require component Members for the objection)
    v = kinds("2022-11-24", {"2022-2899": "2022/2899(DEA)"})["150746"]
    assert (v.kind, v.kind_detail, v.majority_rule) == ("motion", "no_objection", "votes_cast")
    assert (v.outcome, v.outcome_basis, v.n_for, v.n_against, v.n_abstain) == ("adopted", "minutes", 445, 102, 24)
    assert v.subject is not None and v.subject.startswith("Decision to raise no objections pursuant to Rule 111(6)")
    # 23 Apr 2024, 168696: English item title "Recommendation for a decision not to oppose a delegated act: …"
    sig = ev.Signals(ref="B9-0199/2024", label="B9-0199/2024 – Draft decision", proc_types=["DEA"],
                     item_title="Recommendation for a decision not to oppose a delegated act: rules on the ratio")  # fmt: skip
    assert ev.kind_detail("motion", sig, None) == "no_objection"
    objection = ev.Signals(ref="Motion for a resolution", label="B10-0337/2026 – Motion for a resolution",
                           proc_types=["DEA"], item_title="Objection pursuant to Rule 114(3): Trajectory …")  # fmt: skip
    assert ev.kind_detail("motion", objection, None) == "objection"
    assert ev.majority_rule("motion", None, None, ["DEA"], "objection") == "component_members"


def test_own_initiative_single_vote_is_the_resolution():
    # 18 May 2021, 2020/2042(INI): the label ends "Commission proposal", the minutes (PV-9-2021-05-18-VOT item
    # 21) "Motion for a resolution (text as a whole) | RCV | − | 255/260/170": an own-initiative resolution
    v = kinds("2021-05-18", {"2020-2042": "2020/2042(INI)"}, {"A-9-2021-0115": (["2020-2042"], [])})["131503"]
    assert v.procedure_refs == ["2020/2042(INI)"]
    assert (v.kind, v.outcome, v.outcome_basis) == ("resolution", "rejected", "minutes")
    single = ev.Signals(ref="Single vote", label="LGBTIQ rights in the EU - B9-0431/2021 - Single vote",
                        proc_types=["RSP"])  # fmt: skip
    assert ev.classify(single) == "resolution"
    decision = ev.Signals(ref="Proposal for a decision", label="… – Proposal for a decision", proc_types=["RSP"])
    assert ev.classify(decision) == "final"  # a decision, not a resolution
    legislative = ev.Signals(ref="Commission proposal", label="… - A9-0149/2021 - … - Commission proposal",
                             proc_types=["INI"], symbol="***I")  # fmt: skip
    assert ev.classify(legislative) == "final"  # the minutes title the item "***I": not a resolution


def test_french_minutes_of_the_2020_remote_voting_sittings():
    # 13 May 2020: the "Results of votes" exist only as PV-9-2020-05-13-VOT-FNL_fr.xml; item 1 "Accord sur le
    # statut UE-Monténégro … *** | Procédure d'approbation | AN | + | 568/109/11", item 9 "Un filet de sécurité …
    # | Vote unique | AN | + | 616/29/46" (A9-0099/2020, 2020/2051(INL), a resolution)
    rows = ev.parse_minutes((KINDS / "minutes_2020-05-13.xml").read_bytes())
    assert {(r.item, r.outcome, r.symbol, r.title) for r in rows} == {
        ("1.", "adopted", "***", None),  # French block titles are not used as the English subject
        ("9.", "adopted", None, None),
    }
    labels = {"2019-0043": "2019/0043(NLE)", "2020-2051": "2020/2051(INL)"}
    links = {"A-9-2020-0018": (["2019-0043"], []), "A-9-2020-0099": (["2020-2051"], [])}
    titles = {"2020-2051": "A safety net to protect the beneficiaries of EU programmes: setting up an MFF "
                           "contingency plan"}  # fmt: skip
    votes = kinds("2020-05-13", labels, links, proc_titles=titles)
    consent, plan = votes["112779"], votes["113647"]
    assert (consent.outcome, consent.outcome_basis, consent.n_for) == ("adopted", "minutes", 568)
    assert consent.subject is None  # no English title and no procedure title given
    assert (plan.kind, plan.outcome, plan.outcome_basis) == ("resolution", "adopted", "minutes")
    assert plan.subject == titles["2020-2051"]  # the title of its only procedure (EP API process_title)


def test_minutes_fall_back_to_the_french_expression():
    class Http:
        def __init__(self):
            self.urls: list[str] = []

        def get(self, url: str, **_kw) -> bytes:
            self.urls.append(url)
            if url.endswith("/documents/PV-9-2020-05-13-VOT"):
                meta = {"data": [{"is_realized_by": [{"id": "eli/dl/doc/PV-9-2020-05-13-VOT/fr", "is_embodied_by": [
                    {"format": "http://publications.europa.eu/resource/authority/file-type/XML",
                     "is_exemplified_by": "distribution/doc/PV-9-2020-05-13-VOT-FNL_fr.xml"}]}]}]}  # fmt: skip
                return json.dumps(meta).encode()
            if url.endswith("PV-9-2020-05-13-VOT-FNL_fr.xml"):
                return (KINDS / "minutes_2020-05-13.xml").read_bytes()
            return b""  # the English XML: 404

    http = Http()
    rows = ev.fetch_minutes(http, {"id": "MTG-PL-2020-05-13", "date": "2020-05-13", "term": 9})  # type: ignore[arg-type]
    assert len(rows) == 2 and http.urls[-1].endswith("PV-9-2020-05-13-VOT-FNL_fr.xml")


def test_outcome_settled_by_the_counts_under_every_rule():
    # 151201, 13 Dec 2022, early termination of a Vice-President's term (Eva Kaili), 625-1-2: not in the
    # "Results of votes" annex; the main minutes (PV-9-2022-12-13, item 8.1) record "Approved by RCV (625 in
    # favour, 1 against, 2 abstentions)" under "Majority of Parliament's component Members and two thirds of
    # the votes cast required"
    assert ev.derived_outcome("unknown", (625, 1, 2), "2022-12-13") == "adopted"
    assert ev.derived_outcome("two_thirds_cast", (625, 1, 2), "2022-12-13") == "adopted"
    # 8 Jul 2020, motions to reject the Council's position (Mobility Package), majority of component Members
    assert ev.derived_outcome("component_members", (174, 513, 1), "2020-07-08") == "rejected"
    assert ev.derived_outcome("component_members", (353, 300, 10), "2020-07-08") == "adopted"  # 705 seats
    assert ev.derived_outcome("component_members", (352, 300, 10), "2020-07-08") is None  # depends on who sat
    assert ev.derived_outcome("component_members", (376, 300, 10), "2019-10-24") == "adopted"  # 751 seats
    assert ev.derived_outcome("component_members", (375, 300, 10), "2019-10-24") is None
    # no established rule: only a result that holds under every rule
    assert ev.derived_outcome("unknown", (626, 25, 40), "2020-10-20") == "adopted"  # 122258
    assert ev.derived_outcome("unknown", (400, 300, 10), "2020-10-20") is None  # not two thirds
    assert ev.derived_outcome("unknown", (300, 301, 10), "2020-10-20") == "rejected"
    assert ev.derived_outcome("votes_cast", (300, 300, 10), "2020-10-20") is None  # a tie is not derived
    assert ev.derived_outcome("two_thirds_cast", (400, 300, 0), "2025-07-10") == "rejected"


def test_label_with_another_items_document_number():
    # 27 Apr 2021: the Eurofound 2019 discharge (130628, 612-83-3) is labelled with A9-0074/2021, the European
    # GNSS Agency report (block 76, "Report: Ryszard Czarnecki (A9-0074/2021)"); the minutes record its counts
    # in block 59, "2019 discharge: European Foundation for the Improvement of Living and Working Conditions |
    # Report: Joachim Stanisław Brudziński (A9-0094/2021)" (612-83-3 is also a count of block 49)
    sitting = load_sitting("2021-04-27", base=LINKING)
    decs = {str(d["notation_votingId"]): d for d in sitting.decisions}
    eurofound, gnss = ev.draft(decs["130628"], sitting), ev.draft(decs["130645"], sitting)
    assert eurofound.label_docs == ["A-9-2021-0094"] and gnss.label_docs == ["A-9-2021-0074"]
    labels = {"2020-2151": "2020/2151(DEC)", "2020-2168": "2020/2168(DEC)"}
    links = {"A-9-2021-0094": (["2020-2151"], []), "A-9-2021-0074": (["2020-2168"], [])}
    votes = {v.id: v for v in ev.assemble([sitting], labels, links, RETRIEVED).votes}
    assert votes["130628"].procedure_refs == ["2020/2151(DEC)"]
    assert votes["130628"].subject == "2019 discharge: European Foundation for the Improvement of Living and Working Conditions"
    assert (votes["130628"].outcome, votes["130628"].outcome_basis) == ("adopted", "minutes")
    assert votes["130645"].procedure_refs == ["2020/2168(DEC)"]
    assert votes["130645"].subject == "2019 discharge: European GNSS Agency"
    assert ev.label_subject(eurofound.label) == (
        "2019 discharge: European Foundation for the Improvement of Living and Working Conditions",
        ["Joachim Stanisław Brudziński"],
    )


# ----------------------------------- links through the minutes, mandates and rejections (fixtures in minutes_links/)
MLINKS = FIX / "minutes_links"
MLINK_LABELS = {
    "2020-0362": "2020/0362(COD)", "2020-0363": "2020/0363(COD)", "2020-0364": "2020/0364(COD)",
    "2020-0366": "2020/0366(COD)", "2020-0322": "2020/0322(COD)", "2020-0320": "2020/0320(COD)",
    "2022-0090": "2022/0090(COD)", "2022-0096": "2022/0096(COD)", "2021-0068": "2021/0068(COD)",
    "2021-0071": "2021/0071(COD)", "2018-0247": "2018/0247(COD)", "2018-0152A": "2018/0152A(COD)",
    "2021-0211A": "2021/0211A(COD)", "2022-0369": "2022/0369(APP)", "2020-0055": "2020/0055(APP)",
    "2019-0210": "2019/0210(NLE)", "2023-0226": "2023/0226(COD)", "2023-0232": "2023/0232(COD)",
    "2025-0526": "2025/0526(COD)", "2026-0037": "2026/0037(BUD)",
}  # fmt: skip


def mlinks(day: str, links: dict | None = None, **kw) -> dict[str, EpVote]:
    res = ev.assemble([load_sitting(day, base=MLINKS)], MLINK_LABELS, links or {}, RETRIEVED, **kw)
    return {v.id: v for v in res.votes}


def test_urgent_procedure_votes_link_through_the_minutes_block():
    # 18 Dec 2020, Brexit contingency: labels "C9-0399/2020 - Commission proposal"; only the fisheries item
    # (C9-0396/2020) is among the sitting's vote items. The minutes block with each vote's counts names its
    # procedure: "Proposal for a regulation (COM(2020)0826 - C9-0399/2020 - 2020/0362(COD))" (PV-9-2020-12-18-VOT
    # items 43-46). 126354 and 126355 have the same counts (680-3-4): the label's document tells them apart.
    votes = mlinks("2020-12-18")
    got = {vid: (votes[vid].procedure_refs, votes[vid].kind) for vid in ("126353", "126354", "126355", "126356")}
    assert got == {
        "126353": (["2020/0362(COD)"], "final"),
        "126354": (["2020/0363(COD)"], "final"),
        "126355": (["2020/0364(COD)"], "final"),
        "126356": (["2020/0366(COD)"], "final"),  # through its vote item, as before
    }
    rows = ev.parse_minutes((MLINKS / "minutes_2020-12-18.xml").read_bytes())
    assert {r.item: r.procs for r in rows if r.counts == (680, 4, 3)} == {"43.": frozenset({"2020/0362(COD)"})}
    # without the minutes nothing official links them
    alone = ev.assemble([load_sitting("2020-12-18", minutes=False, base=MLINKS)], MLINK_LABELS, {}, RETRIEVED)
    assert {v.id for v in alone.votes if v.procedure_refs} == {"126356"}


def test_agreement_vote_without_a_document_links_through_its_report():
    # 4 Oct 2022, 148304 "Serious cross-border threats to health - Provisional Agreement - Am 278" (544-50-10):
    # minutes block 2 "Serious cross-border threats to health ***I | Report: Véronique Trillet-Lenoir
    # (A9-0247/2021)"; the report is the document of the vote items of 2020/0322(COD) (state index)
    known = {"A-9-2021-0247": {"procs": ["2020-0322"], "symbols": ["***I"]}}
    v = mlinks("2022-10-04", known_docs=known)["148304"]
    assert (v.procedure_refs, v.kind, v.outcome, v.majority_rule) == (["2020/0322(COD)"], "final", "adopted", "votes_cast")
    assert mlinks("2022-10-04")["148304"].procedure_refs == []  # a report no vote item names: no link
    # 15 Mar 2023, 153312 "Law enforcement information exchange - A9-0247/2022 - Lena Düpont - …" (2021/0411(COD)):
    # the minutes block prints the report as A9-0247/2023, an own-initiative report; the block's documents are not
    # used when they do not include the label's
    sitting = load_sitting("2023-03-15", base=MLINKS)
    d = ev.draft(sitting.decisions[0], sitting)
    assert d.label_docs == ["A-9-2022-0247"]
    assert ev.minutes_procs(d, {"A-9-2023-0247": {"2022-2205"}}, {}) == []


def test_misprinted_document_year_links_through_the_fitting_block():
    # 7 Apr 2022: "Gas storage - C9-0126/2021 - Commission proposal" (516-25-15); the minutes print
    # "C9-0126/2022 - 2022/0090(COD)". The file was referred back for negotiations the same day (procedure event
    # 2022-0090-DEC-REFBAK-2022-04-07): a negotiating mandate
    votes = mlinks("2022-04-07", referrals={"2022-0090": ["2022-04-07"]})
    gas, react = votes["141902"], votes["141901"]
    assert (gas.procedure_refs, gas.kind) == (["2022/0090(COD)"], "mandate")
    assert (react.procedure_refs, react.kind) == (["2022/0096(COD)"], "final")  # "C9-0132/2021" for C9-0132/2022


def test_same_sitting_referral_under_rule_59_4_makes_a_mandate():
    # 28 Apr 2021, EU Digital COVID Certificate (French labels only): "… C9-0104/2021 - Proposition de la
    # Commission" 540-119-31, then "… C9-0104/2021 - Renvoi (article 59, paragraphe 4 du règlement)" 569-95-26,
    # adopted; OEIL 2021/0068(COD): "29/04/2021 Matter referred back to the committee responsible for
    # interinstitutional negotiations", T9-0145/2021 "Amendments adopted …"
    votes = mlinks("2021-04-28")
    assert (votes["130712"].kind, votes["130712"].procedure_refs) == ("mandate", ["2021/0068(COD)"])
    assert (votes["130714"].kind, votes["130714"].procedure_refs) == ("mandate", ["2021/0071(COD)"])
    assert (votes["130713"].kind, votes["130713"].outcome) == ("procedural", "adopted")
    # "… C9-0104/2021 - Am 11", minutes Subject "Rejection" (86-591-16): the proposal to reject
    rejection = votes["130538"]
    assert (rejection.kind, rejection.kind_detail, rejection.has_ballots) == ("motion", "reject_proposal", True)
    # 15 Sep 2021: ECDC 135573 (598-84-13) and cross-border threats 135575 (594-85-16), each "Commission
    # proposal" followed by "Referral (Rule 59(4))" on the same report (135574, 135576); OEIL lists T9-0376/2021
    # and T9-0377/2021 as "partial vote at 1st reading"
    links = {"A-9-2021-0253": (["2020-0320"], []), "A-9-2021-0247": (["2020-0322"], []),
             "A-9-2021-0266": (["2018-0247"], [])}  # fmt: skip
    votes = mlinks("2021-09-15", links)
    assert {vid: votes[vid].kind for vid in ("135573", "135574", "135575", "135576")} == {
        "135573": "mandate", "135574": "procedural", "135575": "mandate", "135576": "procedural",
    }  # fmt: skip
    # IPA III, "… - Rejection - Am 1" (94-577-19), item "… *** II": the proposal to reject the Council's position
    ipa = votes["135500"]
    assert (ipa.kind, ipa.kind_detail, ipa.majority_rule) == ("motion", "reject_council_position", "component_members")


def test_rejected_text_then_referred_back_stays_the_final_vote():
    # 8 Jun 2022, ETS revision: "A9-0162/2022 – Peter Liese – Commission proposal" rejected 265-340-34, then
    # "Referral back (Rule 59(4))" adopted 495-120-16: referred back for reconsideration (Rule 59(4), fourth
    # subparagraph), not a negotiating mandate
    votes = mlinks("2022-06-08")
    assert (votes["144283"].kind, votes["144283"].outcome) == ("final", "rejected")
    assert (votes["144284"].kind, votes["144284"].outcome) == ("procedural", "adopted")


def test_proposal_to_reject_tabled_as_an_amendment_is_a_motion():
    # 7 Jul 2021, VIS: label "… – A9-0207/2021 – Paolo Rangel – Am 1"; minutes block 25 "Visa Information System
    # (VIS): visa processing ***II", row "Rejection | 1 | The Left | RCV | - | 114 578 4"
    v = mlinks("2021-07-07", {"A-9-2021-0207": (["2018-0152A"], [])})["134613"]
    assert (v.kind, v.kind_detail, v.majority_rule, v.outcome) == (
        "motion", "reject_council_position", "component_members", "rejected"
    )  # fmt: skip
    assert v.has_ballots and v.procedure_refs == ["2018/0152A(COD)"]
    # new format: referenceText "Proposal to reject the Council position", decided on -AM-17 and -AM-25 (NGT,
    # 17 Jun 2026, 201-431-29); "Proposal for rejection" on -AM-1/2/3 at the Soil Monitoring second reading
    ngt = mlinks("2026-06-17")["194424"]
    assert (ngt.kind, ngt.kind_detail, ngt.majority_rule, ngt.has_ballots) == (
        "motion", "reject_council_position", "component_members", True
    )  # fmt: skip
    soil = mlinks("2025-10-23")
    assert (soil["180520"].kind, soil["180520"].kind_detail) == ("motion", "reject_council_position")
    assert (soil["180521"].kind, soil["180521"].kind_detail) == ("motion", "reject_proposal")  # as before
    # a split vote on a rejection, or an amendment beside it, stays what it is
    split = ev.Signals(ref="§ 3", label="A9-0001/2024 – X – Rejection – § 3", subject="Rejection")
    assert ev.classify(split) == "split_or_separate"
    assert ev.classify(ev.Signals(ref="Am 12", label="A9-0001/2024 – X – Am 12")) == "amendment"


def test_whole_text_vote_labelled_only_by_its_title():
    # 29 Jan 2020, Withdrawal Agreement 112101 (621-49-13): the label is the agreement's title only; the minutes
    # row reads "Consent procedure | RCV | + | 621 49 13"
    v = mlinks("2020-01-29")["112101"]
    assert (v.kind, v.outcome, v.has_ballots) == ("final", "adopted", True)
    assert v.procedure_refs == []  # the block's title differs from the label: no link


def test_french_label_gives_the_item_or_the_document():
    # 16 Apr 2020, 113149 "Regulation amending the Multiannual financial framework 2014-2020 - Consent" (464-11-4):
    # no document in the label and no counts in the French minutes; the French label "Règlement modifiant le cadre
    # financier pluriannuel 2014-2020 - Approbation" is the vote item titled "Règlement modifiant le cadre
    # financier pluriannuel 2014-2020" (eli/dl/proc/2020-0055)
    assert mlinks("2020-04-16")["113149"].procedure_refs == ["2020/0055(APP)"]
    # 13 May 2020, 113700: English label "A9-0088/202 - Clara Aguilera - Consent procedure", French "A9-0088/2020"
    v = mlinks("2020-05-13")["113700"]
    assert (v.procedure_refs, v.kind, v.outcome) == (["2019/0210(NLE)"], "final", "adopted")
    # two vote items with the label's title: no link
    sitting = load_sitting("2020-04-16", base=MLINKS)
    item = next(iter(sitting.items.values()))
    sitting.items["MTG-PL-2020-04-16-VOT-ITM-X"] = ev.VoteItem(id="X", title=item.title, procs=["2020-9999"])
    assert ev.titled_item_procs(ev.draft(sitting.decisions[0], sitting)) == []


def test_majority_stated_in_the_record():
    # 24 Nov 2022, MFF amendment 150407 (490-39-23): minutes "Draft regulation (… 2022/0369(APP)) (Majority of
    # Parliament’s component Members required)" (Art. 312(2) TFEU)
    assert mlinks("2022-11-24")["150407"].majority_rule == "component_members"
    # 26 Mar 2026, EGF/2025/005 AT/KTM 189252: item label "Report: Janusz Lewandowski (A10-0060/2026) (Majority of
    # votes cast required)"
    assert mlinks("2026-03-26")["189252"].majority_rule == "votes_cast"
    stated = [
        ("(Majority of votes cast required)", "final", "votes_cast"),
        ("(Majority of Parliament’s component Members and two thirds of votes cast required)", "final", "two_thirds_cast"),
        ("(Majority of Parliament’s component Members + 3/5 of votes cast)", "final", None),  # another double rule
        ("(Majority of Parliament’s component Members required to amend or reject the Council position)", "final", None),
        ("(Majority of Parliament’s component Members to adopt motion for a resolution)", "resolution", "component_members"),
        ("(Majority of Parliament’s component Members to adopt motion for a resolution)", "final", None),
        ("(majority of Parliament’s component Members) (Majority of votes cast required)", "final", None),  # conflict
    ]  # fmt: skip
    for text, kind, rule in stated:
        assert ev.stated_rule([f"Report: X (A9-0001/2022) {text}"], kind) == rule, text


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
            assert v.method == ev.ROLLCALL and ev.keeps_ballots(v.kind, v.kind_detail)
        if v.kind in ("final", "mandate"):
            assert v.outcome != "lapsed"  # a whole-text vote that fell was never held: kind "other"


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
        warnings.warn(
            f"{len(mismatches)} votes whose voter lists differ from the counts: {mismatches}", stacklevel=2
        )
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
    res = ev.assemble(
        [ev.Sitting.build(sitting, decisions, items)], ev.fetch_procedure_labels(http), {}, RETRIEVED
    )
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


# ------------------------------------------------------------------------- incremental / resumable fetch
class FixtureHttp:
    """Serves the recorded responses in tests/fixtures/ep_votes/ and logs every requested path."""

    def __init__(self):
        self.requests: list[str] = []
        self.meetings = json.loads((FIX / "meetings.json").read_text(encoding="utf-8"))["years"]
        self.sittings = {
            json.loads(p.read_text(encoding="utf-8"))["sitting"]: json.loads(p.read_text(encoding="utf-8"))
            for p in FIX.glob("sitting_*.json")
        }
        procs = json.loads((FIX / "procedures.json").read_text(encoding="utf-8"))["data"]
        detail = json.loads((FIX / "procedure_2021-0106.json").read_text(encoding="utf-8"))["data"]
        self.procs = {r["process_id"]: r for r in procs} | {r["process_id"]: r for r in detail}
        self.docs = json.loads((FIX / "documents.json").read_text(encoding="utf-8"))["responses"]

    def get(self, url: str, params: dict | None = None, **_kw) -> bytes:
        path = url.removeprefix(ev.EP_API).removeprefix("https://data.europarl.europa.eu")
        self.requests.append(path)
        params = params or {}
        if path == "/meetings":
            return json.dumps(self.meetings.get(str(params["year"]), {"data": []})).encode()
        if m := re.fullmatch(r"/meetings/(MTG-PL-[\d-]{10})/(decisions|vote-results)", path):
            raw = self.sittings.get(m.group(1))
            if raw is None:
                return b""
            return json.dumps(raw["decisions" if m.group(2) == "decisions" else "vote_results"]).encode()
        if m := re.fullmatch(r"/distribution/doc/PV-\d+-([\d-]{10})-VOT-FNL_en\.xml", path):
            xml = FIX / f"minutes_{m.group(1)}.xml"
            return xml.read_bytes() if xml.exists() else b""
        if path == "/procedures":
            rows = [r for r in self.procs.values() if r["process_type"].endswith(params["process-type"])]
            return json.dumps({"data": rows if params.get("offset", 0) == 0 else []}).encode()
        if m := re.fullmatch(r"/procedures/([\w,-]+)", path):
            return json.dumps(
                {"data": [self.procs[i] for i in m.group(1).split(",") if i in self.procs]}
            ).encode()
        if m := re.fullmatch(r"/plenary-documents/([\w-]+)", path):
            return json.dumps(self.docs.get(m.group(1), {"data": []})).encode()
        return b""  # e.g. /documents/PV-…-VOT for sittings without recorded minutes


@pytest.fixture
def fetch_env(tmp_path, monkeypatch):
    from pipeline import snapshot

    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.setattr(ev, "_today", lambda: "2026-10-22")
    monkeypatch.setattr(ev, "CHUNK", 4)
    monkeypatch.delenv("EU_INTEL_FULL_REFRESH", raising=False)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    return tmp_path


def _stored() -> dict[str, EpVote]:
    return {v.id: v for v in read_records(ev.SOURCE_ID, "votes", EpVote)}


def test_interrupted_fetch_keeps_completed_chunks_and_resumes(fetch_env, monkeypatch):
    from pipeline import snapshot

    http = FixtureHttp()
    checks = iter([False, True])  # the budget runs out after the first chunk
    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: next(checks, True))
    first = ev.fetch(http)
    assert first.status == "partial" and "12 sittings pending; resumes next run" in first.note
    state = snapshot.read_state(ev.SOURCE_ID)
    assert state["pass"] == "full" and len(state["pending"]) == 12
    done = {v.event_id[:17] for v in _stored().values()}
    assert done == {"MTG-PL-2019-10-24", "MTG-PL-2020-07-08", "MTG-PL-2022-07-05"}  # 2020-07-09: no decisions
    assert state["doc_links"]["RC-9-2019-0118"] == ["2019-2854"]

    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    second = ev.fetch(FixtureHttp())
    assert second.status == "ok"
    state = snapshot.read_state(ev.SOURCE_ID)
    assert state["pending"] == [] and state["last_full"]
    votes = _stored()
    one_pass, _ = assemble(*(p.stem.removeprefix("sitting_") for p in sorted(FIX.glob("sitting_*.json"))))
    assert set(votes) == set(one_pass)
    assert votes["166051"].procedure_refs == ["2021/0106(COD)"] and votes["156022"].kind == "mandate"
    ballots = {b.vote_id for b in read_records(ev.SOURCE_ID, "ballots", EpBallots)}
    assert ballots == {v.id for v in votes.values() if v.has_ballots}


def test_incremental_fetch_touches_only_the_window(fetch_env, monkeypatch):
    from pipeline import snapshot

    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    ev.fetch(FixtureHttp())  # first run: empty snapshot -> full pass
    before = _stored()
    http = FixtureHttp()
    status = ev.fetch(http)
    assert status.status == "ok" and status.note.startswith("window from 2026-05-10")
    sittings = {p.split("/")[2] for p in http.requests if p.startswith("/meetings/MTG-PL-")}
    assert sittings == {"MTG-PL-2026-07-08", "MTG-PL-2026-07-09"}  # latest sitting 2026-07-09 - 60 days
    assert [p for p in http.requests if p == "/meetings"] == ["/meetings"]  # only the 2026 listing
    assert not [p for p in http.requests if p.startswith(("/plenary-documents", "/distribution"))]
    assert _stored() == before  # unchanged answers -> identical records, older votes kept
    assert snapshot.read_state(ev.SOURCE_ID)["pending"] == []


def test_full_refresh_flag_refetches_everything(fetch_env, monkeypatch):
    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    ev.fetch(FixtureHttp())
    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")
    http = FixtureHttp()
    status = ev.fetch(http)
    assert status.note.startswith("full pass: 16/16 sittings")
    assert {p.split("/")[2] for p in http.requests if p.startswith("/meetings/MTG-PL-")} == set(http.sittings)


def test_pending_sittings_resume_when_the_listing_fails(fetch_env, monkeypatch):
    from pipeline import snapshot
    from pipeline.http import HttpError

    checks = iter([False, True])
    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: next(checks, True))
    ev.fetch(FixtureHttp())  # interrupted after the first chunk: 12 sittings pending

    class NoListing(FixtureHttp):
        def get(self, url, params=None, **kw):
            if url.endswith("/meetings"):
                raise HttpError(url, 500, "listing unavailable")
            return super().get(url, params, **kw)

    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    status = ev.fetch(NoListing())
    assert status.status == "ok" and snapshot.read_state(ev.SOURCE_ID)["pending"] == []
    assert "195361" in _stored()  # 2026-07-08, fetched from the pending list alone


def test_a_failing_sitting_stays_pending_without_blocking_its_chunk(fetch_env, monkeypatch):
    from pipeline import snapshot
    from pipeline.http import HttpError

    class TodayNotPublished(FixtureHttp):
        def get(self, url, params=None, **kw):
            if "/meetings/MTG-PL-2026-07-09/" in url:
                raise HttpError(url, 500, "not available")
            return super().get(url, params, **kw)

    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    monkeypatch.setattr(ev, "RETRY_WAIT_S", 0)
    status = ev.fetch(TodayNotPublished())
    assert status.status == "partial" and "1 sittings pending" in status.note
    assert snapshot.read_state(ev.SOURCE_ID)["pending"] == ["MTG-PL-2026-07-09"]
    stored = _stored()
    assert "195361" in stored and "195775" not in stored  # 2026-07-08 kept, 2026-07-09 to be resumed
    assert ev.fetch(FixtureHttp()).status == "ok" and "195775" in _stored()


def test_full_pass_procedure_list_halves_the_page_and_falls_back(fetch_env, monkeypatch):
    """The /procedures list answered HTTP 500 to limit=1000 (the full pass asked for it) and, for COD, to 500
    and 250; the HttpError used to fail the whole source."""
    from pipeline import snapshot
    from pipeline.http import HttpError

    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    one_pass = {v.id: v.procedure_refs for v in assemble(*(p.stem.removeprefix("sitting_")
                for p in sorted(FIX.glob("sitting_*.json"))))[0].values()}  # fmt: skip

    class SmallPagesOnly(FixtureHttp):
        def __init__(self):
            super().__init__()
            self.list_calls: list[tuple[str, int, int | None]] = []

        def get(self, url, params=None, **kw):
            if url.endswith("/procedures"):
                self.list_calls.append((params["process-type"], params["limit"], kw.get("retries")))
                if params["process-type"] == "COD" and params["limit"] > 125:
                    raise HttpError(url, 500, "WebClientRequestException")
            return super().get(url, params, **kw)

    http = SmallPagesOnly()
    assert ev.fetch(http).status == "ok"  # empty snapshot: a full pass, with the list
    assert [c for c in http.list_calls if c[0] == "COD"] == [("COD", 500, 0), ("COD", 250, 0), ("COD", 125, None)]
    assert snapshot.read_state(ev.SOURCE_ID)["list_page"]["COD"] == 125
    assert {v.id: v.procedure_refs for v in _stored().values()} == one_pass

    class ListDown(FixtureHttp):
        def get(self, url, params=None, **kw):
            if url.endswith("/procedures"):
                self.requests.append("/procedures")
                raise HttpError(url, 500, "WebClientRequestException")
            return super().get(url, params, **kw)

    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")
    down = ListDown()
    status = ev.fetch(down)
    # the listing stops at the first type it cannot read; the known references and per-id requests do the rest
    assert status.status == "ok"
    assert f"procedure list unavailable for {len(ev.PROCESS_TYPES)} process types (ACI," in status.note
    assert down.requests.count("/procedures") == 3  # 500 and 250 once each, then 125 (with Http's retries)
    assert {v.id: v.procedure_refs for v in _stored().values()} == one_pass
