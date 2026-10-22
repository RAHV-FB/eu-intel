"""Tests for pipeline.sources.ep_procedures (offline, on real trimmed captures).

Fixtures in tests/fixtures/ep_procedures/:
- ep_<id>.json: EP Open Data API v2 GET /procedures/<id> (format=application/ld+json), 2026-10-22
- oeil_<id>.html: OEIL procedure file, trimmed (see the comment at the top of each file)
- ep_list_COD.json: GET /procedures?process-type=COD, data reduced to the fixture procedures
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_second_reading_gdpr():
    p = build("2012-0011")
    kinds = [(e.date, e.kind) for e in p.events]
    assert ("2016-04-08", EventKind.council_position) in kinds
    second = [e for e in p.events if e.raw_type and e.raw_type.endswith("PLENARY_APPROVE_COUNCIL_POSITION")]
    assert [e.date for e in second] == ["2016-04-14"]


# ---------------------------------------------------------------- fetch orchestration
class FakeHttp:
    """Serves the captured fixtures in place of the network."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url, params=None, **kw):
        self.calls.append(url)
        if url == m.OEIL_FILE:
            pid = m.normalize_proc_id(params["reference"])
            path = FIX / f"oeil_{pid}.html"
            if not path.exists():
                raise m.HttpError(url, 404, "not in fixtures")
            return path.read_bytes()
        if url.startswith(f"{m.EP_API}/procedures/"):
            pid = url.rsplit("/", 1)[1]
            return (FIX / f"ep_{pid}.json").read_bytes()
        raise m.HttpError(url, 404, "not in fixtures")

    def get_json(self, url, params=None, **kw):
        if url == f"{m.EP_API}/procedures":
            if params["process-type"] == "COD":
                return json.loads((FIX / "ep_list_COD.json").read_text())
            return {"data": [], "meta": {"total": 0}}
        if url == f"{m.EP_API}/meps":
            return {"data": []}
        return json.loads(self.get(url, params=params))


def test_fetch_end_to_end_offline(monkeypatch):
    written = {}

    def fake_write(source, name, records, key=None):
        recs = sorted(records, key=key) if key else list(records)
        written[(source, name)] = recs
        return Path("/dev/null")

    monkeypatch.setattr(m, "write_records", fake_write)
    monkeypatch.setattr(m, "featured_ids", lambda: ["2012-0011"])
    monkeypatch.setattr(m, "read_records", lambda *a, **k: [])
    monkeypatch.setattr(m, "EP_API_GAP_S", 0.0)
    monkeypatch.setattr(m, "OEIL_GAP_S", 0.0)
    status = m.fetch(FakeHttp())
    recs = written[("ep_procedures", "procedures")]
    ids = [r.id for r in recs]
    assert ids == sorted(ids)
    # every COD fixture with reference year >= 2014, plus the featured GDPR file (2012)
    expected = {
        p.stem[3:] for p in FIX.glob("ep_2*.json") if ep_proc(p.stem[3:])["process_type"].endswith("COD")
    }
    assert set(ids) == {i for i in expected if int(i[:4]) >= 2014} | {"2012-0011"}
    assert status.status == "ok", status.note
    assert status.records["procedures"] == len(recs)


# ---------------------------------------------------------------- live
@pytest.mark.network
def test_live_ai_act_shape():
    from pipeline.http import default_http

    http = default_http()
    proc = m.as_list(http.get_json(f"{m.EP_API}/procedures/2021-0106", params=m.JSONLD)["data"])[0]
    p = m.build_procedure(proc, RETRIEVED, None, lambda _id: None)
    assert p.reference == "2021/0106(COD)"
    assert any(e.kind == EventKind.signature and e.date == "2024-06-13" for e in p.events)
