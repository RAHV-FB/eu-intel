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
    DISCHARGE_NOTES,
    FINAL_ROLE_LABELS,
    VOTE_DETAIL_LABELS,
    VOTE_OUTCOME_NOTES,
    Builder,
    _vote_index_entry,
    build_search_docs,
    commission_cod_proposal,
    english_procedural,
    final_role,
    referred_back,
    rejection_title,
    search_subject,
    subject_procedure,
    unnamed_parties,
    vote_label_document,
    vote_subject,
)
from pipeline.models.entities import CouncilVote, EpVote, LegalAct, Mep, Organization, Procedure

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


def orgs(*ids: str) -> dict[str, Organization]:
    return {k: Organization.model_validate(v) for k, v in records("ep_people/orgs.json", set(ids)).items()}


def meps(*ids: str) -> dict[str, Mep]:
    return {k: Mep.model_validate(v) for k, v in records("ep_people/meps.json", set(ids)).items()}


# ------------------------------------------------------------------------------------ search documents
def test_search_subtitles_name_the_country_and_tell_same_term_party_records_apart():
    # Anthea McIntyre (111011) was elected in the United Kingdom (code GB, a former member state); Azione has three
    # EP records, two of them within the 2019-2024 term (EP API temporal: 6103 2019-11-20 to 2022-11-08, 6478
    # 2023-12-06 to 2024-07-15); corporate bodies 5500 and 5719 are labelled "-" in every language
    o = orgs("5233", "5500", "5719", "6103", "6478", "6913")
    m = meps("111011", "192634", "197438", "197581", "197617", "197618")
    unnamed = unnamed_parties(list(o.values()))
    assert unnamed == {"5500", "5719"}
    party = {oid: {"label": x.label, "code": x.code, "country": x.country or "", "members_active": 0} for oid, x in o.items()}
    mep = {"111011": {"id": "111011", "name": m["111011"].name, "active": False, "country": "GB", "group_code": "ECR"}}
    b = SimpleNamespace(
        dossier_summary={}, proc={}, curated_of={}, acts_of={}, train_of={}, alias_rules=[], mep_summary=mep,
        group_summaries=[], party_summary=party, s=SimpleNamespace(meps=list(m.values())), topic_list=[],
        topics_cur={}, resolve_ref=lambda ref: None, org=o, unnamed_parties=unnamed,
    )  # fmt: skip
    docs = {(d["k"], d["id"]): d["s"] for d in build_search_docs(b)}
    assert docs[("mep", "111011")] == "Former MEP · United Kingdom · ECR"
    assert docs[("party", "5233")] == "National party · United Kingdom"
    assert docs[("party", "6103")] == "National party · Italy · 2019–2024 term · 20 November 2019 – 8 November 2022"
    assert docs[("party", "6478")] == "National party · Italy · 2019–2024 term · 6 December 2023 – 15 July 2024"
    assert docs[("party", "6913")] == "National party · Italy · 2024–2029 term"
    assert ("party", "5500") not in docs and ("party", "5719") not in docs


def test_vote_subject_is_kept_for_search_when_the_titles_lack_its_words():
    # vote 195775 is titled after the act it amends; its published subject names the ePrivacy Directive
    v = votes("195775")["195775"]
    display = ("Amending Regulation (EU) 2021/1232 as regards the extension of its period of application — motion to "
               "reject the Council's position (second reading)")  # fmt: skip
    assert search_subject(v.subject, display, v.title) == "Temporary derogation from the ePrivacy directive"
    assert search_subject(v.subject, "Temporary derogation from the ePrivacy Directive — motion", v.title) is None
    assert search_subject(None, display) is None


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


def test_decision_recorded_a_day_from_its_vote_links_that_vote():
    # remote voting: 2020/0331(CNS), EP API DEC-134869 dated 6 Jul 2021 (561-43-88), procedure decision
    # 2020-0331-DEC-DCPL-2021-07-07 (OEIL "07/07/2021 Decision by Parliament T9-0329/2021"); 2020/0065(COD),
    # decision of 13 May 2020, final vote 114183 dated 15 May 2020; 2018/0228(COD) (Connecting Europe Facility),
    # second-reading approval of 7 Jul 2021, motion to reject the Council's position 134544 dated 6 Jul 2021
    for pid, vid, day in (("2020-0331", "134869", "2021-07-07"), ("2020-0065", "114183", "2020-05-13"),
                          ("2018-0228", "134544", "2021-07-07")):  # fmt: skip
        p, v = procs(pid)[pid], votes(vid)
        me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-22")
        tl = Builder.timeline(me, p, [], list(v.values()))  # type: ignore[arg-type]
        e = next(e for e in tl if e["date"] == day and e["kind"] == "ep_position")
        assert e["vote_id"] == vid, pid
        assert "its procedure record dates the decision" in e["detail"], pid
    # a negotiating mandate is never taken for the decision
    p, v = procs("2020-0331")["2020-0331"], votes("134869")
    mandate = [v["134869"].model_copy(update={"kind": "mandate"})]
    me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-22")
    tl = Builder.timeline(me, p, [], mandate)  # type: ignore[arg-type]
    assert next(e for e in tl if e["date"] == "2021-07-07" and e["kind"] == "ep_position")["vote_id"] is None


def test_mandate_vote_a_day_before_the_referral_links_it():
    # 2021/0068(COD): vote 130712 on 28 Apr 2021 (amended proposal, 540-119-31), procedure event "Parliament sent the
    # file back to committee to negotiate with the Council" on 29 Apr 2021; the decision of 8 Jun 2021 is 132421.
    # The rejection motion 130538 of 28 Apr leaves that day's "Vote in Parliament" without a single vote to link.
    p, v = procs("2021-0068")["2021-0068"], votes("130712", "130538", "132421")
    me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-22")
    tl = Builder.timeline(me, p, [], list(v.values()))  # type: ignore[arg-type]
    assert next(e for e in tl if e["date"] == "2021-04-29" and e["kind"] == "negotiation_mandate")["vote_id"] == "130712"
    assert next(e for e in tl if e["date"] == "2021-06-08" and e["kind"] == "ep_position")["vote_id"] == "132421"


def test_second_reading_amendments_are_named_in_the_decision():
    # 2025/0429(COD), 9 Jul 2026, PLENARY_AMEND_COUNCIL_POSITION: EP API DEC-195778 "C10-0178/2026 – Article 1, after
    # § 2 – Am 30" ADOPTED 369-236-6 and DEC-195787 "… – Article 3, § 1, point a – Am 26 CP3= 31 CP3= 6= 21=" ADOPTED
    # 362-235-5 (at least 360 of 719 Members needed); both motions to reject the Council's position rejected
    p = procs("2025-0429")["2025-0429"]
    v = votes("195775", "195807", "195778", "195787")
    me = SimpleNamespace(indexed_vote_ids={"195775", "195807"}, council_of={}, today="2026-10-22")
    tl = Builder.timeline(me, p, [], list(v.values()))  # type: ignore[arg-type]
    e = next(e for e in tl if e["date"] == "2026-07-09" and e["kind"] == "ep_position")
    assert e["vote_id"] == "195775"
    assert e["detail"] == (
        "Parliament voted on 2 motions to reject the Council's position and rejected each of them; the vote link "
        "opens the first. Parliament adopted 2 amendments to the Council's position with the votes of a majority of "
        "its component Members: “Article 1, after § 2 – Am 30” (369 for) and “Article 3, § 1, point a – Am 26 CP3= "
        "31 CP3= 6= 21=” (362 for). Votes on amendments are not listed on this site."
    )


def test_final_votes_say_what_they_decide():
    v = votes("115405", "170611", "175931", "125901", "195415", "110686", "144283", "186119", "168353", "141902")
    assert {k: final_role(x) for k, x in v.items()} == {
        "115405": "parliament_decision",  # 2020/2681(RSO), setting up an ECON subcommittee
        "170611": "commission_election",  # "Election of the Commission", 27 Nov 2024 (Art. 17(7) TEU)
        "175931": "discharge",  # 2024/2021(DEC), "Proposal for a decision"
        "125901": "consent",  # 2018/0166(APP), MFF 2021-2027
        "195415": "consent",  # 2025/0271(NLE), "EU–Mexico Interim Agreement on Trade ***"
        "110686": "consultation",  # 2018/0412(CNS), "Requirements for payment service providers *"
        "144283": "legislative",  # 2021/0211A(COD)
        "186119": None,  # an appointment linked to no procedure, no symbol
        "168353": "budget",  # 2024/0003(BUD), an EGF mobilisation the records title "… ***I"
        "141902": None,  # a negotiating mandate
    }
    assert FINAL_ROLE_LABELS["consent"] == "Vote on consent"
    title, _ = Builder.vote_display_title(None, v["125901"], None)  # type: ignore[arg-type]
    assert title == "Council regulation laying down the multiannual financial framework for the years 2021 to 2027 — vote on consent"
    title, _ = Builder.vote_display_title(None, v["110686"], None)  # type: ignore[arg-type]
    assert title == "Requirements for payment service providers — vote on Parliament's opinion"
    assert DISCHARGE_NOTES["adopted"].startswith("Parliament adopted the proposal for a decision on discharge.")


def test_rejected_text_referred_back_for_reconsideration_says_so():
    # 8 Jun 2022, ETS revision: 144283 "A9-0162/2022 – Peter Liese – Commission proposal" rejected 265-340-34, then
    # 144284 "… – Referral back (Rule 59(4))" adopted 495-120-16; 15 Sep 2021, ECDC: 135573 adopted, then referred
    # back for negotiations (135574): a mandate
    v = votes("144283", "144284", "135573", "135574")
    assert referred_back(list(v.values())) == {"144283"}
    me = SimpleNamespace(referred_back={"144283"})
    assert Builder.referral_note(me, v["144283"]) == (  # type: ignore[arg-type]
        "After this vote Parliament referred the file back to the committee responsible for reconsideration "
        "(Rule 59(4) of its Rules of Procedure)."
    )


def test_vote_index_writes_document_numbers_with_a_hyphen():
    # 175067's label prints its report as "A10–0049/2025" (en dash); the official number is A10-0049/2025
    v = votes("175067")["175067"]
    assert v.title.startswith("A10–0049/2025 – Gilles Boyer")
    assert _vote_index_entry({"title": v.title, "source": {}})["title"].startswith("A10-0049/2025 – Gilles Boyer")


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


def test_home_rejected_list_says_what_each_rejection_meant_and_what_followed():
    # 189270 (2025/0429(COD), rejected at first reading 26 Mar 2026; Regulation (EU) 2026/1881, adopted 23 Jul 2026
    # after a second reading); 193822 (2025/0580(CNS), 17 Jun 2026: a negative opinion, OEIL "Awaiting Council
    # decision"); 161821 (2022/0196(COD), rejected 22 Nov 2023, withdrawn by the Commission on 6 May 2024). The
    # timelines are built from the procedures; stage, dates and status labels are those of the build.
    p = procs("2025-0429", "2025-0580", "2022-0196")
    v = votes("189270", "193822", "161821")
    me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-22")
    detail = {
        pid: {"timeline": Builder.timeline(me, p[pid], [], [v[vid]]), "status": {"since": since}}  # type: ignore[arg-type]
        for pid, vid, since in (("2025-0429", "189270", "2026-07-31"), ("2025-0580", "193822", "2026-06-17"),
                                ("2022-0196", "161821", "2024-05-06"))
    }  # fmt: skip
    summary = {
        "2025-0429": {"id": "2025-0429", "type": "COD", "stage": "in_force", "adopted": "2026-07-23", "status_label": "In force"},
        "2025-0580": {"id": "2025-0580", "type": "CNS", "stage": "parliament_position", "adopted": None,
                      "status_label": "Parliament delivered a negative opinion"},
        "2022-0196": {"id": "2022-0196", "type": "COD", "stage": "withdrawn", "adopted": None,
                      "status_label": "Withdrawn by the Commission"},
    }  # fmt: skip
    me = SimpleNamespace(dossier_summary=summary, dossier_detail=detail)
    later = "Parliament rejected the text in this vote, but the procedure continued: it later produced Regulation (EU) 2026/1881."

    def note(vid: str, pid: str | None, outcome_note: str | None = None) -> str:
        x = v[vid]
        s = {"id": x.id, "date": x.date, "outcome": x.outcome, "dossier_id": pid, "outcome_note": outcome_note,
             "kind_label": "Final vote on the text"}  # fmt: skip
        return Builder.home_rejection_note(me, s)  # type: ignore[arg-type]

    assert note("189270", "2025-0429", later) == (
        "Parliament rejected the proposal at first reading. The procedure continued and the act was adopted on "
        "23 July 2026."
    )
    assert note("193822", "2025-0580") == (
        "Parliament delivered its opinion: it rejected the proposal. Under the consultation procedure Parliament's "
        "opinion is not binding: the Council can still adopt the act."
    )
    assert note("161821", "2022-0196") == (
        "Parliament rejected the proposal at first reading. Status now: Withdrawn by the Commission."
    )
    # without a tracked file: what the vote's outcome says, and nothing more
    assert note("161821", None) == "Parliament rejected the text in this vote."


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


# ----------------------------------------------------------------------------- Parliament votes: titles, rules
def test_recommendation_to_raise_no_objections_reads_as_such():
    # 150746, 24 Nov 2022: "Decision to raise no objections pursuant to Rule 111(6): …" (minutes "+ 445/102/24")
    v = votes("150746")["150746"]
    assert (v.kind, v.kind_detail, v.majority_rule) == ("motion", "no_objection", "votes_cast")
    title, from_label = Builder.vote_display_title(None, v, None)  # type: ignore[arg-type]
    assert title.startswith("Decision to raise no objections pursuant to Rule 111(6): value of the clearing")
    assert not from_label and "objection —" not in title
    assert VOTE_OUTCOME_NOTES[("no_objection", "adopted")].startswith("Parliament adopted the recommendation")
    assert VOTE_DETAIL_LABELS["no_objection"] == "Vote on a recommendation to raise no objections to a Commission measure"


def test_same_day_votes_with_one_title_are_told_apart():
    # 30 Jan 2020, "Gender pay gap": B9-0073/2020 adopted 493-82-79, B9-0069/2020 rejected 78-528-50 (EP API
    # MTG-PL-2020-01-30); 9 Jul 2026, two motions to reject the Council's position on C10-0178/2026, one tabled
    # as amendments 1, 2 and 7
    v = votes("112160", "112117", "195775", "195807")
    me = SimpleNamespace(vote_summary={
        "112160": {"display_title": "Gender pay gap — vote on the resolution"},
        "112117": {"display_title": "Gender pay gap — vote on the resolution"},
        "195775": {"display_title": "Amending … — motion to reject the Council's position (second reading)"},
        "195807": {"display_title": "Amending … — motion to reject the Council's position (second reading)"},
    })  # fmt: skip
    Builder.distinguish_vote_titles(me, list(v.values()))  # type: ignore[arg-type]
    got = {k: s["display_title"] for k, s in me.vote_summary.items()}
    assert got["112160"] == "Gender pay gap — vote on the resolution (motion B9-0073/2020)"
    assert got["112117"] == "Gender pay gap — vote on the resolution (motion B9-0069/2020)"
    assert got["195775"].endswith("(second reading) (amendments 1, 2 and 7)")
    assert got["195807"].endswith("(second reading)")
    joint = v["112160"].model_copy(update={"title": "RC-B9-0505/2022 - Motion for a resolution (text as a whole)"})
    assert vote_label_document(joint) == "joint motion RC-B9-0505/2022"


def test_french_procedural_terms_and_procedure_symbols():
    # 199517, 22 Oct 2026: label "RC-B10-0476/2026 - Proposition de résolution (ensemble du texte)"
    v = votes("199517")["199517"]
    title, from_label = Builder.vote_display_title(None, v, None)  # type: ignore[arg-type]
    assert (title, from_label) == ("RC-B10-0476/2026 - Motion for a resolution (text as a whole)", True)
    assert english_procedural("Proposition de la Commission") == "Commission proposal"
    assert english_procedural("Après le § 1") == "Après le § 1"  # not a fixed term: left as published
    # 195775: subject "Temporary derogation from the ePrivacy directive ***II"
    s = votes("195775")["195775"].subject
    assert vote_subject(s) == "Temporary derogation from the ePrivacy directive"
    assert subject_procedure(s) == "ordinary legislative procedure, second reading"
    assert subject_procedure("Administrative cooperation in the field of excise duties *") == "consultation procedure"


def test_no_component_member_count_before_parliament_took_note_of_three_mandates():
    # 109166, 23 Oct 2019: the records count 751 Members, Parliament 747 (press release of 16 Jul 2019); it took
    # note of the three Spanish mandates dated from 2 Jul 2019 only on 13 Jan 2020 (minutes PV-9-2020-01-13)
    me = SimpleNamespace(component_cache={}, members_in_office=lambda d: 751 if d < "2020-02-01" else 704)
    assert Builder.component_members(me, "2019-10-23") is None  # type: ignore[arg-type]
    assert Builder.component_members(me, "2020-01-13") == 751  # type: ignore[arg-type]
    assert Builder.component_members(me, "2020-02-10") == 704  # type: ignore[arg-type]


def test_rapporteurs_show_the_group_held_in_the_role_not_the_current_one():
    # 2021/0106(COD), AI Act. OEIL's key players: "KONEČNÁ Kateřina (The Left)", "MADISON Jaak (ID)",
    # ENVI "SOLÍS PÉREZ Susana (Renew)". Konečná is in PfE since 2026-10-21 and Madison left ID in 2024: their
    # current groups must not be shown. 2016/0107(COD): Pascal Durand was a shadow rapporteur in the 8th term,
    # listed by OEIL as "DURAND Pascal (Verts/ALE)" (that file's roles come from OEIL, with no date).
    from collections import defaultdict

    from pipeline.build import group_slug
    from pipeline.models.entities import Mep, Organization

    ids = {"23699", "197493", "197784", "124693"}
    meps = {k: Mep.model_validate(v) for k, v in records("ep_people/meps.json", ids).items()}
    orgs = [Organization.model_validate(o) for o in json.loads((SNAP / "ep_people" / "orgs.json").read_text("utf-8"))]
    group_orgs: dict[str, list[Organization]] = defaultdict(list)
    for o in orgs:
        if o.kind == "group":
            group_orgs[group_slug(o.code or o.label)].append(o)
    me = SimpleNamespace(
        mep=meps, org={o.id: o for o in orgs}, group_orgs=group_orgs,
        org_slug={o.id: s for s, os_ in group_orgs.items() for o in os_},
        mep_groups={i: sorted((x.start, x.end, x.org_id) for x in m.memberships if x.kind == "group")
                    for i, m in meps.items()},
    )  # fmt: skip
    me.group_at = lambda mep_id, d: Builder.group_at(me, mep_id, d)  # type: ignore[arg-type]
    p = procs("2021-0106", "2016-0107")
    ai = {r["mep_id"]: r for r in Builder.rapporteur_entries(me, p["2021-0106"])}  # type: ignore[arg-type]
    assert (ai["23699"]["group"], ai["23699"]["group_code"], ai["23699"]["role"]) == ("the-left", "The Left", "shadow")
    assert (ai["197493"]["group"], ai["197493"]["group_code"]) == ("id", "ID")
    assert (ai["197784"]["group_code"], ai["197784"]["role"], ai["197784"]["committee"]) == (
        "Renew", "opinion_rapporteur", "ENVI",
    )  # fmt: skip
    durand = [r for r in Builder.rapporteur_entries(me, p["2016-0107"]) if r["mep_id"] == "124693"]  # type: ignore[arg-type]
    assert [(r["group"], r["group_code"]) for r in durand] == [("greens-efa", "Greens/EFA")]
