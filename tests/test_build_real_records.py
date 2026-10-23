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


def test_commission_proposal_of_an_ordinary_procedure_needs_its_com_number():
    p = procs("2023-0052", "2010-0817", "2021-0106", "2022-0906")
    # OEIL prints COM(2023)0126 as plain text next to a EUR-Lex flag link; the record now carries it
    assert p["2023-0052"].com_refs == ["COM(2023)0126"] and commission_cod_proposal(p["2023-0052"])
    assert not commission_cod_proposal(p["2010-0817"])  # initiative of Member States (09288/2010)
    assert commission_cod_proposal(p["2021-0106"])
    # the Court of Justice's request (OEIL documentation gateway "CJEC | Legislative proposal | 07307/2022"): not
    # a Commission proposal, so the Council's qualified majority is not asserted under TEU Art. 16(4)
    assert not commission_cod_proposal(p["2022-0906"])
    prop = next(e for e in p["2022-0906"].events if e.kind.value == "proposal")
    assert (prop.institution, [d.id for d in prop.docs]) == ("CJEU", ["07307/2022"])
    assert Builder.procedure_event(p["2022-0906"], prop).title == "Court of Justice submitted its request (legislative proposal)"
    # an empty list of documents does not make a Commission proposal
    bare = p["2021-0106"].model_copy(update={"events": [
        e.model_copy(update={"docs": []}) for e in p["2021-0106"].events if e.kind.value == "proposal"]})
    assert not commission_cod_proposal(bare)


def test_both_qmv_thresholds_are_given_when_the_legal_basis_is_not_established():
    from pipeline.analysis.council_qmv import assess

    cv = council("ST-7930-2022")["ST-7930-2022"]  # 2022/0077(COD): 25 of 25 taking part
    a = Builder.council_rule_assessment(None, assess, cv, None)  # type: ignore[arg-type]
    assert a and a["legal_basis"] is None and (a["states_required"], a["states_required_alt"]) == (14, 18)
    p = procs("2022-0077")["2022-0077"]
    b = Builder.council_rule_assessment(None, assess, cv, p)  # type: ignore[arg-type]
    # on a Commission proposal, with Denmark and Ireland not taking part: Art. 238(3)(a) TFEU
    assert b and b["legal_basis"] == "TFEU Art. 238(3)(a)" and b["states_required_alt"] is None


def test_council_consent_to_parliaments_ombudsman_statute_is_not_on_a_commission_proposal():
    from pipeline.analysis.council_qmv import assess

    # ST 9947/21, "Consent of the Council (Article 228(4) TFEU); Approval": the sheet prints "QMV without COM" and
    # its footnote "72 % of members … (20 MS)"; the card said whether a Commission proposal existed was not recorded
    cv = council("ST-9947-2021")["ST-9947-2021"]
    a = Builder.council_rule_assessment(None, assess, cv, procs("2019-0900")["2019-0900"])  # type: ignore[arg-type]
    assert a and (a["legal_basis"], a["states_required"], a["states_required_alt"]) == ("TFEU Art. 238(2)", 20, None)
    assert "not established" not in a["note"]


def _built_council(ids: list[str], dossiers: list[str], curated: Path | None = None) -> dict[str, dict]:
    """Builder.build_council on the real records and data/curated/council_votes.yaml (or `curated`)."""
    from pipeline.build import load_council_votes

    fixes, extra, notes = load_council_votes(curated) if curated else load_council_votes()
    p = procs(*dossiers)
    by_ref = {x.reference: x for x in p.values()}
    me = SimpleNamespace(
        s=SimpleNamespace(council=list(council(*ids).values())), council_extra=extra, council_fixes=fixes,
        council_extra_notes=notes, proc=p, files={}, resolve_ref=by_ref.get, council_split_part=lambda cv, d: None,
        council_vote_on=lambda cv, p: (cv.vote_on, None), council_vote_date=lambda cv, p, on: (cv.date, None),
    )  # fmt: skip
    me.council_rule_assessment = lambda assess, cv, p: Builder.council_rule_assessment(me, assess, cv, p)  # type: ignore[arg-type]
    Builder.build_council(me)  # type: ignore[arg-type]
    me.council_records = {r["id"]: r for r in me.council_public}
    return me  # type: ignore[return-value]


def test_council_rule_follows_a_legal_basis_that_requires_unanimity():
    from pipeline.build import council_vote_event

    # The sheets print "Voting Rule: qualified majority", but the acts' citations name Article 19(1) TFEU (ST 9781/24,
    # Council Directive (EU) 2024/1499), 81(3) (ST 5698/24, Decision (EU) 2024/592) and 312 (ST 7391/20, Regulation
    # 2020/538; ST 15907/22, Regulation 2022/2496), under which the Council acts unanimously. Protocol No 37,
    # Article 2 (ST 10959/21, Decision (EU) 2021/1208) requires no unanimity: the sheet's rule stands.
    ids = ["ST-9781-2024", "ST-5698-2024", "ST-7391-2020", "ST-15907-2022", "ST-10959-2021"]
    me = _built_council(ids, ["2022-0401", "2023-0027", "2020-0055", "2022-0369", "2020-0142"])
    r = me.council_records  # type: ignore[attr-defined]
    for vid in ("ST-9781-2024", "ST-5698-2024", "ST-7391-2020"):
        assert (r[vid]["voting_rule"], r[vid]["sheet_voting_rule"], r[vid]["outcome"]) == ("unanimity", "qmv", "adopted")
        assert r[vid]["assessment"]["single_state_veto_possible"] is True
        assert "labels the voting rule “qualified majority”" in r[vid]["voting_rule_note"]
    assert "Article 81(3)" in r["ST-5698-2024"]["voting_rule_note"]
    assert r["ST-5698-2024"]["assessment"]["legal_basis"] == "TFEU Art. 238(4) (participating Member States only)"
    assert r["ST-10959-2021"]["voting_rule"] == "qmv" and "sheet_voting_rule" not in r["ST-10959-2021"]
    # 6 December 2022: Hungary's vote against meant the MFF amendment was not adopted (the sheet marks it adopted);
    # the Council adopted it by written procedure on 15 December 2022, Hungary abstaining (CM 5860/22)
    mff = r["ST-15907-2022"]
    assert (mff["voting_rule"], mff["outcome"], mff["sheet_outcome"]) == ("unanimity", "not_adopted", "adopted")
    assert mff["assessment"]["adopted_by_rule"] is False and "CM 5860/22" in mff["outcome_note"]
    assert council_vote_event(mff)["title"] == "Council did not adopt the act"
    cm = r["CM-5860-2022"]
    assert (cm["dossier_id"], cm["date"], cm["voting_rule"], cm["outcome"], cm["vote_on"]) == (
        "2022-0369", "2022-12-15", "unanimity", "adopted", "act",
    )  # fmt: skip
    assert cm["positions"]["HU"] == "abstain" and sum(x == "for" for x in cm["positions"].values()) == 26
    assert cm["source"]["identifier"] == "CM 5860/22" and "CM 5860/22" in cm["source_note"]
    ev = council_vote_event(cm)
    assert (ev["kind"], ev["title"]) == ("council_adoption", "Council adopted the act (written procedure)")
    # the file is dated by that adoption, as the act itself is (Regulation 2022/2496 "of 15 December 2022")
    me2 = SimpleNamespace(today="2026-10-23", council_of={"2022-0369": [cm, mff]})
    me2.council_dated = lambda p: Builder.council_dated(me2, p)  # type: ignore[arg-type]
    p = procs("2022-0369")["2022-0369"]
    assert Builder.adoption_dates(me2, p, [acts("32022R2496")["32022R2496"]])[0] == "2022-12-15"  # type: ignore[arg-type]


def test_council_rule_correction_is_dropped_when_the_outcome_does_not_follow(tmp_path: Path):
    # without the outcome, the MFF correction would show an act adopted under unanimity over a vote against
    (tmp_path / "council_votes.yaml").write_text(
        "corrections:\n"
        "  - {vote: ST-15907-2022, celex: 32022R2496, legal_basis: TFEU Art. 312(2), citation: x}\n"
        "  - {vote: ST-9781-2024, celex: 32024L1499, legal_basis: TFEU Art. 352, citation: x}\n",
        encoding="utf-8",
    )
    me = _built_council(["ST-15907-2022", "ST-9781-2024"], ["2022-0369", "2022-0401"], tmp_path)
    r = me.council_records  # type: ignore[attr-defined]
    assert (r["ST-15907-2022"]["voting_rule"], r["ST-15907-2022"]["outcome"]) == ("qmv", "adopted")
    assert r["ST-9781-2024"]["voting_rule"] == "qmv"  # a legal basis not in UNANIMITY_BASES is not used


def test_council_list_title_names_the_item_voted_on():
    from pipeline.build import council_vote_label

    # every Member State voted FOR the non-approval of Parliament's amendments to the draft budget (Art. 314(4)(c)
    # TFEU); the country pages showed "Amendments of the European Parliament …" with "For"
    cv = council("ST-14700-2026", "ST-14735-2024", "ST-9781-2024")
    label = {k: council_vote_label(x.title, x.vote_on, x.stage) for k, x in cv.items()}
    assert label["ST-14700-2026"] == (
        "Amendments of the European Parliament to the Council's position on the draft budget for 2027 – "
        "Non-approval of the European Parliament's amendment(s)"
    )
    # "Adoption of the legislative act" on a budget note (the budget is not a legislative act) is left out
    assert cv["ST-14735-2024"].stage.endswith("; Adoption of the legislative act")
    assert label["ST-14735-2024"].endswith("for 2025 – Non-approval of the European Parliament's amendment(s)")
    assert label["ST-9781-2024"].startswith("Council Directive on standards for equality bodies")


def test_featured_card_names_amending_acts_the_timeline_cannot_date():
    # EUDR (2021/0366(COD)): EUR-Lex lists Delegated Regulation (EU) 2026/2102 as amending Regulation (EU) 2023/1115,
    # but it is not in our EUR-Lex data; the card's latest step (23 December 2025) is older than it
    a = acts("32023R1115", "32024R3234", "32025R2650")
    me = SimpleNamespace(dossier_acts={"2021-0366": [a["32023R1115"]]}, act=a)
    note = Builder.undated_amendments_note(me, "2021-0366")  # type: ignore[arg-type]
    assert note == (
        "EUR-Lex also lists Regulation 2026/2102 as amending this act; its dates are not in our data, so the step "
        "above may not be the latest."
    )
    me.act = {**a, "32026R2102": a["32025R2650"]}
    assert Builder.undated_amendments_note(me, "2021-0366") is None  # type: ignore[arg-type]


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


# ----------------------------------------------------------------------------- timelines: steps, dates and order
def stand_in(**kw) -> SimpleNamespace:
    """The Builder state the procedure methods read (with_recorded_events, timeline, adoption_dates), with the
    checked Council dates of data/curated/council_dates.yaml."""
    from pipeline.build import load_council_dates

    state = {"today": "2026-10-23", "notices_by_ref": {}, "acts_of": {}, "votes_of": {}, "council_of": {}, "act": {},
             "act_dates": {}, "indexed_vote_ids": set(), "procedure_event": Builder.procedure_event,
             "council_dates": load_council_dates()}  # fmt: skip
    me = SimpleNamespace(**(state | kw))
    for name in ("council_dated", "checked_council_date", "council_step_dated", "council_vote_date"):
        setattr(me, name, getattr(Builder, name).__get__(me))
    return me


def council_rec(cv: CouncilVote, vote_on: str | None = None) -> dict:
    """A Council vote as build_council publishes it (the fields the timeline reads)."""
    return {"id": cv.id, "date": cv.date, "vote_on": vote_on or cv.vote_on, "outcome": cv.outcome, "stage": cv.stage,
            "written_procedure": cv.written_procedure, "positions": cv.positions, "source": None}  # fmt: skip


def test_council_adoption_is_dated_by_the_acts_own_text():
    # Directive (EU) 2017/1132, footnote 2: "Position of the European Parliament of 5 April 2017 ... and decision of
    # the Council of 29 May 2017"; OEIL "Act adopted by Council after Parliament's 1st reading" 18/04/2017.
    # Regulation (EU) 2016/2030: "Council decision of 20 September 2016"; OEIL 19/10/2016
    from pipeline.build import load_council_dates

    cur = load_council_dates()
    assert len(cur) == 36 and cur["2015/0283(COD)"]["date"] == "2017-05-29"
    for pid, celex, want, oeil in (("2015-0283", "32017L1132", "2017-05-29", "18 April 2017"),
                                   ("2016-0064", "32016R2030", "2016-09-20", "19 October 2016")):  # fmt: skip
        p, a = procs(pid)[pid], acts(celex)[celex]
        me = stand_in(acts_of={pid: [a]}, act={celex: a})
        q = Builder.with_recorded_events(me, p)  # type: ignore[arg-type]
        step = next(e for e in q.events if e.kind.value == "council_adoption")
        assert step.date == want and step.detail and oeil in step.detail and celex in [d.id for d in step.docs]
        assert Builder.adoption_dates(me, q, [a])[0] == want  # type: ignore[arg-type]
        tl = Builder.timeline(me, q, [a], [])  # type: ignore[arg-type]
        assert [x["date"] for x in tl if x["kind"] == "council_adoption"] == [want]
    # an entry for an act that is not the file's is not applied
    p = procs("2015-0283")["2015-0283"]
    assert Builder.checked_council_date(stand_in(), p) is None  # type: ignore[arg-type]


def test_council_vote_of_a_meeting_over_several_days_is_dated_by_the_act():
    # CSDDD: ST 10263/24 is for the 4026th meeting of 23-24 May 2024 (recorded on the first day); its voting sheet
    # gives "Sitting date: 24/05/2024" and Directive (EU) 2024/1760 "decision of the Council of 24 May 2024"
    cv = council("ST-10263-2024", "ST-8001-2024")
    p, a = procs("2022-0051")["2022-0051"], acts("32024L1760")["32024L1760"]
    me = stand_in(acts_of={"2022-0051": [a]}, act={a.celex: a})
    assert cv["ST-10263-2024"].date == "2024-05-23"
    when, note = Builder.council_vote_date(me, cv["ST-10263-2024"], p, "act")  # type: ignore[arg-type]
    assert when == "2024-05-24" and note and "Sitting date: 24/05/2024" in note and "24 May 2024" in note
    other = Builder.council_vote_date(me, cv["ST-10263-2024"], p, "first_reading_position")  # type: ignore[arg-type]
    assert other == ("2024-05-23", None)
    # a vote no entry names keeps the voting result's date (2022/0906: ST 8001/24)
    p2 = procs("2022-0906")["2022-0906"]
    assert Builder.council_vote_date(me, cv["ST-8001-2024"], p2, "act") == (cv["ST-8001-2024"].date, None)  # type: ignore[arg-type]


def test_every_curated_council_date_names_the_files_act():
    from pipeline.build import load_council_dates

    cur = load_council_dates()
    ids = {ref.replace("/", "-").split("(")[0]: e for ref, e in cur.items()}
    p, a = procs(*ids), acts(*{e["celex"] for e in cur.values()})
    for pid, e in ids.items():
        act = a[e["celex"]]
        assert e["celex"] in p[pid].celex_refs or p[pid].reference in act.procedure_refs, pid
        # the Council decided before the act was signed and published
        assert e["date"] <= (act.date_signature or act.date_document or "9999") <= (act.date_publication or "9999")
        assert e["reviewed"] == "2026-10-23"
    assert council(*{e["vote"] for e in cur.values() if e.get("vote")})


def test_curated_council_date_must_be_the_one_its_quote_gives(tmp_path: Path):
    from pipeline.build import load_council_dates

    (tmp_path / "council_dates.yaml").write_text(
        '- {procedure: "2015/0283(COD)", celex: "32017L1132", date: "2017-05-28",\n'
        '   quote: "Position of the European Parliament of 5 April 2017 and decision of the Council of 29 May 2017."}\n'
        '- {procedure: "2016/0064(COD)", celex: "32016R2030", date: "2016-09-20",\n'
        '   quote: "Position of the European Parliament of 6 July 2016 and Council decision of 20 September 2016."}\n',
        encoding="utf-8",
    )
    assert list(load_council_dates(tmp_path)) == ["2016/0064(COD)"]


def test_council_vote_on_the_derogation_from_the_eight_week_period_is_not_the_adoption():
    # 2020/0067(COD), 20 May 2020, both on PE-CONS 15/20: ST 8159/20 adopted the act (22-4-1); ST 8160/20's voting
    # sheet is on "Derogation, on the basis of the second subparagraph of Article 3(3) of the Council's Rules of
    # Procedure, from the eight-week period" (25-0-2). ST 7391/20 REV 1 (2020/0055) only notes "Derogation from the
    # 8-week period provided for in Article 3(3) ..." next to the adoption: it adopted the act.
    from pipeline.build import council_vote_event

    cv = council("ST-8159-2020", "ST-8160-2020", "ST-7391-2020")
    p = procs("2020-0067", "2020-0055")
    me = SimpleNamespace(s=SimpleNamespace(council=list(cv.values())))
    on, note = Builder.council_vote_on(me, cv["ST-8160-2020"], p["2020-0067"])  # type: ignore[arg-type]
    assert on == "other" and note and "ST 8159/20" in note and "PE-CONS 15/20" in note
    assert Builder.council_vote_on(me, cv["ST-8159-2020"], p["2020-0067"]) == ("act", None)  # type: ignore[arg-type]
    assert Builder.council_vote_on(me, cv["ST-7391-2020"], p["2020-0055"]) == ("act", None)  # type: ignore[arg-type]
    ev = council_vote_event(council_rec(cv["ST-8160-2020"], on))
    assert (ev["kind"], ev["key"]) == ("other", False)
    assert ev["title"] == (
        "Council decided to derogate from the eight-week period for national parliaments (written procedure)"
    )
    assert council_vote_event(council_rec(cv["ST-8159-2020"]))["title"] == "Council adopted the act (written procedure)"


def test_council_consent_by_vote_is_the_councils_step():
    # 2019/0900(APP), Statute of the European Ombudsman: ST 9947/21 "Consent of the Council (Article 228(4) TFEU) -
    # Approval", 18 June 2021, the step OEIL lists as "Act adopted by Council after consultation of Parliament"
    from pipeline.build import council_vote_event

    cv = council("ST-9947-2021")["ST-9947-2021"]
    p = procs("2019-0900")["2019-0900"]
    ev = council_vote_event(council_rec(cv))
    assert (ev["kind"], ev["title"], ev["key"]) == ("council_adoption", "Council gave its consent", True)
    me = stand_in(council_of={"2019-0900": [council_rec(cv)]})
    tl = Builder.timeline(me, p, [], [])  # type: ignore[arg-type]
    council_day = [x["id"] for x in tl if x["date"] == "2021-06-18" and x["institution"] == "Council"]
    assert council_day == ["council-ST-9947-2021"]


def test_consultation_opinion_recorded_as_amendments_is_parliaments_opinion():
    # 2018/0173(CNS), 24 Oct 2018: EP API PLENARY_AMEND; OEIL "Decision by Parliament T8-0415/2018" ("Approves the
    # Commission proposal as amended"). 2011/0436(APP), 19 Nov 2013: T7-0462/2013 "Consents to the draft".
    # 2022/0154(CNS), 16 Jan 2024: one opinion, not a second one derived from its final vote 163120.
    p = procs("2018-0173", "2011-0436", "2022-0154")
    ev = {pid: Builder.with_recorded_events(stand_in(), p[pid]).events for pid in p}  # type: ignore[arg-type]

    def day(pid: str, d: str) -> list[tuple[str, str]]:
        return [(e.kind.value, e.title) for e in ev[pid] if e.date == d and e.institution == "EP"]

    assert day("2018-0173", "2018-10-24") == [("ep_position", "Parliament delivered its opinion")]
    assert day("2011-0436", "2013-11-19") == [("ep_position", "Parliament voted on consent")]
    v = votes("163120")
    q = Builder.with_recorded_events(stand_in(votes_of={"2022-0154": list(v.values())}), p["2022-0154"])  # type: ignore[arg-type]
    assert [(e.kind.value, e.title) for e in q.events if e.date == "2024-01-16"] == [
        ("ep_position", "Parliament delivered its opinion")
    ]
    tl = Builder.timeline(stand_in(indexed_vote_ids=set(v)), q, [], list(v.values()))  # type: ignore[arg-type]
    assert [(x["key"], x["vote_id"]) for x in tl if x["date"] == "2024-01-16"] == [(True, "163120")]


def test_vote_on_a_request_for_urgent_procedure_says_so():
    # 2025/3502(COD), 16 Dec 2025: the only vote is decision 182690 "Request for an urgent decision", adopted by show
    # of hands. 2020/0128(COD), 8 Jul 2020: 116197 "Request for urgent procedure", 618-62-13 (roll call).
    p = procs("2025-3502", "2020-0128")
    v = votes("182690", "116197")
    last = Builder.timeline(stand_in(), p["2025-3502"], [], [v["182690"]])[-1]  # type: ignore[arg-type]
    assert (last["date"], last["title"], last["detail"]) == (
        "2025-12-16", "Parliament approved the request for an urgent decision", "By show of hands"
    )
    assert last["source"]["identifier"] == "MTG-PL-2025-12-16-DEC-182690"
    tl = Builder.timeline(stand_in(), p["2020-0128"], [], [v["116197"]])  # type: ignore[arg-type]
    day = [x for x in tl if x["date"] == "2020-07-08"]
    assert [(x["title"], x["detail"]) for x in day] == [
        ("Parliament approved the request for urgent procedure", "618 in favour, 62 against, 13 abstentions")
    ]
    assert {d["id"] for d in day[0]["docs"]} == {
        "PV-9-2020-07-08-ITM-018", "C-9-2020-0185", "PV-9-2020-07-08-VOT-ITM-027"
    }  # fmt: skip
    # without the vote in our data, the records keep their neutral titles
    tl = Builder.timeline(stand_in(), p["2020-0128"], [], [])  # type: ignore[arg-type]
    assert [x["title"] for x in tl if x["date"] == "2020-07-08"] == ["Vote in Parliament", "Results of vote in Parliament"]


def test_signature_of_an_ordinary_procedure_act_is_both_presidents_on_the_acts_date():
    # 2017/0329(COD): EP/OEIL "Final act signed" 11 Apr 2018, the day before the Council adopted the act (12 Apr);
    # Directive (EU) 2018/597 "of 18 April 2018", signed by the Presidents of Parliament and Council (Art. 297(1) TFEU)
    from pipeline.build import JOINT_ACT_RE

    p, a = procs("2017-0329")["2017-0329"], acts("32018L0597")["32018L0597"]

    def sig(tl: list[dict]) -> list[tuple[str, str, str]]:
        return [(x["date"], x["title"], x["institution"]) for x in tl if x["kind"] == "signature"]

    joint = "Signed by the Presidents of Parliament and Council"
    assert sig(Builder.timeline(stand_in(), p, [a], [])) == [("2018-04-18", joint, "EP and Council")]  # type: ignore[arg-type]
    # without the act in our data: the EP's record, shown as the joint signature it is
    assert sig(Builder.timeline(stand_in(), p, [], [])) == [("2018-04-11", joint, "EP and Council")]  # type: ignore[arg-type]
    # a Council act that names an act of Parliament and the Council in its title is not one
    c = acts("32021R1696")["32021R1696"]
    assert JOINT_ACT_RE.match(a.title) and not JOINT_ACT_RE.match(c.title)


def test_steps_of_one_day_are_in_procedural_order():
    # 2020/0055(APP), 17 Apr 2020: Parliament's vote, the Council's adoption by written procedure (ST 7391/20 REV 1),
    # publication and entry into force of Council Regulation (EU, Euratom) 2020/538, all that day.
    # 2016/0132(COD), 14 May 2024: the Council adopted the act (ST 9841/24) before it was signed.
    p = procs("2020-0055", "2016-0132")
    cv = council("ST-7391-2020", "ST-9841-2024")
    a = acts("32020R0538", "32024R1358")
    me = stand_in(council_of={"2020-0055": [council_rec(cv["ST-7391-2020"])],
                              "2016-0132": [council_rec(cv["ST-9841-2024"])]})  # fmt: skip
    tl = Builder.timeline(me, p["2020-0055"], [a["32020R0538"]], [])  # type: ignore[arg-type]
    assert [x["kind"] for x in tl if x["date"] == "2020-04-17"] == [
        "plenary_vote", "council_adoption", "publication", "entry_into_force"
    ]
    tl = Builder.timeline(me, p["2016-0132"], [a["32024R1358"]], [])  # type: ignore[arg-type]
    assert [x["kind"] for x in tl if x["date"] == "2024-05-14"] == ["council_adoption", "signature"]


def test_vote_records_of_a_sitting_list_only_the_files_documents():
    # re-derived snapshot records (pipeline.sources.ep_procedures.build_events): 2020/0112(APP) keeps only its own
    # report A9-0227/2021; 2019/0900(APP) no longer lists A9-0170/2021 (Black Sea fisheries, 2019/2159(INI))
    p = procs("2020-0112", "2019-0900", "2020-0067", "2016-0132")
    assert [d.id for d in p["2020-0112"].documents if d.kind == "report"] == ["A-9-2021-0227"]
    # a joint debate's reports (the asylum files debated together) are not the file's key documents
    assert [d.id for d in p["2016-0132"].documents if d.kind == "report"] == ["A-8-2017-0212"]
    assert "A-9-2021-0170" not in {d.id for e in p["2019-0900"].events for d in e.docs}
    assert max(len(e.docs) for e in p["2020-0067"].events) < 10


# ------------------------------------------------------------------------- acts, types of act, implementation
def test_type_of_act_of_a_file_not_adopted_is_the_one_proposed():
    # OEIL "Legislative instrument". 2023/0085(COD), Green Claims: "Directive"; COM(2023) 166 is a "Proposal for a
    # DIRECTIVE ...". 2016/0284(COD) was proposed as a regulation and became Directive (EU) 2019/789: the build takes
    # the adopted act's type first.
    from pipeline.build import proposed_instrument

    p = procs("2023-0085", "2016-0284")
    assert proposed_instrument(p["2023-0085"]) == "directive"
    assert proposed_instrument(p["2016-0284"]) == "regulation"
    assert proposed_instrument(p["2023-0085"].model_copy(update={"instrument": "Act"})) is None


def _impl_builder(measures: dict, checks: dict | None = None) -> SimpleNamespace:
    me = SimpleNamespace(measures_by=measures, measure_celexes={c for c, _ in measures}, optouts={}, infr_by_celex={},
                         transposition_checks=checks or {}, today="2026-10-23", act_refs={}, not_participating_by_ref={})  # fmt: skip
    me.transposition_status = lambda c, k, d: Builder.transposition_status(me, c, k, d)  # type: ignore[arg-type]
    me.not_participating = lambda c, k: Builder.not_participating(me, c, k)  # type: ignore[arg-type]
    me.participation_recorded = lambda c, k: Builder.participation_recorded(me, c, k)  # type: ignore[arg-type]
    me.infr_info = lambda i, c=None: Builder.infr_info(me, i, c)  # type: ignore[arg-type]
    me.implementation_table = lambda a: Builder.implementation_table(me, a)  # type: ignore[arg-type]
    me.implementations = lambda acts: Builder.implementations(me, acts)  # type: ignore[arg-type]
    return me


def _measures(*celex: str) -> dict:
    from collections import defaultdict

    from pipeline.models.entities import NationalMeasure

    by: dict = defaultdict(list)
    with (SNAP / "implementation" / "measures.json").open(encoding="utf-8") as f:
        for line in f:
            if any(f'"directive_celex":"{c}"' in line for c in celex):
                r = json.loads(line.strip().rstrip(","))
                by[(r["directive_celex"], r["country"])].append(NationalMeasure.model_validate(r))
    return by


def test_a_file_with_two_directives_has_a_table_for_each():
    # 2013/0400(CNS) adopted Council Directive 2014/86/EU and Council Directive (EU) 2015/121. Cellar lists measures
    # of Ireland (1) and Sweden (2) for the second only; both directives' deadline (31 December 2015) is before 2019,
    # so the table says that infringement cases closed before 2019 are not in the data
    a = acts("32014L0086", "32015L0121")
    me = _impl_builder(_measures("32014L0086", "32015L0121"))
    tables = Builder.implementations(me, [a["32014L0086"], a["32015L0121"]])  # type: ignore[arg-type]
    assert [(t["celex"], t["act"]) for t in tables] == [
        ("32014L0086", "Council Directive 2014/86/EU"), ("32015L0121", "Council Directive (EU) 2015/121"),
    ]  # fmt: skip
    rows = {t["celex"]: {c["country"]: (c["measures"], c["status"]) for c in t["countries"]} for t in tables}
    assert rows["32014L0086"]["IE"] == (0, "none_found") and rows["32015L0121"]["IE"] == (1, "measures_notified")
    assert rows["32015L0121"]["SE"] == (2, "measures_notified")
    assert all(t["infringements_from"] == "2019-01-01" for t in tables)
    assert "cases closed before then are not included" in tables[0]["note"]


def test_countries_the_directive_exempts_are_not_shown_as_missing_measures():
    # Directive (EU) 2016/798, Art. 33(4): "The obligation to transpose and implement this Directive shall not apply
    # to Cyprus and Malta for as long as no rail system is established within their territories."
    # Directive (EU) 2016/1629, Art. 40: "addressed to the Member States except Denmark, Estonia, Ireland, Greece,
    # Spain, Cyprus, Latvia, Malta, Portugal, Slovenia and Finland"
    from pipeline.build import load_transposition_checks

    checks = load_transposition_checks()
    a = acts("32016L0798", "32016L1629", "32021L1233")
    me = _impl_builder(_measures("32016L0798", "32016L1629", "32021L1233"), checks)
    rail = {c["country"]: c["status"] for c in Builder.implementation_table(me, a["32016L0798"])["countries"]}  # type: ignore[arg-type]
    assert (rail["CY"], rail["MT"]) == ("not_required", "not_required") and rail["IE"] != "not_required"
    vessels = Builder.implementation_table(me, a["32016L1629"])  # type: ignore[arg-type]
    assert sum(c["status"] == "not_required" for c in vessels["countries"]) == 11
    assert vessels["exemption"]["provision"] == "Art. 40"
    # a conditional derogation names no country: quoted, no row changed (32021L1233 applies Art. 39(4) of 2017/2397)
    boat = Builder.implementation_table(me, a["32021L1233"])  # type: ignore[arg-type]
    assert boat["exemption"]["countries"] is None and "Article 39(4)" in boat["exemption"]["quote"]
    assert not [c for c in boat["countries"] if c["status"] == "not_required"]


def test_infringement_cut_off_matches_the_source_module():
    from pipeline.build import INFRINGEMENTS_FROM
    from pipeline.sources.implementation import INFRINGEMENTS_SINCE_YEAR

    assert INFRINGEMENTS_FROM == f"{INFRINGEMENTS_SINCE_YEAR}-01-01"


def test_partial_repeal_and_partial_application_on_entry_into_force_are_stated():
    # Decision 2014/335/EU, Euratom: in force per EUR-Lex; Cellar records Decision (EU, Euratom) 2020/2053 as
    # repealing it with role AP (Art. 11(1): "Subject to paragraph 2, Decision 2014/335/EU, Euratom is repealed").
    # DMA, Art. 54: "Article 3(6) and (7) and Articles 40, 46, 47, 48, 49 and 50 shall apply from 1 November 2022".
    from datetime import date

    from pipeline.analysis.status import classify

    a = acts("32014D0335", "32020D2053", "32022R1925")
    p = procs("2011-0183", "2020-0374")
    s = classify(p["2011-0183"], [a["32014D0335"]], [], date(2026, 10, 23), others=a)
    assert s.stage == "in_force" and "partly repealed by Council Decision (EU, Euratom) 2020/2053." in s.explanation
    assert [r.celex for r in s.named_acts] == ["32020D2053"]
    s = classify(p["2020-0374"], [a["32022R1925"]], [], date(2026, 10, 23), others=a)
    assert "EUR-Lex records that some provisions apply from that date." in s.explanation
    assert s.application.entry_into_force == "2022-11-01" and s.application.partial_on_entry_into_force
    assert "2022-11-01" not in s.application.application_dates


def test_dates_set_by_a_corrigendum_cite_it():
    # AMMR, Regulation (EU) 2024/1351, Art. 85 as published: "It shall apply from 1 July 2026"; corrigendum OJ L,
    # 2025/90929, point 10: read "It shall apply from 12 June 2026" (the date EUR-Lex records)
    from pipeline.build import act_date_source, apply_act_dates, load_act_dates

    cur = load_act_dates()["32024R1351"]
    assert act_date_source(cur, "2026-06-12")["label"] == (
        "Corrigendum to Regulation (EU) 2024/1351, OJ L, 2025/90929, 25.11.2025"
    )
    assert act_date_source(cur, "2024-06-11")["label"] == "Regulation (EU) 2024/1351, Article 85"
    a = apply_act_dates(acts("32024R1351")["32024R1351"], cur)
    assert a.other_application_dates == ["2026-06-12"] and not a.partial_on_entry_into_force


# ------------------------------------------------------------------- split parents and Parliament reports
def test_split_parts_and_the_main_file_of_a_report_are_linked_from_the_status_text():
    # 2016/0400(COD) was split into 2016/0400A(COD) (Regulation (EU) 2019/1243) and 2016/0400B(COD) (withdrawn);
    # OEIL has no file for the parent. 2020/0112R(APP) is Parliament's interim report on 2020/0112(APP).
    p = procs("2016-0400A", "2016-0400B", "2020-0112", "2020-0112R")
    me = SimpleNamespace(
        proc=p, split_children={"2016-0400": ["2016-0400A", "2016-0400B"]},
        _status_dict=Builder._status_dict, _procedure_ref=Builder._procedure_ref,
    )  # fmt: skip
    split = Builder.classify(me, SimpleNamespace(id="2016-0400"))  # type: ignore[arg-type]
    assert split["status"]["named_acts"] == [
        {"celex": "", "label": "2016/0400A(COD)", "url": p["2016-0400A"].oeil_url, "dossier": "2016-0400A"},
        {"celex": "", "label": "2016/0400B(COD)", "url": p["2016-0400B"].oeil_url, "dossier": "2016-0400B"},
    ]
    assert all(a["label"] in split["status"]["explanation"] for a in split["status"]["named_acts"])
    report = Builder.classify(me, p["2020-0112R"])  # type: ignore[arg-type]
    assert report["status"]["named_acts"] == [
        {"celex": "", "label": "2020/0112(APP)", "url": p["2020-0112"].oeil_url, "dossier": "2020-0112"},
    ]
    assert "2020/0112(APP)" in report["status"]["explanation"]
    assert report["next_step"]["text"] == "None for this report. See the main procedure 2020/0112(APP) for the proposal."
