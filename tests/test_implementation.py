"""Tests for pipeline.sources.implementation (offline; fixtures are real trimmed responses)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from pipeline import snapshot
from pipeline.http import HttpError
from pipeline.models.entities import InfringementCase, NationalMeasure
from pipeline.sources import implementation as imp

FX = Path(__file__).parent / "fixtures" / "implementation"
NOW = "2026-10-22T00:00:00Z"
NIS2 = "32022L2555"


def sparql_rows(name: str) -> list[dict[str, str]]:
    d = json.loads((FX / name).read_text(encoding="utf-8"))
    return [{k: v["value"] for k, v in b.items()} for b in d["results"]["bindings"]]


def cases_fixture() -> list[dict]:
    return json.loads((FX / "themis_cases_sample.json").read_text(encoding="utf-8"))["records"]


def names() -> dict[str, str]:
    return imp.country_names(
        json.loads((FX / "themis_refdata_memberstate_en.json").read_text(encoding="utf-8"))
    )


# ------------------------------------------------------------------ national implementing measures
def test_directive_celex_only():
    assert imp.is_directive_celex("32022L2555")
    assert not imp.is_directive_celex("32024R1689")  # regulation
    assert not imp.is_directive_celex("32022D2481")  # decision
    assert not imp.is_directive_celex("32019L0790R(01)")  # corrigendum
    assert not imp.is_directive_celex(None)
    with pytest.raises(ValueError):
        imp.measures_query("32024R1689")
    with pytest.raises(ValueError):
        imp.parse_measure_rows("32024R1689", [], NOW)


def test_parse_measures_nis2():
    recs = imp.parse_measure_rows(NIS2, sparql_rows("cellar_nim_32022L2555.json"), NOW)
    assert recs and all(isinstance(r, NationalMeasure) for r in recs)
    assert all(r.directive_celex == NIS2 for r in recs)
    assert len({r.id for r in recs}) == len(recs)
    assert all(r.id.startswith("72022L2555") for r in recs)
    assert all(r.title for r in recs)
    assert all(
        r.source.url == "https://eur-lex.europa.eu/legal-content/EN/NIM/?uri=CELEX:32022L2555" for r in recs
    )
    assert all(r.source.identifier and r.source.identifier.startswith("MNE(") for r in recs)
    # alpha-3 authority codes normalised to ISO alpha-2
    assert set(Counter(r.country for r in recs)) == {"CZ", "IT", "LU", "MT", "PL", "SE"}

    mt = next(r for r in recs if r.id == "72022L2555MLT_202501976")
    assert mt.country == "MT"
    assert mt.date == "2025-04-08"
    assert (
        mt.title
        == "Measures for a High Common Level of Cybersecurity across the European Union (Malta) Order, 2025"
    )
    assert mt.source.identifier == "MNE(2025)01976"
    assert mt.url and mt.url.startswith("https://")


def test_placeholder_dates_are_dropped():
    rows = sparql_rows("cellar_nim_32022L2555.json")
    placeholder = {r["m"] for r in rows if r.get("doj") == "1001-01-01"}
    assert placeholder, "fixture should contain Cellar's 1001-01-01 placeholder"
    recs = imp.parse_measure_rows(NIS2, rows, NOW)
    assert all(r.date != "1001-01-01" for r in recs)
    assert sum(1 for r in recs if r.date is None) >= len(placeholder)
    assert imp._clean_date("9999-12-31") is None
    assert imp._clean_date("2025-04-08T10:00:00.000+02:00") == "2025-04-08"


def test_absence_of_measures_creates_no_records():
    """No placeholder/"missing" records: absence is not a finding (UI shows NO_MEASURES_LABEL)."""
    recs = imp.parse_measure_rows(NIS2, sparql_rows("cellar_nim_32022L2555.json"), NOW)
    assert "IE" not in {r.country for r in recs}  # Ireland: no NIS2 measure in this fixture
    assert imp.parse_measure_rows(NIS2, [], NOW) == []
    assert imp.NO_MEASURES_LABEL == "No measures found in the available dataset"


def test_measure_model_has_no_compliance_judgement():
    """A notified measure is not an assessment of correct transposition: no such field exists."""
    fields = set(NationalMeasure.model_fields)
    assert not fields & {"compliant", "complete", "correct", "status", "score", "conformity"}


def test_featured_directives_filters_non_directives(tmp_path):
    p = tmp_path / "featured.yaml"
    p.write_text(
        "acts:\n  - celex: 32022L2555\n  - celex: 32024R1689\n  - {celex: [32019L0790, 32022L2464]}\n",
        encoding="utf-8",
    )
    assert imp.featured_directives(p) == ["32019L0790", "32022L2464", "32022L2555"]
    assert imp.featured_directives(tmp_path / "missing.yaml") == []


# ----------------------------------------------------------------------------- infringements
def test_export_legal_basis():
    lb = imp.parse_export_legal_basis((FX / "themis_export_32019L0790.xlsx").read_bytes())
    assert len(lb) == 23
    assert lb["INFR(2021)0330"] == ["32019L0790"]
    assert all(v == ["32019L0790"] for v in lb.values())


def test_single_act_celex_only_when_unambiguous():
    assert imp.single_act_celex(["32019L0790"]) == "32019L0790"
    # Treaty articles are not the act concerned
    assert imp.single_act_celex(["12008E260§2", "32008L0050"]) == "32008L0050"
    # several acts named by the register: do not choose
    assert imp.single_act_celex(["32005L0036", "32013L0055"]) is None
    assert imp.single_act_celex([]) is None
    assert imp.single_act_celex(None) is None


def test_parse_cases_stage_verbatim_and_status():
    lb = imp.parse_export_legal_basis((FX / "themis_export_32019L0790.xlsx").read_bytes())
    cases = {c.id: c for c in (imp.parse_case(r, names(), NOW, lb) for r in cases_fixture()) if c}
    assert all(isinstance(c, InfringementCase) for c in cases.values())

    pt = cases["INFR(2021)0330"]  # referred to Court, later closed
    assert pt.country == "PT" and pt.status == "closed"
    assert pt.latest_stage == "Closing of the case"
    assert pt.latest_decision_date == "2025-12-11"
    assert pt.celex == "32019L0790"  # stated in the register's legal-basis column
    assert pt.non_communication is True

    ie = cases["INFR(2024)0279"]  # open case at referral stage: NOT a Court judgment
    assert ie.country == "IE" and ie.status == "open"
    assert ie.latest_stage == "Referral to Court Art. 258 TFEU  - 260(3) TFEU"  # verbatim, double space kept
    assert ie.latest_decision_date == "2026-07-08"
    assert ie.celex is None  # no legal-basis data for this case in the fixture -> no guess

    pl = cases["INFR(2019)2137"]
    assert pl.non_communication is False and pl.status == "open"
    assert pl.latest_stage == "Reasoned opinion Art. 258 TFEU"
    assert pl.latest_decision_date == "2024-12-16"

    assert cases["INFR(2024)0155"].country == "GR"  # register key "EL"
    assert cases["INFR(2011)2054"].country == "GB"  # register key "UK"
    for c in cases.values():
        assert c.source.institution == "Commission"
        assert c.source.identifier == c.id
        assert "refId=INFR%28" in c.source.url


def test_latest_stage_matches_a_source_decision_type():
    for rec in cases_fixture():
        c = imp.parse_case(rec, names(), NOW)
        assert c is not None
        assert c.latest_stage in {d["decisionType"] for d in rec["decisions"]}


def test_ddmmyyyy():
    assert imp._ddmmyyyy("1/06/2023") == "2023-06-01"
    assert imp._ddmmyyyy("29/01/2026") == "2026-01-29"
    assert imp._ddmmyyyy("31/02/2026") is None
    assert imp._ddmmyyyy(None) is None


# ------------------------------------------------------------------------------ fetch() wiring
class FakeHttp:
    """Serves fixtures; the Scoreboard host is blocked as observed live (CloudFront 403)."""

    def sparql(self, query: str, **kw):
        if "measure_national_implementing_implements_resource_legal" in query:
            return sparql_rows("cellar_nim_32022L2555.json") if NIS2 in query else []
        return [{"celex": NIS2}, {"celex": "32019L0790R(01)"}]

    def get(self, url: str, **kw):
        raise HttpError(url, 403, "Request blocked")

    def get_json(self, url: str, **kw):
        return json.loads((FX / "themis_refdata_memberstate_en.json").read_text(encoding="utf-8"))

    def request(self, method: str, url: str, **kw):
        if url.endswith("/export"):
            return (FX / "themis_export_32019L0790.xlsx").read_bytes()
        body = json.loads(kw["data"])
        recs = cases_fixture() if body["page"] == 0 else []
        return json.dumps({"totalRows": len(cases_fixture()), "records": recs}).encode()


def test_fetch_writes_only_succeeded_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.setattr(imp, "FEATURED_YAML", tmp_path / "none.yaml")
    st = imp.fetch(FakeHttp())  # type: ignore[arg-type]
    out = tmp_path / imp.SOURCE_ID
    assert (out / "measures.json").exists()
    assert (out / "infringements.json").exists()
    assert not (out / "indicators.json").exists()  # scoreboard unreachable -> nothing written
    assert st.status == "partial"
    assert st.records["measures"] == 11 and st.records["infringements"] == 6
    assert "indicators" not in st.records
    assert "403" in (st.note or "")
    measures = snapshot.read_records(imp.SOURCE_ID, "measures", NationalMeasure)
    assert {m.directive_celex for m in measures} == {NIS2}  # corrigendum CELEX never queried


# ------------------------------------------------------------------------------- live checks
@pytest.mark.network
def test_live_nis2_measures():
    from pipeline.http import default_http

    recs = imp.parse_measure_rows(NIS2, default_http().sparql(imp.measures_query(NIS2)), NOW)
    assert len({r.country for r in recs}) >= 20


@pytest.mark.network
def test_live_register_search():
    from pipeline.http import default_http

    recs = imp.search_cases(default_http(), refId="INFR(2021)0330")
    assert recs and recs[0]["infringementNumber"] == "INFR(2021)0330"
