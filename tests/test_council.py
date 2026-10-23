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
    assert m.meeting == "4024th meeting of the COUNCIL OF THE EUROPEAN UNION"
    assert m.configuration == "Transport, Telecommunications and Energy"
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


def test_statements_heading_is_not_a_statement():
    # ST 7085/20, annex 2: the centred heading "STATEMENTS" above "Statement by Spain", "… by Greece", …
    p = pages("ST-7085-2020-INIT.txt")
    assert C.parse_statements(p) == ["Statement by Spain", "Statement by Greece", "Statement by the Commission"]
    assert all(C.STATEMENTS_HEADING_RE.fullmatch(h) for h in ("STATEMENTS", "STATEMENT", "Joint declarations"))
    assert not C.STATEMENTS_HEADING_RE.fullmatch("Statement by France")


def test_statement_headings_printed_at_the_margin_are_statements():
    # ST 8502/21 (IPA III), annex 2: four statements; two headings start at the margin (one after a page break,
    # one indented by two) and were missed, so the vote card listed two
    assert C.parse_statements(pages("ST-8502-2021-INIT.txt")) == [
        "Statement by Hungary",
        "Statement by the European Commission on a geopolitical dialogue with the European Parliament on the the "
        "Instrument for Pre-Accession Assistance (IPA III)",
        "Statement by the European Commission on the modulation/suspension of assistance in Article 8 , paragraph 5 "
        "of Regulation No. 2021/XXX/ of the European Parliament and of the Council of XX/XX/2021 establishing the "
        "Instrument for Pre-Accession Assistance (IPA III)",
        "Statement of the European Commission on the advisory nature of strategic boards as in in Article 12 of "
        "Regulation No. 2021/XXX/of the European Parliament and of the Council of XX/XX 2021 establishing the "
        "Instrument for Pre-Accession Assistance (IPA III)",
    ]
    # ST 7232/20 REV 1 (Mobility Package I), annex 2: three statements by eight Member States, indented by two
    bg = "Statement by Bulgaria, Cyprus, Hungary, Latvia, Lithuania, Malta, Poland and Romania"
    assert C.parse_statements(pages("ST-7232-2020-REV-1.txt")) == [
        "Statement by Belgium", bg, f"{bg} (2)", f"{bg} (3)", "Statement by Estonia", "Statement by Hungary"
    ]
    # a subheading at the margin that names no author is part of the statement above it (ST 14341/20: "Statement in
    # relation to Recital 6" under "Statement by the Commission")
    assert C.parse_statements(pages("ST-14341-2020-INIT.txt")) == ["Statement by Poland", "Statement by the Commission"]


def test_statement_headings_with_a_prefix_or_less_indented_lines():
    # ST 6149/21 (Recovery and Resilience Facility): the first heading's second line is indented by two (it was cut
    # after "COUNCIL AND"); "ADDITIONAL DECLARATION BY …" and "COMMISSION DECLARATION ON …" were not read
    assert C.parse_statements(pages("ST-6149-2021-INIT.txt")) == [
        "JOINT DECLARATION BY THE EUROPEAN PARLIAMENT, COUNCIL AND COMMISSION ON THE ESTABLISHMENT OF REPORTING "
        "REQUIREMENTS TO ENABLE THE ISSUANCE OF BONDS CONTRIBUTING TO ENVIRONMENTAL OBJECTIVES FOR NEXTGENERATIONEU",
        "JOINT DECLARATION BY THE EUROPEAN PARLIAMENT AND THE COMMISSION ON DATA COLLECTION FOR EFFECTIVE CONTROLS "
        "AND AUDITS",
        "ADDITIONAL DECLARATION BY THE COMMISSION ON DATA COLLECTION FOR EFFECTIVE CONTROLS AND AUDITS",
        "COMMISSION DECLARATION ON THE METHODOLOGY FOR CLIMATE TRACKING",
        "Statement by Malta",
    ]


def test_bare_short_reference_number_is_not_a_council_document():
    # ST 6219/25 (RESTORE, 2024/0275(COD)): "Reference document: 102/24"; OEIL lists the file's draft final act as
    # 00102/2024/LEX (PE-CONS 102/24): the record said "ST 102/24". A four-digit number is a Council document.
    assert C.parse_note(text("ST-6219-2025-INIT.page1.txt")).council_doc is None
    assert C.parse_note(pages("ST-14522-2025-REV-1.txt")[0]).council_doc == "ST 10498/25"


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
    assert C.parse_dates("7+8 June 2021, Luxembourg") == ["2021-06-07", "2021-06-08"]
    assert C.parse_dates("Brussels, 27.05.2025") == ["2025-05-27"]
    assert C.parse_dates("4 Decmber 2020") == ["2020-12-04"]  # typo in the published note
    assert C.parse_dates("no date") == []


def test_subject_variants():
    m = C.NoteMeta(
        subject="Voting result X Adoption 3638th meeting of the COUNCIL OF THE EUROPEAN UNION "
        "(Competitiveness (Internal Market, Industry, Research and Space)) 27 and 28 September 2018, Brussels"
    )
    C._parse_subject(m)
    assert (m.title, m.step) == ("X", "Adoption")
    assert m.configuration == "Competitiveness (Internal Market, Industry, Research and Space)"
    m = C.NoteMeta(
        subject="Voting result X Adoption of the legislative act 4100th meeting of the COUNCIL OF THE "
        "EUROPEAN UNION (General Affairs), Brussels, 27.05.2025"
    )
    C._parse_subject(m)
    assert (m.configuration, m.meeting_dates) == ("General Affairs", ["2025-05-27"])
    m = C.NoteMeta(subject="Voting result X Outcome of the written procedure completed on 4 Decmber 2020")
    C._parse_subject(m)
    assert m.written_procedure and m.written_procedure_date == "2020-12-04" and m.meeting is None


# ------------------------------------------------------------------ what was voted on
def test_item_listed_after_the_written_procedure_line():
    # ST 7100/21: the first-reading position is listed after "Outcome of the written procedure ...";
    # it used to be lost, so the vote read as an adoption of the act.
    m = C.parse_note(text("ST-7100-2021-INIT.page1.txt"))
    assert m.title == (
        "REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL on preventing the dissemination of terrorist content"
    )
    assert m.step == "Adoption of the Council's position at first reading and of the statement of the Council's reasons"
    assert m.written_procedure_date == "2021-03-16"
    assert C.vote_subject(m.title, m.step) == "first_reading_position"


def test_title_ends_at_the_first_item_voted_on():
    m = C.NoteMeta(
        subject="Voting result Position of the Council at first reading with a view to the adoption of a REGULATION "
        "OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL on preventing plastic pellet losses - Adoption of a Council's "
        "position (at first reading) - Adoption of the statement of the Council's reasons - 4118th meeting of the "
        "COUNCIL OF THE EUROPEAN UNION (Agriculture and Fisheries) 22 September 2025, Brussels"
    )
    C._parse_subject(m)
    assert m.title.endswith("on preventing plastic pellet losses")
    assert m.step == "Adoption of a Council's position (at first reading); Adoption of the statement of the Council's reasons"
    assert m.meeting_dates == ["2025-09-22"]
    m = C.NoteMeta(
        subject="Voting result REGULATION X Adoption of the legislative act, and Approval of the joint statements "
        "Outcome of the written procedure completed on 22 December 2020"
    )
    C._parse_subject(m)
    assert (m.title, m.step) == ("REGULATION X", "Adoption of the legislative act; Approval of the joint statements")
    m = C.NoteMeta(
        subject="Voting result Amendments of the European Parliament to the Council's position on the draft budget for "
        "2026 - Non-approval of the European Parliament's amendment(s)"
    )
    C._parse_subject(m)
    assert m.title == "Amendments of the European Parliament to the Council's position on the draft budget for 2026"
    assert m.step == "Non-approval of the European Parliament's amendment(s)"


@pytest.mark.parametrize(
    ("title", "step", "expected"),
    [
        ("REGULATION X", "Adoption of the Council's position at first reading and of the statement of the Council's reasons",
         "first_reading_position"),
        ("REGULATION X", "Adoption of the Council first reading position and Statement of Reasons; Approval of the joint "
         "statement", "first_reading_position"),
        ("Position of the Council at first reading with a view to the adoption of a REGULATION X", "Adoption",
         "first_reading_position"),
        ("Position of the Council at first reading with a view to the adoption of a REGULATION X",
         "Adoption of the statement of the Council's reasons", "first_reading_position"),
        # second reading: approving Parliament's amendments adopts the act
        ("REGULATION X", "Approval of the European Parliament's amendments to the Council’s position at first reading; "
         "Adoption of the legislative act", "act"),
        ("REGULATION X", "Adoption of the legislative act; Approval of the Council declaration", "act"),
        ("REGULATION X", "Adoption of legilsative act", "act"),  # typo in the published note
        ("COUNCIL DIRECTIVE amending Directive 2006/112/EC", "Adoption", "act"),
        ("Council position on draft amending budget No 2 to the general budget for 2025",
         "Adoption of the Council's position", "other"),
        ("Joint text on the general budget of the European Union for the financial year 2025",
         "Approval; Adoption of the legislative act", "other"),
        ("COUNCIL DIRECTIVE on standards for equality bodies",
         "Agreement in principle; Request for the consent of the European Parliament", "other"),
        ("REGULATION X", None, None),
    ],
)  # fmt: skip
def test_vote_subject(title, step, expected):
    assert C.vote_subject(title, step) == expected
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
def test_sheet_2019_template_with_ring_shaped_abstain_icon():
    # ST 7859/19: the 2019 template draws "abstain" as a yellow ring around a disc; its legend used to be
    # missed, so the record had no positions, rule or outcome although the sheet shows them.
    s = annex("ST-7859-2019-INIT")
    assert (s.rule, s.outcome) == ("qmv", "adopted")
    pos = C.sheet_positions(s, "2019-03-22")
    assert pos["GB"] == "abstain" and sum(1 for p in pos.values() if p == "for") == 27


@needs_poppler
def test_sheet_rule_read_when_footnote_glyphs_leave_sparse_pixel_rows():
    s = annex("ST-5847-2021-INIT")  # the QMV footnote line has 1-pixel rows at 100 dpi
    assert (s.rule, s.outcome) == ("qmv", "adopted")


@needs_poppler
def test_unreadable_slot_keeps_rule_and_outcome_and_names_the_state():
    # ST 7080/24: Latvia's row is not in the published image. Positions stay empty (fail closed), the
    # final result and rule are still read, and the record says exactly what could not be read.
    pdf = (FIX / "ST-7080-2024-INIT.annex.pdf").read_bytes()
    with pytest.raises(C.SheetError) as exc:
        C.analyse_sheet(C.render_page(pdf, 1))
    err = exc.value
    assert err.partial is not None and (err.partial.rule, err.partial.outcome) == ("qmv", "adopted")
    assert err.unreadable == [("left", 13), ("right", 13)]
    v = C._versions_from_rows([{"work": "w", "docid": "consil:ST_7080_2024_INIT", "date": "2024-02-27",
                                "title": "Voting result"}])["ST-7080-2024"][0]  # fmt: skip
    meta = C.NoteMeta(title="REGULATION X", step="Adoption of legislative act", meeting_dates=["2024-02-26"],
                      meeting="4007th meeting of the COUNCIL OF THE EUROPEAN UNION")  # fmt: skip
    parsed = C.Parsed(v, ["p1"], meta, None, f"p2: {err}", partial=[(2, err)])
    vote, problem = C.build_vote([parsed], "t")
    assert vote.positions == {} and (vote.voting_rule, vote.outcome, vote.vote_on) == ("qmv", "adopted", "act")
    assert vote.positions_note == (
        "We could not read Latvia's vote from the published voting sheet (page 2), so no individual positions "
        "are shown for this vote."
    )
    assert "unreadable" in problem


def _sheet(rule: str, outcome: str, abstain_first: bool = False) -> C.Sheet:
    left = ["abstain" if abstain_first else "for"] + ["for"] * 13
    return C.Sheet(left=left, right=["for"] * 13 + ["grey"], outcome=outcome, rule=rule)


def test_several_sheets_keep_only_what_they_agree_on():
    # ST 7085/20: one sheet for the act, one for the derogation from the 8-week period; which is which is not
    # machine-readable, so no positions; rule and outcome are kept because both sheets agree on them.
    v = C._versions_from_rows([{"work": "w", "docid": "consil:ST_7085_2020_INIT", "date": "2020-03-30",
                                "title": "Voting result"}])["ST-7085-2020"][0]  # fmt: skip
    meta = C.NoteMeta(title="Regulation X", step="Adoption of the legislative act", written_procedure=True,
                      written_procedure_date="2020-03-30")  # fmt: skip
    sheets = [(2, _sheet("qmv", "adopted", abstain_first=True)), (3, _sheet("qmv", "adopted"))]
    parsed = C.Parsed(v, ["p1"], meta, None, "several voting sheets in one note", sheets=sheets)
    vote, _ = C.build_vote([parsed], "t")
    assert vote.positions == {} and (vote.voting_rule, vote.outcome) == ("qmv", "adopted")
    assert vote.positions_note.startswith("The voting-result document contains 2 voting sheets (pages 2 and 3)")
    assert "source does not record" not in vote.positions_note
    sheets = [(2, _sheet("qmv", "adopted")), (3, _sheet("unanimity", "not_adopted"))]
    vote, _ = C.build_vote([C.Parsed(v, ["p1"], meta, None, "several", sheets=sheets)], "t")
    assert (vote.voting_rule, vote.outcome) == ("unknown", "unknown")


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
    assert vote.source.identifier == "ST 10199/24"
    assert vote.stage == "Adoption of the Legislative Act"
    assert vote.meeting == "4024th meeting of the COUNCIL OF THE EUROPEAN UNION"
    assert vote.written_procedure is False
    assert vote.vote_on == "act" and vote.positions_note is None


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


def test_written_procedure_record_fields():
    groups = C._versions_from_rows(rows())
    (v,) = groups["ST-9552-2024"]
    p = pages("ST-9552-2024-INIT.txt")
    vote, _ = C.build_vote([C.Parsed(v, p, C.parse_note(p[0]), None, "no voting sheet")], "t")
    assert vote.written_procedure is True and vote.meeting is None and vote.configuration is None
    assert vote.date == "2024-02-28" and vote.stage == "Adoption of the legislative act"
    assert vote.source.identifier == "ST 9552/24"
    assert vote.statements[-1] == "Statement by the Republic of Bulgaria"


def test_st_number():
    groups = C._versions_from_rows(rows())
    assert [C.st_number(v) for v in groups["ST-15212-2024"]] == [
        "ST 15212/24",
        "ST 15212/24 REV 1",
        "ST 15212/24 COR 1",
    ]


# ------------------------------------------------------------------ incremental fetch
class FakeHttp:
    def __init__(self, rows, error=None):
        self.rows, self.error, self.gets = rows, error, []

    def sparql(self, query, **kw):
        return self.rows

    def get(self, url, **kw):
        self.gets.append(url)
        if self.error:
            raise self.error
        raise AssertionError(f"unexpected download {url}")


def _seed(tmp_path, monkeypatch, fingerprint):
    from pipeline import snapshot
    from pipeline.models.entities import CouncilVote

    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.setattr(C, "poppler_available", lambda: True)
    ai_rows = [r for r in rows() if r["docid"] == "consil:ST_10199_2024_INIT"]
    prev = CouncilVote.model_validate(
        {
            "id": "ST-10199-2024",
            "date": "2024-05-21",
            "title": "REGULATION ... (Artificial Intelligence Act)",
            "voting_rule": "qmv",
            "outcome": "adopted",
            "positions": {"DE": "for"},
            "source": {
                "institution": "Council",
                "url": C.DOC_URL.format(doc="ST-10199-2024-INIT"),
                "identifier": "ST 10199/24",
                "retrieved_at": "2026-01-01T00:00:00Z",
            },
        }
    )
    fp = fingerprint(C._versions_from_rows(ai_rows)["ST-10199-2024"])
    state = C.CouncilNoteState(
        id="ST-10199-2024", fingerprint=fp, versions=["ST-10199-2024-INIT"], vote_id=prev.id
    )
    snapshot.write_records("council", "votes", [prev])
    snapshot.write_records("council", "notes", [state])
    return snapshot, ai_rows, prev


def test_fetch_reuses_unchanged_notes_without_downloading(tmp_path, monkeypatch):
    snapshot, ai_rows, prev = _seed(tmp_path, monkeypatch, C.note_fingerprint)
    http = FakeHttp(ai_rows)
    st = C.fetch(http)
    assert http.gets == [] and st.status == "ok" and st.records["votes"] == 1
    from pipeline.models.entities import CouncilVote

    (v,) = snapshot.read_records("council", "votes", CouncilVote)
    assert v == prev  # including the original retrieved_at


def test_fetch_changed_note_with_transient_error_keeps_previous_and_retries(tmp_path, monkeypatch):
    from pipeline.http import HttpError
    from pipeline.models.entities import CouncilVote

    snapshot, ai_rows, prev = _seed(tmp_path, monkeypatch, lambda versions: "stale-fingerprint")
    http = FakeHttp(ai_rows, error=HttpError("u", 503, "unavailable"))
    st = C.fetch(http)
    assert len(http.gets) == 1 and st.status == "partial"
    assert snapshot.read_records("council", "votes", CouncilVote) == [prev]
    assert snapshot.read_records("council", "notes", C.CouncilNoteState) == []  # retried next run


def test_fetch_after_deadline_defers_changed_notes_and_keeps_them_linked(tmp_path, monkeypatch):
    import time

    from pipeline.models.entities import CouncilVote

    snapshot, ai_rows, prev = _seed(tmp_path, monkeypatch, lambda versions: "stale-fingerprint")
    monkeypatch.setenv("EU_INTEL_FETCH_DEADLINE", str(time.time() - 1))
    http = FakeHttp(ai_rows)  # any download would fail the test
    st = C.fetch(http)
    assert http.gets == [] and st.status == "partial" and "time budget reached" in st.note
    assert snapshot.read_records("council", "votes", CouncilVote) == [prev]
    (state,) = snapshot.read_records("council", "notes", C.CouncilNoteState)
    assert state.vote_id == prev.id and state.fingerprint == C.DEFERRED_FINGERPRINT  # re-read next run
    # the next run, still failing to download, keeps the vote (it is still linked to its note)
    monkeypatch.delenv("EU_INTEL_FETCH_DEADLINE")
    from pipeline.http import HttpError

    st = C.fetch(FakeHttp(ai_rows, error=HttpError("u", 503, "unavailable")))
    assert snapshot.read_records("council", "votes", CouncilVote) == [prev]


def test_fetch_after_deadline_still_reuses_unchanged_notes(tmp_path, monkeypatch):
    import time

    snapshot, ai_rows, prev = _seed(tmp_path, monkeypatch, C.note_fingerprint)
    monkeypatch.setenv("EU_INTEL_FETCH_DEADLINE", str(time.time() - 1))
    st = C.fetch(FakeHttp(ai_rows))
    assert st.status == "ok" and st.records["votes"] == 1


def test_fetch_refuses_truncated_listing(tmp_path, monkeypatch):
    snapshot, _ai_rows, _prev = _seed(tmp_path, monkeypatch, C.note_fingerprint)
    st = C.fetch(FakeHttp([]))
    assert st.status == "failed" and "previously 1" in st.note


def test_reprocess_replaces_only_the_given_notes(tmp_path, monkeypatch):
    from pipeline.models.entities import CouncilVote

    snapshot, ai_rows, prev = _seed(tmp_path, monkeypatch, C.note_fingerprint)
    other = prev.model_copy(update={"id": "ST-1-2024", "title": "untouched"})
    snapshot.write_records("council", "votes", [prev, other])
    snapshot.write_records(
        "council",
        "notes",
        [*snapshot.read_records("council", "notes", C.CouncilNoteState),
         C.CouncilNoteState(id="ST-1-2024", fingerprint="old", vote_id="ST-1-2024")],
    )  # fmt: skip
    page1 = text("ST-10199-2024-INIT.page1.txt")

    class Http(FakeHttp):
        def get(self, url, **kw):
            self.gets.append(url)
            return b"%PDF"

    def parse(v, pdf):
        return C.Parsed(v, [page1], C.parse_note(page1), None, "no voting sheet")

    monkeypatch.setattr(C, "parse_document", parse)
    http = Http(ai_rows)
    assert C.reprocess(http, ["ST-10199-2024"]) == {"ST-10199-2024": "ST-10199-2024-INIT: no voting sheet"}
    assert http.gets == [C.DOC_URL.format(doc="ST-10199-2024-INIT")]  # re-read although its fingerprint is unchanged
    votes = {v.id: v for v in snapshot.read_records("council", "votes", CouncilVote)}
    assert votes["ST-1-2024"] == other
    assert votes["ST-10199-2024"].vote_on == "act" and votes["ST-10199-2024"].positions == {}
    assert votes["ST-10199-2024"].positions_note.startswith("We found no voting sheet")
    states = {s.id: s for s in snapshot.read_records("council", "notes", C.CouncilNoteState)}
    assert states["ST-1-2024"].fingerprint == "old"
    with pytest.raises(ValueError):
        C.reprocess(http, ["ST-404-2024"])


# ------------------------------------------------------------------ notes the listing used to miss
def test_listing_accepts_a_title_that_starts_after_a_dash_or_bullet():
    # 26 notes of 2020-2025 have English titles "- Voting result - …", "· Voting result ·", "− Voting result −" or
    # "- Voting Result …" (ST 9887/25, the wolf Directive; 10177/25; 6219/25; 9902/25); ST 11790/25 INIT runs on
    # without a space. A title that only mentions a voting result further on is still not a voting-result note.
    titles = {
        "ST_9887_2025_INIT": "- Voting result - DIRECTIVE OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending …",
        "ST_10177_2025_INIT": "· Voting result · Council Regulation on strengthening the security of identity cards …",
        "ST_6219_2025_INIT": "− Voting result − REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending …",
        "ST_9902_2025_INIT": "- Voting Result REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL suspending …",
        "ST_11790_2025_INIT": "Voting resultREGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending …",
        "ST_1_2025_INIT": "Corrigendum to the voting result of …",
    }
    rows = [{"work": f"w{i}", "docid": f"consil:{d}", "date": "2025-06-12", "title": t}
            for i, (d, t) in enumerate(titles.items())]  # fmt: skip
    assert sorted(C._versions_from_rows(rows)) == [
        "ST-10177-2025", "ST-11790-2025", "ST-6219-2025", "ST-9887-2025", "ST-9902-2025"
    ]  # fmt: skip
    assert 'CONTAINS(LCASE(STR(?title)), "voting result")' in C.SPARQL_VOTING_RESULTS


def test_parse_note_wolf_directive_subject_with_dashes():
    m = C.parse_note(text("ST-9887-2025-INIT.page1.txt"))
    assert m.procedure_refs == ["2025/0058(COD)"]
    assert m.title == (
        "DIRECTIVE OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending Council Directive 92/43/EEC as regards "
        "the protection status of the wolf (Canis lupus)"
    )
    assert m.step == "Adoption of the legislative act"
    assert m.meeting == "4101st meeting of the COUNCIL OF THE EUROPEAN UNION"
    assert m.configuration == "Transport, Telecommunications and Energy"
    assert m.meeting_dates == ["2025-06-05", "2025-06-06"]


def test_written_procedure_initiated_by_cm_is_dated_by_the_council_event():
    # ST 7108/21 (European Defence Fund): "Outcome of the written procedure initiated by CM 2163/21", no completion
    # date; Cellar attaches the note (dated 17 March 2021) to ADP_R1_POS_byCONSIL of 16 March 2021
    page1 = text("ST-7108-2021-INIT.page1.txt")
    m = C.parse_note(page1)
    assert m.written_procedure and m.written_procedure_date is None
    assert m.step == "Adoption of the Council's position at first reading and of the statement of the Council's reasons"
    row = {"work": "w", "docid": "consil:ST_7108_2021_INIT", "date": "2021-03-17",
           "title": "- Voting result - REGULATION …", "evdate": "2021-03-16", "evtype": "ADP_R1_POS_byCONSIL"}  # fmt: skip
    (v,) = C._versions_from_rows([row])["ST-7108-2021"]
    vote, _ = C.build_vote([C.Parsed(v, [page1], m, None, "no voting sheet")], "t")
    assert (vote.date, vote.written_procedure, vote.vote_on) == ("2021-03-16", True, "first_reading_position")
    # without a Council event, the note's own date
    (v,) = C._versions_from_rows([{**row, "evdate": "", "evtype": ""}])["ST-7108-2021"]
    assert C.build_vote([C.Parsed(v, [page1], m, None, "no voting sheet")], "t")[0].date == "2021-03-17"


def test_statements_include_explanations_by_a_state_and_draft_joint_statements():
    # ST 14020/20, Annex II (rule-of-law conditionality): five headed texts, the Commission's statement twice
    assert C.parse_statements(pages("ST-14020-2020-INIT.txt")) == [
        "Explanation by Hungary of its vote",
        "Statement by Hungary",
        "Statement by the Commission",
        "Draft Joint Statement by the Council, the European Parliament and the Commission",
        "Statement by the Commission (2)",
    ]


def test_statements_come_from_the_latest_version_that_prints_any():
    # ST 11580/20: the INIT's Annex II carried statements on the Taxonomy Regulation; REV 1 replaces the note and
    # prints only Italy's statement on the regulation voted on
    rev_pages = pages("ST-11580-2020-REV-1.txt")
    rows = [{"work": "w1", "docid": "consil:ST_11580_2020_INIT", "date": "2020-10-07", "title": "‒ Voting result"},
            {"work": "w2", "docid": "consil:ST_11580_2020_REV_1", "date": "2020-10-07", "title": "‒ Voting result"}]  # fmt: skip
    init, rev = C._versions_from_rows(rows)["ST-11580-2020"]
    init_pages = [rev_pages[0], "                          Statement by Austria\n\nWe share the objective …\n"]
    p_init = C.Parsed(init, init_pages, C.parse_note(init_pages[0]), None, "no voting sheet")
    p_rev = C.Parsed(rev, rev_pages, C.parse_note(rev_pages[0]), None, "no voting sheet")
    vote, _ = C.build_vote([p_init, p_rev], "t")
    assert vote.statements == ["Statement by Italy"]
    # a corrigendum printing no statements keeps those of the version before it
    p_cor = C.Parsed(rev, [rev_pages[0]], C.parse_note(rev_pages[0]), None, "no voting sheet")
    assert C.build_vote([p_rev, p_cor], "t")[0].statements == ["Statement by Italy"]
