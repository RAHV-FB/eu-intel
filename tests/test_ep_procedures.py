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
    for var in ("EU_INTEL_FULL_REFRESH", "EU_INTEL_FETCH_BUDGET_S"):
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


# ---------------------------------------------------------------- live
@pytest.mark.network
def test_live_ai_act_shape():
    from pipeline.http import default_http

    http = default_http()
    proc = m.as_list(http.get_json(f"{m.EP_API}/procedures/2021-0106", params=m.JSONLD)["data"])[0]
    p = m.build_procedure(proc, RETRIEVED, None, lambda _id: None)
    assert p.reference == "2021/0106(COD)"
    assert any(e.kind == EventKind.signature and e.date == "2024-06-13" for e in p.events)
