"""Tests for the Council voting-results source (offline: real trimmed documents in tests/fixtures/council/).

Fixtures
- *.page1.txt / *.txt: `pdftotext -layout` of real Council "Voting result" notes (data.consilium.europa.eu).
- *.annex.pdf: the annex page (GSC voting sheet image) of real notes, cut out with `pdfseparate`.
- sparql_voting_results.json: real Cellar SPARQL rows for a few notes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.sources import council as C

FIX = Path(__file__).parent / "fixtures" / "council"
needs_poppler = pytest.mark.skipif(not C.poppler_available(), reason="poppler-utils not installed")


def text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def pages(name: str) -> list[str]:
    p = text(name).split("\f")
    return p[:-1] if p and not p[-1].strip() else p


def annex(doc: str) -> C.Sheet:
    pdf = (FIX / f"{doc}.annex.pdf").read_bytes()
    return C.analyse_sheet(C.render_page(pdf, 1))


def rows() -> list[dict[str, str]]:
    return json.loads((FIX / "sparql_voting_results.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ page 1 (text)
def test_parse_note_ai_act():
    m = C.parse_note(text("ST-10199-2024-INIT.page1.txt"))
    assert m.procedure_refs == ["2021/0106(COD)"]
    assert m.doc_number == "10199/24"
    assert m.title.startswith(
        "REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL laying down harmonised rules on artificial intelligence"
    )
    assert m.title.endswith("(Artificial Intelligence Act)")
    assert m.step == "Adoption of the Legislative Act"
    assert (m.meeting, m.configuration) == ("4024", "Transport, Telecommunications and Energy")
    assert m.meeting_dates == ["2024-05-21"]
    assert m.council_doc == "PE-CONS 24/24"
    assert m.written_procedure_date is None and m.nullified == []


def test_parse_note_written_procedure_and_statements():
    p = pages("ST-9552-2024-INIT.txt")
    m = C.parse_note(p[0])
    assert (
        m.title
        == "Regulation of the European Parliament and of the Council establishing the Ukraine Facility"
    )
    assert m.written_procedure_date == "2024-02-28"
    assert m.meeting is None and m.configuration is None
    assert m.procedure_refs == ["2023/0200(COD)"]
    assert m.council_doc == "PE-CONS 10/24"
    assert C.parse_statements(p) == [
        "Declaration by the Commission on its institutional prerogatives in relation to budget "
        "implementation within the framework of the Ukraine Facility",
        "Statement by the Republic of Bulgaria",
    ]


def test_parse_note_council_position_multi_day_meeting():
    m = C.parse_note(pages("ST-14522-2025-REV-1.txt")[0])
    assert m.title.startswith(
        "Position of the Council at first reading with a view to the adoption of a REGULATION"
    )
    assert C._act_type(m.title) == "council_position"
    assert m.configuration == "Agriculture and Fisheries Council"
    assert m.meeting_dates == ["2025-10-27", "2025-10-28"]
    assert m.council_doc == "ST 10498/25"
    assert m.procedure_refs == ["2023/0129(COD)"]


def test_corrigenda():
    void = C.parse_note(pages("ST-15212-2024-COR-1.txt")[0])
    assert void.nullified == ["INIT"]
    assert void.procedure_refs == ["2023/0237(COD)"]
    assert void.meeting_dates == ["2024-11-05"]
    fix = C.parse_note(pages("ST-14997-2018-COR-1.txt")[0])
    assert fix.procedure_refs == ["2016/0288(COD)"]  # the corrigendum's purpose
    assert fix.meeting_dates == ["2018-12-03", "2018-12-04"]
    app = C.parse_note(pages("ST-9742-2026-COR-1.txt")[0])
    assert app.procedure_refs == ["2025/0900(APP)"]
    assert C._act_type(app.title) == "decision"
    assert app.configuration == "General Affairs"


def test_parse_dates():
    assert C.parse_dates("21 May 2024, Brussels") == ["2024-05-21"]
    assert C.parse_dates("3 and 4 December 2018, Brussels") == ["2018-12-03", "2018-12-04"]
    assert C.parse_dates("27-28 October 2025, Luxembourg") == ["2025-10-27", "2025-10-28"]
    assert C.parse_dates("no date") == []


# ------------------------------------------------------------------ Cellar listing
def test_versions_from_sparql_rows():
    groups = C._versions_from_rows(rows())
    assert [v.suffix for v in groups["ST-15212-2024"]] == ["INIT", "REV_1", "COR_1"]
    ai = groups["ST-10199-2024"][0]
    assert ai.doc_id == "ST-10199-2024-INIT"
    assert ai.events == ["2024-05-21"]  # from the procedure-event URI
    assert groups["ST-9584-2019"][0].events == ["2019-05-22"]  # from the Cellar event's date
    assert C._event_date(["2025-10-28"], ["2025-10-27", "2025-10-28"]) == "2025-10-28"
    assert C._event_date(["2025-11-03"], ["2025-10-27", "2025-10-28"]) is None


# ------------------------------------------------------------------ annex (voting sheet image)
@needs_poppler
def test_sheet_ai_act_all_in_favour():
    s = annex("ST-10199-2024-INIT")
    assert s.rule == "qmv" and s.outcome == "adopted"
    pos = C.sheet_positions(s, "2024-05-21")
    assert len(pos) == 27 and set(pos.values()) == {"for"}


@needs_poppler
def test_sheet_eurodac_against_abstain_not_participating():
    s = annex("ST-9841-2024-INIT")
    pos = C.sheet_positions(s, "2024-05-14")
    assert s.rule == "qmv" and s.outcome == "adopted"
    assert {c for c, p in pos.items() if p == "not_participating"} == {"DK", "IE"}
    assert {c for c, p in pos.items() if p == "against"} == {"HU", "PL"}
    assert {c for c, p in pos.items() if p == "abstain"} == {"CZ", "SK"}
    assert sum(1 for p in pos.values() if p == "for") == 21


@needs_poppler
def test_sheet_unanimity_2026():
    s = annex("ST-9746-2026-INIT")
    assert s.rule == "unanimity" and s.outcome == "adopted"
    assert set(C.sheet_positions(s, "2026-05-26").values()) == {"for"}


@needs_poppler
def test_sheet_eu28_with_united_kingdom():
    s = annex("ST-9584-2019-INIT")
    pos = C.sheet_positions(s, "2019-05-22")
    assert len(pos) == 28 and pos["GB"] == "for" and pos["DE"] == "abstain"
    assert sum(1 for p in pos.values() if p == "for") == 27
    with pytest.raises(C.SheetError):
        C.sheet_positions(s, "2020-03-01")  # 28th slot filled after the UK left


@needs_poppler
def test_build_vote_ai_act():
    groups = C._versions_from_rows(rows())
    v = groups["ST-10199-2024"][0]
    page1 = text("ST-10199-2024-INIT.page1.txt")
    parsed = C.Parsed(v, [page1, ""], C.parse_note(page1), annex("ST-10199-2024-INIT"), None)
    vote, problem = C.build_vote([parsed], "2026-10-22T00:00:00Z")
    assert problem is None
    assert vote.id == "ST-10199-2024"
    assert vote.date == "2024-05-21"
    assert vote.procedure_refs == ["2021/0106(COD)"]
    assert vote.council_doc == "PE-CONS 24/24"
    assert vote.configuration == "Transport, Telecommunications and Energy"
    assert (vote.voting_rule, vote.outcome, vote.act_type) == ("qmv", "adopted", "regulation")
    assert set(vote.positions.values()) == {"for"} and len(vote.positions) == 27
    assert vote.source.institution == "Council"
    assert vote.source.url == "https://data.consilium.europa.eu/doc/document/ST-10199-2024-INIT/EN/pdf"
    assert vote.source.identifier == "ST 10199 2024 INIT"


def test_build_vote_drops_nullified_versions_and_keeps_sheetless_metadata():
    groups = C._versions_from_rows(rows())
    init, _rev, cor = groups["ST-15212-2024"]
    cor_pages = pages("ST-15212-2024-COR-1.txt")
    p_init = C.Parsed(init, ["x"], C.NoteMeta(title="old"), None, "no voting sheet")
    p_cor = C.Parsed(cor, cor_pages, C.parse_note(cor_pages[0]), None, "no voting sheet")
    vote, problem = C.build_vote([p_init, p_cor], "2026-10-22T00:00:00Z")
    assert vote.title.startswith(
        "REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending Regulation (EC)"
    )
    assert vote.positions == {} and vote.voting_rule == "unknown" and vote.outcome == "unknown"
    assert "ST-15212-2024-INIT" not in problem  # the void INIT is ignored
    vote, problem = C.build_vote([C.Parsed(init, ["x"], C.NoteMeta(nullified=["INIT"]), None, None)], "t")
    assert vote is None


def test_fetch_without_poppler_reports_failure(monkeypatch):
    monkeypatch.setattr(C, "poppler_available", lambda: False)
    st = C.fetch(object())  # type: ignore[arg-type]
    assert st.status == "failed" and "poppler" in st.note


# ------------------------------------------------------------------ live
@pytest.mark.network
def test_live_ai_act_voting_result():
    from pipeline.http import default_http

    http = default_http()
    groups = C.list_versions(http)
    assert len(groups) > 600
    (v,) = groups["ST-10199-2024"]
    parsed = C.parse_document(v, http.get(C.DOC_URL.format(doc=v.doc_id)))
    vote, problem = C.build_vote([parsed], "now")
    assert problem is None and vote.date == "2024-05-21" and vote.procedure_refs == ["2021/0106(COD)"]
    assert vote.voting_rule == "qmv" and vote.outcome == "adopted" and set(vote.positions.values()) == {"for"}


def test_split_procedure_reference_in_ep_format():
    page = "       Interinstitutional File:\n         2016/0224/A(COD)\n\n                      VOTE 63\n"
    assert C.parse_note(page).procedure_refs == ["2016/0224A(COD)"]


def test_merge_meta_latest_non_empty_wins():
    init = C.NoteMeta(title="t", council_doc="PE-CONS 65/24", procedure_refs=["2023/0237(COD)"])
    cor = C.NoteMeta(title="t corrected", procedure_refs=["2023/0238(COD)"])
    m = C._merge_meta([init, cor])
    assert (m.title, m.council_doc, m.procedure_refs) == ("t corrected", "PE-CONS 65/24", ["2023/0238(COD)"])
