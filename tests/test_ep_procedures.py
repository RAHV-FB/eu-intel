"""Tests for pipeline.sources.ep_procedures (offline, on real trimmed captures).

Fixtures in tests/fixtures/ep_procedures/:
- ep_<id>.json: EP Open Data API v2 GET /procedures/<id> (format=application/ld+json), 2026-10-22
- oeil_<id>.html: OEIL procedure file, trimmed (see the comment at the top of each file)
- ep_list_COD.json: GET /procedures?process-type=COD, data reduced to the fixture procedures
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from lxml import html as lxml_html

from pipeline.models.entities import EventKind, Procedure
from pipeline.sources import ep_procedures as m

FIX = Path(__file__).parent / "fixtures" / "ep_procedures"
RETRIEVED = "2026-10-22T12:00:00Z"


def ep_json(pid: str) -> dict:
    return json.loads((FIX / f"ep_{pid}.json").read_text(encoding="utf-8"))


def ep_proc(pid: str) -> dict:
    return ep_json(pid)["data"][0]


def oeil_info(pid: str) -> m.OeilInfo:
    return m.parse_oeil((FIX / f"oeil_{pid}.html").read_bytes())


def build(pid: str, with_oeil: bool = True) -> Procedure:
    return m.build_procedure(ep_proc(pid), RETRIEVED, oeil_info(pid) if with_oeil else None, lambda _id: None)


# ---------------------------------------------------------------- mapping table
def test_activity_mapping_is_complete_and_deterministic():
    for code, (kind, title) in m.ACTIVITY_MAP.items():
        assert isinstance(kind, EventKind)
        assert title and title[0].isupper() and not title.endswith(".")
        assert m.activity_title(f"def/ep-activities/{code}") == m.activity_title(code)
    # every activity type seen in the fixtures is mapped (not "other" by accident)
    seen = {
        m.last_segment(m.activity_type(e))
        for f in FIX.glob("ep_2*.json")
        for e in m.as_list(json.loads(f.read_text())["data"][0].get("consists_of"))
        if isinstance(e, dict)
    }
    assert seen <= set(m.ACTIVITY_MAP), seen - set(m.ACTIVITY_MAP)


def test_unknown_activity_type_is_neutral_other():
    kind, title = m.activity_title("def/ep-activities/SOME_NEW_TYPE")
    assert kind == EventKind.other
    assert title == "Parliament activity: Some new type"


def test_reading_is_added_only_when_stated():
    rdg1 = "http://publications.europa.eu/resource/authority/procedure-phase/RDG1"
    assert (
        m.activity_title("PLENARY_ADOPT_POSITION", rdg1)[1] == "Parliament took its decision (first reading)"
    )
    assert m.activity_title("PLENARY_ADOPT_POSITION")[1] == "Parliament took its decision"
    # second-reading types carry the reading in their own title
    assert "second reading" in m.activity_title("PLENARY_APPROVE_COUNCIL_POSITION")[1]


def test_list_valued_activity_type_uses_specific_type():
    # 2022/0051(COD): a plenary vote carries [PLENARY_VOTE, PLENARY_ACTIVITY]
    events = [e for e in ep_proc("2022-0051")["consists_of"] if isinstance(e.get("had_activity_type"), list)]
    assert events, "fixture should contain a list-valued had_activity_type"
    assert m.last_segment(m.activity_type(events[0])) == "PLENARY_VOTE"


# ---------------------------------------------------------------- documents
@pytest.mark.parametrize(
    ("uri", "label", "kind", "url"),
    [
        (
            "eli/dl/doc/A-9-2023-0188",
            "A9-0188/2023",
            "report",
            "https://www.europarl.europa.eu/doceo/document/A-9-2023-0188_EN.html",
        ),
        (
            "eli/dl/doc/TA-9-2024-0138",
            "T9-0138/2024",
            "adopted_text",
            "https://www.europarl.europa.eu/doceo/document/TA-9-2024-0138_EN.html",
        ),
        (
            "eli/dl/doc/ENVI-AD-699056",
            "Committee opinion ENVI PE699.056",
            "opinion",
            "https://www.europarl.europa.eu/doceo/document/ENVI-AD-699056_EN.html",
        ),
        ("eli/dl/doc/CJ40-AG-758862", "Provisional agreement text CJ40 PE758.862", "agreement", None),
        ("eli/dl/doc/C-9-2021-0146", "C9-0146/2021", "other", None),
    ],
)
def test_ep_document_refs(uri, label, kind, url):
    d = m.ep_docref(uri)
    assert (d.id, d.label, d.kind, d.url) == (uri.rsplit("/", 1)[1], label, kind, url)


def test_normalize_proc_id():
    assert m.normalize_proc_id("2012-0011") == "2012-0011"
    assert m.normalize_proc_id("2012/0011(COD)") == "2012-0011"
    assert m.normalize_proc_id("2023/0077B(COD)") == "2023-0077B"
    assert m.normalize_proc_id("COM(2012)0011") is None


# ---------------------------------------------------------------- OEIL parsing
def test_parse_oeil_ai_act():
    info = oeil_info("2021-0106")
    assert info.status == "Procedure completed"
    assert info.instrument == "Regulation"
    assert [(s.code, s.scheme) for s in info.subjects] == [("3.30.06", "ep"), ("3.40.06", "ep")]
    assert [d.id for d in info.com_docs] == ["COM(2021)0206"]
    assert [f.id for f in info.final_acts] == ["32024R1689"]
    assert info.committee_names["IMCO"] == "Internal Market and Consumer Protection"
    labels = [e.label for e in info.events]
    assert "Act adopted by Council after Parliament's 1st reading" in labels


def test_parse_oeil_skips_corrigenda_in_final_act():
    # GDPR: the final-act section also links the corrigendum 32016R0679R(02)
    assert [f.id for f in oeil_info("2012-0011").final_acts] == ["32016R0679"]


def test_parse_oeil_corrigendum_entries_are_not_final_acts():
    # EPBD 2021/0426(COD): OEIL lists "Corrigendum to final act 32025R1328", which is Commission Implementing
    # Regulation (EU) 2025/1328 implementing the directive, not a final act of the procedure
    assert [f.id for f in oeil_info("2021-0426").final_acts] == ["32024L1275"]


# ---------------------------------------------------------------- building records
def test_build_ai_act():
    p = build("2021-0106")
    assert (p.id, p.reference, p.type) == ("2021-0106", "2021/0106(COD)", "COD")
    assert p.title.startswith("Harmonised rules on Artificial Intelligence")
    assert p.oeil_url == "https://oeil.europarl.europa.eu/oeil/en/procedure-file?reference=2021/0106(COD)"
    assert p.com_refs == ["COM(2021)0206"]
    assert p.celex_refs == ["32024R1689"]
    assert p.stage_raw == "Procedure completed"
    assert p.started == "2021-04-21"
    assert {(c.code, c.role) for c in p.committees} >= {
        ("IMCO", "joint"),
        ("LIBE", "joint"),
        ("ENVI", "opinion"),
    }
    rapporteurs = {(r.mep_id, r.role, r.committee) for r in p.rapporteurs}
    assert ("124867", "rapporteur", "IMCO") in rapporteurs  # Brando Benifei
    assert ("197665", "rapporteur", "LIBE") in rapporteurs

    dates = [e.date for e in p.events]
    assert dates == sorted(dates)
    by = {(e.date, e.kind): e for e in p.events}
    assert by[("2021-04-21", EventKind.proposal)].institution == "Commission"
    assert by[("2024-02-13", EventKind.provisional_agreement)].institution == "EP"
    pos = by[("2024-03-13", EventKind.ep_position)]
    assert pos.raw_type == "def/ep-activities/PLENARY_AMEND_PROPOSAL"
    assert "TA-9-2024-0138" in [d.id for d in pos.docs]
    assert by[("2024-05-21", EventKind.council_adoption)].institution == "Council"
    assert by[("2024-06-13", EventKind.signature)].raw_type == "def/ep-activities/SIGNATURE"
    assert by[("2024-07-12", EventKind.publication)].institution == "EUR-Lex"
    # vote records are folded into the same-day decision (no separate "Results of vote" entries)
    assert not [e for e in p.events if e.raw_type and e.raw_type.endswith("PLENARY_VOTE_RESULTS")]
    assert "PV-9-2024-03-13-VOT-ITM-002" in [d.id for d in pos.docs]
    # 2023-06-14: amendments voted + referral back for negotiations - NOT a first-reading position
    june = [e for e in p.events if e.date == "2023-06-14"]
    assert {e.kind for e in june} == {EventKind.plenary_vote, EventKind.negotiation_mandate}
    # event ids are unique and every event has a source
    assert len({e.id for e in p.events}) == len(p.events)
    assert all(e.source.retrieved_at == RETRIEVED for e in p.events)
    assert {d.id for d in p.documents} >= {"COM(2021)0206", "A-9-2023-0188", "TA-9-2024-0138"}


def test_build_without_oeil_keeps_ep_data_only():
    p = build("2021-0106", with_oeil=False)
    assert p.stage_raw is None and p.subjects == [] and p.com_refs == [] and p.celex_refs == []
    assert not [e for e in p.events if e.institution in ("Commission", "Council")]
    assert p.started == "2021-06-07"  # first EP event (referral), not invented


def test_type_of_act_proposed_from_oeil():
    # OEIL "Legislative instrument": 2023/0448(COD), still at committee stage, "Regulation"; none without OEIL
    assert build("2023-0448").instrument == "Regulation"
    assert build("2021-0106").instrument == "Regulation"
    assert build("2021-0106", with_oeil=False).instrument is None


def test_withdrawn_proposal_epprivacy():
    p = build("2017-0003")
    assert p.stage_raw == "Procedure lapsed or withdrawn"
    w = [e for e in p.events if e.kind == EventKind.withdrawal]
    assert [(e.date, e.institution) for e in w] == [("2025-10-06", "Commission")]
    # OEIL Council debate on a day with an EP event of the same kind ("other") is still kept
    assert [e.date for e in p.events if e.institution == "Council"] == ["2017-06-09", "2017-12-04"]


def test_participants_fall_back_to_oeil_for_old_files():
    proc = ep_proc("2012-0011")
    assert not m.as_list(proc.get("had_participation"))  # EP API has none for this file
    p = build("2012-0011")
    assert ("LIBE", "responsible") in {(c.code, c.role) for c in p.committees}
    lead = [r for r in p.rapporteurs if r.role == "rapporteur"]
    assert [(r.mep_id, r.name, r.committee) for r in lead] == [("96736", "ALBRECHT Jan Philipp", "LIBE")]


def test_rapporteur_names_from_resolver():
    names = {"124867": "Brando Benifei"}
    p = m.build_procedure(ep_proc("2021-0106"), RETRIEVED, oeil_info("2021-0106"), names.get)
    assert {r.name for r in p.rapporteurs if r.mep_id == "124867"} == {"Brando Benifei"}


def test_rapporteur_appointment_dates_from_the_ep_participations():
    # The build gives each rapporteur the group held on this date, not the MEP's current group: OEIL lists
    # "KONEČNÁ Kateřina (The Left)" (shadow since 2021-12-01; PfE only from 2026-10-21) and "MADISON Jaak (ID)".
    p = build("2021-0106")
    by = {(r.mep_id, r.role): r for r in p.rapporteurs}
    assert by[("23699", "shadow")].date == "2021-12-01"  # participation 2021-0106-NMSR-23699-2021-12-01
    assert by[("197493", "shadow")].date == "2022-01-24"
    assert by[("197784", "opinion_rapporteur")].date == "2021-09-15"  # ENVI, Susana Solís Pérez
    assert all(r.date and r.group is None for r in p.rapporteurs)  # EP API entries: date, no printed group


def test_shadow_rapporteur_for_an_opinion_has_its_own_role():
    # EP API participation_role RAPPORTEUR_SHADOW_OPINION (was stored as the vague "other")
    p = m.build_procedure(ep_proc("2023-0448"), RETRIEVED, oeil_info("2023-0448"), lambda i: f"MEP {i}")
    roles = {r.role for r in p.rapporteurs}
    assert "shadow_opinion" in roles and "other" not in roles


def test_oeil_key_players_keep_the_group_printed_for_each_role():
    info = oeil_info("2021-0106")
    imco, libe = (next(pl for pl in info.players if pl.code == c) for c in ("IMCO", "LIBE"))
    assert imco.groups == {"124867": "S&D"}  # BENIFEI Brando (S&D), rapporteur
    # the joint committees' shadow rapporteurs are listed in the row after LIBE's
    assert libe.groups["23699"] == "The Left" and libe.groups["197493"] == "ID"
    # older files take their rapporteurs from OEIL, with the group printed next to the name
    p = build("2012-0011")
    lead = next(r for r in p.rapporteurs if r.role == "rapporteur")
    assert (lead.mep_id, lead.group, lead.date) == ("96736", "Verts/ALE", None)


def participants_with_oeil(pid: str) -> list[tuple[str, str, str | None, str | None]]:
    """Committees and rapporteurs as build_procedure derives them, from the real EP API participations and OEIL
    key players of `pid` (fixtures trimmed to those parts)."""
    proc = json.loads((FIX / f"participants_{pid}.json").read_text(encoding="utf-8"))["data"][0]
    oeil = m.parse_oeil((FIX / f"players_{pid}.html").read_bytes())
    committees, rapps = m.build_participants(proc, lambda i: f"MEP {i}", {})
    rapps = m.oeil_rapporteur_committees(rapps, committees, oeil)
    return sorted((r.mep_id or "", r.role, r.committee, r.date) for r in rapps if r.role in ("rapporteur", "opinion_rapporteur"))


def test_rapporteur_committee_null_in_the_ep_api_is_read_from_oeil():
    # 2021/0240(COD): participation 2021-0240-NMCP-96899-null-2021-10-28 is "in name of" org/null; OEIL's key
    # players: "CONT Budgetary Control FERNANDES José Manuel (EPP) 28/10/2021". Never the string "null".
    assert ("96899", "opinion_rapporteur", "CONT", "2021-10-28") in participants_with_oeil("2021-0240")
    proc = json.loads((FIX / "participants_2021-0240.json").read_text(encoding="utf-8"))["data"][0]
    _c, rapps = m.build_participants(proc, lambda i: f"MEP {i}", {})
    assert {r.committee for r in rapps if r.mep_id == "96899"} == {None}  # without OEIL: no committee, not "null"


def test_rapporteur_for_a_subcommittee_is_listed_under_the_committee_giving_the_opinion():
    # 2025/0045(COD), Omnibus I: the EP API names the subcommittee DROI for Barry Andrews
    # (2025-0045-NMCP-204332-DROI-2025-04-10); the file's committee for opinion is AFET, and OEIL lists
    # "AFET Foreign Affairs ANDREWS Barry (Renew) 10/04/2025".
    rows = participants_with_oeil("2025-0045")
    assert ("204332", "opinion_rapporteur", "AFET", "2025-04-10") in rows
    assert not any(r[2] == "DROI" for r in rows)
    # the other rapporteurs keep the committee the EP API gives
    assert ("197405", "rapporteur", "JURI", "2025-03-18") in rows and ("256805", "opinion_rapporteur", "EMPL", "2025-04-16") in rows


def test_rapporteur_listed_for_a_subcommittee_and_its_committee_is_one_appointment():
    # 2023/0187(CNS): Herbert Dorfmann for FISC (2023-06-27) and for ECON (2024-09-12); OEIL lists him for ECON
    # (rapporteur appointed 12/09/2024, former rapporteur 27/06/2023): one rapporteur entry, the later date
    assert participants_with_oeil("2023-0187") == [("96787", "rapporteur", "ECON", "2024-09-12")]


def built_participants(pid: str, with_oeil: bool = True) -> Procedure:
    """build_procedure on the real EP API participations and OEIL key players of `pid` (fixtures trimmed to those)."""
    proc = json.loads((FIX / f"participants_{pid}.json").read_text(encoding="utf-8"))["data"][0]
    oeil = m.parse_oeil((FIX / f"players_{pid}.html").read_bytes()) if with_oeil else None
    return m.build_procedure({**proc, "process_title": {"en": "Test"}}, RETRIEVED, oeil, lambda i: f"MEP {i}")


def committees_of(p: Procedure) -> list[tuple[str, str, bool]]:
    return [(c.code, c.role, c.former) for c in p.committees]


def test_one_committee_leading_a_file_in_two_terms_is_not_joint():
    # 2023/0226(COD), new genomic techniques: participations 2023-0226-MHE-ENVI and 2023-0226-MAIN-ENVI, both
    # COMMITTEE_LEAD; OEIL "Committee responsible ENVI", "Former committee responsible ENVI",
    # "Former committee for opinion AGRI"
    assert committees_of(built_participants("2023-0226", with_oeil=False)) == [
        ("ENVI", "responsible", False), ("AGRI", "opinion", False)]  # fmt: skip
    assert committees_of(built_participants("2023-0226")) == [("ENVI", "responsible", False), ("AGRI", "opinion", True)]


def test_a_committee_succeeded_by_another_is_former_not_joint():
    # 2023/0131(COD), pharmaceutical package: the EP API gives ENVI (MHE) and SANT (MAIN) as leads; OEIL "Committee
    # responsible SANT – WÖLKEN Tiemo (S&D) 19/02/2025", "Former committee responsible ENVI – WÖLKEN Tiemo (S&D)
    # 11/05/2023", the opinions under "Former committee for opinion"
    p = built_participants("2023-0131")
    assert committees_of(p)[:2] == [("SANT", "responsible", False), ("ENVI", "responsible", True)]
    assert not any(c.role == "joint" for c in p.committees)
    assert {c.code for c in p.committees if c.role == "opinion" and c.former} == {"AGRI", "BUDG", "CONT", "IMCO", "ITRE", "LIBE"}
    wolken = {(r.committee, r.former) for r in p.rapporteurs if r.mep_id == "185619"}
    assert wolken == {("SANT", False), ("ENVI", True)}
    # 2013/0072(COD), air passenger rights: TRAN, then Parliament's delegation to the Conciliation Committee (LEGI)
    p = built_participants("2013-0072")
    assert committees_of(p)[:2] == [("LEGI", "responsible", False), ("TRAN", "responsible", True)]
    # OEIL's former rapporteur ARIAS ECHEVERRÍA Pablo (PPE), whom the EP API does not list
    arias = [r for r in p.rapporteurs if r.mep_id == "96808"]
    assert [(r.role, r.committee, r.former, r.group) for r in arias] == [("rapporteur", "TRAN", True, "PPE")]


def test_a_lead_that_oeil_lists_only_for_an_opinion_is_a_committee_for_opinion():
    # 2024/0061(COD), EDIP: the EP API also gives AFET as a lead (2024-0061-MAIN-AFET); OEIL "Joint committee
    # responsible SEDE / ITRE", "Committee for opinion AFET"
    p = built_participants("2024-0061")
    assert {(c.code, c.role) for c in p.committees if not c.former} == {
        ("SEDE", "joint"), ("ITRE", "joint"), ("AFET", "opinion"), ("CONT", "opinion"), ("IMCO", "opinion"), ("BUDG", "other")}  # fmt: skip


def test_appointments_of_an_earlier_term_are_former():
    # 2023/0290(COD), toy safety: shadow rapporteurs appointed in the 9th term (ECR Beata Mazurek 2023-11-15, The Left
    # Stelios Kouloglou 2024-02-16) beside those of the 10th (ECR Piotr Müller, The Left Luke Ming Flanagan)
    p = built_participants("2023-0290", with_oeil=False)
    shadows = {r.mep_id: r.former for r in p.rapporteurs if r.role == "shadow"}
    assert shadows["197538"] and shadows["130833"]
    assert not shadows["257080"] and not shadows["124985"]
    assert not next(r for r in p.rapporteurs if r.role == "rapporteur").former  # Marion Walsmann, 10th term
    assert [r.former for r in p.rapporteurs] == sorted(r.former for r in p.rapporteurs)  # current ones first


def test_shadow_rapporteurs_that_only_oeil_lists_are_added():
    # 2025/0313(APP): OEIL lists the shadows GYŐRI, NESCI, KELLEHER Billy (Renew), ANDRESEN Rasmus (Greens/EFA) and
    # TRIDICO; the EP API record has 96830, 239260 and 257133 only
    p = build("2025-0313")
    shadows = {r.mep_id: r for r in p.rapporteurs if r.role == "shadow"}
    assert set(shadows) == {"96830", "239260", "257133", "197818", "197448"}
    assert (shadows["197818"].group, shadows["197818"].committee, shadows["197818"].date) == ("Renew", None, None)
    assert (shadows["197448"].group, shadows["197448"].former) == ("Greens/EFA", False)
    assert shadows["96830"].date == "2025-12-15" and shadows["96830"].group is None  # the API's entry, as it was


def test_oeil_tabling_steps_where_the_ep_api_records_none():
    # 2012/0011(COD), GDPR: no EP API TABLING_PLENARY; OEIL "Committee report tabled for plenary, 1st reading"
    # 22/11/2013 A7-0402/2013 and "Committee recommendation tabled for plenary, 2nd reading" 12/04/2016 A8-0139/2016
    p = build("2012-0011")
    tabled = [(e.date, e.title, e.institution, [d.id for d in e.docs]) for e in p.events if "tabled for the plenary" in e.title]
    assert tabled == [
        ("2013-11-22", "Committee report tabled for the plenary", "EP", ["A-7-2013-0402"]),
        ("2016-04-12", "Committee recommendation for second reading tabled for the plenary", "EP", ["A-8-2016-0139"]),
    ]
    docs = {d.id: d for d in p.documents}
    # a key report is dated by its tabling, not by the vote that also cites it (14 April 2016)
    assert (docs["A-8-2016-0139"].label, docs["A-8-2016-0139"].date) == ("A8-0139/2016", "2016-04-12")
    # where the EP API records the tabling, OEIL's is not repeated (2023/0112(COD): A9-0153/2024, A10-0066/2026)
    p = build("2023-0112")
    tabled = [e for e in p.events if "tabled for the plenary" in e.title]
    assert [(e.source.institution, [d.id for d in e.docs]) for e in tabled] == [
        ("EP", ["A-9-2024-0153"]), ("EP", ["A-10-2026-0066"])]  # fmt: skip


def test_commission_document_in_the_old_ep_register_links_eur_lex():
    # OEIL links COM(2012)0011 to /registre/docs_autres_institutions/... (COM(2012)0643 answers 404 there) and gives
    # the EUR-Lex link next to it
    p = build("2012-0011")
    com = next(d for d in p.documents if d.id == "COM(2012)0011")
    assert com.url == ("https://eur-lex.europa.eu/smartapi/cgi/sga_doc?smartapi!celexplus!prod!DocNumber&lg=EN"
                       "&type_doc=COMfinal&an_doc=2012&nu_doc=0011")  # fmt: skip
    assert not any("/registre/" in (d.url or "") for e in p.events for d in e.docs)
    # an unfilled template is not a link (2015/0906(COD): "CELEX:[%SECTOR]2015[%DESCRIPTOR]0110")
    cell = lxml_html.fromstring(
        '<td><a href="https://eur-lex.europa.eu/LexUriServ/LexUriServ.do?uri=CELEX:[%SECTOR]2015[%DESCRIPTOR]0110:EN:NOT">'
        "N8-0110/2015</a></td>"
    )
    assert m._cell_refs(cell) == [("N8-0110/2015", None)]


def test_second_reading_gdpr():
    p = build("2012-0011")
    kinds = [(e.date, e.kind) for e in p.events]
    assert ("2016-04-08", EventKind.council_position) in kinds
    second = [e for e in p.events if e.raw_type and e.raw_type.endswith("PLENARY_APPROVE_COUNCIL_POSITION")]
    assert [e.date for e in second] == ["2016-04-14"]


def test_vote_records_keep_only_the_documents_of_the_file():
    # 2020/0128(COD): MTG-PL-2020-07-08-PVCRE-ITM-18 ("Announcement of voting results") and the items folded into
    # the 10 Jul decision list 20 documents of other files (A9-0131/2020 is Europol and New Zealand, 2020/2048);
    # the file had no committee report: its documents are the proposal and the text adopted (OEIL)
    p = build("2020-0128")
    assert [d.id for d in p.documents] == ["COM(2020)0261", "TA-9-2020-0203"]
    by = {e.id: [d.id for d in e.docs] for e in p.events}
    assert by["MTG-PL-2020-07-08-PVCRE-ITM-18"] == ["PV-9-2020-07-08-ITM-018"]  # the item's own minutes
    # an item based on a single document: the vote on urgent procedure for this file's proposal (C9-0185/2020)
    assert by["MTG-PL-2020-07-08-VOT-ITM-20200708027"] == ["C-9-2020-0185", "PV-9-2020-07-08-VOT-ITM-027"]
    assert not [d for d in by["2020-0128-DEC-DCPL-2020-07-10"] if d.startswith(("A-", "B-", "C-"))]
    # an item of this file alone keeps the registered text it is based on: 2016/0139(COD), 18 Apr 2023, the
    # Council's position C9-0047/2023 and the file's recommendation A9-0076/2023
    second = next(e for e in build("2016-0139").events if e.id == "2016-0139-DEC-DCPL-2023-04-18")
    assert {"C-9-2023-0047", "A-9-2023-0076", "TA-9-2023-0096"} <= {d.id for d in second.docs}


def test_vote_records_keep_the_registered_text_a_vote_on_the_file_names():
    # 2020/0128(COD): the file's own C9-0185/2020 is listed in MTG-PL-2020-07-08-PVCRE-ITM-18 with 19 documents of
    # other files; EP vote 116299 on this file alone is labelled "C9-0185/2020 - Commission proposal"
    p = m.build_procedure(ep_proc("2020-0128"), RETRIEVED, oeil_info("2020-0128"), lambda _id: None,
                          vote_refs={("9", "0185")})  # fmt: skip
    by = {e.id: [d.id for d in e.docs] for e in p.events}
    assert by["MTG-PL-2020-07-08-PVCRE-ITM-18"] == ["C-9-2020-0185", "PV-9-2020-07-08-ITM-018"]
    assert [d for d in by["2020-0128-DEC-DCPL-2020-07-10"] if d.startswith(("A-", "B-", "C-"))] == ["C-9-2020-0185"]
    assert [d.id for d in p.documents] == ["COM(2020)0261", "TA-9-2020-0203"]  # not a key document

    # by term and number (vote 128850 on 2020/0378(COD) prints "C9-0430/2021" for C-9-2020-0430), and only when
    # the item lists one text of that number
    def item(*docs: str) -> dict:
        return {"process_id": "2020-0378", "consists_of": [{
            "activity_id": "MTG-PL-2021-03-11-PVCRE-ITM-4", "activity_date": "2021-03-11",
            "had_activity_type": "def/ep-activities/PLENARY_VOTE",
            "based_on_a_realization_of": [f"eli/dl/doc/{d}" for d in docs]}]}  # fmt: skip

    def kept(proc: dict) -> list[str]:
        (e,) = m.build_events(proc, RETRIEVED, None, "2020/0378(COD)", {("9", "0430")})
        return [d.id for d in e.docs]

    assert kept(item("C-9-2020-0431", "C-9-2020-0430", "A-9-2021-0016")) == ["C-9-2020-0430"]
    assert kept(item("C-9-2019-0430", "C-9-2020-0430", "A-9-2021-0016")) == []


def test_vote_label_refs_are_read_from_votes_on_one_file(monkeypatch):
    from types import SimpleNamespace

    # the ep_votes snapshot's labels (vote 117279) of votes on one file only
    votes = [SimpleNamespace(title="C9-0186/2020 - Commission Proposal", procedure_refs=["2020/0127(COD)"]),
             SimpleNamespace(title="C9-0001/2020 - joint", procedure_refs=["2020/0001(COD)", "2020/0002(COD)"])]  # fmt: skip
    monkeypatch.setattr(m, "read_records", lambda *a: votes)
    assert m.vote_label_refs() == {"2020-0127": {("9", "0186")}}


def test_vote_records_fold_into_parliaments_decision_on_negotiations():
    # 2016/0133(COD), 16 Nov 2017: the vote record of the day belongs to the vote confirming the committee's
    # mandate; no separate "Results of vote in Parliament" entry
    day = [e for e in build("2016-0133").events if e.date == "2017-11-16"]
    assert [(e.id, e.kind) for e in day] == [("2016-0133-DEC-PLEIN1-2017-11-16", EventKind.negotiation_mandate)]
    assert [d.id for d in day[0].docs] == ["A-8-2017-0345", "PV-8-2017-11-16-VOT-ITM-004"]


def test_parse_oeil_reads_references_printed_as_text():
    # 2018/0417(CNS): "<span>COM(2018)0825</span>" followed by a textless EUR-Lex flag link, in the key events and
    # in the Commission's documentation gateway
    info = oeil_info("2018-0417")
    url = "https://eur-lex.europa.eu/smartapi/cgi/sga_doc?smartapi!celexplus!prod!DocNumber&lg=EN&type_doc=COMfinal&an_doc=2018&nu_doc=0825"  # noqa: E501
    assert (info.events[0].label, info.events[0].refs) == ("Legislative proposal published", [("COM(2018)0825", url)])
    assert [(d.id, d.url) for d in info.com_docs] == [("COM(2018)0825", url)]
    p = build("2018-0417")
    assert p.com_refs == ["COM(2018)0825"]
    assert [d.id for e in p.events if e.kind == EventKind.proposal for d in e.docs] == ["COM(2018)0825"]
    # 2016/0357A(COD): the agreed text's references, printed as text, on the committee's approval of it
    approval = next(e for e in build("2016-0357A").events if e.date == "2018-04-25")
    assert [d.id for d in approval.docs] == ["GEDA/A/(2018)003214", "PE622.103"]


def test_proposal_of_another_initiator_named_by_the_documentation_gateway():
    # 2022/0906(COD), amendment of the Statute of the Court of Justice: "CJEC | Legislative proposal | 07307/2022"
    assert oeil_info("2022-0906").other_docs == [("CJEC", "Legislative proposal", "07307/2022")]
    prop = [e for e in build("2022-0906").events if e.kind == EventKind.proposal]
    assert [(e.institution, e.title, [d.id for d in e.docs]) for e in prop] == [
        ("CJEU", "Court of Justice submitted its request (legislative proposal)", ["07307/2022"])
    ]


def test_committee_approval_of_a_text_agreed_in_2nd_reading_negotiations():
    # 2016/0357A(COD) ETIAS: OEIL "25/04/2018 Approval in committee of the text agreed at 2nd reading
    # interinstitutional negotiations"; the title names no reading (Parliament then decided at first reading)
    p = build("2016-0357A")
    e = next(e for e in p.events if e.date == "2018-04-25")
    assert (e.kind, e.title) == (EventKind.provisional_agreement,
                                 "Parliament committee approved the provisional agreement with the Council")  # fmt: skip
    assert "Decision by Parliament, 1st reading" in [x.label for x in oeil_info("2016-0357A").events]


def test_second_reading_committee_steps_are_a_recommendation():
    # 2023/0112(COD): EP API stage RDG2; A10-0066/2026 is a "RECOMMENDATION FOR SECOND READING"
    by = {e.id: e.title for e in build("2023-0112").events}
    assert by["ECON-PR-785218-DEPOT-2026-03-10"] == "Draft recommendation for second reading presented in Parliament committee"
    assert by["2023-0112-DEC-ADCP-2026-03-18"] == "Parliament committee adopted its recommendation for second reading"
    assert by["2023-0112-DEPOT-2026-03-19"] == "Committee recommendation for second reading tabled for the plenary"
    rdg1 = "http://publications.europa.eu/resource/authority/procedure-phase/RDG1"
    assert m.activity_title("COMMITTEE_ADOPTING_REPORT", rdg1)[1] == "Parliament committee adopted its report"


def test_consultation_decision_recorded_as_amendments_carries_the_text_adopted():
    # 2018/0173(CNS), 24 Oct 2018: EP API PLENARY_AMEND without the text; OEIL "Decision by Parliament T8-0415/2018"
    e = next(e for e in build("2018-0173").events if e.id == "2018-0173-DEC-DCPL-2018-10-24")
    ta = next(d for d in e.docs if d.id == "TA-8-2018-0415")
    assert (ta.label, ta.kind, ta.date) == ("T8-0415/2018", "adopted_text", "2018-10-24")


# ---------------------------------------------------------------- fetch orchestration
class FakeHttp:
    """Serves the captured fixtures in place of the network and counts requests."""

    def __init__(self):
        self.detail_calls: list[str] = []
        self.oeil_calls: list[str] = []

    def get(self, url, params=None, **kw):
        if url == m.OEIL_FILE:
            pid = m.normalize_proc_id(params["reference"])
            self.oeil_calls.append(pid)
            return self._fixture(f"oeil_{pid}.html", url)
        if url.startswith(f"{m.EP_API}/procedures/"):
            pid = url.rsplit("/", 1)[1]
            self.detail_calls.append(pid)
            return self._fixture(f"ep_{pid}.json", url)
        raise m.HttpError(url, 404, "not in fixtures")

    @staticmethod
    def _fixture(name, url):
        for path in (FIX / name, FIX / "discovery" / name):
            if path.exists():
                return path.read_bytes()
        raise m.HttpError(url, 404, "not in fixtures")  # the real API/OEIL answer 404 for unknown ids

    def get_json(self, url, params=None, **kw):
        if url == f"{m.EP_API}/procedures":
            if params["process-type"] == "COD":
                return json.loads((FIX / "ep_list_COD.json").read_text())
            return {"data": [], "meta": {"total": 0}}
        if url == f"{m.EP_API}/meps":
            return {"data": []}
        return json.loads(self.get(url, params=params))


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    """Isolated data/snapshot with the real eurlex fixture acts; fixed 'today'; no env overrides."""
    import pipeline.snapshot as snap

    monkeypatch.setattr(snap, "SNAPSHOT", tmp_path)
    (tmp_path / "eurlex").mkdir()
    (tmp_path / "eurlex" / "acts.json").write_text((FIX / "eurlex_acts.json").read_text(), encoding="utf-8")
    monkeypatch.setattr(m, "featured_ids", lambda: ["2012-0011"])
    monkeypatch.setattr(m, "_today", lambda: date(2026, 10, 22))
    monkeypatch.setattr(m, "EP_API_GAP_S", 0.0)
    monkeypatch.setattr(m, "OEIL_GAP_S", 0.0)
    for var in ("EU_INTEL_FULL_REFRESH", "EU_INTEL_FETCH_BUDGET_S", "EU_INTEL_FETCH_DEADLINE"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def in_scope() -> set[str]:
    """COD fixtures with reference year >= 2014 (ep_list_COD.json) + the featured GDPR file."""
    listed = {x["process_id"] for x in json.loads((FIX / "ep_list_COD.json").read_text())["data"]}
    return {i for i in listed if int(i[:4]) >= 2014} | {"2012-0011"}


def snapshot_ids(root: Path) -> list[str]:
    return [r["id"] for r in json.loads((root / "ep_procedures" / "procedures.json").read_text())]


def test_fetch_full_run_from_empty_snapshot(snapshot_dir):
    http = FakeHttp()
    status = m.fetch(http)
    assert status.status == "ok", status.note
    ids = snapshot_ids(snapshot_dir)
    assert ids == sorted(ids) and set(ids) == in_scope()
    assert sorted(http.detail_calls) == sorted(in_scope())
    state = json.loads((snapshot_dir / "ep_procedures" / "_state.json").read_text())
    assert state["pending"] == [] and state["last_complete"]
    assert status.records["procedures"] == len(ids) and status.records["pending"] == 0


def test_incremental_run_skips_terminal_procedures(snapshot_dir):
    m.fetch(FakeHttp())
    before = (snapshot_dir / "ep_procedures" / "procedures.json").read_text().splitlines()
    http = FakeHttp()
    status = m.fetch(http)
    assert status.status == "ok", status.note
    fetched = set(http.detail_calls)
    # terminal (in force / withdrawn) and without an event in the last 120 days: reused as is
    skipped = {"2021-0106", "2021-0104", "2022-0051", "2017-0003", "2022-0196"}
    assert fetched == in_scope() - skipped
    assert "2012-0011" in fetched  # featured: always refreshed
    assert {"2024-0098", "2025-0059"} <= fetched  # terminal but with recent events (Oct 2026)
    assert {"2023-0448", "2023-0126", "2018-0329"} <= fetched  # open files
    after = (snapshot_dir / "ep_procedures" / "procedures.json").read_text().splitlines()
    unchanged = [line for line in before if any(f'"id":"{i}"' in line for i in skipped)]
    assert len(unchanged) == len(skipped) and all(line in after for line in unchanged)
    assert status.records["fetched_this_run"] == len(fetched)


def test_full_refresh_env_fetches_everything(snapshot_dir, monkeypatch):
    m.fetch(FakeHttp())
    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")
    http = FakeHttp()
    m.fetch(http)
    assert set(http.detail_calls) == in_scope()


def test_resume_after_interruption(snapshot_dir, monkeypatch):
    monkeypatch.setattr(m, "CHUNK_SIZE", 3)
    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")
    real_chunk = m._fetch_chunk
    calls = {"n": 0}

    def crashing_chunk(run, ids):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated interruption (e.g. CI timeout)")
        return real_chunk(run, ids)

    monkeypatch.setattr(m, "_fetch_chunk", crashing_chunk)
    with pytest.raises(RuntimeError):
        m.fetch(FakeHttp())
    order = sorted(in_scope(), reverse=True)  # fetch order: newest first
    assert set(snapshot_ids(snapshot_dir)) == set(order[:6])  # chunks 1-2 are kept
    state = json.loads((snapshot_dir / "ep_procedures" / "_state.json").read_text())
    assert state["mode"] == "full" and state["pending"] == order[6:]

    monkeypatch.setattr(m, "_fetch_chunk", real_chunk)
    monkeypatch.delenv("EU_INTEL_FULL_REFRESH")
    http = FakeHttp()
    status = m.fetch(http)
    assert status.status == "ok", status.note
    assert set(snapshot_ids(snapshot_dir)) == in_scope()
    assert http.detail_calls[: len(order) - 6] and set(order[6:]) <= set(http.detail_calls)
    first_chunk = set(http.detail_calls[:3])
    assert first_chunk <= set(order[6:])  # pending ids are continued first
    state = json.loads((snapshot_dir / "ep_procedures" / "_state.json").read_text())
    assert state["pending"] == [] and state["last_mode"] == "full"


def test_time_budget_stops_after_a_chunk_and_resumes(snapshot_dir, monkeypatch):
    monkeypatch.setattr(m, "CHUNK_SIZE", 4)
    monkeypatch.setenv("EU_INTEL_FETCH_BUDGET_S", "0")
    status = m.fetch(FakeHttp())
    n = len(in_scope())
    assert status.status == "partial"
    assert f"{n - 4} pending; resumes next run" in status.note
    assert len(snapshot_ids(snapshot_dir)) == 4
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S")
    assert m.fetch(FakeHttp()).status == "ok"
    assert set(snapshot_ids(snapshot_dir)) == in_scope()


# ---------------------------------------------------------------- id discovery
def test_in_scope_ref():
    assert m.in_scope_ref("2016/0224A(COD)") == "2016-0224A"
    assert m.in_scope_ref("2014/0308(CNS)") == "2014-0308"
    assert m.in_scope_ref("2025/0313(APP)") == "2025-0313"
    assert m.in_scope_ref("2013/0001(COD)") is None  # before 2014
    assert m.in_scope_ref("2014/0332(NLE)") is None  # not a legislative type in scope
    assert m.in_scope_ref("COM(2021)0206") is None


def test_split_parts():
    assert m.split_parts("2021-0211", ["2021-0211A", "2021-0211B", "2021-0212", "2021-0211"]) == [
        "2021-0211A",
        "2021-0211B",
    ]


def test_parse_oeil_title():
    info = m.parse_oeil((FIX / "discovery" / "oeil_2018-0900.html").read_bytes())
    assert info.title == "Statute of the Court of Justice: amendment of Protocol No 3"
    assert info.status == "Procedure completed"


def test_invalid_records_are_not_invented():
    def rec(pid):
        return json.loads((FIX / "discovery" / f"ep_{pid}.json").read_text())["data"][0]

    # 2021-0211: no process_id, label, type or title in the EP record; OEIL has no page either
    with pytest.raises(m.InvalidRecord, match="no English title"):
        m.build_procedure(
            {**rec("2021-0211"), "process_id": "2021-0211"},
            RETRIEVED,
            None,
            lambda _: None,
            None,
            "2021/0211(COD)",
        )
    # 2018-0900: one EP record merges 2018/0900(COD) and 2018/0900(NLE)
    with pytest.raises(m.InvalidRecord, match="merges several procedures"):
        m.build_procedure(rec("2018-0900"), RETRIEVED, None, lambda _: None)


def add_discovery_snapshots(root: Path) -> None:
    """Real EP vote and EUR-Lex act records (from the pipeline snapshots) that reference procedures
    missing from the paged list."""
    (root / "ep_votes").mkdir(exist_ok=True)
    (root / "ep_votes" / "votes.json").write_text((FIX / "discovery" / "ep_votes_sample.json").read_text())
    acts = json.loads((root / "eurlex" / "acts.json").read_text())
    acts += json.loads((FIX / "discovery" / "eurlex_acts_sample.json").read_text())
    (root / "eurlex" / "acts.json").write_text(json.dumps(acts, ensure_ascii=False))


def test_discovery_includes_legislative_train_references(snapshot_dir):
    # The digital services tax, 2018/0073(CNS): no act and no EP vote record name it, the Train's file does (real
    # train snapshot record, "Blocked", blocking institution COUNCIL)
    url = ("https://www.europarl.europa.eu/legislative-train/theme-deeper-and-fairer-internal-market-with-a-strengthened-"
           "industrial-base-taxation/file-digital-services-tax-on-revenues-from-certain-digital-tax-services")  # fmt: skip
    rec = {
        "blocking_institution": "COUNCIL", "last_updated": "2023-05-20", "procedure_refs": ["2018/0073(CNS)"],
        "source": {"identifier": "digital-services-tax-on-revenues-from-certain-digital-tax-services",
                   "institution": "LegislativeTrain", "label": "Legislative Train Schedule", "published": "2023-05-20",
                   "retrieved_at": "2026-10-22T17:52:59Z", "url": url},
        "status": "Blocked", "theme": "Deeper and fairer internal market with a strengthened industrial base: taxation",
        "title": "Proposal for a Directive on the common system of a digital services tax on revenues resulting from "
                 "the provision of certain digital services", "url": url,
    }  # fmt: skip
    (snapshot_dir / "train").mkdir(exist_ok=True)
    (snapshot_dir / "train" / "files.json").write_text(json.dumps([rec]))
    assert m.discover_refs()["2018-0073"] == ("2018/0073(CNS)", "train")


def test_discovery_union_of_list_acts_votes_featured(snapshot_dir):
    add_discovery_snapshots(snapshot_dir)
    found = m.discover_refs()
    assert found["2023-0320"] == ("2023/0320(CNS)", "ep_votes")
    assert found["2025-0313"] == ("2025/0313(APP)", "ep_votes")
    assert found["2020-0082"] == ("2020/0082(CNS)", "ep_votes")
    assert found["2021-0211"] == ("2021/0211(COD)", "eurlex")
    assert found["2014-0332"] == ("2014/0332(CNS)", "eurlex")
    assert found["2018-0900"] == ("2018/0900(COD)", "eurlex")

    http = FakeHttp()
    status = m.fetch(http)
    assert status.status == "ok", status.note
    # usable records referenced only by votes are added (CNS / APP files absent from the COD list)
    assert set(snapshot_ids(snapshot_dir)) == in_scope() | {"2023-0320", "2025-0313"}
    state = json.loads((snapshot_dir / "ep_procedures" / "_state.json").read_text())
    assert set(state["unavailable"]) == {"2021-0211", "2018-0900", "2020-0082", "2014-0332"}
    assert "no English title" in state["unavailable"]["2021-0211"]
    assert "merges several procedures" in state["unavailable"]["2018-0900"]
    assert "2018-0900" in status.note and "ids skipped (no usable EP record" in status.note
    assert status.records["unavailable"] == 4

    again = FakeHttp()
    m.fetch(again)  # incremental: a merged/split record is not requested again; 404s and
    calls = set(again.detail_calls)  # records without a title are retried (they may be fixed)
    assert "2018-0900" not in calls
    assert {"2014-0332", "2020-0082", "2021-0211"} <= calls


def test_full_refresh_retries_unavailable_ids(snapshot_dir, monkeypatch):
    add_discovery_snapshots(snapshot_dir)
    m.fetch(FakeHttp())
    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")
    http = FakeHttp()
    m.fetch(http)
    assert {"2021-0211", "2018-0900", "2020-0082", "2014-0332"} <= set(http.detail_calls)


# ---------------------------------------------------------------- failures: OEIL, EP list, time limits
class OeilDown(FakeHttp):
    """OEIL answers HTTP 500 (after Http's own retries) or, with `page`, a 200 page without the file."""

    def __init__(self, page: bytes | None = None):
        super().__init__()
        self.page = page

    def get(self, url, params=None, **kw):
        if url == m.OEIL_FILE:
            self.oeil_calls.append(m.normalize_proc_id(params["reference"]))
            if self.page is not None:
                return self.page
            raise m.HttpError(url, 500, "gave up after 6 attempts: retryable status 500")
        return super().get(url, params=params, **kw)


class ListDown(FakeHttp):
    """GET /procedures (the paged list) answers HTTP 500; single records still work."""

    def get_json(self, url, params=None, **kw):
        if url == f"{m.EP_API}/procedures":
            raise m.HttpError(url, 500, "WebClientRequestException")
        return super().get_json(url, params=params, **kw)


def records_by_id(root: Path) -> dict[str, str]:
    lines = (root / "ep_procedures" / "procedures.json").read_text().splitlines()
    return {json.loads(x.rstrip(","))["id"]: x for x in lines if x.startswith("{")}


def state_of(root: Path) -> dict:
    return json.loads((root / "ep_procedures" / "_state.json").read_text())


@pytest.mark.parametrize(
    "http_down",
    [OeilDown, lambda: OeilDown(b"<html><body><h1>Service temporarily unavailable</h1></body></html>")],
    ids=["oeil-500", "oeil-200-without-procedure-file"],
)
def test_oeil_outage_keeps_enriched_records(snapshot_dir, http_down):
    """An incremental run while OEIL is down must not replace enriched records by stripped ones."""
    m.fetch(FakeHttp())
    before = records_by_id(snapshot_dir)
    http = http_down()
    status = m.fetch(http)
    refetched = set(http.detail_calls)
    assert refetched and set(http.oeil_calls) >= refetched
    assert records_by_id(snapshot_dir) == before  # every record unchanged, byte for byte
    assert status.status == "failed"  # nothing could be refreshed; the snapshot is unchanged
    assert "kept unchanged because their OEIL page could not be read" in status.note
    assert set(state_of(snapshot_dir)["pending"]) == refetched  # retried first by the next run

    again = FakeHttp()  # OEIL is back
    status = m.fetch(again)
    assert status.status == "ok", status.note
    assert set(again.detail_calls[: len(refetched)]) == refetched
    assert state_of(snapshot_dir)["pending"] == []


def test_oeil_failure_for_some_files_is_partial(snapshot_dir):
    m.fetch(FakeHttp())
    before = records_by_id(snapshot_dir)

    class OneDown(FakeHttp):
        def get(self, url, params=None, **kw):
            if url == m.OEIL_FILE and params["reference"] == "2023/0448(COD)":
                raise m.HttpError(url, 503, "gave up")
            return super().get(url, params=params, **kw)

    status = m.fetch(OneDown())
    assert status.status == "partial"  # a previously enriched record could not be re-enriched
    assert "2023-0448" in status.note
    after = records_by_id(snapshot_dir)
    assert after["2023-0448"] == before["2023-0448"]
    assert state_of(snapshot_dir)["pending"] == ["2023-0448"]


def test_new_file_without_oeil_is_recorded_and_retried(snapshot_dir, monkeypatch):
    """A file seen for the first time while OEIL is down: EP data only (as before), refreshed later."""
    monkeypatch.setattr(m, "OUTAGE_STOP", len(in_scope()) + 1)  # every file is tried (the outage stop: below)
    status = m.fetch(OeilDown())
    recs = m.read_records(m.SOURCE_ID, "procedures", Procedure)
    assert recs and all(r.stage_raw is None and not r.subjects for r in recs)
    assert status.status == "partial"
    http = FakeHttp()
    m.fetch(http)
    assert set(http.detail_calls) == {r.id for r in recs}  # "no OEIL data": every one is re-fetched
    assert all(r.stage_raw for r in m.read_records(m.SOURCE_ID, "procedures", Procedure) if r.id != "2012-0011")


def test_record_needing_oeil_title_is_not_dropped_while_oeil_is_down(snapshot_dir):
    add_discovery_snapshots(snapshot_dir)
    m.fetch(OeilDown())
    state = state_of(snapshot_dir)
    # 2021-0211 has no English title in the EP record; without OEIL it cannot be judged "unusable"
    assert "2021-0211" not in state["unavailable"] and "2021-0211" in state["pending"]


def test_oeil_page_check():
    info = m.parse_oeil((FIX / "oeil_2021-0106.html").read_bytes())
    assert info.has_basic_info and info.reference == "2021/0106(COD)"
    m.check_oeil_page(info, "2021/0106(COD)")
    with pytest.raises(m.OeilPageError, match="shows procedure"):
        m.check_oeil_page(info, "2022/0196(COD)")
    with pytest.raises(m.OeilPageError, match="no procedure file"):
        m.check_oeil_page(m.parse_oeil(b"<html><body>Maintenance</body></html>"), "2021/0106(COD)")


def test_listing_outage_resumes_pending_ids(snapshot_dir, monkeypatch):
    monkeypatch.setattr(m, "CHUNK_SIZE", 4)
    monkeypatch.setenv("EU_INTEL_FETCH_BUDGET_S", "0")
    m.fetch(FakeHttp())  # interrupted backfill: one chunk done, the rest pending
    pending = state_of(snapshot_dir)["pending"]
    assert len(pending) == len(in_scope()) - 4
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S")
    http = ListDown()
    status = m.fetch(http)
    assert set(pending) <= set(http.detail_calls)
    assert set(snapshot_ids(snapshot_dir)) == in_scope()
    assert status.status == "partial"
    assert "procedure list was unavailable" in status.note
    assert state_of(snapshot_dir)["pending"] == []


def test_listing_outage_without_snapshot_fails(snapshot_dir):
    with pytest.raises(m.HttpError):
        m.fetch(ListDown())


def test_listing_halves_the_page_on_server_errors():
    class Picky:
        def __init__(self):
            self.limits = []

        def get_json(self, url, params=None, **kw):
            self.limits.append(params["limit"])
            if params["limit"] > 250:
                raise m.HttpError(url, 500, "WebClientRequestException")
            rows = [{"process_id": f"2024-{i:04d}", "label": f"2024/{i:04d}(COD)"} for i in range(300)]
            page = rows[params["offset"] : params["offset"] + params["limit"]]
            return {"data": page, "meta": {"total": len(rows)}}

    http = Picky()
    ids = m.list_procedure_ids(http, "COD")  # type: ignore[arg-type]
    assert len(ids) == 300 and http.limits == [500, 250, 250]

    class Broken(Picky):
        def get_json(self, url, params=None, **kw):
            self.limits.append(params["limit"])
            raise m.HttpError(url, 500, "down")

    broken = Broken()
    with pytest.raises(m.HttpError):
        m.list_procedure_ids(broken, "COD")  # type: ignore[arg-type]
    assert broken.limits == [500, 250, 125]


def test_run_deadline_in_the_past_starts_nothing(snapshot_dir, monkeypatch):
    import time

    m.fetch(FakeHttp())
    before = records_by_id(snapshot_dir)
    monkeypatch.setenv("EU_INTEL_FETCH_DEADLINE", str(time.time() - 1))
    http = FakeHttp()
    status = m.fetch(http)
    assert http.detail_calls == [] and http.oeil_calls == []
    assert status.status == "partial" and "time budget reached" in status.note
    assert records_by_id(snapshot_dir) == before
    assert state_of(snapshot_dir)["pending"]  # the selected ids wait for the next run


def test_budget_stops_starting_ids_inside_a_later_chunk(snapshot_dir, monkeypatch):
    monkeypatch.setattr(m, "CHUNK_SIZE", 4)
    run = m._Run(FakeHttp(), {}, {}, deadline=time_past(), min_progress=4)
    assert not run.out_of_time()  # the first chunk always runs
    run.started = 4
    assert run.out_of_time()
    hard = m._Run(FakeHttp(), {}, {}, hard_deadline=time_past(), min_progress=4)
    assert hard.out_of_time()  # the run-wide deadline applies from the first id


def time_past() -> float:
    import time

    return time.monotonic() - 1


class ApiDown(FakeHttp):
    """GET /procedures/{id} answers HTTP 500 (after Http's own retries) for every id."""

    def get(self, url, params=None, **kw):
        if url.startswith(f"{m.EP_API}/procedures/"):
            self.detail_calls.append(url.rsplit("/", 1)[1])
            raise m.HttpError(url, 500, "gave up")
        return super().get(url, params=params, **kw)


def test_sequential_retries_stop_during_an_outage(snapshot_dir, monkeypatch):
    monkeypatch.setattr(m, "OUTAGE_STOP", 100)  # the parallel pass tries every id (the outage stop: below)
    http = ApiDown()
    status = m.fetch(http)
    n = len(in_scope())
    assert len(http.detail_calls) == n + m.SEQUENTIAL_RETRY_STOP  # parallel pass + 3 one-by-one retries
    assert status.status == "failed"


def test_an_outage_stops_the_parallel_pass(snapshot_dir, monkeypatch):
    """Every EP call fails (with Http's 240 s per call, a chunk of 100 ids could take up to 100 minutes): once
    OUTAGE_STOP ids failed in a row, no new id is started and there is no one-by-one retry."""
    m.fetch(FakeHttp())
    before = records_by_id(snapshot_dir)
    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")  # every id is to be fetched
    http = ApiDown()
    status = m.fetch(http)
    n = len(in_scope())
    assert m.OUTAGE_STOP <= len(http.detail_calls) <= m.OUTAGE_STOP + m.MAX_WORKERS - 1 < n
    assert status.status == "failed" and f"Stopped after {m.OUTAGE_STOP} ids in a row failed" in status.note
    assert records_by_id(snapshot_dir) == before
    assert set(state_of(snapshot_dir)["pending"]) == in_scope()  # all of them resume next run
    monkeypatch.delenv("EU_INTEL_FULL_REFRESH")
    again = FakeHttp()
    assert m.fetch(again).status == "ok" and set(again.detail_calls) == in_scope()


SYNTH = [f"2024-{n:04d}" for n in range(500, 560)]  # 60 open COD files made from the 2023/0448 captures
KEEP_FAILING = {SYNTH[i] for i in (3, 10, 17, 24, 31, 38, 45, 52)}  # OUTAGE_STOP of them, scattered


class Synth(FakeHttp):
    """Lists and serves the SYNTH files. The `bad` ones fail at the EP API (HTTP 500 after Http's retries), or
    with oeil=True their OEIL page does (HTTP 503)."""

    def __init__(self, bad=frozenset(), oeil=False):
        super().__init__()
        self.bad, self.oeil = set(bad), oeil

    def get(self, url, params=None, **kw):
        if url == m.OEIL_FILE:
            pid = m.normalize_proc_id(params["reference"])
            self.oeil_calls.append(pid)
            if self.oeil and pid in self.bad:
                raise m.HttpError(url, 503, "gave up after 6 attempts: retryable status 503")
            page = (FIX / "oeil_2023-0448.html").read_text(encoding="utf-8")
            return page.replace("2023/0448", pid.replace("-", "/")).encode()
        if url.startswith(f"{m.EP_API}/procedures/"):
            pid = url.rsplit("/", 1)[1]
            self.detail_calls.append(pid)
            if not self.oeil and pid in self.bad:
                raise m.HttpError(url, 500, "gave up after 6 attempts: retryable status 500")
            body = (FIX / "ep_2023-0448.json").read_text(encoding="utf-8")
            return body.replace("2023-0448", pid).replace("2023/0448", pid.replace("-", "/")).encode()
        return super().get(url, params=params, **kw)

    def get_json(self, url, params=None, **kw):
        if url == f"{m.EP_API}/procedures":
            if params["process-type"] == "COD" and params["offset"] == 0:
                data = [{"process_id": i, "label": i.replace("-", "/") + "(COD)"} for i in SYNTH]
                return {"data": data, "meta": {"total": len(SYNTH)}}
            return {"data": [], "meta": {"total": 0}}
        return super().get_json(url, params=params, **kw)


@pytest.mark.parametrize("oeil", [False, True], ids=["ep-api-500", "oeil-503"])
def test_files_that_keep_failing_do_not_stop_the_others(snapshot_dir, monkeypatch, oeil):
    """OUTAGE_STOP files that fail in every run used to be resumed first and to trip the outage stop at once,
    so from the third run on the other files were never refreshed again. Ids that failed in an earlier run now
    come last and do not count towards the stop; a real outage still stops the run."""
    monkeypatch.setattr(m, "featured_ids", lambda: [])
    monkeypatch.setattr(m, "discover_refs", lambda: {})
    assert m.fetch(Synth()).status == "ok"
    healthy = set(SYNTH) - KEEP_FAILING
    for run in (2, 3, 4):
        http = Synth(KEEP_FAILING, oeil=oeil)
        status = m.fetch(http)
        assert status.status == "partial" and "Stopped after" not in status.note, status.note
        assert status.records["fetched_this_run"] == len(healthy)
        if run > 2:  # the files that failed before come after every other file
            assert set(http.detail_calls[: len(healthy) - m.MAX_WORKERS]) <= healthy
            assert f"{len(KEEP_FAILING)} files failed in more than one run in a row" in status.note
        state = state_of(snapshot_dir)
        assert set(state["pending"]) == KEEP_FAILING and state["unsettled"]["ids"] == sorted(KEEP_FAILING)
        assert state["failing"] == {i: {"since": "2026-10-22", "runs": run - 1} for i in sorted(KEEP_FAILING)}

    if not oeil:  # an outage: new failures still stop the run after OUTAGE_STOP ids
        down = Synth(set(SYNTH))
        status = m.fetch(down)
        assert status.status == "failed" and f"Stopped after {m.OUTAGE_STOP} ids in a row failed" in status.note
        new_failures = [i for i in down.detail_calls if i not in KEEP_FAILING]
        assert len(set(new_failures)) <= m.OUTAGE_STOP + m.MAX_WORKERS - 1
        assert not set(down.detail_calls) & KEEP_FAILING  # they come last: not reached
        assert set(state_of(snapshot_dir)["pending"]) == set(SYNTH)
    back = Synth()
    assert m.fetch(back).status == "ok" and set(back.detail_calls) == set(SYNTH)
    assert state_of(snapshot_dir)["pending"] == [] and state_of(snapshot_dir)["failing"] == {}


def test_failures_of_ids_that_failed_before_do_not_count_towards_the_outage_stop():
    run = m._Run(FakeHttp(), {}, {}, failed_before=["2024-0503"])
    for _ in range(m.OUTAGE_STOP):
        run.note_result(False, "2024-0503")
    assert not run.outage and not run.out_of_time()
    for _ in range(m.OUTAGE_STOP - 1):
        run.note_result(False, "2024-0504")
    run.note_result(False, "2024-0503")  # does not count, nor does it reset the run of new failures
    assert not run.outage
    run.note_result(False, "2024-0505")
    assert run.outage


def test_budget_applies_to_the_first_chunk_once_ids_keep_failing(snapshot_dir, monkeypatch):
    run = m._Run(FakeHttp(), {}, {}, deadline=time_past(), min_progress=100)
    assert not run.out_of_time()  # the first chunk normally runs whatever the budget
    for _ in range(m.SEQUENTIAL_RETRY_STOP):
        run.note_result(False)
    assert run.out_of_time()  # ... but not while its ids keep failing
    run.note_result(True)
    assert not run.out_of_time()
    within = m._Run(FakeHttp(), {}, {}, min_progress=100)  # budget not reached: only an outage stops it
    for _ in range(m.OUTAGE_STOP - 1):
        within.note_result(False)
    assert not within.out_of_time()
    within.note_result(False)
    assert within.out_of_time() and within.outage

    # a whole run with the budget already used up: a few ids are tried, not the whole first chunk
    monkeypatch.setattr(m, "OUTAGE_STOP", 100)
    monkeypatch.setenv("EU_INTEL_FETCH_BUDGET_S", "0")
    http = ApiDown()
    status = m.fetch(http)
    assert len(http.detail_calls) <= m.SEQUENTIAL_RETRY_STOP + m.MAX_WORKERS - 1 < len(in_scope())
    assert status.status == "partial" and "time budget reached" in status.note
    assert set(state_of(snapshot_dir)["pending"]) == in_scope()


class OeilGone(FakeHttp):
    """OEIL answers 404 for 2023/0448(COD) (e.g. a file OEIL replaced or split), whose record has OEIL data."""

    def get(self, url, params=None, **kw):
        if url == m.OEIL_FILE and params["reference"] == "2023/0448(COD)":
            self.oeil_calls.append("2023-0448")
            raise m.HttpError(url, 404, "no procedure file")
        return super().get(url, params=params, **kw)


def test_persistent_oeil_404_stops_being_pending(snapshot_dir):
    m.fetch(FakeHttp())
    before = records_by_id(snapshot_dir)["2023-0448"]
    seen = []
    for _ in range(m.OEIL_GONE_RUNS + 1):
        status = m.fetch(OeilGone())
        seen.append((status.status, state_of(snapshot_dir)["pending"]))
        assert records_by_id(snapshot_dir)["2023-0448"] == before  # the stored record (with OEIL data) stays
    # pending while it may be a passing problem, then kept as is: the source is no longer partial for good
    assert seen == [("partial", ["2023-0448"])] * (m.OEIL_GONE_RUNS - 1) + [("ok", [])] * 2
    assert "OEIL no longer has a procedure file" in status.note and "2023-0448 (since 2026-10-22)" in status.note
    assert state_of(snapshot_dir)["oeil_gone"]["2023-0448"]["runs"] == m.OEIL_GONE_RUNS + 1
    assert state_of(snapshot_dir)["unsettled"]["ids"] == []
    m.fetch(FakeHttp())  # the OEIL file is back: the record is read again and the count is cleared
    assert state_of(snapshot_dir)["oeil_gone"] == {}


def test_unsettled_ids_are_recorded_for_change_detection(snapshot_dir):
    """_state.json names the files this run did not refresh completely, stamped with the run's attempted_at
    (that of its manifest entry), so change detection sets them aside instead of every file."""
    first = m.fetch(FakeHttp())
    assert state_of(snapshot_dir)["unsettled"] == {"attempted_at": first.attempted_at, "ids": []}

    class SomeDown(FakeHttp):  # OEIL fails for an enriched file and for a new one
        def get(self, url, params=None, **kw):
            if url == m.OEIL_FILE and params["reference"] in ("2023/0448(COD)", "2023/0320(CNS)"):
                raise m.HttpError(url, 503, "gave up")
            return super().get(url, params=params, **kw)

    add_discovery_snapshots(snapshot_dir)  # brings in 2023-0320, new in this run
    status = m.fetch(SomeDown())
    state = state_of(snapshot_dir)
    assert state["unsettled"]["attempted_at"] == status.attempted_at
    # 2023-0448: kept as it was and pending; 2023-0320: recorded with EP API data only
    assert state["unsettled"]["ids"] == ["2023-0320", "2023-0448"]
    rec = {r.id: r for r in m.read_records(m.SOURCE_ID, "procedures", Procedure)}
    assert rec["2023-0320"].stage_raw is None
    m.fetch(FakeHttp())
    assert state_of(snapshot_dir)["unsettled"]["ids"] == []


def test_listing_remembers_the_page_size_and_fails_fast(snapshot_dir):
    class SmallPagesOnly(FakeHttp):
        def __init__(self):
            super().__init__()
            self.list_calls: list[tuple[str, int, int | None]] = []

        def get_json(self, url, params=None, **kw):
            if url == f"{m.EP_API}/procedures":
                self.list_calls.append((params["process-type"], params["limit"], kw.get("retries")))
                if params["process-type"] == "COD" and params["limit"] > 125:
                    raise m.HttpError(url, 500, "WebClientRequestException")
            return super().get_json(url, params=params, **kw)

    http = SmallPagesOnly()
    assert m.fetch(http).status == "ok"
    # a single attempt at 500 and at 250 (no retries before halving); Http's usual retries at the smallest page
    cod = [c for c in http.list_calls if c[0] == "COD"]
    assert cod == [("COD", 500, 0), ("COD", 250, 0), ("COD", 125, None)]
    assert state_of(snapshot_dir)["list_page"] == {"APP": 500, "CNS": 500, "COD": 125}
    again = SmallPagesOnly()
    m.fetch(again)
    assert [c for c in again.list_calls if c[0] == "COD"] == [("COD", 125, None)]  # starts at the size that worked


# ---------------------------------------------------------------- live
@pytest.mark.network
def test_live_ai_act_shape():
    from pipeline.http import default_http

    http = default_http()
    proc = m.as_list(http.get_json(f"{m.EP_API}/procedures/2021-0106", params=m.JSONLD)["data"])[0]
    p = m.build_procedure(proc, RETRIEVED, None, lambda _id: None)
    assert p.reference == "2021/0106(COD)"
    assert any(e.kind == EventKind.signature and e.date == "2024-06-13" for e in p.events)
