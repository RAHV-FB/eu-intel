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
    VOTE_DETAIL_LABELS,
    VOTE_OUTCOME_NOTES,
    Builder,
    build_search_docs,
    commission_cod_proposal,
    english_procedural,
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
