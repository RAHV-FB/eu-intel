"""Tests for pipeline.sources.eurlex.

Offline tests parse real (trimmed) Cellar SPARQL responses from tests/fixtures/eurlex/ (each
<name>.json was produced by the query in <name>.rq) for: AI Act 32024R1689, GDPR 32016R0679,
CSRD 32022L2464, NIS2 32022L2555, MDR 32017R0745, Chips Act 32023R1781, Council Decision
32024D0592 and Council Decision 32019D1096 (whose dossier reference contradicts its type).
Snapshot tests check invariants of data/snapshot/eurlex/acts.json when it exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pipeline.http import HttpError
from pipeline.models.entities import LegalAct
from pipeline.snapshot import read_records
from pipeline.sources import eurlex as E

FIX = Path(__file__).parent / "fixtures" / "eurlex"
RETRIEVED = "2026-10-22T00:00:00Z"
AI_ACT = "http://publications.europa.eu/resource/cellar/dc8116a1-3fe6-11ef-865a-01aa75ed71a1"
GDPR = "http://publications.europa.eu/resource/cellar/3e485e15-11bd-11e6-ba9a-01aa75ed71a1"
MDR = "http://publications.europa.eu/resource/cellar/83bdc18f-315d-11e7-9412-01aa75ed71a1"


def fixture_rows(name: str) -> list[dict[str, str]]:
    """Rows exactly as pipeline.http.Http.sparql returns them."""
    doc = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    return [{k: v["value"] for k, v in b.items()} for b in doc["results"]["bindings"]]


VALUES_RE = re.compile(r"VALUES \?w \{ (.*?) \}")


class FixtureClient:
    """Answers the module's batched queries from the fixtures (rows filtered to the batch's works)."""

    def __init__(self) -> None:
        self.calls = 0

    def sparql(self, query: str) -> list[dict[str, str]]:
        self.calls += 1
        m = VALUES_RE.search(query)
        assert m, query
        works = [w.strip("<>") for w in m[1].split()]
        for name, build, _ in E.QUERIES:
            if build(works) == query:
                return [r for r in fixture_rows(name) if r["w"] in works]
        raise AssertionError(f"unexpected query: {query[:300]}")


@pytest.fixture(scope="module")
def fixture_acts() -> dict[str, LegalAct]:
    works = sorted(r["w"] for r in fixture_rows("celex_lookup"))
    acts, dropped = E.collect(FixtureClient(), works, RETRIEVED)
    assert not dropped
    return {a.celex: a for a in acts}


# ------------------------------------------------------------------------------------- small parsers
def test_format_procedure_ref():
    assert E.format_procedure_ref("2021/0106/COD") == "2021/0106(COD)"
    assert E.format_procedure_ref("2021/0106/COD", E.AUTH + "procedure/OLP") == "2021/0106(COD)"
    assert E.format_procedure_ref("2011/0058/CNS", E.AUTH + "procedure/SLP") == "2011/0058(CNS)"
    assert E.format_procedure_ref("2010/2001(BUD)") == "2010/2001(BUD)"
    # contradictory reference/type (Cellar: "2018/0359/COD" typed NLE) and malformed references
    assert E.format_procedure_ref("2018/0359/COD", E.AUTH + "procedure/NLE") is None
    assert E.format_procedure_ref("2008/0073/") is None
    assert E.format_procedure_ref("COD 2013/0162") is None


def test_split_eif_uses_date_type_annotations():
    ev, ma = {"EV"}, {"MA"}
    # retroactive application date and the 1001-01-01 placeholder are not the entry into force
    assert E.split_eif(["1001-01-01", "2014-01-01", "2014-03-16"], {"2014-01-01": ma, "2014-03-16": ev}) == (
        "2014-03-16",
        ["2014-01-01"],
    )
    # decisions that take effect on notification (PE) when no EV date exists
    assert E.split_eif(["2024-01-26"], {"2024-01-26": {"PE"}}) == ("2024-01-26", [])
    # only application dates recorded -> no entry-into-force date (no guessing)
    assert E.split_eif(["2014-07-01"], {"2014-07-01": ma}) == (None, ["2014-07-01"])
    # no annotations at all -> plain property meaning (earliest)
    assert E.split_eif(["2025-01-01", "2024-01-01"], {}) == ("2024-01-01", ["2025-01-01"])
    assert E.split_eif(["1001-01-01"], {"1001-01-01": {"PE"}}) == (None, [])


def test_small_formatters():
    assert E.directory_code("131030") == "13.10.30"
    assert E.oj_date_label("2016-05-04") == "4.5.2016"
    assert E.act_type_for(E.AUTH + "resource-type/DEC_IMPL", "32017D0290") == "decision"
    assert E.act_type_for(E.AUTH + "resource-type/REG", "32024R1689") == "regulation"
    assert E.act_type_for(None, "32022L2464") == "directive"
    assert E._annotation_code("{EV|http://publications.europa.eu/resource/authority/fd_335/EV}") == "EV"
    assert E._annotation_code(
        "{MA/PART|http://publications.europa.eu/resource/authority/fd_335/MA%2FPART}"
    ) == ("MA/PART")


def test_whole_repeal():
    assert E.whole_repeal({})  # link without annotations
    assert E.whole_repeal({"a": (False, set())})
    assert not E.whole_repeal({"a": (True, {"A"}), "b": (False, {"AP"})})  # MDR -> 93/42/EEC
    assert E.whole_repeal({"a": (True, set()), "b": (False, {"A"})})


# ------------------------------------------------------------------------- records from fixtures
def test_ai_act(fixture_acts):
    a = fixture_acts["32024R1689"]
    assert a.procedure_refs == ["2021/0106(COD)"]
    assert a.act_type == "regulation"
    assert a.title.startswith("Regulation (EU) 2024/1689 of the European Parliament and of the Council")
    assert "(Artificial Intelligence Act)" in a.title
    assert a.eli == "http://data.europa.eu/eli/reg/2024/1689/oj"
    assert (a.date_document, a.date_signature, a.date_publication) == (
        "2024-06-13",
        "2024-06-13",
        "2024-07-12",
    )
    assert a.oj_ref == "OJ L, 2024/1689, 12.7.2024"
    assert a.entry_into_force == "2024-08-01"
    assert a.other_application_dates == ["2025-02-02", "2025-08-02", "2026-08-02", "2027-08-02"]
    assert a.end_of_validity is None and a.in_force is True
    assert a.transposition_deadlines == []
    assert "32008R0300" in a.amends and "32020L1828" in a.amends
    assert {(s.scheme, s.code, s.label) for s in a.subjects} >= {
        ("subject-matter", "RDT", "Research and technological development"),
        ("eurovoc", "3030", "artificial intelligence"),
        ("directory", "13.10.30", "Research and technological development"),
    }
    assert a.eurlex_url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689"
    assert a.source.institution == "EUR-Lex" and a.source.identifier == "32024R1689"
    assert a.source.retrieved_at == RETRIEVED


def test_gdpr(fixture_acts):
    a = fixture_acts["32016R0679"]
    assert a.procedure_refs == ["2012/0011(COD)"]
    assert a.oj_ref == "OJ L 119, 4.5.2016" and a.date_publication == "2016-05-04"
    assert a.date_signature == "2016-04-27"
    assert a.entry_into_force == "2016-05-24" and a.other_application_dates == ["2018-05-25"]
    # explicit repeal of Directive 95/46/EC; the implicit repeal of one annex point of 1882/2003 is not
    assert a.repeals == ["31995L0046"]


def test_directives_transposition(fixture_acts):
    csrd, nis2 = fixture_acts["32022L2464"], fixture_acts["32022L2555"]
    assert csrd.act_type == "directive" and csrd.transposition_deadlines == ["2024-07-06"]
    assert csrd.procedure_refs == ["2021/0104(COD)"]
    assert csrd.oj_ref == "OJ L 322, 16.12.2022"
    assert nis2.transposition_deadlines == ["2024-10-17", "2024-10-18"]
    assert nis2.procedure_refs == ["2020/0359(COD)"]
    assert nis2.repeals == ["32016L1148"]


def test_quirky_acts(fixture_acts):
    mdr = fixture_acts["32017R0745"]
    assert mdr.entry_into_force == "2017-05-25"  # not the 1001-01-01 placeholder
    assert "1001-01-01" not in mdr.other_application_dates
    assert mdr.repeals == []  # Cellar classes the repeal of 90/385/EEC and 93/42/EEC as partial
    chips = fixture_acts["32023R1781"]  # linked to its dossier only via the adopted proposal
    assert chips.procedure_refs == ["2022/0032(COD)"]
    dec = fixture_acts["32024D0592"]  # takes effect on notification, before OJ publication
    assert dec.entry_into_force == "2024-01-26" and dec.date_publication == "2024-02-16"
    assert dec.procedure_refs == ["2023/0027(CNS)"]
    assert fixture_acts["32019D1096"].procedure_refs == []  # "2018/0359/COD" typed NLE: not linked


# ---------------------------------------------------------------------------- batching and paging
def test_run_batched_splits_failing_batches():
    calls: list[int] = []

    class Flaky:
        def sparql(self, query: str) -> list[dict[str, str]]:
            works = VALUES_RE.search(query)[1].split()
            calls.append(len(works))
            if "<w5>" in works:
                raise HttpError("u", 500, "fails whenever w5 is in the batch")
            if len(works) > 2:
                raise HttpError("u", 504, "gateway timeout")
            return [{"w": w.strip("<>")} for w in works]

    works = [f"w{i}" for i in range(10)]
    rows, failed = E.run_batched(Flaky(), lambda ws: E._values(ws), works, batch=8, workers=1)
    assert failed == {"w5"}
    assert sorted(r["w"] for r in rows) == sorted(set(works) - {"w5"})
    assert calls[0] == 8


def test_run_batched_does_not_split_malformed_queries():
    class Broken:
        def sparql(self, query: str) -> list[dict[str, str]]:
            raise HttpError("u", 400, "Virtuoso 37000 Error SP030: SPARQL compiler")

    with pytest.raises(HttpError):
        E.run_batched(Broken(), lambda ws: E._values(ws), ["a", "b"], batch=2, workers=1)


def test_discover_scope_pages_and_filters():
    rows = fixture_rows("scope_page_trimmed")
    queries: list[str] = []

    class Pager:
        def sparql(self, query: str) -> list[dict[str, str]]:
            queries.append(query)
            limit, offset = map(int, re.search(r"LIMIT (\d+) OFFSET (\d+)", query).groups())
            return rows[offset : offset + limit]

    scope = E.discover_scope(Pager(), page=3)
    assert len(queries) == 3  # 8 rows in pages of 3
    assert sorted(scope.values()) == [
        "32016R0679",
        "32017R0745",
        "32022L2464",
        "32022L2555",
        "32023R1781",
        "32024D0592",
        "32024R1689",
    ]  # 32019D1096 dropped: its reference contradicts the dossier type


def test_read_featured_celex(tmp_path):
    assert E.read_featured_celex(tmp_path / "missing.yaml") == []
    p = tmp_path / "featured.yaml"
    # the curated file's shape: a list of dossier entries with `celex: [...]`
    p.write_text(
        '- id: "2021-0106"\n  reference: "2021/0106(COD)"\n  celex: ["32024R1689"]\n'
        '- id: "2024-0001"\n  celex: []\n'
        '- id: "2012-0011"\n  celex: ["32016R0679", "02016R0679-20160504"]\n',
        encoding="utf-8",
    )
    assert E.read_featured_celex(p) == ["32016R0679", "32024R1689"]
    p.write_text("celex:\n  - 32022L2464\n  - {celex: 32022L2555, note: NIS2}\n", encoding="utf-8")
    assert E.read_featured_celex(p) == ["32022L2464", "32022L2555"]


# ------------------------------------------------------------------------------ snapshot invariants
SNAPSHOT = read_records("eurlex", "acts", LegalAct)
needs_snapshot = pytest.mark.skipif(not SNAPSHOT, reason="no data/snapshot/eurlex/acts.json")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LETTER = {"R": "regulation", "L": "directive", "D": "decision"}


@needs_snapshot
def test_snapshot_ids_and_types():
    celexes = [a.celex for a in SNAPSHOT]
    assert len(celexes) == len(set(celexes))
    assert celexes == sorted(celexes)
    for a in SNAPSHOT:
        assert E.FEATURED_CELEX_RE.match(a.celex), a.celex
        if a.celex[5] in LETTER:
            assert a.act_type == LETTER[a.celex[5]], a.celex
        assert a.eurlex_url == E.eurlex_url(a.celex)
        assert a.source.institution == "EUR-Lex" and a.source.identifier == a.celex
        assert a.title.strip() == a.title and a.title
        for ref in a.procedure_refs:
            assert re.match(r"^\d{4}/\d{4}\([A-Z]{3}\)$", ref), (a.celex, ref)
        for rel in (a.amends, a.amended_by, a.repeals, a.repealed_by):
            assert rel == sorted(set(rel)) and a.celex not in rel
            assert all(E.LINKED_CELEX_RE.match(c) for c in rel), (a.celex, rel)


@needs_snapshot
def test_snapshot_scope_has_procedures():
    featured = set(E.read_featured_celex())
    for a in SNAPSHOT:
        if a.celex not in featured:
            assert E.BASE_CELEX_RE.match(a.celex), a.celex
            assert a.date_document and a.date_document >= E.MIN_DOCUMENT_DATE, a.celex
            assert any(r[-4:-1] in E.PROCEDURE_TYPES for r in a.procedure_refs), a.celex


@needs_snapshot
def test_snapshot_dates():
    for a in SNAPSHOT:
        dates = [a.date_document, a.date_signature, a.date_publication, a.entry_into_force, a.end_of_validity]
        dates += a.other_application_dates + a.transposition_deadlines
        assert all(ISO.match(d) and d not in E.PLACEHOLDER_DATES for d in dates if d), a.celex
        assert a.other_application_dates == sorted(set(a.other_application_dates))
        assert a.entry_into_force not in a.other_application_dates
        assert a.transposition_deadlines == sorted(set(a.transposition_deadlines))
        if a.transposition_deadlines:
            assert a.act_type == "directive", a.celex
        if a.date_signature and a.date_publication:
            assert a.date_signature <= a.date_publication, a.celex
        if a.date_document and a.date_publication:
            assert a.date_document <= a.date_publication, a.celex
        # Acts signed by the Presidents of Parliament and Council enter into force by reference to
        # publication. (Council acts may take effect on adoption/notification, before publication.)
        if a.date_signature and a.date_publication and a.entry_into_force:
            assert a.date_publication <= a.entry_into_force, a.celex


@needs_snapshot
def test_snapshot_matches_curated_references():
    """Each curated dossier's final act(s) are in the snapshot, linked to that dossier's reference."""
    import yaml

    if not E.FEATURED_FILE.exists():
        pytest.skip("no data/curated/featured.yaml")
    entries = yaml.safe_load(E.FEATURED_FILE.read_text(encoding="utf-8")) or []
    by = {a.celex: a for a in SNAPSHOT}
    for e in entries if isinstance(entries, list) else []:
        for celex in e.get("celex") or []:
            assert celex in by, celex
            if e.get("reference"):
                assert e["reference"] in by[celex].procedure_refs, (celex, e["reference"])


@needs_snapshot
def test_snapshot_known_acts():
    by = {a.celex: a for a in SNAPSHOT}
    if "32024R1689" in by:
        assert by["32024R1689"].procedure_refs == ["2021/0106(COD)"]
    if "32016R0679" in by:
        assert by["32016R0679"].procedure_refs == ["2012/0011(COD)"]


# ----------------------------------------------------------------------------------------- live
@pytest.mark.network
def test_live_known_acts():
    from pipeline.http import Http

    http = Http(cache_dir=None)
    works = E.resolve_celex(http, ["32024R1689", "32016R0679", "32022L2555"])
    acts, dropped = E.collect(http, sorted(works.values()), RETRIEVED)
    by = {a.celex: a for a in acts}
    assert not dropped
    assert by["32024R1689"].procedure_refs == ["2021/0106(COD)"]
    assert by["32024R1689"].entry_into_force == "2024-08-01"
    assert by["32016R0679"].procedure_refs == ["2012/0011(COD)"]
    assert by["32022L2555"].transposition_deadlines == ["2024-10-17", "2024-10-18"]
