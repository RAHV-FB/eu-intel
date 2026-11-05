"""The law in context from EUR-Lex / Cellar (pipeline/sources/lawcontext.py, pipeline/analysis/lawcontext.py).

The Cellar answers in tests/fixtures/lawcontext are real: the rows that the source's own queries returned on
5 November 2026 for a few acts and procedures (sparql/*.json), and summary texts as content negotiation served them
(texts/). Nothing here reads data/snapshot: the frozen test data has no files of this source.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from pipeline.http import HttpError
from pipeline.models.entities import (
    ActContext,
    AdvisoryOpinion,
    ConsolidatedVersion,
    CourtCase,
    CourtDecision,
    LegalAct,
    OfficialSummary,
    Procedure,
    ProcedureCase,
    ProcedureNotice,
    SourceRef,
    SourceStatus,
)
from pipeline.snapshot import read_records, write_records
from pipeline.sources import lawcontext as L

FIX = Path(__file__).parent / "fixtures" / "lawcontext"
BUILD_FIX = Path(__file__).parent / "fixtures" / "build"
NOW = "2026-11-05T15:00:00Z"
SRC = SourceRef(institution="EUR-Lex", url="https://eur-lex.europa.eu/", retrieved_at=NOW)


def rows(name: str) -> list[dict[str, str]]:
    return json.loads((FIX / "sparql" / f"{name}.json").read_text(encoding="utf-8"))


def text(name: str) -> bytes:
    return (FIX / "texts" / name).read_bytes()


# ------------------------------------------------------------------------------------------- the summary texts
def test_the_opening_section_of_a_current_summary():
    """General data protection regulation (GDPR), LEGISSUM 310401_2 (xhtml5, last updated 24 March 2026): the four
    points of "WHAT IS THE AIM OF THE REGULATION?", as list items, verbatim."""
    paras, heading, complete, items = L.summary_text(text("310401_2.xhtml5"))
    assert heading == "WHAT IS THE AIM OF THE REGULATION?"
    assert paras[0].startswith("Regulation (EU) 2016/679, the General Data Protection Regulation (GDPR), protects "
                               "individuals (natural persons) when their data is being processed")  # fmt: skip
    assert paras[1] == ("It allows individuals to better control their personal data. It also modernises and unifies "
                        "rules, allowing businesses to reduce red tape and to benefit from greater consumer trust.")  # fmt: skip
    assert len(paras) == 4 and items == [0, 1, 2, 3] and complete
    assert not any("<" in p or "  " in p for p in paras)  # plain text


def test_older_formats():
    # xhtml of 2016 (Directive (EU) 2015/2193): subscripts joined, the glossary asterisk dropped
    paras, heading, complete, items = L.summary_text(text("200505_2.xhtml"))
    assert heading == "WHAT DOES THIS DIRECTIVE DO?" and items == [] and complete
    assert paras == [
        "It lays down rules to control air emissions of sulphur dioxide (SO2), nitrogen oxides (NOx) and dust "
        "(particles) from medium combustion plants, as well as rules to monitor carbon monoxide (CO) emissions from "
        "these plants.",
        "The aim is to reduce potential harm to human health and the environment.",
    ]
    # html of 2014 (Regulation (EU) No 513/2014): "SUMMARY", up to its first sub-heading ("Operational objectives")
    paras, heading, complete, items = L.summary_text(text("230401_1.html"))
    assert heading == "SUMMARY" and not complete and len(paras) == 2
    assert paras[0].startswith("Known as the ISF-Police regulation, the instrument aims to contribute to a high level")


def test_a_long_paragraph_is_cut_after_a_sentence():
    body = ("<h2>WHAT IS THE AIM OF THE DIRECTIVE?</h2><p>" + "A sentence of the summary. " * 60 + "</p>").encode()
    (para,), _, complete, _ = L.summary_text(body)
    assert para.endswith("summary. …") and len(para) <= L.PARAGRAPH_CHARS + 2 and not complete
    assert L.summary_text(b"<p>No section looked for.</p>") == ([], None, True, [])


def test_content_negotiation_asks_for_each_format_in_turn():
    asked: list[str] = []

    class Http:
        def get(self, url, headers=None, use_cache=True):
            asked.append(headers["Accept"])
            if headers["Accept"] != "text/html":
                raise HttpError(url, 404, "does not hold a content datastream of the requested type")
            return b"<p>ok</p>"

    assert L.fetch_summary_text(Http(), "230401_1", ["xhtml", "fmx4"]) == b"<p>ok</p>"
    assert asked == ["application/xhtml+xml", "text/html"]  # not the xhtml5 type, which it does not hold
    with pytest.raises(HttpError):
        L.fetch_summary_text(Http(), "310401_2", ["xhtml5", "fmx4"])


# ------------------------------------------------------------------------------------------------ identifiers
def test_identifiers():
    assert L.cellar_ref("2021/0106(COD)") == "2021/0106/COD" and L.cellar_ref("2016/0224A(COD)") is None
    assert L.case_number("62024CJ0312") == "C-312/24" and L.case_number("62025TN0730") == "T-730/25"
    assert L.case_numbers("Joined Cases T-685/24 and T-686/24") == {"T-685/24", "T-686/24"}
    assert L.case_numbers("Joined Cases C-541/20 to C-543/20") == {"C-541/20", "C-542/20", "C-543/20"}


def test_consolidated_versions_only_of_the_act_itself():
    """For NIS2 the link also gives versions of the acts it amends (02018L1972-20241018, 02014R0910-20241018):
    the answer of a query without the filter on the act's own CELEX, 5 November 2026."""
    raw = json.loads((FIX / "cellar_consolidated_nis2_unfiltered.json").read_text(encoding="utf-8"))
    got = L.parse_consolidated([{"c": "32022L2555", **r} for r in raw])
    assert got == {"32022L2555": [ConsolidatedVersion(celex="02022L2555-20221227", date="2022-12-27")]}
    filtered = L.parse_consolidated(rows("consolidated"))
    assert [v.celex for v in filtered["32022L2555"]] == ["02022L2555-20221227"]
    assert [v.date for v in filtered["32024R1689"]] == ["2024-07-12", "2026-07-27"]  # AI Act, after 2026/1744


def test_cases_pending_decided_or_not_known():
    interp = L.parse_interpretations(rows("interpretations"), {r["j"]: r["case"] for r in rows("case_ids")})
    decided = {c: {n for d in v for n in L.case_numbers(d.case)} for c, v in interp.items()}
    cases = {k.celex: k for v in L.parse_cases(rows("cases"), decided).values() for k in v}
    # C-660/26 (GDPR): a case file with only the notice of the new case
    assert (cases["62026CN0660"].case, cases["62026CN0660"].state) == ("C-660/26", "pending")
    assert cases["62026CN0660"].kind == "preliminary_reference" and cases["62026CN0660"].lodged == "2026-06-16"
    # C-312/24 (GDPR): its file is closed and lists the judgment of 4 June 2026
    assert cases["62024CN0312"].state == "decided"
    # C-272/19 (GDPR): no case file in Cellar: not known
    assert cases["62019CN0272"].case is None and cases["62019CN0272"].state is None
    # T-686/24 (excise duty, a preliminary reference to the General Court): its file records nothing more, but the
    # judgment interpreting the directive is in "Joined Cases T-685/24 and T-686/24"
    assert cases["62024TN0686"].state == "decided"
    # T-239/25: an action for the annulment of the Packaging and Packaging Waste Regulation, in whole or in part
    assert (cases["62025TN0239"].kind, cases["62025TN0239"].state) == ("annulment", "pending")


def test_the_action_against_the_withdrawal_of_the_standard_essential_patents_proposal():
    (k,) = L.parse_withdrawal_cases(rows("withdrawal_cases"), NOW)
    assert (k.reference, k.case, k.lodged, k.annulled, k.proposal) == (
        "2023/0133(COD)", "C-727/25", "2025-11-14", "52025XC05423", "52023PC0232")  # fmt: skip
    assert k.applicants == ["European Parliament"] and k.state == "pending"  # fd_110 "Institutions" left out


def test_opinions_of_the_committees():
    ops = {o.celex: o for o in L.parse_opinions(rows("opinions"), NOW)}
    assert {c: (o.body, o.procedure_refs, o.date) for c, o in ops.items()} == {
        "52020AE5749": ("EESC", ["2020/0359(COD)"], "2021-04-27"),
        "52021AE2482": ("EESC", ["2021/0106(COD)"], "2021-09-22"),
        "52021AR2682": ("CoR", ["2021/0106(COD)"], "2021-12-02"),
        "52023AE2306": ("EESC", ["2023/0133(COD)"], "2023-09-20"),
    }


# ----------------------------------------------------------------------------------------------- fetch
TEXTS = {  # the summaries whose text is in the fixtures, with the only type content negotiation serves each in
    "310401_2": ("application/xhtml+xml;type=xhtml5", "310401_2.xhtml5"),
    "200505_2": ("application/xhtml+xml", "200505_2.xhtml"),
    "230401_1": ("text/html", "230401_1.html"),
}
KEYS = {"summaries": "c", "consolidated": "c", "interpretations": "c", "case_ids": "j", "cases": "c",
        "opinions": "ref", "withdrawal_cases": "ref"}  # fmt: skip


def query_kind(q: str) -> str:
    for needle, kind in (("summary_summarizes_work", "summaries"), ("act_consolidated", "consolidated"),
                         ("expression_case-law_identifier_case", "case_ids"), ("renders_obsolete", "withdrawal_cases"),
                         ("case-law_interpretes", "interpretations"), ("submits_preliminary_question", "cases"),
                         ("corporate-body/EESC", "opinions")):  # fmt: skip
        if needle in q:
            return kind
    raise AssertionError(q)


class Cellar:
    """Answers the source's queries with the saved answers, for the identifiers of each query's VALUES (as Cellar
    would), and serves the summary texts by content negotiation. `fail`: query kinds that fail; `only`: rows kept."""

    def __init__(self, fail: tuple[str, ...] = (), only: dict[str, list[dict[str, str]]] | None = None) -> None:
        self.fail, self.only = fail, only or {}
        self.texts: list[str] = []

    def sparql(self, query: str, use_cache: bool = True) -> list[dict[str, str]]:
        kind = query_kind(query)
        if kind in self.fail:
            raise HttpError("https://publications.europa.eu/webapi/rdf/sparql", 503, "Service Unavailable")
        asked = set(re.findall(r'"([^"]+)"\^\^xsd:string', query))
        return [r for r in self.only.get(kind, rows(kind)) if r[KEYS[kind]] in asked]

    def get(self, url: str, headers: dict[str, str] | None = None, use_cache: bool = True) -> bytes:
        sid = url.rsplit("/", 1)[-1]
        accept, name = TEXTS.get(sid, (None, None))
        if not headers or headers.get("Accept") != accept or headers.get("Accept-Language") != "eng":
            raise HttpError(url, 404, "does not hold a content datastream of the requested type")
        self.texts.append(sid)
        return text(name)


# the acts the fixtures answer for, with their procedures as EUR-Lex records them
ACTS = {"32016R0679": "2012/0011(COD)", "32014R0254": "2011/0340(COD)", "32015L2193": "2013/0442(COD)",
        "32014R0513": "2011/0368(COD)", "32020L0262": "2018/0176(CNS)", "32024R1689": "2021/0106(COD)",
        "32022L2555": "2020/0359(COD)", "32025R0040": "2022/0396(COD)"}  # fmt: skip


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """A snapshot with the acts and procedures the fixtures answer for, and the withdrawn 2023/0133(COD)."""
    import pipeline.snapshot as snap

    monkeypatch.setattr(snap, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    monkeypatch.delenv("EU_INTEL_FETCH_DEADLINE", raising=False)
    acts = [LegalAct(celex=c, act_type={"R": "regulation", "L": "directive"}[c[5]], title=f"Act {c}",
                     procedure_refs=[r], eurlex_url=f"https://eur-lex.europa.eu/eli/{c}", source=SRC)
            for c, r in ACTS.items()]  # fmt: skip
    write_records("eurlex", "acts", acts)
    refs = [*ACTS.values(), "2023/0133(COD)"]
    write_records("ep_procedures", "procedures", [
        Procedure(id=r[:9].replace("/", "-"), reference=r, type=r[-4:-1], title=r, oeil_url="https://oeil", source=SRC)
        for r in refs])  # fmt: skip
    write_records("eurlex", "procedure_notices", [ProcedureNotice(
        id="2023/0133(COD):withdrawn:2025-10-06", reference="2023/0133(COD)", kind="withdrawn", date="2025-10-06",
        source=SRC)])  # fmt: skip
    return tmp_path


def summaries() -> dict[str, OfficialSummary]:
    return {s.id: s for s in read_records("lawcontext", "summaries", OfficialSummary)}


def contexts() -> dict[str, ActContext]:
    return {r.celex: r for r in read_records("lawcontext", "acts", ActContext)}


def test_fetch(stored):
    cellar = Cellar()
    status = L.fetch(cellar)
    sums = summaries()
    assert sums["310401_2"].acts == ["32016R0679"] and sums["310401_2"].date == "2026-03-24"
    assert sums["310401_2"].title == "General data protection regulation (GDPR)"
    assert sums["310401_2"].abstract == ("The regulation protects personal data in the EU while allowing such data to "
                                         "move freely between EU Member States.")  # fmt: skip
    assert sums["310401_2"].url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=LEGISSUM:310401_2"
    assert (sums["310401_2"].text_status, sums["310401_2"].text_date) == ("ok", "2026-03-24")
    assert sums["200505_2"].aim_heading == "WHAT DOES THIS DIRECTIVE DO?"
    # the two summaries of Regulation (EU) No 254/2014 are obsolete: not read
    obsolete = [s for s in sums.values() if "32014R0254" in s.acts]
    assert len(obsolete) == 2 and all(s.obsolete and s.text_status == "not_read" for s in obsolete)
    # texts the fixtures lack (the AI Act's, NIS2's, ...): unavailable, read again next run
    assert sums["4762484"].text_status == "unavailable" and status.status == "partial"
    assert sorted(cellar.texts) == ["200505_2", "230401_1", "310401_2"]
    ctx = contexts()
    assert set(ctx) == set(ACTS)
    assert [v.celex for v in ctx["32024R1689"].consolidated] == ["02024R1689-20240712", "02024R1689-20260727"]
    assert [v.celex for v in ctx["32022L2555"].consolidated] == ["02022L2555-20221227"]
    assert CourtDecision(celex="62024CJ0312", case="Case C-312/24", date="2026-06-04",
                         ecli="ECLI:EU:C:2026:449") in ctx["32016R0679"].interpreted_by  # fmt: skip
    assert {k.celex: k.state for k in ctx["32016R0679"].cases} == {"62026CN0660": "pending", "62024CN0312": "decided",
                                                                    "62019CN0272": None}  # fmt: skip
    assert [o.celex for o in read_records("lawcontext", "opinions", AdvisoryOpinion)] == [
        "52020AE5749", "52021AE2482", "52021AR2682", "52023AE2306"]  # fmt: skip
    (wd,) = read_records("lawcontext", "procedure_cases", ProcedureCase)
    assert (wd.case, wd.reference, wd.state) == ("C-727/25", "2023/0133(COD)", "pending")
    assert status.records["acts_with_summary"] == 7 and status.records["opinions"] == 4
    assert status.records["procedure_cases"] == 1 and "1 actions against the withdrawal" in status.note


def test_texts_are_read_again_only_when_the_summary_changes(stored):
    L.fetch(Cellar())
    again = Cellar()
    L.fetch(again)
    assert again.texts == []  # every text read is of the summary's current version; the others are not served
    # EUR-Lex updates the GDPR summary: its text is read again
    newer = [{**r, "date": "2026-11-04"} if r.get("id") == "310401_2" else r for r in rows("summaries")]
    third = Cellar(only={"summaries": newer})
    L.fetch(third)
    assert third.texts == ["310401_2"] and summaries()["310401_2"].text_date == "2026-11-04"


def test_a_text_that_cannot_be_read_again_keeps_its_earlier_reading(stored):
    L.fetch(Cellar())
    before = summaries()["310401_2"]
    newer = [{**r, "date": "2026-11-04"} if r.get("id") == "310401_2" else r for r in rows("summaries")]

    class TextsDown(Cellar):
        def get(self, url, headers=None, use_cache=True):
            raise HttpError(url, 503, "Service Unavailable")

    status = L.fetch(TextsDown(only={"summaries": newer}))
    after = summaries()["310401_2"]
    # the text shown stays that of the version it was read from, dated as such
    assert (after.aim, after.text_status, after.text_date, after.date) == (before.aim, "ok", "2026-03-24", "2026-11-04")
    assert status.status == "partial" and status.records["summaries_pending"] >= 1


def test_a_failed_or_short_answer_keeps_the_records_of_its_batch(stored):
    L.fetch(Cellar())
    gdpr = contexts()["32016R0679"]
    assert gdpr.cases and gdpr.interpreted_by
    status = L.fetch(Cellar(fail=("cases",)))
    assert contexts()["32016R0679"].cases == gdpr.cases and status.status == "partial"
    assert "cases (8 items: query failed)" in status.note
    # an answer with fewer than half of the links recorded for its batch (Cellar can cut an answer short, HTTP 200)
    many = [CourtDecision(celex=f"62020CJ{n:04d}", date="2020-01-01") for n in range(20)]
    write_records("lawcontext", "acts", [c.model_copy(update={"interpreted_by": many}) if c.celex == "32016R0679" else c
                                         for c in contexts().values()])  # fmt: skip
    status = L.fetch(Cellar())
    assert contexts()["32016R0679"].interpreted_by == many and "interpretations (8 items: answer with" in status.note


def test_nothing_answered_fails_and_writes_nothing(stored):
    with pytest.raises(RuntimeError, match="no Cellar query answered"):
        L.fetch(Cellar(fail=("summaries", "consolidated", "interpretations", "cases")))
    assert not (stored / "lawcontext").exists()


# ------------------------------------------------------------------------------------------------- the build
def law_files(snapshot: Path) -> None:
    """lawcontext records for the build fixture's invented acts (tests/fixtures/build: 32099R0001 amends 32099L0003)."""
    import pipeline.snapshot as snap

    real = snap.SNAPSHOT
    try:
        snap.SNAPSHOT = snapshot
        write_records("lawcontext", "summaries", [
            OfficialSummary(id="test_1", acts=["32099L0003"], title="Test thingamajigs", date="2024-06-01",
                            aim=["It sets rules on test thingamajigs.", "rules on colours;", "rules on sizes."],
                            aim_items=[1, 2], aim_heading="WHAT IS THE AIM OF THE DIRECTIVE?", text_status="ok",
                            text_date="2024-06-01", url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=LEGISSUM:test_1",
                            source=SRC),
            OfficialSummary(id="test_old", acts=["32099L0003"], title="Old", date="2020-01-01", obsolete=True,
                            url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=LEGISSUM:test_old", source=SRC),
        ])  # fmt: skip
        write_records("lawcontext", "acts", [ActContext(
            celex="32099R0001", source=SRC,
            consolidated=[ConsolidatedVersion(celex="02099R0001-20241221", date="2024-12-21"),
                          ConsolidatedVersion(celex="02099R0001-20991231", date="2099-12-31")],
            interpreted_by=[CourtDecision(celex="62098CJ0001", case="Case C-1/98", date="2025-01-15")],
            cases=[CourtCase(celex="62099CN0005", case="C-5/99", kind="preliminary_reference", lodged="2026-01-10",
                             state="pending"),
                   CourtCase(celex="62098CN0001", case="C-1/98", kind="preliminary_reference", state="decided")],
        )])  # fmt: skip
        write_records("lawcontext", "opinions", [AdvisoryOpinion(
            celex="52098AE0001", body="EESC", procedure_refs=["2099/0001(COD)"], date="2098-05-01", title="Opinion",
            url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52098AE0001", source=SRC)])  # fmt: skip
        write_records("lawcontext", "procedure_cases", [ProcedureCase(
            id="62099CN0007:2099/0002(CNS)", celex="62099CN0007", reference="2099/0002(CNS)", case="C-7/99",
            lodged="2026-02-01", annulled="52099XC00001", proposal="52098PC0002", applicants=["European Parliament"],
            state="pending", source=SRC)])  # fmt: skip
        snap.update_manifest(SourceStatus(source="lawcontext", status="ok", fetched_at=NOW, attempted_at=NOW))
    finally:
        snap.SNAPSHOT = real


def built(tmp_path: Path, with_law: bool) -> Path:
    from pipeline.build import build

    shutil.copytree(BUILD_FIX / "snapshot", tmp_path / "snapshot")
    if with_law:
        law_files(tmp_path / "snapshot")
    out = tmp_path / "public"
    assert build(out=out, snapshot=tmp_path / "snapshot", curated=BUILD_FIX / "curated", state=tmp_path / "state",
                 today="2026-10-22") == 0  # fmt: skip
    return out


def dossier(out: Path, pid: str) -> dict:
    return json.loads((out / "dossiers" / f"{pid}.json").read_text(encoding="utf-8"))


LAW_KEYS = ("official_summaries", "court", "consolidated", "advisory_opinions")


def test_the_build_attaches_the_law_context_by_identifier(tmp_path):
    from pipeline.contract import Contract, check_public

    out = built(tmp_path, with_law=True)
    d3 = dossier(out, "2099-0003")
    (s,) = d3["official_summaries"]  # the obsolete one is not shown
    assert (s["id"], s["date"], s["aim_items"]) == ("test_1", "2024-06-01", [1, 2])
    # last updated before Regulation (EU) 2099/1, which amends the directive, was published (1 December 2024)
    assert s["predates"] == {"celex": "32099R0001", "label": "Regulation (EU) 2099/1", "date": "2024-12-01"}
    d1 = dossier(out, "2099-0001")
    assert [x["case"] for x in d1["court"]["interpreted_by"]] == ["C-1/98"]
    assert [(x["case"], x["kind"], x["court"]) for x in d1["court"]["pending"]] == [
        ("C-5/99", "preliminary_reference", "Court of Justice")]  # the decided case is not listed
    assert d1["consolidated"] == [{"act": "32099R0001", "act_label": "Regulation (EU) 2099/1", "versions": [
        {"celex": "02099R0001-20241221", "date": "2024-12-21"}, {"celex": "02099R0001-20991231", "date": "2099-12-31"}]}]
    assert [(o["celex"], o["body"]) for o in d1["advisory_opinions"]] == [("52098AE0001", "EESC")]
    (wd,) = dossier(out, "2099-0002")["court"]["pending"]
    assert (wd["kind"], wd["applicants"], wd["annulled"]) == ("annulment_of_withdrawal", ["European Parliament"],
                                                              "52099XC00001")  # fmt: skip
    assert check_public(out, Contract.load()).lines() == []
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    law = next(x for x in meta["sources"] if x["id"] == "lawcontext")
    assert law["fetched_at"] == NOW and law["summary"].startswith("EUR-Lex's summaries of EU legislation for 1 acts")
    # distinct judgments and cases: C-5/99 on the regulation and C-7/99, the action against a withdrawal
    assert "1 judgments and orders interpreting 1 of the acts, 2 cases before the Court" in law["summary"]


def test_without_the_source_the_pages_are_built_as_before(tmp_path):
    out = built(tmp_path, with_law=False)
    for f in (out / "dossiers").glob("*.json"):
        if f.name != "index.json":
            assert not set(LAW_KEYS) & set(json.loads(f.read_text(encoding="utf-8"))), f.name
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    law = next(x for x in meta["sources"] if x["id"] == "lawcontext")
    assert (law["status"], law["fetched_at"]) == ("unavailable", None)


def test_validate_accepts_an_absent_source_and_checks_a_present_one(tmp_path):
    from pipeline.validate import MIN_RECORDS, check

    shutil.copytree(BUILD_FIX / "snapshot", tmp_path / "snapshot")
    floors = {k: v for k, v in MIN_RECORDS.items() if k[0] == "lawcontext"}
    assert not [e for e in check(tmp_path / "snapshot", min_records=floors).errors if "lawcontext" in e]
    law_files(tmp_path / "snapshot")  # recorded in the manifest: now its floors apply
    errors = [e for e in check(tmp_path / "snapshot", min_records=floors).errors if "lawcontext" in e]
    assert any("lawcontext/acts.json: 1 records, fewer than the 600" in e for e in errors), errors
