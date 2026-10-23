"""Tests for pipeline.sources.eurlex.

Offline tests parse real (trimmed) Cellar SPARQL responses from tests/fixtures/eurlex/ (each
<name>.json was produced by the query in <name>.rq) for: AI Act 32024R1689, GDPR 32016R0679,
CSRD 32022L2464, NIS2 32022L2555, MDR 32017R0745, Chips Act 32023R1781, Council Decision
32024D0592, Council Decision 32019D1096 (whose dossier reference contradicts its type), and the
regression cases 32020R0127 (wrong year in Cellar's dates), 32016R2031 (repeal link changed by a later
act), 32022L2041 / 32020R1055 (partially annulled), 32019R1157 (declared invalid) and 32017R1001
(trade-mark judgments linked to it that do not annul it).
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
    # Art. 41(1) NIS2: adopt and publish by 17 October 2024, apply from 18 October 2024
    assert [(t.date, t.labels, t.articles) for t in nis2.transposition_dates] == [
        ("2024-10-17", ["ADOPTION"], ["41.1"]),
        ("2024-10-18", ["APPLICATION"], ["41.1"]),
    ]
    assert [(t.date, t.labels) for t in csrd.transposition_dates] == [("2024-07-06", [])]
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


def test_entry_into_force_pending():
    """Electoral Act amendment 2018/994: EV value 1001-01-01 (date of notification), in force = 0."""
    f = E.Facts()
    f.props.update({
        "celex": {"32018D0994"},
        "eif": {"1001-01-01"},
        "end_of_validity": {"9999-12-31"},
        "in_force": {"0"},
    })  # fmt: skip
    f.titles.add("Council Decision (EU, Euratom) 2018/994 of 13 July 2018 amending the Act concerning the election")
    E.add_eif_types({"w": f}, [{"w": "w", "d": "1001-01-01", "type": "{EV|http://publications.europa.eu/resource/"
                                "authority/fd_335/EV}", "comment": DATNOT + " {V|.../fd_335/V} {ART|.../fd_335/ART} 2.2"}])  # fmt: skip
    act = E.build_act("w", f, RETRIEVED)
    assert act is not None
    assert act.entry_into_force is None and act.entry_into_force_pending
    assert act.entry_into_force_articles == ["2.2"] and not act.effect_on_notification
    assert act.in_force is False and act.end_of_validity is None


DATNOT = "{DATNOT|http://publications.europa.eu/resource/authority/fd_335/DATNOT}"


def test_effect_on_notification_is_not_a_pending_entry_into_force():
    """Decision 2020/853 ("addressed to the Federal Republic of Germany", Art. 3): Cellar gives its date of
    effect (PE) as 1001-01-01 with comment DATNOT and no EV value; it takes effect on notification."""
    f = E.Facts()
    f.props.update({
        "celex": {"32020D0853"},
        "eif": {"1001-01-01"},
        "end_of_validity": {"9999-12-31"},
        "in_force": {"0"},
    })  # fmt: skip
    f.titles.add("Decision (EU) 2020/853 of the European Parliament and of the Council of 18 June 2020 empowering Germany")
    E.add_eif_types({"w": f}, [{"w": "w", "d": "1001-01-01", "type": "{PE|http://publications.europa.eu/resource/"
                                "authority/fd_335/PE}", "comment": DATNOT}])  # fmt: skip
    act = E.build_act("w", f, RETRIEVED)
    assert act is not None
    assert act.effect_on_notification and not act.entry_into_force_pending
    assert act.entry_into_force is None and act.entry_into_force_articles == []


def test_validity_notes():
    """Cellar's comments on end-of-validity values (live values, 2026-10-23)."""
    auth = "http://publications.europa.eu/resource/authority/fd_330/"
    f = E.Facts()
    E.add_validity_notes({"w": f}, [
        # 32014R0335: end of validity 2013-12-31, before the act itself (11 March 2014)
        {"w": "w", "d": "2013-12-31", "c": f"{{A/PAR|{auth}A%2FPAR}} "
                                           "{32014R0508|http://publications.europa.eu/resource/celex/32014R0508}"},
        # 32015R2424
        {"w": "w", "d": "2017-09-30", "c": f"{{AI/PAR|{auth}AI%2FPAR}} 32017R1001 {{AND|{auth}AND}} 32017R1430"},
        # 32020D1531, next to 9999-12-31
        {"w": "w", "d": "2024-03-17", "c": f"{{FIN/VAL/PART|{auth}FIN%2FVAL%2FPART}} {{V|{auth}V}} 32024D0867 "
                                           f"{{ART|{auth}ART}} 6 {{repealing.act.provisional.date.notification."
                                           "disclaimer|http://publications.europa.eu/resource/authority/fd_365/"
                                           "repealing.act.provisional.date.notification.disclaimer}"},
        # 32019R1157: replaced after judgment C-61/22 (case law is not an act)
        {"w": "w", "d": "2025-07-09", "c": f"{{R/PAR|{auth}R%2FPAR}} 32025R1208 {{V|{auth}V}} 62022CJ0061"},
        {"w": "w", "d": "9999-12-31", "c": "placeholder"},
    ])  # fmt: skip
    notes = [(n.date, n.partial, n.codes, n.acts) for n in E.validity_notes(f)]
    assert notes == [
        ("2013-12-31", False, ["A/PAR"], ["32014R0508"]),
        ("2017-09-30", False, ["AI/PAR", "AND"], ["32017R1001", "32017R1430"]),
        ("2024-03-17", True, ["FIN/VAL/PART", "V", "ART", "repealing.act.provisional.date.notification.disclaimer"],
         ["32024D0867"]),
        ("2025-07-09", False, ["R/PAR", "V"], ["32025R1208"]),
    ]


def test_transposition_dates_annotations():
    notes = {
        "2025-04-14": {"{APPLICATION|x/APPLICATION} {V|x/V} {ART|x/ART} 6.1"},
        "2026-12-31": {"{ADOPTION|x/ADOPTION} {AU+TARD|x/AU%2BTARD} {V|x/V} {ART|x/ART} 6.2"},
    }
    got = E.transposition_dates(["2025-04-14", "2026-12-31", "2027-01-01"], notes)
    assert [(t.date, t.labels, t.articles) for t in got] == [
        ("2025-04-14", ["APPLICATION"], ["6.1"]),
        ("2026-12-31", ["ADOPTION", "AU+TARD"], ["6.2"]),
        ("2027-01-01", [], []),
    ]


def test_title_date():
    assert E.title_date(
        "Regulation (EU) 2020/127 of the European Parliament and of the Council of 29 January 2020 amending"
    ) == ("2020-01-29")
    assert E.title_date("Council Decision (EU) 2024/592 of 23 January 2024 empowering France") == "2024-01-23"
    assert E.title_date("Directive 2014/60/EU ... amending Regulation (EU) No 1024/2012 (Recast)") is None


def test_official_title_date_prevails(fixture_acts):
    # Cellar records work_date_document and resource_legal_date_signature 2019-01-29 for this act;
    # its official title (and OJ text) says "of 29 January 2020", and the proposal dates from 2019-10-31.
    a = fixture_acts["32020R0127"]
    assert a.title.startswith(
        "Regulation (EU) 2020/127 of the European Parliament and of the Council of 29 January 2020"
    )
    assert (a.date_document, a.date_signature) == ("2020-01-29", "2020-01-29")
    assert a.procedure_refs == ["2019/0253(COD)"]


def test_repeal_kept_when_changed_by_later_act(fixture_acts):
    # The repeal of Directive 2000/29/EC is annotated with "32017R0625 {AR} 165 {PO} 16" (the provision
    # of Regulation 2017/625 that amended the repealing article), not with a part of 2000/29/EC.
    a = fixture_acts["32016R2031"]
    assert a.repeals == [
        "31969L0464",
        "31974L0647",
        "31993L0085",
        "31998L0057",
        "32000L0029",
        "32006L0091",
        "32007L0033",
    ]
    assert not E._target_location(
        "32017R0625 {AR|http://publications.europa.eu/resource/authority/fd_370/AR} 165"
    )
    assert E._target_location("{AR|http://publications.europa.eu/resource/authority/fd_370/AR} 3")


def test_court_rulings(fixture_acts):
    (mw,) = fixture_acts["32022L2041"].court_rulings
    assert (mw.celex, mw.case_number, mw.ecli, mw.date) == (
        "62023CJ0019",
        "C-19/23",
        "ECLI:EU:C:2025:865",
        "2025-11-11",
    )
    assert mw.effect == "annulment" and mw.provisions == ["A05P1", "A05P2", "A05P3"]
    assert mw.title == (
        "Judgment of the Court (Grand Chamber) of 11 November 2025. "
        "Kingdom of Denmark v European Parliament and Council of the European Union."
    )
    assert mw.effect_text.endswith("Partial annulment – Article 5(1), in part, (2) and (3) in fine")
    assert mw.url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62023CJ0019"
    (mob,) = fixture_acts["32020R1055"].court_rulings
    assert (mob.celex, mob.case_number, mob.effect) == (
        "62020CJ0541",
        "Joined Cases C-541/20 to C-555/20",
        "annulment",
    )
    assert mob.provisions == ["A01PT3"]
    (ids,) = fixture_acts["32019R1157"].court_rulings
    assert (ids.celex, ids.case_number, ids.effect, ids.date) == (
        "62022CJ0061",
        "C-61/22",
        "invalidity",
        "2024-03-21",
    )
    # General Court trade-mark judgments (defended by EUIPO) linked to the EU Trade Mark Regulation
    assert fixture_acts["32017R1001"].court_rulings == []
    assert fixture_acts["32024R1689"].court_rulings == []


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
    rows = fixture_rows("scope_pages_trimmed")
    queries: list[str] = []

    class Pager:
        def sparql(self, query: str) -> list[dict[str, str]]:
            queries.append(query)
            if query == E.scope_count_query():
                return [{"n": str(len(rows))}]
            limit, offset = map(int, re.search(r"LIMIT (\d+) OFFSET (\d+)", query).groups())
            return rows[offset : offset + limit]

    scope, gap = E.discover_scope(Pager(), page=3)
    assert len(queries) == len(rows) // 3 + 1 + 1  # pages, then the count
    assert gap is None  # the rows add up to Cellar's count
    assert "32024R1689" in scope.values() and "32016R0679" in scope.values()
    # 32019D1096 dropped: its reference contradicts the dossier type
    assert sorted(scope.values()) == sorted({r["celex"] for r in rows} - {"32019D1096"})

    class Truncated(Pager):  # the second page answered short (a partial result): the paging ends there
        def sparql(self, query: str) -> list[dict[str, str]]:
            got = super().sparql(query)
            return got[:1] if "OFFSET 3" in query else got

    scope, gap = E.discover_scope(Truncated(), page=3)
    assert gap == f"4 rows against {len(rows)} counted by Cellar" and len(scope) < len(rows) - 1


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


def test_validity_notes_from_fixtures(fixture_acts):
    # 32019R1157 (identity cards), declared invalid in C-61/22: "Replaced by 32025R1208" on 2025-07-09
    a = fixture_acts["32019R1157"]
    assert [(n.date, n.codes[0], n.acts) for n in a.validity_notes] == [("2025-07-09", "R/PAR", ["32025R1208"])]
    assert fixture_acts["32024R1689"].validity_notes == []


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
def test_snapshot_unrecorded_entry_into_force():
    for a in SNAPSHOT:
        assert not (a.entry_into_force_pending and a.effect_on_notification), a.celex
        if a.effect_on_notification:
            assert a.act_type == "decision" and a.entry_into_force is None, a.celex
        if a.entry_into_force_articles:
            assert a.entry_into_force_pending, a.celex
        for n in a.validity_notes:
            assert ISO.match(n.date) and n.date not in E.PLACEHOLDER_DATES, a.celex
    by = {a.celex: a for a in SNAPSHOT}
    assert by["32020D0853"].effect_on_notification and by["32018D0994"].entry_into_force_pending


@needs_snapshot
def test_snapshot_scope_has_procedures():
    # featured acts and final acts that OEIL records for a procedure (Cellar may not link them to it)
    featured = set(E.read_featured_celex()) | set(E.procedure_celex_refs())
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
                # EUR-Lex links acts of split procedures (2016/0224A(COD)) to the parent reference
                parent = re.sub(r"^(\d{4}/\d{4})[A-Z]", r"\1", e["reference"])
                refs = by[celex].procedure_refs
                assert e["reference"] in refs or parent in refs, (celex, e["reference"])


@needs_snapshot
def test_snapshot_dates_match_official_title():
    for a in SNAPSHOT:
        td = E.title_date(a.title)
        if td:
            assert a.date_document == td, a.celex
            if a.date_signature:
                assert a.date_signature == td, a.celex
        for r in a.procedure_refs:
            if a.date_document:
                assert a.date_document[:4] >= r[:4], (a.celex, r)  # not adopted before its procedure began


@needs_snapshot
def test_snapshot_court_rulings():
    for a in SNAPSHOT:
        assert [(r.date or "", r.celex) for r in a.court_rulings] == sorted(
            (r.date or "", r.celex) for r in a.court_rulings
        )
        for r in a.court_rulings:
            assert re.match(r"^6\d{4}[A-Z]{2}\d{4}$", r.celex), (a.celex, r.celex)
            assert r.title.startswith("Judgment of the"), (a.celex, r.celex)
            if r.date and a.date_publication:
                assert r.date > a.date_publication, (a.celex, r.celex)


@needs_snapshot
def test_snapshot_known_acts():
    by = {a.celex: a for a in SNAPSHOT}
    if "32024R1689" in by:
        assert by["32024R1689"].procedure_refs == ["2021/0106(COD)"]
    if "32016R0679" in by:
        assert by["32016R0679"].procedure_refs == ["2012/0011(COD)"]
    if "32020R0127" in by:
        assert by["32020R0127"].date_signature == "2020-01-29"
    if "32016R2031" in by:
        assert "32000L0029" in by["32016R2031"].repeals
    if "32022L2041" in by:
        assert [r.case_number for r in by["32022L2041"].court_rulings] == ["C-19/23"]


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


def test_procedure_notices():
    rows = [
        {"ref": "2016/0337/CNS", "type": E.AUTH + "event/RPL_byCOM", "date": "2023-09-12", "doc": "COM/2023/532/FINAL"},
        {"ref": "2023/0133/COD", "type": E.AUTH + "event/WDW_byCOM", "date": "2025-10-06"},
        {"ref": "2023/0133/COD", "type": E.AUTH + "event/WDW_byCOM", "date": "2025-10-06", "doc": "JO C/2025/5423"},
        {"ref": "2023/0133/COD", "type": E.AUTH + "event/ADP_byCOM", "date": "2023-04-27"},
    ]
    got = E.build_notices(rows, RETRIEVED)
    assert [(n.reference, n.kind, n.date, n.document) for n in got] == [
        ("2016/0337(CNS)", "replaced", "2023-09-12", "COM(2023)0532"),
        ("2023/0133(COD)", "withdrawn", "2025-10-06", None),
    ]
    assert got[0].id == "2016/0337(CNS):replaced:2023-09-12"
    assert got[0].source.url == "https://eur-lex.europa.eu/procedure/EN/2016_337"


# ------------------------------------------------------------------------- fetch: incomplete answers
def notice_rows(n: int) -> list[dict[str, str]]:
    """n Commission withdrawals on made-up procedures 2016/0001/COD ... (rows as the notices query gives them)."""
    return [
        {"ref": f"2016/{i:04d}/COD", "type": E.AUTH + "event/WDW_byCOM", "date": "2020-01-01"}
        for i in range(1, n + 1)
    ]


class Cellar:
    """Answers fetch()'s queries: the scope pages and their count (scope_pages_trimmed), the batched act
    queries (FixtureClient) and the procedure notices. `scope_rows` / `count` / `notices` change the answers."""

    def __init__(self, scope_rows=None, count=None, notices=None):
        self.rows = fixture_rows("scope_pages_trimmed") if scope_rows is None else scope_rows
        self.count = count if count is not None else len(fixture_rows("scope_pages_trimmed"))
        self.notices = notice_rows(21) if notices is None else notices
        self.acts = FixtureClient()
        self.queries: list[str] = []

    def sparql(self, query: str) -> list[dict[str, str]]:
        self.queries.append(query)
        if query == E.scope_count_query():
            if isinstance(self.count, Exception):
                raise self.count
            return [{"n": str(self.count)}]
        if "LIMIT" in query and "OFFSET" in query:
            limit, offset = map(int, re.search(r"LIMIT (\d+) OFFSET (\d+)", query).groups())
            return self.rows[offset : offset + limit]
        if query == E.procedure_notices_query():
            if isinstance(self.notices, Exception):
                raise self.notices
            return self.notices
        return self.acts.sparql(query)


@pytest.fixture
def eurlex_snapshot(tmp_path, monkeypatch):
    import pipeline.snapshot as snap

    monkeypatch.setattr(snap, "SNAPSHOT", tmp_path)
    monkeypatch.setattr(E, "read_featured_celex", lambda: [])
    monkeypatch.setattr(E, "procedure_celex_refs", lambda: [])
    for var in ("EU_INTEL_FETCH_BUDGET_S", "EU_INTEL_FETCH_DEADLINE"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def stored(root: Path, name: str) -> list[str]:
    return (root / "eurlex" / f"{name}.json").read_text(encoding="utf-8").splitlines()


def unsettled(root: Path) -> dict:
    return json.loads((root / "eurlex" / "_state.json").read_text(encoding="utf-8"))["unsettled"]


def test_fetch_keeps_the_stored_notices_when_the_answer_is_empty_or_short(eurlex_snapshot):
    """An empty or truncated notices answer (Virtuoso can answer a timed-out query with HTTP 200 and part of
    the rows) used to rewrite procedure_notices.json, 272 -> 0, with status 'ok': the dossiers withdrawn or
    replaced on these notices alone then changed status, permanently in the activity log."""
    first = E.fetch(Cellar())
    assert first.status == "ok" and "21 withdrawal/replacement notices" in first.note
    assert unsettled(eurlex_snapshot) == {"attempted_at": first.attempted_at, "acts": [], "procedures": []}
    before = stored(eurlex_snapshot, "procedure_notices")
    for answer in ([], notice_rows(19), RuntimeError("SPARQL endpoint unavailable")):
        status = E.fetch(Cellar(notices=answer))
        assert stored(eurlex_snapshot, "procedure_notices") == before
        assert status.status == "partial" and "previous file kept" in status.note
        # every dossier resting on the stored notices waits for a refreshed answer (pipeline/analysis/activity.py)
        assert len(unsettled(eurlex_snapshot)["procedures"]) == 21
    # within 5%: written, and the procedure that lost its notice is named for change detection
    status = E.fetch(Cellar(notices=notice_rows(20)))
    assert len(stored(eurlex_snapshot, "procedure_notices")) == 20 + 2
    assert status.status == "ok" and unsettled(eurlex_snapshot)["procedures"] == ["2016/0021(COD)"]


def test_fetch_keeps_stored_acts_missing_from_an_incomplete_scope_answer(eurlex_snapshot, monkeypatch):
    """discover_scope stops at the first short page, which a truncated answer also is: works missing from it
    used to be dropped from acts.json while the run reported 'ok'."""
    E.fetch(Cellar())
    before = stored(eurlex_snapshot, "acts")
    rows = fixture_rows("scope_pages_trimmed")
    short = [r for r in rows if r["celex"] not in ("32016R0679", "32024R1689")]  # GDPR, AI Act
    status = E.fetch(Cellar(scope_rows=short))  # Cellar still counts every row
    assert stored(eurlex_snapshot, "acts") == before  # the two stored records are kept as they were
    assert status.status == "partial" and "scope answer possibly incomplete (12 rows against 14" in status.note
    assert "2 stored acts missing from this run's answers kept" in status.note
    assert unsettled(eurlex_snapshot)["acts"] == ["32016R0679", "32024R1689"]
    # the count cannot be read: not checked, so they are kept as well
    status = E.fetch(Cellar(scope_rows=short, count=HttpError("u", 500, "count failed")))
    assert stored(eurlex_snapshot, "acts") == before and status.status == "partial"
    # a complete answer without them (its rows match the count): they left the scope and are removed
    monkeypatch.setattr(E, "MAX_FAILED_SHARE", 0.2)  # (the fixture is small: 2 of 13 is more than 5%)
    status = E.fetch(Cellar(scope_rows=short, count=len(short)))
    celex = {json.loads(x.rstrip(","))["celex"] for x in stored(eurlex_snapshot, "acts") if x.startswith("{")}
    assert len(celex) == 11 and not {"32016R0679", "32024R1689"} & celex
    assert status.status == "ok" and unsettled(eurlex_snapshot)["acts"] == []


def test_fetch_starts_no_query_after_its_time_budget(eurlex_snapshot, monkeypatch):
    E.fetch(Cellar())
    before = stored(eurlex_snapshot, "acts")
    monkeypatch.setenv("EU_INTEL_FETCH_BUDGET_S", "0")
    http = Cellar()
    with pytest.raises(RuntimeError, match="no acts could be built"):  # the source fails: its files are kept
        E.fetch(http)
    assert not any("VALUES ?w" in q for q in http.queries)  # no act query was started
    assert stored(eurlex_snapshot, "acts") == before
