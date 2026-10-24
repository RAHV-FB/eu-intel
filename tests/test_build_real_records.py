"""pipeline/build.py rules checked on the real records that showed each problem (data/snapshot/, read only).

Skipped when the snapshot is not present. Builder methods are called on a minimal stand-in holding only the
attributes they read.
"""

from __future__ import annotations

import json
import re
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
    _vote_title_entry,
    act_label,
    build_search_docs,
    commission_cod_proposal,
    discharge_note,
    english_procedural,
    final_role,
    referred_back,
    rejection_title,
    search_subject,
    subject_procedure,
    undotted_acronym,
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


def test_party_acronyms_written_with_dots_are_also_searchable_without_them():
    # EP open data labels Nea Demokratia 6730 "N.D.", Democratic Rally 6764 "DI.SY.", Democratic Party 6766 "DI.KO."
    # and EDEK 5190 "K.S. EDEK"; "SP.A" (5172) and "E.Verde" (6324) are not dotted acronyms: "SPA" would outrank Spain
    o = orgs("6730", "6764", "6766", "5190", "5172", "6324")
    party = {oid: {"label": x.label, "code": x.code, "country": x.country or "", "members_active": 0} for oid, x in o.items()}
    b = SimpleNamespace(
        dossier_summary={}, proc={}, curated_of={}, acts_of={}, train_of={}, alias_rules=[], mep_summary={},
        group_summaries=[], party_summary=party, s=SimpleNamespace(meps=[]), topic_list=[], topics_cur={},
        resolve_ref=lambda ref: None, org=o, unnamed_parties=set(),
    )  # fmt: skip
    docs = {d["id"]: d.get("a") for d in build_search_docs(b) if d["k"] == "party"}
    assert docs == {"6730": "N.D. | ND", "6764": "DI.SY. | DISY", "6766": "DI.KO. | DIKO", "5190": "K.S. EDEK | KS EDEK",
                    "5172": "SP.A", "6324": "E.Verde"}  # fmt: skip
    assert undotted_acronym("GRÜNE.") is None and undotted_acronym("Ind.") is None and undotted_acronym("PiS") is None


def test_search_entries_carry_the_types_of_the_files_acts():
    # "whistleblower directive" and "USB-C regulation" found nothing: the files of Directive (EU) 2019/1937 and
    # Directive (EU) 2022/2380 had no word for the type of their act; a proposal (no act yet) has none
    p = procs("2018-0106", "2021-0291")
    a = acts("32019L1937", "32022L2380")
    of = {"2018-0106": [a["32019L1937"]], "2021-0291": [a["32022L2380"]]}
    summary = {pid: {"title": p[pid].title, "ref": p[pid].reference, "status_label": "In force", "featured": False,
                     "type": "COD", "last_event": None, "celex": [x.celex for x in of[pid]]} for pid in p}  # fmt: skip
    summary["2099-0001"] = {**summary["2018-0106"], "celex": []}
    b = SimpleNamespace(
        dossier_summary=summary, proc={**p, "2099-0001": p["2018-0106"]}, curated_of={}, acts_of={**of, "2099-0001": []},
        train_of={}, split_children={}, alias_rules=[], mep_summary={}, group_summaries=[], party_summary={},
        s=SimpleNamespace(meps=[]), topic_list=[], topics_cur={}, resolve_ref=lambda ref: None, org={}, unnamed_parties=set(),
    )  # fmt: skip
    x = {d["id"]: d["x"].split() for d in build_search_docs(b) if d["k"] == "dossier"}
    assert "directive" in x["2018-0106"] and "directive" in x["2021-0291"]
    assert not {"directive", "regulation", "decision"} & set(x["2099-0001"])


def test_act_number_of_a_title_written_without_a_space_after_the_act_type():
    # Cellar's title of 32014L0063 reads "Directive2014/63/EU of the European Parliament ...": the country pages
    # wrote "Directive 2014/63" (from the CELEX id); 32022R0870 reads "Regulation(EU) 2022/870 ..."
    a = acts("32014L0063", "32022R0870", "32022L2555")
    assert act_label(a["32014L0063"]) == "Directive 2014/63/EU"
    assert act_label(a["32022R0870"]) == "Regulation (EU) 2022/870"
    assert act_label(a["32022L2555"]) == "Directive (EU) 2022/2555"


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


def test_council_document_is_not_shown_as_the_councils_proposal():
    # 2010/0817(COD), European Investigation Order: OEIL "Initiative Belgium, Bulgaria, Estonia, Spain, Austria,
    # Slovenia and Sweden", recorded with Council document 09288/2010; the Council does not initiate an ordinary
    # procedure. 2008/0027(NLE): 13395/2014 is the Council's request for consent; Council Decision (EU) 2016/1218
    # "Having regard to the proposal from the European Commission", so it does not date the proposal
    p = procs("2010-0817", "2008-0027", "2014-0807", "2025-0806", "2017-0810", "2015-0804", "2011-0183")
    ini = next(e for e in p["2010-0817"].events if e.kind.value == "proposal")
    e = Builder.procedure_event(p["2010-0817"], ini)
    # the initiative as OEIL's title names it (ep_procedures keeps it as the detail); Directive 2014/41/EU: "Having
    # regard to the initiative of the Kingdom of Belgium, the Republic of Bulgaria, the Republic of Estonia, …"
    assert ini.detail == "Initiative Belgium, Bulgaria, Estonia, Spain, Austria, Slovenia and Sweden"
    assert (e.title, e.institution, e.kind.value, e.detail) == (
        "Member States' initiative published (as recorded by the Legislative Observatory)", "OEIL", "proposal",
        "The Legislative Observatory names it: “Initiative Belgium, Bulgaria, Estonia, Spain, Austria, Slovenia and "
        "Sweden”.")  # fmt: skip
    # an initiator OEIL does not name (2017/0810(COD), ECB recommendation): the Legislative Observatory's record
    ecb = next(e for e in p["2017-0810"].events if e.kind.value == "proposal")
    assert Builder.procedure_event(p["2017-0810"], ecb).title == (
        "Legislative proposal published (as recorded by the Legislative Observatory)")
    req = next(e for e in p["2008-0027"].events if e.kind.value == "proposal")
    e = Builder.procedure_event(p["2008-0027"], req)
    assert (e.title, e.institution, e.kind.value) == ("Council text submitted to Parliament", "Council", "other")
    q = Builder.with_recorded_events(stand_in(), p["2008-0027"])  # type: ignore[arg-type]
    assert Builder.proposal_date(q) is None
    # a consultation without a COM document: the Council consults Parliament on a text it need not have drafted
    # (2025/0806(CNS), 09737/2025: ST 9737/25, cover note of the President of the ECB, "Recommendation for a Council
    # Regulation … (ECB/2025/17)"; 2014/0807(CNS), 10896/2014; 2015/0804(CNS), a Council implementing decision)
    for pid in ("2025-0806", "2014-0807", "2015-0804"):
        cns = next(e for e in p[pid].events if e.kind.value == "proposal")
        e = Builder.procedure_event(p[pid], cns)
        assert (e.title, e.institution, e.kind.value) == ("Text submitted to Parliament by the Council", "Council",
                                                          "proposal"), pid  # fmt: skip
    # with the Commission's proposal in the file, a Council document is the Council's text for reconsultation
    # (2011/0183(CNS), 05602/2014)
    re_cns = next(e for e in p["2011-0183"].events if [d.id for d in e.docs] == ["05602/2014"])
    assert Builder.procedure_event(p["2011-0183"], re_cns).title == "Council text submitted to Parliament"


def test_both_qmv_thresholds_are_given_when_the_legal_basis_is_not_established():
    from pipeline.analysis.council_qmv import assess

    cv = council("ST-7930-2022")["ST-7930-2022"]  # 2022/0077(COD): 25 of 25 taking part
    a = Builder.council_rule_assessment(None, assess, cv, None)  # type: ignore[arg-type]
    assert a and a["legal_basis"] is None and (a["states_required"], a["states_required_alt"]) == (14, 18)
    # the note says what is missing: here the vote is not linked to a file (it said "the procedure record names
    # no Commission proposal" for every such vote)
    assert "this vote is not linked to a procedure file in our data" in a["note"]
    p = procs("2022-0077")["2022-0077"]
    b = Builder.council_rule_assessment(None, assess, cv, p)  # type: ignore[arg-type]
    # on a Commission proposal, with Denmark and Ireland not taking part: Art. 238(3)(a) TFEU
    assert b and b["legal_basis"] == "TFEU Art. 238(3)(a)" and b["states_required_alt"] is None


def test_act_adopted_at_the_request_of_the_court_of_justice_needs_72_percent():
    from pipeline.analysis.council_qmv import assess

    # 2022/0906(COD): OEIL "CJEC | Legislative proposal | 07307/2022"; Regulation (EU, Euratom) 2024/2019 "Having
    # regard to the request of the Court of Justice" (Art. 281 TFEU, second paragraph), so not on a Commission
    # proposal: TFEU Art. 238(2), 20 of 27 Member States. The card said both thresholds, 15 or 20.
    from pipeline.build import court_request

    cv = council("ST-8001-2024")["ST-8001-2024"]
    p = procs("2022-0906", "2021-0106", "2010-0817")
    assert court_request(p["2022-0906"]) and not court_request(p["2021-0106"]) and not court_request(p["2010-0817"])
    a = Builder.council_rule_assessment(None, assess, cv, p["2022-0906"])  # type: ignore[arg-type]
    assert a and (a["legal_basis"], a["states_required"], a["states_required_alt"]) == ("TFEU Art. 238(2)", 20, None)
    assert "not established" not in a["note"]


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


def test_failed_reassessment_after_a_dropped_correction_does_not_stop_the_build(tmp_path: Path, monkeypatch):
    # the assessment under the sheet's rule, after the correction is dropped, is guarded like the first one
    (tmp_path / "council_votes.yaml").write_text(
        "corrections:\n  - {vote: ST-15907-2022, celex: 32022R2496, legal_basis: TFEU Art. 312(2), citation: x,\n"
        "     sources: [{label: act, url: 'https://eur-lex.europa.eu/eli/reg/2022/2496/oj'}]}\n",
        encoding="utf-8",
    )

    original = Builder.council_rule_assessment
    calls: list[str] = []

    def assessment(me, assess, cv, p):
        calls.append(cv.voting_rule)
        if cv.voting_rule == "qmv":
            raise ValueError("population figures unavailable")
        return original(me, assess, cv, p)

    monkeypatch.setattr(Builder, "council_rule_assessment", assessment)
    # without an outcome, the unanimity reading contradicts the sheet's "adopted": the correction is dropped
    r = _built_council(["ST-15907-2022"], ["2022-0369"], tmp_path).council_records["ST-15907-2022"]  # type: ignore[attr-defined]
    assert calls == ["unanimity", "qmv"]
    assert (r["voting_rule"], r["outcome"], r["assessment"]) == ("qmv", "adopted", None)


def test_council_vote_in_the_budget_procedure_is_not_the_adoption_of_an_act():
    # ST 10354/25, "Council Decision adopting the Council's position on draft amending budget No 1 …" (2025/0091
    # (BUD)), subject "Adoption of the legislative act": shown as "Act adopted"; the other draft amending budget
    # positions (ST 12944/25, 15603/25, 10726/26) were already "other"
    from pipeline.build import council_vote_items, council_vote_label

    cv = council("ST-10354-2025")["ST-10354-2025"]
    assert (cv.vote_on, cv.stage, cv.procedure_refs) == ("act", "Adoption of the legislative act", ["2025/0091(BUD)"])
    on, note = Builder.council_vote_on(SimpleNamespace(s=SimpleNamespace(council=[cv])), cv, None)  # type: ignore[arg-type]
    assert on == "other" and note and "2025/0091(BUD)" in note and "does not by itself adopt a budget" in note
    # no item remains once "Adoption of the legislative act" is left out: the row is tagged "Other Council decision"
    assert council_vote_items(cv.title, on, cv.stage, cv.procedure_refs) is None
    assert council_vote_label(cv.title, on, cv.stage, cv.procedure_refs) == cv.title


def test_council_summary_counts_every_vote_listed():
    # the About page's source card said "746 voting results …, 744 of them with each Member State's position", its
    # records table 747 Council votes, and the country pages count 745 with positions: CM-5860-2022 (curated, from the
    # Council's communication on the written procedure) is listed and counted, so the summary counts it too; so is
    # CM-5860-2022-2, the Pillar Two Directive's adoption recorded in the same communication (one document named once)
    me = _built_council(["ST-15907-2022", "ST-7085-2020"], ["2022-0369", "2021-0433"])
    assert len(me.council_public) == 4  # type: ignore[attr-defined]
    st = SimpleNamespace(fetched_at="2026-10-23T00:00:00Z", records={}, status="ok")
    summary = Builder.source_summary(me, "council", st)  # type: ignore[arg-type]
    assert summary.startswith(
        "4 votes of the Council of the EU (2020–2022), 3 of them with each Member State's position: 2 from the "
        "Council's voting-result documents and 2 adoptions by written procedure from the Council's communication on "
        "its outcome (CM 5860/22). 1 voting-result document could not be read and is shown without positions."
    )


def test_council_rule_correction_links_the_texts_it_was_checked_against(tmp_path: Path):
    from pipeline.build import council_vote_event

    # the ST 15907/22 step said only "Council did not adopt the act", sourced to the sheet that marks it adopted
    me = _built_council(["ST-15907-2022"], ["2022-0369"])
    mff = me.council_records["ST-15907-2022"]  # type: ignore[attr-defined]
    labels = [x["label"] for x in mff["correction_sources"]]
    assert labels == ["Council Regulation (EU, Euratom) 2022/2496, citations", "Council of the EU – ST 15179/22",
                      "Council of the EU – ST 15179/1/22 REV 1", "Council of the EU – CM 5842/22",
                      "Council of the EU – CM 5860/22"]  # fmt: skip
    # ST 15179/22 of 28 November 2022, point 2, quoted as written (the note said "only", and dated it 9 December)
    assert "on 28 November 2022, that “In accordance with Article 312(2)" in mff["outcome_note"]
    assert "may adopt the Regulation acting unanimously and after obtaining the consent" in mff["outcome_note"]
    ev = council_vote_event(mff)
    assert ev["title"] == "Council did not adopt the act" and "Hungary's vote against" in ev["detail"]
    assert [d["label"] for d in ev["docs"]] == labels and all(d["url"].startswith("https://") for d in ev["docs"])
    # a correction that lists no text it was checked against is not applied
    (tmp_path / "council_votes.yaml").write_text(
        "corrections:\n"
        "  - {vote: ST-9781-2024, celex: 32024L1499, legal_basis: TFEU Art. 19(1), citation: x}\n",
        encoding="utf-8",
    )
    assert _built_council(["ST-9781-2024"], ["2022-0401"], tmp_path).council_records["ST-9781-2024"]["voting_rule"] == "qmv"  # type: ignore[attr-defined]


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
    # "Adoption of the legislative act" on a budget note is left out: there the Council's vote does not by itself
    # adopt the budget, which Parliament and the Council establish together (Art. 314(1) and (9) TFEU)
    assert cv["ST-14735-2024"].stage.endswith("; Adoption of the legislative act")
    assert label["ST-14735-2024"].endswith("for 2025 – Non-approval of the European Parliament's amendment(s)")
    assert label["ST-9781-2024"].startswith("Council Directive on standards for equality bodies")


def test_featured_card_names_amending_acts_the_timeline_cannot_date():
    # EUDR (2021/0366(COD)): EUR-Lex lists Delegated Regulation (EU) 2026/2102 as amending Regulation (EU) 2023/1115,
    # but it is not in our EUR-Lex data; the card's latest step (23 December 2025) is older than it
    a = acts("32023R1115", "32024R3234", "32025R2650")
    me = SimpleNamespace(dossier_acts={"2021-0366": [a["32023R1115"]]}, act=a, checked_act_types={},
                         latest_event=lambda pid: {"date": "2025-12-23"})  # fmt: skip
    me.celex_label = lambda c: Builder.celex_label(me, c)  # type: ignore[arg-type]
    note = Builder.undated_amendments_note(me, "2021-0366")  # type: ignore[arg-type]
    assert note == (
        "EUR-Lex also lists Regulation 2026/2102 as amending this act. That act is not in our data, so its publication "
        "is not shown and the step above may not be the latest."
    )
    # its type as the text checked for data/curated/act_dates.yaml gives it ("Delegated Regulation (EU) 2026/2102,
    # Annex"; Cellar: "Commission Delegated Regulation (EU) 2026/2102 of 13 July 2026 amending Regulation (EU)
    # 2023/1115"), as in the related files, where it read "Regulation 2026/2102" next to the legislative acts
    me.checked_act_types = {"32026R2102": "Delegated Regulation"}
    assert note.replace("Regulation 2026", "Delegated Regulation 2026") == Builder.undated_amendments_note(me, "2021-0366")  # type: ignore[arg-type]
    # an amending act of a year before the latest step predates it: no note
    me.latest_event = lambda pid: {"date": "2027-01-04"}
    assert Builder.undated_amendments_note(me, "2021-0366") is None  # type: ignore[arg-type]
    me.latest_event = lambda pid: {"date": "2025-12-23"}
    me.act = {**a, "32026R2102": a["32025R2650"]}
    assert Builder.undated_amendments_note(me, "2021-0366") is None  # type: ignore[arg-type]


def test_an_act_known_only_by_its_celex_id_takes_its_type_from_the_checked_text():
    # data/curated/act_dates.yaml (EUDR) cites "Delegated Regulation (EU) 2026/2102, Annex", celex 32026R2102; the
    # Batteries Regulation's Commission Delegated Regulation (EU) 2026/1770 is named by no checked text
    from pipeline.build import checked_act_types, load_act_dates

    kinds = checked_act_types(load_act_dates())
    assert kinds["32026R2102"] == "Delegated Regulation"
    assert all(re.fullmatch(r"(?:(?:Implementing|Delegated) )?(?:Regulation|Directive|Decision)", k) for k in kinds.values())
    # a label whose number is not the CELEX id's is not used
    assert checked_act_types({"x": {"sources": [{"label": "Delegated Regulation (EU) 2026/2103", "celex": "32026R2102"}]}}) == {}
    me = SimpleNamespace(checked_act_types=kinds)
    assert Builder.celex_label(me, "32026R2102") == "Delegated Regulation 2026/2102"  # type: ignore[arg-type]
    assert Builder.celex_label(me, "32026R1770") == "Regulation 2026/1770"  # type: ignore[arg-type]
    assert Builder.celex_label(me, "32013R1303") is None  # type: ignore[arg-type]


# ------------------------------------------------------------------- Parliament's decisions in the timeline
def test_steps_of_one_day_are_kept_apart_unless_they_record_the_same_step():
    # 2025/0545(COD): the EP API records 10 committee opinions, FEMM's of 14 July 2026 (FEMM-AD-786992) on the day of
    # AGRI's, REGI's of 1 September on the day of ITRE's and TRAN's of 2 September on the day of EMPL's
    me = SimpleNamespace(indexed_vote_ids=set(), council_of={}, today="2026-10-23")
    p = procs("2025-0545")["2025-0545"]
    opinions = [(e["date"], e["detail"]) for e in Builder.timeline(me, p, [], []) if e["kind"] == "committee_opinion"]  # type: ignore[arg-type]
    assert len(opinions) == 10
    assert {("2026-07-14", "Committee: AGRI"), ("2026-07-14", "Committee: FEMM"), ("2026-09-01", "Committee: REGI"),
            ("2026-09-02", "Committee: TRAN")} <= set(opinions)  # fmt: skip
    # 2016/0131(COD), 7 Oct 2021: EP items 3 "European Union Agency for Asylum ***I (debate)" and 5 "(continuation of
    # debate)" are one debate: one step, with the verbatim report and minutes of both items
    p = procs("2016-0131")["2016-0131"]
    day = [e for e in Builder.timeline(me, p, [], []) if e["date"] == "2021-10-07" and e["kind"] == "plenary_debate"]  # type: ignore[arg-type]
    assert len(day) == 1
    assert {"CRE-9-2021-10-07-ITM-003", "CRE-9-2021-10-07-ITM-005", "A-8-2016-0392"} <= {d["id"] for d in day[0]["docs"]}


def test_a_joint_debate_names_the_other_files_and_keeps_this_files_documents():
    # EP item MTG-PL-2026-03-25-PVCRE-ITM-15, "Deposit protection and early intervention measures (joint debate)",
    # cites A10-0067/2026 (2023/0111(COD)), A10-0065/2026 (2023/0115(COD)) and A10-0066/2026 (2023/0112(COD)), with
    # their registered texts; OEIL's 2023/0112(COD) shows "Debate in Parliament" with none of the others
    ps = procs("2023-0111", "2023-0112", "2023-0115")
    me = SimpleNamespace(indexed_vote_ids=set(), council_of={}, today="2026-10-23", procedures=list(ps.values()), proc=ps,
                         curated_of={}, adopted_title=lambda p: None)  # fmt: skip
    me.dossier_title = lambda p: Builder.dossier_title(me, p)  # type: ignore[arg-type]
    Builder.index_file_documents(me)  # type: ignore[arg-type]
    tl = Builder.joint_debates(me, ps["2023-0112"], Builder.timeline(me, ps["2023-0112"], [], []))  # type: ignore[arg-type]
    step = next(e for e in tl if e["id"] == "MTG-PL-2026-03-25-PVCRE-ITM-15")
    assert step["title"] == "Joint debate in Parliament"
    assert [d["id"] for d in step["docs"]] == ["A-10-2026-0066", "CRE-10-2026-03-25-ITM-015", "PV-10-2026-03-25-ITM-015"]
    assert [(j["id"], j["report"]["label"]) for j in step["joint_with"]] == [
        ("2023-0111", "A10-0067/2026"), ("2023-0115", "A10-0065/2026")]  # fmt: skip
    # a debate of this file alone is left as it is (2016/0131(COD), 7 Oct 2021: its report A8-0392/2016 and C8-0174/2016)
    p = procs("2016-0131")["2016-0131"]
    me.procedures, me.proc = [*ps.values(), p], {**ps, p.id: p}
    Builder.index_file_documents(me)  # type: ignore[arg-type]
    day = [e for e in Builder.joint_debates(me, p, Builder.timeline(me, p, [], [])) if e["date"] == "2021-10-07"]  # type: ignore[arg-type]
    assert [(e["title"], "joint_with" in e) for e in day if e["kind"] == "plenary_debate"] == [("Debate in Parliament", False)]
    assert "C-8-2016-0174" in {d["id"] for e in day for d in e["docs"]}


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
    # its amendments decided it, not the rejected motions to reject the Council's position (listed on their own)
    assert tl["2026-07-09"]["vote_id"] is None
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


def _steps(pid: str, *vote_ids: str) -> dict[str, dict]:
    """Timeline steps of a file by event id, built with the given votes all listed."""
    p, v = procs(pid)[pid], votes(*vote_ids)
    me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-22")
    return {e["id"]: e for e in Builder.timeline(me, p, [], list(v.values()))}  # type: ignore[arg-type]


def test_mandate_vote_links_the_vote_on_the_text_not_the_referral():
    # 2021/0068(COD): vote 130712 on 28 Apr 2021 (amended proposal, 540-119-31), then 130713 "… C9-0104/2021 - Renvoi
    # (article 59, paragraphe 4 du règlement)" 569-95-26, a procedural vote that is not listed; procedure events of 29
    # Apr 2021 "Parliament voted amendments to the proposal" (PLENARY_AMEND) and "Parliament sent the file back to
    # committee to negotiate with the Council"; the decision of 8 Jun 2021 is 132421. The rejected motion to reject
    # the proposal 130538 (86-591-16) of 28 Apr decides no step.
    tl = _steps("2021-0068", "130712", "130538", "132421")
    assert tl["MTG-PL-2021-04-28-PVCRE-ITM-13"]["vote_id"] == "130712"
    assert tl["2021-0068-DEC-DCPL-2021-04-29"]["vote_id"] == "130712"
    assert "its procedure record dates the decision 29 April 2021" in tl["2021-0068-DEC-DCPL-2021-04-29"]["detail"]
    assert tl["2021-0068-DEC-REFBAK-2021-04-29"]["vote_id"] is None
    assert tl["2021-0068-DEC-DCPL-2021-06-08"]["vote_id"] == "132421"
    # the twin file 2021/0071(COD) the same way (130714, referral 130715)
    tl = _steps("2021-0071", "130714", "132423")
    assert [tl[k]["vote_id"] for k in ("MTG-PL-2021-04-28-PVCRE-ITM-13", "2021-0071-DEC-DCPL-2021-04-29",
                                        "2021-0071-DEC-REFBAK-2021-04-29")] == ["130714", "130714", None]  # fmt: skip
    # 2021/0197(COD), 8 Jun 2022: the mandate vote 144009 and the rejected motion to reject the proposal 144352
    tl = _steps("2021-0197", "144009", "144352")
    assert (tl["2021-0197-DEC-DCPL-2022-06-08"]["vote_id"], tl["2021-0197-DEC-REFBAK-2022-06-08"]["vote_id"]) == (
        "144009", None
    )  # fmt: skip
    # 2021/0008(COD): mandate vote 135241 dated 15 Sep 2021 (then 135242 "Referral (Rule 59(4))"), decision on the
    # amendments and referral recorded on 16 Sep 2021
    tl = _steps("2021-0008", "135241")
    assert (tl["2021-0008-DEC-DCPL-2021-09-16"]["vote_id"], tl["2021-0008-DEC-REFBAK-2021-09-16"]["vote_id"]) == (
        "135241", None
    )  # fmt: skip


def test_mandate_vote_link_is_on_a_milestone_shown_by_default():
    # 2021/0106(COD), AI Act: 14 Jun 2023, "Parliament voted amendments to the proposal" (2021-0106-DEC-DCPL-
    # 2023-06-14) links mandate vote 156022 (499-28-93) and is a key step, beside the referral back
    tl = _steps("2021-0106", "156022", "166051")
    dcpl, ref = tl["2021-0106-DEC-DCPL-2023-06-14"], tl["2021-0106-DEC-REFBAK-2023-06-14"]
    assert (dcpl["vote_id"], dcpl["key"], ref["vote_id"], ref["key"]) == ("156022", True, None, True)
    # 2026/0325(COD): no procedure event yet for the vote of 22 Oct 2026; the step built from mandate vote 199592
    # ("C10-0258/2026 – Commission proposal", 341-225-6) links it
    p, v = procs("2026-0325")["2026-0325"], votes("199592", "199567")
    me = SimpleNamespace(notices_by_ref={}, acts_of={}, votes_of={"2026-0325": list(v.values())}, today="2026-10-23",
                         procedure_event=Builder.procedure_event, checked_council_date=lambda p: None,
                         indexed_vote_ids=set(v), council_of={})  # fmt: skip
    p = Builder.with_recorded_events(me, p)  # type: ignore[arg-type]
    tl = {e["id"]: e for e in Builder.timeline(me, p, [], list(v.values()))}  # type: ignore[arg-type]
    assert tl["vote-199592-negotiation_mandate"]["vote_id"] == "199592"
    # a record of the sitting ("Vote in Parliament") linking the mandate vote stays a detail
    tl = _steps("2021-0068", "130712", "130538", "132421")
    assert tl["MTG-PL-2021-04-28-PVCRE-ITM-13"]["key"] is False
    assert tl["2021-0068-DEC-DCPL-2021-04-29"]["key"] is True


def test_rejected_motion_to_reject_decides_no_other_step():
    # 2021/0206(COD), 8 Jun 2022: 144420 "Social Climate Fund – … – Proposal for rejection" rejected 91-512-27, then
    # committee amendments adopted (PV-9-2022-06-08-VOT); the vote on the text came on 22 Jun 2022 (145868)
    tl = _steps("2021-0206", "144420", "145868")
    assert tl["2021-0206-DEC-DCPL-2022-06-08"]["vote_id"] is None
    assert tl["2021-0206-DEC-DCPL-2022-06-22"]["vote_id"] == "145868"


def test_second_reading_amendments_are_named_in_the_decision():
    # 2025/0429(COD), 9 Jul 2026, PLENARY_AMEND_COUNCIL_POSITION: EP API DEC-195778 "C10-0178/2026 – Article 1, after
    # § 2 – Am 30" ADOPTED 369-236-6 and DEC-195787 "… – Article 3, § 1, point a – Am 26 CP3= 31 CP3= 6= 21=" ADOPTED
    # 362-235-5 (at least 360 of 719 Members needed); both motions to reject the Council's position rejected
    p = procs("2025-0429")["2025-0429"]
    v = votes("195775", "195807", "195778", "195787")
    me = SimpleNamespace(indexed_vote_ids={"195775", "195807"}, council_of={}, today="2026-10-22")
    tl = Builder.timeline(me, p, [], list(v.values()))  # type: ignore[arg-type]
    e = next(e for e in tl if e["date"] == "2026-07-09" and e["kind"] == "ep_position")
    assert e["vote_id"] is None
    assert e["detail"] == (
        "Parliament amended the Council's position in 2 votes, each adopted with the votes of a majority of its "
        "component Members: “Article 1, after § 2 – Am 30” (369 for) and “Article 3, § 1, point a – Am 26 CP3= 31 CP3= "
        "6= 21=” (362 for). Votes on amendments are not listed on this site."
    )
    # 2013/0072(COD), 21 Jan 2026: no listed vote that day; EP API DEC-183557 "A10-0001/2026 – Andrey Novakov –
    # Amendments by the committee responsible – put to the vote collectively – Am 1-243" ADOPTED 632-15-9
    p, v = procs("2013-0072")["2013-0072"], votes("183557", "195007")
    me = SimpleNamespace(indexed_vote_ids={"195007"}, council_of={}, today="2026-10-22")
    tl = Builder.timeline(me, p, [], list(v.values()))  # type: ignore[arg-type]
    e = next(e for e in tl if e["date"] == "2026-01-21" and e["kind"] == "ep_position")
    assert e["vote_id"] is None
    assert e["detail"] == (
        "Parliament amended the Council's position in one vote, adopted with the votes of a majority of its component "
        "Members: “Andrey Novakov – Amendments by the committee responsible – put to the vote collectively – Am 1-243” "
        "(632 for). Votes on amendments are not listed on this site."
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


def test_consent_named_by_the_label_of_a_vote_without_a_symbol():
    # 13 May 2020 and 11 Nov 2020, French-only minutes: subjects without "***"; labels "A9-0088/202 - Clara Aguilera -
    # Consent procedure" (2019/0210(NLE)) and "A9-0199/2020 - Iuliu Winkler - Consent procedure" (2020/0089(NLE)).
    # 124727 "A9-0182/2020 - … - Consent procedure" is linked to 2019/0226M(NLE), a resolution procedure: no role
    v = votes("113700", "124729", "124727", "152545")
    assert {k: final_role(x) for k, x in v.items()} == {
        "113700": "consent", "124729": "consent", "124727": None, "152545": "consultation",
    }  # fmt: skip


def test_discharge_votes_say_what_the_outcome_decided():
    # 4 May 2022, minutes PV-9-2022-05-04-VOT: Court of Auditors (142787, 291-333-8, "-") and Council (142821,
    # 555-60-13, "+") under "Proposal for a decision to postpone the discharge"; Court of Justice (142809) under
    # "Decision on discharge". 18 Oct 2022, Frontex 2020 (149084): "Decision to refuse discharge" (Decision (EU)
    # 2023/325 "Refuses to grant … discharge"). Rules of Procedure, 9th term, Annex V, Article 5(1)(b): "If a proposal
    # to postpone discharge fails to secure a majority, discharge shall be deemed to have been granted"
    v = votes("142787", "142821", "142809", "149084", "175931", "191886")
    assert {k: x.kind_detail for k, x in v.items()} == {
        "142787": "postpone_discharge", "142821": "postpone_discharge", "142809": None, "149084": "refuse_discharge",
        "175931": None, "191886": "postpone_discharge",
    }  # fmt: skip
    assert discharge_note(v["142787"]) == (
        "Parliament rejected the proposal to postpone discharge. Under its Rules of Procedure, discharge is therefore "
        "deemed to have been granted (Annex V, Article 5(1)(b))."
    )
    assert discharge_note(v["142821"]) == "Parliament adopted the proposal and so postponed its decision on discharge."
    assert discharge_note(v["149084"]) == "Parliament adopted the proposal and so refused discharge."
    assert discharge_note(v["142809"]) == DISCHARGE_NOTES["adopted"]
    # the Rules of a later term are not checked: a rejection is stated as such only
    rejected = v["191886"].model_copy(update={"outcome": "rejected"})
    assert discharge_note(rejected) == "Parliament rejected the proposal to postpone discharge."
    assert final_role(v["191886"]) == "discharge"
    assert VOTE_DETAIL_LABELS["postpone_discharge"] == "Vote on a proposal to postpone discharge"
    title, _ = Builder.vote_display_title(None, v["142787"], None)  # type: ignore[arg-type]
    assert title == "Discharge 2020: EU general budget - Court of Auditors — vote on a proposal to postpone discharge"


def test_misprinted_label_vote_on_its_file():
    # 28 Apr 2021, bluefin tuna 130719 (643-11-47): linked to 2019/0272(COD) through its French label and minutes
    # (see test_ep_votes); OEIL 2019/0272(COD): "28/04/2021 Decision by Parliament, 1st reading T9-0142/2021"
    v = votes("130719")
    assert v["130719"].procedure_refs == ["2019/0272(COD)"]
    tl = _steps("2019-0272", "130719")
    assert next(e for e in tl.values() if e["date"] == "2021-04-28" and e["kind"] == "ep_position")["vote_id"] == "130719"


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


def test_vote_titles_entry_keeps_only_what_the_mep_and_group_tables_show():
    # 112160, 30 Jan 2020, "Gender pay gap", told apart from 112117 by its motion number: the vote tables of the MEP
    # and group pages show its date, title, the line "kind of vote · distinction" and (MEP page) the result
    v = votes("112160")["112160"]
    assert (v.date, v.outcome, v.n_for, v.n_against, v.n_abstain) == ("2020-01-30", "adopted", 493, 82, 79)
    summary = {
        "id": v.id, "date": v.date, "title": v.title, "kind": v.kind, "kind_detail": None, "final_role": None,
        "display_title": "Gender pay gap — vote on the resolution (motion B9-0073/2020)",
        "distinction": "motion B9-0073/2020", "kind_label": "Vote on a resolution", "outcome": v.outcome,
        "outcome_basis": "published", "outcome_note": None, "for": v.n_for, "against": v.n_against,
        "abstain": v.n_abstain, "dossier_id": None, "dossier_ref": None, "procedure_ref": None, "subject": None,
        "topics": [], "margin": None, "has_ballots": True, "source": v.source.model_dump(),
    }  # fmt: skip
    entry = _vote_index_entry(summary)
    assert _vote_title_entry(entry) == {
        "id": "112160", "date": "2020-01-30", "outcome": "adopted", "kind_label": "Vote on a resolution",
        "display_title": "Gender pay gap — vote on the resolution (motion B9-0073/2020)",
        "distinction": "motion B9-0073/2020",
    }  # fmt: skip
    # French passages of Parliament's own label keep their runs; a procedure reference is kept when there is one
    parts = [[None, "Gender pay gap — "], ["fr", "ensemble du texte"]]
    entry |= {"display_title": "Gender pay gap — ensemble du texte", "display_title_parts": parts, "procedure_ref": "2019/2870(RSP)"}
    got = _vote_title_entry(entry)
    assert got["display_title_parts"] == parts and got["procedure_ref"] == "2019/2870(RSP)" and "title" not in got
    # a vote with no display title is shown by Parliament's label (VoteTitle's fallback): the only case in which
    # the label is written
    assert _vote_title_entry(entry | {"display_title": ""})["title"] == entry["title"]


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
    # 199517, 22 Oct 2026: label as first published, "RC-B10-0476/2026 - Proposition de résolution (ensemble du texte)",
    # without an English subject (the EP API gave "RC-B10-0476/2026 – Motion for a resolution (as a whole)" and the
    # vote item's English title on 23 Oct 2026)
    first = {"title": "RC-B10-0476/2026 - Proposition de résolution (ensemble du texte)", "subject": None}
    v = votes("199517")["199517"].model_copy(update=first)
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


def test_snapshot_rapporteur_committees_are_among_the_files_committees():
    # re-derived with ep_procedures.oeil_rapporteur_committees over the cached EP API and OEIL answers:
    # 2021/0240(COD) "org/null" -> CONT, 2025/0045(COD) DROI -> AFET, 2023/0187(CNS) FISC + ECON -> ECON
    p = procs("2021-0240", "2025-0045", "2023-0187")
    by = {(pid, r.mep_id): r.committee for pid, x in p.items() for r in x.rapporteurs if r.role != "shadow"}
    assert by[("2021-0240", "96899")] == "CONT" and by[("2025-0045", "204332")] == "AFET"
    assert [(r.committee, r.date) for r in p["2023-0187"].rapporteurs if r.role == "rapporteur"] == [("ECON", "2024-09-12")]
    for x in p.values():
        codes = {c.code for c in x.committees}
        assert all(r.committee in codes for r in x.rapporteurs if r.role in ("rapporteur", "opinion_rapporteur")), x.id


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
    assert len(cur) == 37 and cur["2015/0283(COD)"]["date"] == "2017-05-29"
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


def test_second_vote_of_the_same_meeting_is_dated_by_its_sheet_and_the_act():
    # Schengen Borders Code: ST 10264/24, the same 4026th meeting of 23-24 May 2024 as ST 10263/24; its sheet reads
    # "Item: 2021/0428(COD) (Document: 40/24)" and "Sitting date: 24/05/2024", and Regulation (EU) 2024/1717 "Position
    # of the European Parliament of 24 April 2024 ... and decision of the Council of 24 May 2024"
    from pipeline.build import council_vote_event

    cv = council("ST-10264-2024")["ST-10264-2024"]
    p, a = procs("2021-0428")["2021-0428"], acts("32024R1717")["32024R1717"]
    me = stand_in(acts_of={"2021-0428": [a]}, act={a.celex: a})
    assert cv.date == "2024-05-23"
    when, note = Builder.council_vote_date(me, cv, p, "act")  # type: ignore[arg-type]
    assert when == "2024-05-24" and note and "Sitting date: 24/05/2024" in note and "Regulation (EU) 2024/1717" in note
    rec = council_rec(cv) | {"date": when}
    me = stand_in(acts_of={"2021-0428": [a]}, act={a.celex: a}, council_of={"2021-0428": [rec]})
    q = Builder.with_recorded_events(me, p)  # type: ignore[arg-type]
    assert Builder.adoption_dates(me, q, [a])[0] == "2024-05-24"  # type: ignore[arg-type]
    tl = Builder.timeline(me, q, [a], [])  # type: ignore[arg-type]
    assert [(x["date"], x["id"]) for x in tl if x["kind"] == "council_adoption"] == [("2024-05-24", "council-ST-10264-2024")]
    assert council_vote_event(rec)["date"] == "2024-05-24"


def test_oeil_steps_of_one_council_decision_are_one_step():
    # 2014/0174(COD): OEIL lists "Act adopted by Council after Parliament's 1st reading" on 13 July and 6 October 2015;
    # Regulation (EU) 2015/1843 gives one decision: "Position of the European Parliament of 7 July 2015 ... and decision
    # of the Council of 18 September 2015"
    from pipeline.validate import dossier_contradictions

    p, a = procs("2014-0174")["2014-0174"], acts("32015R1843")["32015R1843"]
    assert sorted(e.date for e in p.events if e.kind.value == "council_adoption") == ["2015-07-13", "2015-10-06"]
    me = stand_in(acts_of={"2014-0174": [a]}, act={a.celex: a})
    q = Builder.with_recorded_events(me, p)  # type: ignore[arg-type]
    steps = [e for e in q.events if e.kind.value == "council_adoption"]
    assert [e.date for e in steps] == ["2015-09-18"]
    assert steps[0].detail and steps[0].detail.endswith("The Legislative Observatory gives 13 July 2015 and 6 October 2015.")
    tl = Builder.timeline(me, q, [a], [])  # type: ignore[arg-type]
    assert [x["date"] for x in tl if x["kind"] == "council_adoption"] == ["2015-09-18"]
    assert Builder.adoption_dates(me, q, [a])[0] == "2015-09-18"  # type: ignore[arg-type]
    assert dossier_contradictions({"type": "COD", "celex": [a.celex], "timeline": tl}) == []
    # without the act's date both OEIL steps are shown, which the validator reports
    before = Builder.timeline(stand_in(), Builder.with_recorded_events(stand_in(), p), [], [])  # type: ignore[arg-type]
    assert dossier_contradictions({"type": "COD", "celex": [a.celex], "timeline": before}) == [
        "Council adoption steps on 2 days: 2015-07-13, 2015-10-06"
    ]


def test_council_adoption_recorded_before_a_second_reading_is_not_the_adoption():
    # 2018/0202(COD) (EGF): OEIL "Act adopted by Council after Parliament's 1st reading" on 21 April 2021, the day of
    # "Council position published"; Parliament approved the Council's position at second reading on 27 April 2021.
    # Regulation (EU) 2021/691: "position of the Council at first reading of 19 April 2021 ... Position of the
    # European Parliament of 27 April 2021"
    from pipeline.validate import dossier_contradictions

    p = procs("2018-0202")["2018-0202"]
    me = stand_in()
    q = Builder.with_recorded_events(me, p)  # type: ignore[arg-type]
    day = [e for e in q.events if e.date == "2021-04-21" and e.raw_type == "oeil:Act adopted by Council after Parliament's 1st reading"]
    assert [(e.kind.value, e.institution) for e in day] == [("other", "OEIL")]
    assert day[0].title == "Recorded by the Legislative Observatory: “Act adopted by Council after Parliament's 1st reading”"
    assert day[0].detail and "at second reading on 27 April 2021" in day[0].detail
    tl = Builder.timeline(me, q, [], [])  # type: ignore[arg-type]
    assert not [x for x in tl if x["kind"] == "council_adoption" and x["date"] < "2021-04-27"]
    assert [x["key"] for x in tl if x["id"] == day[0].id] == [False]
    assert Builder.adoption_dates(me, q, [])[0] == "2021-04-27"  # type: ignore[arg-type]
    assert dossier_contradictions({"type": "COD", "celex": ["32021R0691"], "timeline": tl}) == []
    # the step as it was shown is caught by the validator
    shown = [*tl, {"date": "2021-04-21", "kind": "council_adoption", "title": "Council adopted the act after Parliament's first reading"}]
    assert dossier_contradictions({"type": "COD", "celex": ["32021R0691"], "timeline": shown}) == [
        "Council adoption step of 2021-04-21, before Parliament's second reading of 2021-04-27"
    ]
    # the same OEIL event without a later second reading is the adoption (2014/0174(COD))
    q2 = Builder.with_recorded_events(me, procs("2014-0174")["2014-0174"])  # type: ignore[arg-type]
    assert [e.title for e in q2.events if e.kind.value == "council_adoption"] == [
        "Council adopted the act after Parliament's first reading"
    ] * 2


def test_consent_step_states_the_outcome_the_status_gives():
    # 2025/0313(APP): decision MTG-PL-2026-10-06-DEC-197472, ADOPTED 462-121-75; the status says "Parliament gave its
    # consent", and so does the timeline step of that day
    from datetime import date

    from pipeline.analysis.status import classify

    p, v = procs("2025-0313")["2025-0313"], votes("197472")
    me = stand_in(votes_of={"2025-0313": list(v.values())}, indexed_vote_ids=set(v))
    q = Builder.with_recorded_events(me, p)  # type: ignore[arg-type]
    tl = Builder.timeline(me, q, [], list(v.values()))  # type: ignore[arg-type]
    step = [(x["title"], x["vote_id"]) for x in tl if x["date"] == "2026-10-06" and x["kind"] == "ep_position"]
    assert step == [("Parliament gave its consent", "197472")]
    assert classify(q, [], [], date(2026, 10, 23), votes=list(v.values())).label == "Parliament gave its consent"
    # without an officially recorded outcome the step only says that Parliament voted
    tl = Builder.timeline(stand_in(), Builder.with_recorded_events(stand_in(), p), [], [])  # type: ignore[arg-type]
    assert [x["title"] for x in tl if x["date"] == "2026-10-06" and x["kind"] == "ep_position"] == [
        "Parliament voted on consent"
    ]


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
    # Rules of Procedure, Art. 3(3): "The Council shall decide in accordance with the voting rule applicable for
    # the adoption of the act or position concerned" (hence the act's qualified majority, TEU Art. 16(4))
    assert "in accordance with the voting rule applicable for the adoption of the act or position concerned" in note
    # the card and the country rows name the derogation, not "Adoption of the legislative act" listed first
    from pipeline.build import COUNCIL_DEROGATION_ITEM, council_vote_items, council_vote_label

    d = cv["ST-8160-2020"]
    assert d.stage.startswith("Adoption of the legislative act; Derogation")
    assert council_vote_items(d.title, on, d.stage) == COUNCIL_DEROGATION_ITEM
    assert council_vote_label(d.title, on, d.stage).endswith(f"[2020/0067(COD)] – {COUNCIL_DEROGATION_ITEM}")
    assert council_vote_items(d.title, "act", cv["ST-8159-2020"].stage) is None
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
    # without the act in our data: the EP's record on its date, which can be a week early (here before the Council's
    # adoption), credited to both Presidents as every ordinary-procedure act is signed (Art. 297(1) TFEU: "shall be
    # signed by the President of the European Parliament and by the President of the Council"), with that said
    tl = Builder.timeline(stand_in(), p, [], [])  # type: ignore[arg-type]
    assert sig(tl) == [("2018-04-11", "Final act signed", "EP and Council")]
    assert next(x["detail"] for x in tl if x["kind"] == "signature") == (
        "Signed by the Presidents of Parliament and of the Council (Article 297(1) TFEU); date as the European "
        "Parliament's procedure record gives it.")  # fmt: skip
    # the newest files, not yet in EUR-Lex (2025/0106(COD), 21 Oct 2026: EP API 2025-0106-SIGN-2026-10-21); a
    # consultation's act is the Council's, signed by its President only, and keeps the EP's record as it is
    q = procs("2025-0106")["2025-0106"]
    assert sig(Builder.timeline(stand_in(), q, [], [])) == [("2026-10-21", "Final act signed", "EP and Council")]  # type: ignore[arg-type]
    cns = p.model_copy(update={"type": "CNS"})
    assert sig(Builder.timeline(stand_in(), cns, [], [])) == [("2018-04-11", "Final act signed", "EP")]  # type: ignore[arg-type]
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


def test_trilogue_tabling_and_second_reading_steps_follow_the_decision_they_depend_on():
    # 2025/0132(COD), 17 Dec 2025: the first trilogue after Parliament confirmed the mandate (vote 182896);
    # 2025/0359(COD), 26 Mar 2026: after the referral back to committee to negotiate; 2024/0071(COD), 16 Jun 2025:
    # the agreed text tabled for the plenary after the committee approved it; 2018/0136(COD), 14 Dec 2020: the
    # Council's first-reading position (ST 14020/20, written procedure), then the second-reading referral and the
    # committee's recommendation, adopted and tabled
    p = procs("2025-0132", "2025-0359", "2024-0071", "2018-0136")
    cv = council("ST-14020-2020")["ST-14020-2020"]
    me = stand_in(council_of={"2018-0136": [council_rec(cv)]})

    def day(pid: str, d: str) -> list[str]:
        return [x["title"] for x in Builder.timeline(me, p[pid], [], []) if x["date"] == d]  # type: ignore[arg-type]

    tri = "Negotiation meeting with the Council (trilogue)"
    assert day("2025-0132", "2025-12-17") == ["Parliament confirmed the committee's mandate to negotiate with the Council", tri]
    assert day("2025-0359", "2026-03-26")[-2:] == [
        "Parliament sent the file back to committee to negotiate with the Council", tri
    ]
    assert day("2024-0071", "2025-06-16") == [
        "Parliament committee approved the provisional agreement with the Council", "Amendments tabled for the plenary"
    ]
    assert day("2018-0136", "2020-12-14") == [
        "Council adopted its position at first reading (written procedure)",
        "Announced in Parliament and referred to committee (second reading)",
        "Parliament committee adopted its recommendation for second reading",
        "Committee recommendation for second reading tabled for the plenary",  # OEIL's key event, A9-0262/2020
    ]


def test_vote_records_of_a_sitting_list_only_the_files_documents():
    # re-derived snapshot records (pipeline.sources.ep_procedures.build_events): 2020/0112(APP) keeps only its own
    # report A9-0227/2021; 2019/0900(APP) no longer lists A9-0170/2021 (Black Sea fisheries, 2019/2159(INI))
    p = procs("2020-0112", "2019-0900", "2020-0067", "2016-0132")
    assert [d.id for d in p["2020-0112"].documents if d.kind == "report"] == ["A-9-2021-0227"]
    # a joint debate's reports (the asylum files debated together) are not the file's key documents
    assert [d.id for d in p["2016-0132"].documents if d.kind == "report"] == ["A-8-2017-0212"]
    assert "A-9-2021-0170" not in {d.id for e in p["2019-0900"].events for d in e.docs}
    assert max(len(e.docs) for e in p["2020-0067"].events) < 10
    # the file's own registered text, which only the sitting's vote items of several files list, is kept when an
    # EP vote on the file alone names it: 2020/0127(COD), vote 117279 "C9-0186/2020 - Commission Proposal";
    # 2020/0378(COD), vote 128850 "C9-0430/2021" (sic) for C-9-2020-0430
    q = procs("2020-0127", "2020-0378", "2020-0362")
    assert "C-9-2020-0186" in {d.id for e in q["2020-0127"].events if e.id == "2020-0127-DEC-DCPL-2020-09-17" for d in e.docs}
    assert "C-9-2020-0430" in {d.id for e in q["2020-0378"].events for d in e.docs}
    assert "C-9-2021-0430" not in {d.id for e in q["2020-0378"].events for d in e.docs}
    # the day's urgent-procedure vote record (125802)
    assert "C-9-2020-0399" in {d.id for e in q["2020-0362"].events if e.id == "MTG-PL-2020-12-15-PVCRE-ITM-9" for d in e.docs}


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
    assert boat["exemption"]["named"] is None


def test_exemptions_are_quoted_whole_and_rows_state_their_condition():
    # Directive (EU) 2016/798, Art. 33(4), second subparagraph: "However, as soon as a public or private entity submits
    # an official application to build a railway line ... within 2 years of the receipt of the application."
    # Directive (EU) 2016/797, Art. 57(5) exempts Cyprus and Malta from the articles it lists only (Article 13, ...,
    # Article 54), with the same second subparagraph: their rows are not marked, and the page names them
    from pipeline.build import load_transposition_checks

    checks = load_transposition_checks()
    a = acts("32016L0797", "32016L0798", "32016L1629")
    me = _impl_builder(_measures("32016L0797", "32016L0798", "32016L1629"), checks)
    safety = Builder.implementation_table(me, a["32016L0798"])["exemption"]  # type: ignore[arg-type]
    interop = Builder.implementation_table(me, a["32016L0797"])  # type: ignore[arg-type]
    assert safety["provision"] == "Art. 33(4)" and safety["quote"].endswith("within 2 years of the receipt of the application.")
    ex = interop["exemption"]
    assert (ex["provision"], ex["countries"], ex["named"]) == ("Art. 57(5)", None, ["CY", "MT"])
    assert ex["quote"].endswith("within two years of receipt of the application.")
    assert not [c for c in interop["countries"] if c["status"] == "not_required"]
    # country pages: the provision and its condition next to "Not required by the directive"
    assert Builder.not_required_note(me, "32016L0798") == (  # type: ignore[arg-type]
        "Art. 33(4): for as long as no rail system is established within its territory (measures are due within two "
        "years of an official application to build a railway line)"
    )
    assert Builder.not_required_note(me, "32016L1629") == "Art. 40: the directive is not addressed to it"  # type: ignore[arg-type]
    assert Builder.not_required_note(me, "32016L0797") is None  # type: ignore[arg-type]


def test_next_step_after_the_deadline_states_the_directives_own_exceptions():
    # Directive (EU) 2016/798 binds Cyprus and Malta (Art. 36: "addressed to the Member States") but Art. 33(4) exempts
    # them while they have no rail system; Art. 33(2) and (2a) let Member States extend the period to 16 June 2020 and
    # 31 October 2020 (Directive (EU) 2020/700, recital 2: "Seventeen Member States have notified ... an extension")
    from datetime import date

    from pipeline.analysis.status import classify
    from pipeline.build import apply_transposition_checks, load_transposition_checks

    checks = load_transposition_checks()
    today = date(2026, 10, 23)
    ids = {"2013-0016": "32016L0798", "2013-0015": "32016L0797", "2016-0050": "32017L2397", "2021-0039": "32021L1233",
           "2013-0302": "32016L1629"}  # fmt: skip
    p, a = procs(*ids), acts(*ids.values())
    step = {pid: classify(p[pid], [apply_transposition_checks(a[c], checks.get(c))], [], today).next_step.text
            for pid, c in ids.items()}  # fmt: skip
    assert step["2013-0016"].startswith(
        "The transposition deadline (16 June 2019) has passed: the Member States bound by the directive were required to "
        "adopt national measures by then, except as its text provides. Member States that extended the transposition "
        "period by one year under Art. 33(2) had until 16 June 2020"
    )
    assert "Under Art. 33(4), the obligation to transpose and implement the directive does not apply to Cyprus and Malta" in (
        step["2013-0016"])  # fmt: skip
    assert "Under Art. 57(5), the obligation to transpose and implement the articles it lists" in step["2013-0015"]
    assert "Under Art. 39(4), a Member State is not obliged to transpose the directive" in step["2016-0050"]
    assert "the derogation in Article 39(4) of Directive (EU) 2017/2397 applies to it" in step["2021-0039"]
    # Directive (EU) 2016/1629 is not addressed to eleven Member States (Art. 40): they are not bound by it
    assert step["2013-0302"] == (
        "The transposition deadline (7 October 2018) has passed: the Member States bound by the directive were required "
        "to adopt national measures by then."
    )
    # the general deadline's timeline step says it too
    me = stand_in(today="2026-10-23")
    rail = apply_transposition_checks(a["32016L0798"], checks.get("32016L0798"))
    tl = Builder.timeline(me, p["2013-0016"], [rail], [])  # type: ignore[arg-type]
    dl = [x for x in tl if x["kind"] == "transposition_deadline"]
    assert [(x["date"], x["title"]) for x in dl] == [("2019-06-16", "Deadline for Member States to transpose the directive (passed)")]
    # the act by its number, not "Directive 32016L0798" (its CELEX id)
    assert dl[0]["detail"].startswith("Directive (EU) 2016/798. Exceptions in its text: Member States that extended")


def test_next_step_before_the_deadline_speaks_of_the_member_states_bound():
    # Directive (EU) 2024/2842 (2023/0393(COD)): Denmark and Ireland are "Not bound" in its table; the deadline,
    # 4 December 2026, is ahead
    from datetime import date

    from pipeline.analysis.status import classify
    from pipeline.build import apply_transposition_checks, load_transposition_checks

    p, a = procs("2023-0393")["2023-0393"], acts("32024L2842")["32024L2842"]
    text = classify(p, [apply_transposition_checks(a, load_transposition_checks().get(a.celex))], [], date(2026, 10, 23))
    assert text.next_step.text.startswith("The Member States bound by the directive must transpose it into national law by ")
    assert "EU countries" not in text.next_step.text


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
    # the date Cellar records for the repeal: Decision 2020/2053 "shall apply from 1 January 2021" (Art. 12)
    assert s.stage == "in_force" and (
        "partly repealed by Council Decision (EU, Euratom) 2020/2053 with effect from 1 January 2021." in s.explanation
    )
    assert [r.celex for r in s.named_acts] == ["32020D2053"]
    s = classify(p["2020-0374"], [a["32022R1925"]], [], date(2026, 10, 23), others=a)
    assert "EUR-Lex records that some provisions apply from that date." in s.explanation
    assert s.application.entry_into_force == "2022-11-01" and s.application.partial_on_entry_into_force
    assert "2022-11-01" not in s.application.application_dates


def test_no_longer_in_force_dates_from_the_repeal_cellar_records():
    # Cellar's start_of_validity on the repeal link (LegalAct.repeal_dates) counts where it is recorded.
    from datetime import date

    from pipeline.analysis.status import classify

    today = date(2026, 10, 23)
    a = acts("32014R0543", "32015R2219", "32014R0252", "32015R0754", "32014L0061", "32024R1309", "32014R0517",
             "32024R0573", "32017L0853", "32021L0555", "32015L0849", "32024L1640")  # fmt: skip
    p = procs("2013-0812", "2011-0445", "2013-0080", "2012-0305", "2015-0269", "2013-0025")

    def st(pid: str, celex: str):
        return classify(p[pid], [a[celex]], [], today, others=a)

    # Regulation 543/2014 (CEPOL): end of validity and repeal both 2016-07-01; Regulation (EU) 2015/2219, Art. 40(1):
    # Decision 2005/681/JHA, as amended by Regulation (EU) No 543/2014, "is hereby replaced ... with effect from
    # 1 July 2016" - not 2 July
    s = st("2013-0812", "32014R0543")
    assert (s.stage, s.since) == ("no_longer_in_force", "2016-07-01")
    assert s.explanation == (
        "The act was adopted and published. EUR-Lex gives 1 July 2016 as the end of its validity and records it as "
        "repealed by Regulation (EU) 2015/2219 with effect from 1 July 2016."
    )
    # Regulation 252/2014: repealed by the codification 2015/754 (Art. 11) on its entry into force, 8 June 2015
    # (Art. 12: twentieth day after publication in OJ L 123, 19.5.2015); Cellar: both dates 2015-06-08
    s = st("2011-0445", "32014R0252")
    assert s.since == "2015-06-08" and "repealed by Regulation (EU) 2015/754 with effect from 8 June 2015." in s.explanation
    assert "is a codification: the rules continue in it" in s.explanation
    # Directive 2014/61/EU, repealed in stages by Regulation (EU) 2024/1309: Art. 18(1) as corrected, "with effect
    # from 12 November 2025"; Art. 18(2) keeps provisions "in force until" 12 February and 12 May 2026, the dates
    # from which the replacing provisions apply (Art. 19(3)): no single day is asserted
    s = st("2013-0080", "32014L0061")
    assert (s.stage, s.since) == ("no_longer_in_force", None)
    assert s.explanation == (
        "The act was adopted and published. EUR-Lex records it as repealed by Regulation (EU) 2024/1309 with effect "
        "from 12 November 2025, except for some provisions, whose repeal it records with effect from later dates. "
        "EUR-Lex gives 12 May 2026 as the end of the act's validity."
    )
    # Regulation 517/2014 (F-gases): Regulation (EU) 2024/573, Art. 35(1) "is repealed", (2) Article 12 "shall
    # continue to apply until 31 December 2024"
    s = st("2012-0305", "32014R0517")
    assert s.since is None and "Regulation (EU) 2024/573 with effect from 11 March 2024, except for some" in s.explanation
    # the usual case: the repeal takes effect the day after the last day of validity (Directive (EU) 2021/555)
    s = st("2015-0269", "32017L0853")
    assert s.since == "2021-04-26" and "its validity ended on 25 April 2021." in s.explanation
    # a repeal still ahead: AMLD4, end of validity 9 July 2027
    s = st("2013-0025", "32015L0849")
    assert s.stage == "in_force" and "and that Directive (EU) 2024/1640 repeals it with effect from 10 July 2027." in (
        s.explanation
    )


def test_partial_application_on_entry_into_force_without_other_dates_says_so():
    # Regulation (EU) 2025/12 (API data, 2022/0424(COD)): EUR-Lex marks the entry into force as the date of some
    # provisions and records no other date; Art. 46: "It shall apply from the date two years from the date on which
    # the router starts operations, as determined by the Commission", with exceptions from the entry into force
    from datetime import date

    from pipeline.analysis.status import classify

    a = acts("32025R0012")
    s = classify(procs("2022-0424")["2022-0424"], [a["32025R0012"]], [], date(2026, 10, 23), others=a)
    assert s.stage == "in_force" and a["32025R0012"].other_application_dates == []
    # Cellar gives the general date (MA 1001-01-01 "V ART 46") and that of Art. 46(b) (MA/PART) as not recorded
    assert ("EUR-Lex records that some provisions apply from that date. EUR-Lex records no date from which the act in "
            "general applies (it refers to Art. 46), nor one from which some of its provisions apply (it refers to "
            "Art. 46(b)).") in s.explanation  # fmt: skip
    assert s.application.partial_on_entry_into_force and s.application.application_dates == []
    assert [(x.partial, x.articles) for x in s.application.application_unrecorded] == [
        (False, ["Art. 46"]), (True, ["Art. 46(b)"])]  # fmt: skip


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


def _classified(pid: str, today: str = "2026-10-23", **kw):
    """(status, procedure as the build gives it to classify) of a snapshot file, without acts or train files."""
    from datetime import date

    from pipeline.analysis.status import classify

    q = Builder.with_recorded_events(stand_in(**kw), procs(pid)[pid])  # type: ignore[arg-type]
    return classify(q, [], [], date.fromisoformat(today)), q


def test_parliaments_own_proposal_opens_the_electoral_law_files():
    # 2022/0902(APP): T9-0129/2022 of 3 May 2022, para. 38 "Adopts the annexed proposal and submits it to the Council"
    # (Art. 223(1) TFEU: the Council acts "after obtaining the consent of the European Parliament" on Parliament's
    # proposal); ST 9333/22: "PROPOSAL From: Roberta METSOLA, President of the European Parliament; date of receipt:
    # 19 May 2022; To: … President of the Council". No Council text was submitted to Parliament
    s, q = _classified("2022-0902")
    assert (s.stage, s.label, s.since) == ("proposed", "Parliament adopted its proposal", "2022-05-03")
    assert "no Council draft submitted to Parliament" in s.explanation
    assert s.next_step.institution == "Council" and s.next_step.text.startswith("The Council agrees on the text")
    assert Builder.proposal_date(q) == "2022-05-03"
    tl = Builder.timeline(stand_in(), q, [], [])  # type: ignore[arg-type]
    assert [(x["title"], x["institution"]) for x in tl if x["key"]] == [
        ("Parliament adopted its proposal for the act", "EP")]  # fmt: skip
    assert not any("Council text" in x["title"] for x in tl)
    # 2025/0900(APP): Parliament's proposal T10-0257/2025 of 13 November 2025 dates the file; the Council's draft
    # 06708/2026 of 17 March 2026 ("Having regard to the proposal from the European Parliament") is still its step
    s, q = _classified("2025-0900", "2026-03-20")
    assert Builder.proposal_date(q) == "2025-11-13"
    steps = [(e.date, e.kind.value, e.title, e.institution) for e in q.events if e.kind.value == "proposal"]
    assert steps == [("2025-11-13", "proposal", "Parliament adopted its proposal for the act", "EP"),
                     ("2026-03-17", "proposal", "Council text submitted to Parliament", "Council")]  # fmt: skip
    assert s.label == "Under examination in Parliament"


def test_referral_back_for_reconsideration_ends_the_mandate():
    # 2022/0135(COD), Kuwait/Qatar visas: committee decision of 1 Dec 2022 announced on 12 Dec 2022, and that day the
    # report was referred back (minutes PV-9-2022-12-12, item 5: "the President proposed the referral back to
    # committee under Rule 198 of the report … (A9-0288/2022). … The House agreed to the proposal"); OEIL "Matter
    # referred back to the committee responsible for reconsideration", then only "Resumption of business"
    s, q = _classified("2022-0135")
    assert (s.stage, s.label, s.since) == ("proposed", "Referred back to committee", "2022-12-12")
    assert "holds no mandate to negotiate" in s.explanation
    assert s.next_step.institution == "EP" and s.next_step.text.startswith("The committee reconsiders the file")
    tl = {x["id"]: x for x in Builder.timeline(stand_in(), q, [], [])}  # type: ignore[arg-type]
    assert tl["2022-0135-DEC-REFBAK-2022-12-12"]["key"] is True
    # 2025/0385(COD): mandate announced 6 Jul 2026, referral back for reconsideration 9 Jul, new committee report
    # 8 Oct, referral back for negotiations 20 Oct 2026
    for day, want in (("2026-07-08", ("negotiations", "Mandate to negotiate with the Council")),
                      ("2026-07-10", ("proposed", "Referred back to committee")),
                      ("2026-10-09", ("proposed", "Committee report adopted")),
                      ("2026-10-23", ("negotiations", "Mandate to negotiate with the Council"))):  # fmt: skip
        s, _ = _classified("2025-0385", day)
        assert (s.stage, s.label) == want, day


def test_agreement_after_parliaments_first_reading_is_an_early_second_reading_agreement():
    # 2023/0210(COD), Payment Services Regulation: first reading 23 Apr 2024 (T9-0298/2024); OEIL 5 May 2026
    # "Approval in committee of the text agreed at early 2nd reading interinstitutional negotiations"; the Council
    # then adopts its first-reading position, which Parliament approves at second reading (Art. 294(5), (7)(a) TFEU)
    s, _ = _classified("2023-0210")
    assert (s.stage, s.label, s.since, s.basis) == (
        "parliament_position", "Early second-reading agreement reached", "2026-05-05", "source")  # fmt: skip
    assert "23 April 2024" in s.explanation and "5 May 2026" in s.explanation and "It is not law yet" in s.explanation
    assert s.next_step.institution == "Council" and "Article 294(7)(a) TFEU" in s.next_step.text
    assert "approves Parliament's position" not in s.next_step.text
    # negotiations after the first reading without an agreement (2023/0085(COD), Green Claims: trilogues from 28 Jan
    # 2025; 2018/0332(COD), clock changes: the committee's decision announced on 9 Oct 2019)
    s, _ = _classified("2023-0085")
    assert (s.label, s.since) == ("Negotiations with the Council after Parliament's first reading", "2025-01-28")
    s, _ = _classified("2018-0332")
    assert (s.label, s.since) == ("Committee decided to negotiate with the Council after Parliament's first reading",
                                  "2019-10-09")  # fmt: skip
    # an agreement before Parliament's first reading stays "Approved by Parliament" (2023/0134(COD))
    assert _classified("2023-0134")[0].label == "Approved by Parliament"


def test_negotiations_after_parliaments_first_reading_are_not_second_reading_negotiations():
    # 2023/0226(COD), new genomic techniques: OEIL 8 Apr 2025 "Committee decision to open interinstitutional
    # negotiations after 1st reading in Parliament", the Council's first-reading position 21 Apr 2026, the second
    # reading only after it (Art. 294(7) TFEU); 2010/0208(COD), 11 Nov 2014: "… at 2nd reading"
    from pipeline.sources.ep_procedures import OEIL_EVENT_MAP

    after = "Parliament committee decided to open negotiations with the Council after Parliament's first reading"
    label = "Committee decision to open interinstitutional negotiations after 1st reading in Parliament"
    assert OEIL_EVENT_MAP[label][2] == after
    p = procs("2023-0226", "2010-0208")
    e = next(e for e in p["2023-0226"].events if e.raw_type == f"oeil:{label}")
    assert (e.date, Builder.procedure_event(p["2023-0226"], e).title) == ("2025-04-08", after)
    second = [e.title for e in p["2010-0208"].events if e.raw_type == (
        "oeil:Committee decision to open interinstitutional negotiations at 2nd reading")]  # fmt: skip
    assert second == ["Parliament committee decided to open second-reading negotiations with the Council"]
    # no readings in a consultation
    cns = p["2023-0226"].model_copy(update={"type": "CNS"})
    assert Builder.procedure_event(cns, e).title == "Parliament committee decided to open negotiations with the Council"


def test_publication_is_dated_by_the_official_journal():
    # 2018/0069(COD): EP API 2018-0069-PUB-2019-07-25, but Regulation (EU) 2019/982 is headed "20.6.2019 … Official
    # Journal of the European Union L 164/1"; the EP's date is that of 2016/0074(COD)'s Regulation (EU) 2019/1241
    # ("25.7.2019 … L 198/105"), whose EP record gives 20 June 2019
    for pid, celex, oj, ep in (("2016-0074", "32019R1241", "2019-07-25", "20 June 2019"),
                               ("2018-0069", "32019R0982", "2019-06-20", "25 July 2019")):  # fmt: skip
        p, a = procs(pid)[pid], acts(celex)[celex]
        tl = Builder.timeline(stand_in(), p, [a], [])  # type: ignore[arg-type]
        pubs = [x for x in tl if x["kind"] == "publication"]
        assert [(x["date"], x["title"], x["institution"]) for x in pubs] == [
            (oj, "Published in the Official Journal of the EU", "EUR-Lex")], pid  # fmt: skip
        assert f"The European Parliament's procedure record gives {ep} for its publication." in pubs[0]["detail"]
    # the latest step of 2018/0069 is the entry into force of 10 July 2019, not the EP's 25 July 2019
    assert [x["date"] for x in tl if x["state"] == "done"][-1] == "2019-07-10"
    # an EP record on the act's own publication day stays (2021/0106(COD), AI Act, 12 July 2024)
    p, a = procs("2021-0106")["2021-0106"], acts("32024R1689")["32024R1689"]
    tl = Builder.timeline(stand_in(), p, [a], [])  # type: ignore[arg-type]
    assert [x["id"] for x in tl if x["kind"] == "publication"] == ["2021-0106-PUB-2024-07-12"]


def test_a_mandate_vote_is_linked_once():
    # 2025/0393(COD), 6 Oct 2026: vote 197467 on the amended text (515-108-35), then the referral back for
    # negotiations (T10-0325/2026, Rule 60(4)); the vote is on "Parliament voted amendments to the proposal", and the
    # mandate step built from it links none (as 2021/0106(COD) on 14 Jun 2023)
    v = votes("197467")
    me = stand_in(votes_of={"2025-0393": list(v.values())}, indexed_vote_ids=set(v))
    q = Builder.with_recorded_events(me, procs("2025-0393")["2025-0393"])  # type: ignore[arg-type]
    tl = {x["id"]: x for x in Builder.timeline(me, q, [], list(v.values()))}  # type: ignore[arg-type]
    dcpl, mandate = tl["2025-0393-DEC-DCPL-2026-10-06"], tl["vote-197467-negotiation_mandate"]
    assert (dcpl["vote_id"], dcpl["key"], mandate["vote_id"], mandate["key"]) == ("197467", True, None, True)


def test_unlinked_act_is_named_in_the_status_not_linked():
    # 2025/0806(CNS): Council Regulation (EU) 2026/415 of 16 December 2025 (OJ L, 2026/415, 20.2.2026), "Having regard
    # to the Opinion of the European Parliament (2)", "(2) Opinion of 26 November 2025" (the file's T10-0297/2025), and
    # "the Recommendation of the European Central Bank (1)", OJ C/2025/3224, ECB/2025/17 (ST 9737/25, the file's
    # 09737/2025); Cellar records no procedure for the act, OEIL "Awaiting final decision"
    from pipeline.build import _as_dict, load_unlinked_acts

    s, q = _classified("2025-0806")
    me = SimpleNamespace(unlinked_acts=load_unlinked_acts(), _status_dict=Builder._status_dict)
    before = Builder._status_dict(_as_dict(s))
    r = Builder.unlinked_act_status(me, q, [], before)  # type: ignore[arg-type]
    st = r["status"]
    assert (st["stage"], st["label"], st["since"]) == ("unknown", "Final act not linked in the official records", None)
    assert st["explanation"].startswith(
        "Parliament delivered its opinion on 26 November 2025. Council Regulation (EU) 2026/415 of 16 December 2025, "
        "published in the Official Journal on 20 February 2026, cites “the Opinion of the European Parliament” of 26 "
        "November 2025")  # fmt: skip
    assert "Recommendation of the European Central Bank ECB/2025/17" in st["explanation"]
    assert "09737/2025" in st["explanation"]
    assert ("No official record links that act to this procedure: EUR-Lex records no procedure for it (checked on 23 "
            "October 2026), and the Legislative Observatory lists no final act") in st["explanation"]  # fmt: skip
    assert st["named_acts"][0]["celex"] == "32026R0415" and r["stall"] is None and r["next_step"]["basis"] == "unknown"
    # not applied once an act is linked, nor without Parliament's opinion of the day the act cites
    assert Builder.unlinked_act_status(me, q, [acts("32021R1163")["32021R1163"]], before) == before  # type: ignore[arg-type]
    other = q.model_copy(update={"events": [e for e in q.events if e.kind.value != "ep_position"]})
    assert Builder.unlinked_act_status(me, other, [], before) == before  # type: ignore[arg-type]


def test_council_position_by_written_procedure_is_dated_by_cellar():
    # ST 7360/20 (Taxonomy Regulation): note of 16 April 2020; Regulation (EU) 2020/852 "Position of the Council at
    # first reading of 15 April 2020", Cellar ADP_R1_POS_byCONSIL 2020-04-15 (re-read with council.reprocess);
    # ST 7236/20 and 7237/20: Regulations (EU) 2020/741 and 2020/1056, "first reading of 7 April 2020"
    cv = council("ST-7360-2020", "ST-7236-2020", "ST-7237-2020")
    assert [(cv[k].date, cv[k].written_procedure) for k in ("ST-7360-2020", "ST-7236-2020", "ST-7237-2020")] == [
        ("2020-04-15", True), ("2020-04-07", True), ("2020-04-07", True)]  # fmt: skip


# ------------------------------------------------------------------- where a regulation applies
def test_a_regulation_is_never_said_to_apply_in_all_eu_countries():
    # The next step read "The regulation applies directly in all EU countries" for every regulation. Return Regulation
    # (EU) 2026/2280, recital 67: "Denmark is not taking part in the adoption of this Regulation and is not bound by it
    # or subject to its application"; Art. 50: "directly applicable in the Member States in accordance with the
    # Treaties". EPPO, Council Regulation (EU) 2017/1939, recital 110: "Member States of the European Union which do
    # not participate in enhanced cooperation on the establishment of the EPPO are not bound by this Regulation";
    # Regulation (EU) 2026/467, recital 43: "This Regulation does not apply to Member States which do not participate
    # in the enhanced cooperation"; Art. 20(4) TEU: such acts "shall bind only participating Member States".
    from datetime import date

    from pipeline.analysis.status import classify, regulation_applies

    files = {"2025-0059": "32026R2280", "2013-0255": "32017R1939", "2026-0008": "32026R0467", "2016-0224A": "32024R1348"}
    a, p = acts(*files.values()), procs(*files)
    text = {pid: classify(p[pid], [a[c]], [], date(2026, 10, 23), others=a).next_step.text for pid, c in files.items()}
    assert not [t for t in text.values() if "all EU countries" in t or "every Member State" in t]
    assert text["2025-0059"].startswith("The regulation applies directly; no national transposition is needed.")
    for pid in ("2013-0255", "2026-0008"):
        assert text[pid].startswith(
            "The regulation applies directly only in the Member States taking part in the enhanced cooperation it "
            "implements (Article 20(4) TEU); no national transposition is needed."
        ), pid
    assert regulation_applies(a["32024R1348"]) == "applies directly"


# ------------------------------------------------------------------- application dates EUR-Lex gives as not recorded
def test_application_date_given_as_not_recorded_is_never_read_as_applying_from_entry_into_force():
    # ETIAS, Regulation (EU) 2018/1240, Art. 96: "This Regulation shall apply from the date determined by the Commission
    # in accordance with Article 88, with the exception of Articles 6, 11, 12 ... which shall apply from 9 October 2018";
    # Cellar: MA 1001-01-01 "V ART 96". The page said only "Some provisions apply from 3 Aug 2021" and that the
    # regulation "applies directly in all EU countries".
    from datetime import date

    from pipeline.analysis.status import classify

    a = acts("32018R1240", "32018R1241")
    s = classify(procs("2016-0357A")["2016-0357A"], list(a.values()), [], date(2026, 10, 23), others=a)
    assert s.stage == "in_force"
    assert "EUR-Lex records no date from which the act in general applies (it refers to Art. 96)." in s.explanation
    # nor "in all EU countries": which Member States a regulation binds is for its text to say (test_a_regulation_is_...)
    assert s.next_step.text.startswith(
        "A regulation applies directly; no national transposition is needed. EUR-Lex records no date "
        "from which this regulation in general applies (it refers to Art. 96)."
    )
    assert [(x.partial, x.articles) for x in s.application.application_unrecorded] == [(False, ["Art. 96"])]


def test_a_date_set_since_by_the_decision_the_act_refers_to_replaces_not_recorded():
    # Clinical Trials Regulation, Art. 99: it "shall apply as from six months after the publication of the notice
    # referred to in Article 82(3)"; Commission Decision (EU) 2021/1240 (OJ L 275, 31.7.2021): 31 January 2022. EPPO,
    # Art. 120(2): tasks from a date the Commission sets; Implementing Decision (EU) 2021/856, Art. 1: 1 June 2021
    from datetime import date

    from pipeline.analysis.status import classify
    from pipeline.build import act_date_source, apply_act_dates, load_act_dates

    cur = load_act_dates()
    ctr = apply_act_dates(acts("32014R0536")["32014R0536"], cur["32014R0536"])
    assert ctr.application_unrecorded == [] and ctr.other_application_dates == ["2022-01-31"]
    assert act_date_source(cur["32014R0536"], "2022-01-31")["url"].endswith("CELEX:32021D1240")
    s = classify(procs("2012-0192")["2012-0192"], [ctr], [], date(2026, 10, 23))
    assert "no date" not in s.explanation and s.next_step.text.startswith("The regulation applies directly")
    eppo = apply_act_dates(acts("32017R1939")["32017R1939"], cur["32017R1939"])
    assert eppo.application_unrecorded == [] and eppo.partial_application_dates == ["2021-06-01"]


def test_regulations_that_did_not_apply_under_their_own_condition_say_so():
    # Regulation (EU) 2019/503, Art. 8(3): it "shall not apply if a withdrawal agreement concluded with the United
    # Kingdom in accordance with Article 50(2) of the Treaty on European Union has entered into force by" the day
    # following that on which the Treaties cease to apply to the United Kingdom; the Withdrawal Agreement entered into
    # force on 1 February 2020 (EUR-Lex, CELEX 12020W/TXT)
    from pipeline.build import load_act_dates

    cur = load_act_dates()
    brexit = [c for c, e in cur.items() if any("12020W/TXT" in (s.get("url") or "") for s in e.get("sources") or [])]
    assert len(brexit) == 15 and "32019R0503" in brexit
    for c in brexit:
        assert "did not apply" in cur[c]["reason"] and not cur[c].get("application"), c
        assert any(not x.partial for x in acts(c)[c].application_unrecorded), c  # EUR-Lex gives no date


def test_entry_into_force_on_the_twentieth_day_after_publication_is_not_a_day_late():
    # PRIMA, Decision (EU) 2017/1324, Art. 15: "This Decision shall enter into force on the twentieth day following that
    # of its publication in the Official Journal of the European Union" (OJ L 185, 18.7.2017): 7 August 2017; Cellar
    # records 2017-08-08 with its own rule "DATPUB +20"
    from datetime import date, timedelta

    from pipeline.build import apply_act_dates, load_act_dates

    a = acts("32017D1324")["32017D1324"]
    rule = (date.fromisoformat(a.date_publication) + timedelta(days=a.entry_into_force_after_publication)).isoformat()
    assert (a.entry_into_force, rule) == ("2017-08-08", "2017-08-07")
    assert apply_act_dates(a, load_act_dates()["32017D1324"]).entry_into_force == "2017-08-07"


# ------------------------------------------------------------------- the timeline of an act
def test_act_steps_name_the_act_and_the_first_application_date_is_not_further():
    # PPWR, Regulation (EU) 2025/40, Art. 71: "It shall apply from 12 August 2026. However, Article 67(5) shall apply
    # from 12 February 2029." Nothing applied before 12 August 2026; the steps named it "Regulation 32025R0040".
    me = stand_in(today="2026-10-23")
    a = acts("32025R0040")["32025R0040"]
    tl = Builder.timeline(me, procs("2022-0396")["2022-0396"], [a], [])  # type: ignore[arg-type]
    app = {x["date"]: x["title"] for x in tl if x["kind"] == "application"}
    assert app == {"2026-08-12": "Rules started to apply (date recorded by EUR-Lex)",
                   "2029-02-12": "Some provisions start to apply (date recorded by EUR-Lex)"}  # fmt: skip
    assert {x["detail"] for x in tl if x["id"].startswith("act-")} == {"Regulation (EU) 2025/40"}


def test_the_date_an_act_applies_from_in_general_is_when_its_rules_start_also_after_dates_for_some_provisions():
    # Asylum Procedure Regulation, Regulation (EU) 2024/1348, Art. 79(2): "This Regulation shall apply from 12 June
    # 2026"; Cellar records 27 February 2026 for some provisions (MA/PART) and 12 June 2026 (MA). The headline read
    # "Further provisions started to apply" for 12 June 2026, where "When it applies" reads "Rules apply from".
    me = stand_in(today="2026-10-23")
    cases = {"2016-0224A": "32024R1348", "2016-0106": "32017R2226", "2023-0226": "32026R1388", "2023-0252": "32023R2663"}
    a, p = acts(*cases.values()), procs(*cases)
    app = {pid: {x["date"]: x["title"] for x in Builder.timeline(me, p[pid], [a[c]], []) if x["kind"] == "application"}  # type: ignore[arg-type]
           for pid, c in cases.items()}  # fmt: skip
    assert app["2016-0224A"] == {"2026-02-27": "Some provisions started to apply (date recorded by EUR-Lex)",
                                 "2026-06-12": "Rules started to apply (date recorded by EUR-Lex)"}  # fmt: skip
    # EES, Regulation (EU) 2017/2226: some provisions from its entry into force; Cellar "MA V ART 73 ET 32025D1544"
    assert app["2016-0106"] == {"2025-10-12": "Rules started to apply (date recorded by EUR-Lex)"}
    # NGT, Regulation (EU) 2026/1388, Art. 38: "It shall apply from 17 July 2028. However, Articles 29, 30 and 31 shall
    # apply from 16 July 2026" (its entry into force)
    assert app["2023-0226"] == {"2028-07-17": "Rules start to apply (date recorded by EUR-Lex)"}
    # a later date that is not partial either is further (EUR-Lex: 28 November 2023 and 1 January 2024)
    assert app["2023-0252"] == {"2023-11-28": "Rules started to apply (date recorded by EUR-Lex)",
                                "2024-01-01": "Further provisions started to apply (date recorded by EUR-Lex)"}  # fmt: skip


def test_an_application_date_before_the_act_itself_is_said_to_be_retroactive():
    # Regulation (EU) 2021/23, Art. 97: "It shall apply from 12 August 2022 with the exception of: Article 95 which
    # shall apply from 4 July 2020"; the act is "of 16 December 2020". The step sat between the January 2020
    # negotiation steps and the September 2020 agreement with nothing to say it was retroactive.
    from pipeline.build import apply_act_dates, load_act_dates

    me = stand_in(today="2026-10-23")
    a = acts("32021R0023")["32021R0023"]
    tl = {x["date"]: x for x in Builder.timeline(me, procs("2016-0365")["2016-0365"], [a], []) if x["kind"] == "application"}  # type: ignore[arg-type]
    assert tl["2020-07-04"]["title"] == "Some provisions started to apply retroactively (date recorded by EUR-Lex)"
    assert tl["2020-07-04"]["detail"] == (
        "Regulation (EU) 2021/23. This date is earlier than the act itself, dated 16 December 2020: what applies from "
        "it does so retroactively."
    )
    assert [x["title"] for d, x in sorted(tl.items()) if "retroactiv" in x["title"] + x["detail"]] == [tl["2020-07-04"]["title"]]
    # a checked date that already says so is not marked twice (Council Regulation (EU, Euratom) 2021/768, Art. 9)
    cur = load_act_dates()
    me = stand_in(today="2026-10-23", act_dates=cur)
    own = apply_act_dates(acts("32021R0768")["32021R0768"], cur["32021R0768"])
    step = next(x for x in Builder.timeline(me, procs("2018-0132")["2018-0132"], [own], []) if x["kind"] == "application")  # type: ignore[arg-type]
    assert (step["date"], step["title"]) == ("2021-01-01", "Started to apply: The Regulation in general, retroactively (Art. 9)")
    assert "earlier than the act" not in step["detail"]


def test_a_second_reading_approval_decided_by_a_rejected_motion_to_reject_says_so():
    # 2017/0121(COD), 8 Jul 2020: the only roll-call was 116204, "A9-0114/2020 - Kateřina Konečná - Proposal for
    # rejection (Rule 67(1))", rejected 218-469-7; the step "Parliament approved the Council's position at second
    # reading" linked it as "How MEPs voted" with nothing to say no vote on the approval was held. 2017/0122(COD):
    # vote 116205 of 8 July 2020, the decision recorded on 9 July (remote voting)
    from pipeline.build import REJECTED_MOTION_APPROVAL

    v = votes("116204", "116205")
    assert [(x.kind_detail, x.outcome) for x in v.values()] == [("reject_council_position", "rejected")] * 2
    p = procs("2017-0121", "2017-0122")
    me = SimpleNamespace(indexed_vote_ids=set(v), council_of={}, today="2026-10-23")
    step = {pid: next(x for x in Builder.timeline(me, p[pid], [], [v[vid]]) if x["id"] == sid)  # type: ignore[arg-type]
            for pid, vid, sid in (("2017-0121", "116204", "2017-0121-DEC-DCPL-2020-07-08"),
                                  ("2017-0122", "116205", "2017-0122-DEC-DCPL-2020-07-09"))}  # fmt: skip
    assert (step["2017-0121"]["vote_id"], step["2017-0121"]["detail"]) == ("116204", REJECTED_MOTION_APPROVAL)
    assert "Article 294(7)(a) TFEU" in REJECTED_MOTION_APPROVAL and "motion to reject" in REJECTED_MOTION_APPROVAL
    assert step["2017-0122"]["vote_id"] == "116205"
    assert step["2017-0122"]["detail"] == (
        "Parliament's vote records date this vote 8 July 2020; its procedure record dates the decision 9 July 2020. "
        + REJECTED_MOTION_APPROVAL
    )


def test_a_debate_is_joint_only_with_files_whose_own_record_shows_the_debate():
    # EP item MTG-PL-2020-10-20-PVCRE-ITM-5, "Common agricultural policy - support for strategic plans ... - financing,
    # management and monitoring - ... amendment of the CMO and other Regulations (debate)": the three CAP files. It
    # also cites A9-0198/2020, A9-0199/2020 and A9-0200/2020, reports dated after the debate; A9-0200/2020 is the VAT
    # Northern Ireland report of 2020/0165(CNS), tabled on 29 October 2020, whose record shows no debate that day.
    # MTG-PL-2021-06-08-PVCRE-ITM-20, "European Social Fund Plus (ESF+) 2021-2027 ***II (continuation of debate)",
    # also cites C9-0196/2021 of 2018/0258(COD), which was debated on its own the day before (item 22).
    ids = ["2018-0216", "2018-0217", "2018-0218", "2020-0165", "2018-0258", "2018-0206", "2021-0204", "2021-0206",
           "2021-0207", "2021-0211A", "2021-0214"]  # fmt: skip
    ps = procs(*ids)
    me = SimpleNamespace(indexed_vote_ids=set(), council_of={}, today="2026-10-23", procedures=list(ps.values()), proc=ps,
                         curated_of={}, adopted_title=lambda p: None)  # fmt: skip
    me.dossier_title = lambda p: Builder.dossier_title(me, p)  # type: ignore[arg-type]
    Builder.index_file_documents(me)  # type: ignore[arg-type]
    tl = {pid: Builder.joint_debates(me, ps[pid], Builder.timeline(me, ps[pid], [], [])) for pid in ids}  # type: ignore[arg-type]
    cap = {"2018-0216", "2018-0217", "2018-0218"}
    for pid in cap:
        step = next(e for e in tl[pid] if e["id"] == "MTG-PL-2020-10-20-PVCRE-ITM-5")
        assert step["title"] == "Joint debate in Parliament"
        assert {j["id"] for j in step["joint_with"]} == cap - {pid}, pid
        assert not {"A-9-2020-0198", "A-9-2020-0199", "A-9-2020-0200"} & {d["id"] for d in step["docs"]}
    assert not [e for e in tl["2020-0165"] if e["kind"] == "plenary_debate"]
    # the customs equipment file keeps its own debate of 7 June 2021 and not the ESF+ item of 8 June
    assert [(e["date"], e["title"]) for e in tl["2018-0258"] if e["kind"] == "plenary_debate" and e["date"] >= "2021"] == [
        ("2021-06-07", "Debate in Parliament")]  # fmt: skip
    esf = next(e for e in tl["2018-0206"] if e["id"] == "MTG-PL-2021-06-08-PVCRE-ITM-20")
    assert (esf["title"], esf.get("joint_with")) == ("Debate in Parliament", None)
    # a file whose own record shows a debate in Parliament that day (OEIL) is named: item 2 of 7 June 2022, "... (joint
    # debate – Fit for 55 (part 1))", cites A9-0162/2022 of 2021/0211A(COD), whose OEIL file has "Debate in Parliament"
    fit = next(e for e in tl["2021-0204"] if e["id"] == "MTG-PL-2022-06-07-PVCRE-ITM-2")
    assert [j["id"] for j in fit["joint_with"]] == ["2021-0206", "2021-0207", "2021-0211A", "2021-0214"]


def test_the_pillar_two_directive_adoption_is_recorded_from_the_councils_communication():
    # CM 5860/22, point 2: "(a) all delegations voted in favour of, except for Hungary that abstained, the adoption of
    # the Council Directive on ensuring a global minimum level of taxation ... The required unanimity has been
    # reached"; the written procedure "was completed on 15 December 2022 at 22:11". The page said that no Council vote
    # is linked to the file; Council Directive (EU) 2022/2523 is "of 14 December 2022".
    from pipeline.build import council_vote_event

    me = _built_council([], ["2021-0433"])
    cm = me.council_records["CM-5860-2022-2"]  # type: ignore[attr-defined]
    assert (cm["dossier_id"], cm["date"], cm["voting_rule"], cm["outcome"], cm["vote_on"], cm["written_procedure"]) == (
        "2021-0433", "2022-12-15", "unanimity", "adopted", "act", True)  # fmt: skip
    assert cm["positions"]["HU"] == "abstain" and sum(x == "for" for x in cm["positions"].values()) == 26
    assert cm["source"]["identifier"] == "CM 5860/22"
    assert '"was completed on 15 December 2022 at 22:11"' in cm["source_note"]
    assert '"Council Directive (EU) 2022/2523 of 14 December 2022"' in cm["source_note"]
    assert len(cm["statements"]) == 2 and cm["statements"][1].startswith("Statement by Sweden")
    assert council_vote_event(cm)["title"] == "Council adopted the act (written procedure)"


def test_a_date_checked_against_the_text_cites_that_text_as_its_source():
    # DSA, Regulation (EU) 2022/2065, Art. 93(2): 17 February 2024 (EUR-Lex records 17 February 2022); the step's
    # source said "EUR-Lex / Cellar – CELEX 32022R2065", the record that lacks the date
    from pipeline.build import apply_act_dates, load_act_dates

    cur = load_act_dates()
    me = stand_in(today="2026-10-23", act_dates=cur)
    a = apply_act_dates(acts("32022R2065")["32022R2065"], cur["32022R2065"])
    tl = Builder.timeline(me, procs("2020-0361")["2020-0361"], [a], [])  # type: ignore[arg-type]
    step = next(x for x in tl if x["kind"] == "application" and x["date"] == "2024-02-17")
    assert step["source"]["url"] == step["docs"][0]["url"] == "https://eur-lex.europa.eu/eli/reg/2022/2065/oj"
    assert step["source"]["label"] == "Regulation (EU) 2022/2065, Article 93 (checked 23 October 2026)"


def test_older_act_titles_that_begin_with_the_number_give_the_number():
    a = acts("32014D0335", "32014D0899", "32024D2829")
    assert [act_label(x) for x in a.values()] == [
        "Council Decision 2014/335/EU, Euratom", "Council Decision 2014/899/EU", "Decision (EU) 2024/2829"]  # fmt: skip


# ------------------------------------------------------------------- titles and links of the adopted act
def test_a_procedure_title_that_does_not_describe_the_adopted_act_gives_way_to_the_acts():
    # 2023/0393(COD): "Extending Directive [XXXX] to third country nationals ..."; Directive (EU) 2024/2842 extends
    # Directive (EU) 2024/2841. 2021/0395(COD) names Framework Decision 2002/465/JHA, which Directive (EU) 2023/2843
    # does not amend, and not Directive 2011/99/EU, which it does (Art. 10).
    from pipeline.build import title_misfit

    p, a = procs("2023-0393", "2021-0395", "2016-0002"), acts("32024L2842", "32023L2843", "32019L0884")
    pairs = {"2023-0393": "32024L2842", "2021-0395": "32023L2843", "2016-0002": "32019L0884"}
    assert {pid: title_misfit(p[pid].title, a[c].title) for pid, c in pairs.items()} == {
        "2023-0393": True, "2021-0395": True, "2016-0002": False}  # fmt: skip
    me = SimpleNamespace(curated_of={}, acts_of={pid: [a[c]] for pid, c in pairs.items()},
                         act_dossiers={c: {pid} for pid, c in pairs.items()})  # fmt: skip
    me.adopted_title = lambda q: Builder.adopted_title(me, q)  # type: ignore[arg-type]
    assert Builder.dossier_title(me, p["2023-0393"]) == (  # type: ignore[arg-type]
        "Extending Directive (EU) 2024/2841 to third-country nationals legally residing in a Member State")
    assert Builder.dossier_title(me, p["2021-0395"]).startswith("Amending Directives 2011/99/EU and 2014/41/EU")  # type: ignore[arg-type]
    assert Builder.adopted_title(me, p["2016-0002"]) is None  # type: ignore[arg-type]


def test_an_amending_title_that_leaves_out_an_act_the_law_amends_gives_way_to_the_acts():
    # Regulation (EU) 2026/1744 is "amending Regulations (EU) 2024/1689, (EU) 2018/1139 and (EU) 2023/1230"; the header
    # of 2025/0359(COD) gave the proposal's "Amending Regulations (EU) 2024/1689 and (EU) 2018/1139" as its official
    # title. Regulation (EU) 2024/886 also amends Directives 98/26/EC and (EU) 2015/2366, which 2022/0341(COD)'s
    # title leaves out. 2012/0288(COD) names its directives in words ("the fuel quality directive"): not checked.
    from pipeline.build import celex_numbers, title_misfit

    pairs = {"2025-0359": "32026R1744", "2022-0341": "32024R0886", "2012-0288": "32015L1513", "2016-0002": "32019L0884"}
    p, a = procs(*pairs), acts(*pairs.values())
    assert {pid: title_misfit(p[pid].title, a[c].title, a[c].amends) for pid, c in pairs.items()} == {
        "2025-0359": True, "2022-0341": True, "2012-0288": False, "2016-0002": False}  # fmt: skip
    # without the act's amendment links, only the earlier rule applies
    assert not title_misfit(p["2025-0359"].title, a["32026R1744"].title)
    assert celex_numbers("31998L0026") == {"1998/26", "26/1998", "98/26"}
    me = SimpleNamespace(curated_of={}, acts_of={pid: [a[c]] for pid, c in pairs.items()},
                         act_dossiers={c: {pid} for pid, c in pairs.items()})  # fmt: skip
    assert "(EU) 2023/1230" in (Builder.adopted_title(me, p["2025-0359"]) or "")  # type: ignore[arg-type]
    assert Builder.adopted_title(me, p["2016-0002"]) is None  # type: ignore[arg-type]


def test_an_amendment_link_to_the_wrong_act_is_corrected_both_ways():
    # Regulation (EU) 2024/1689 (AI Act), Art. 105: "In Article 8 of Directive 2014/90/EU, the following paragraph is
    # added"; Cellar links it to Implementing Regulation (EU) No 90/2014 (32014R0090) instead
    from pipeline.build import apply_act_relations, load_act_relations
    from pipeline.validate import cited_acts

    a = acts("32024R1689", "32014L0090")
    assert "32014R0090" in a["32024R1689"].amends and cited_acts(a["32024R1689"].title)[(2014, 90)] == {"Directive"}
    fixed = {x.celex: x for x in apply_act_relations(list(a.values()), load_act_relations())}
    assert "32014L0090" in fixed["32024R1689"].amends and "32014R0090" not in fixed["32024R1689"].amends
    assert fixed["32014L0090"].amended_by == ["32021L1206", "32024R1689"]
    # a correction Cellar no longer needs is not applied
    stale = [{"act": "32024R1689", "replace": "32014R0091", "with": "32014L0090", "evidence": "x"}]
    assert apply_act_relations(list(a.values()), stale) == list(a.values())


# ------------------------------------------------------------------- national measures
def test_denmark_row_states_its_decision_on_a_directive_building_upon_the_schengen_acquis():
    # Directive (EU) 2023/977, recital 40: Denmark is not bound, and decides under Protocol No 22, Art. 4, whether to
    # implement it; ST 15298/23: "Denmark hereby gives notice that it has decided to implement the above measure in
    # accordance with Article 4 of the Protocol". The row showed only "Not bound" next to a non-communication case.
    from pipeline.build import load_denmark_schengen
    from pipeline.models.entities import DirectiveOptOut

    oo = {k: DirectiveOptOut.model_validate(v) for k, v in records("optouts/directives.json", {"32023L0977"}, "celex").items()}
    assert oo["32023L0977"].schengen_art4 == ["DK"] and oo["32023L0977"].quotes[-1].startswith("Given that this Directive")
    me = _impl_builder(_measures("32023L0977"))
    me.optouts, me.denmark_schengen = oo, load_denmark_schengen()
    me.schengen_note = lambda c, k: Builder.schengen_note(me, c, k)  # type: ignore[arg-type]
    row = next(r for r in Builder.implementation_table(me, acts("32023L0977")["32023L0977"])["countries"]  # type: ignore[arg-type]
               if r["country"] == "DK")
    assert row["status"] == "not_participating"
    assert row["status_note"] == (
        "Denmark decided to implement it in its national law under Article 4 of Protocol No 22, as it notified the "
        "Council on 9 November 2023 (ST 15298/23): an obligation under international law, not under EU law.")
    assert row["status_note_url"] == "https://data.consilium.europa.eu/doc/document/ST-15298-2023-INIT/en/pdf"
    me.denmark_schengen = {}
    assert Builder.schengen_note(me, "32023L0977", "DK")[0].startswith("It builds upon the Schengen acquis")  # type: ignore[arg-type,index]
    assert Builder.schengen_note(me, "32023L0977", "IE") is None  # type: ignore[arg-type]


def test_next_step_gives_the_later_date_the_text_sets_for_some_national_measures():
    # CSDDD, Directive (EU) 2024/1760, Art. 37(1) as replaced by Directive (EU) 2026/470, Art. 4, point (22): "They
    # shall apply those measures from 26 July 2029 with the exception of the measures necessary to comply with Article
    # 16, which Member States shall apply for financial years starting on or after 1 January 2030."
    from datetime import date

    from pipeline.analysis.status import classify
    from pipeline.build import apply_transposition_checks, load_transposition_checks

    a = apply_transposition_checks(acts("32024L1760")["32024L1760"], load_transposition_checks()["32024L1760"])
    s = classify(procs("2022-0051")["2022-0051"], [a], [], date(2026, 10, 23))
    assert ("The national measures are to apply from 26 July 2029. The measures necessary to comply with Article 16 "
            "(reporting on these matters in an annual statement) are to apply for financial years starting on or after "
            "1 January 2030 (Art. 37(1), as replaced by Directive (EU) 2026/470, Art. 4, point (22)).") in s.next_step.text
    assert "except as its text provides" not in s.next_step.text  # the transposition deadline has no exception
    app = next(x for x in s.application.transposition if x.kind == "application")
    assert app.date == "2029-07-26" and "Article 16" in (app.exceptions or "")
