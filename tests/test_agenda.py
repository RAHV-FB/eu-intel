"""The steps the Council and Parliament have scheduled (pipeline/sources/agenda.py) and their place on the site
(pipeline/analysis/scheduled.py, pipeline/build.py). The parsing tests read real answers of 5 November 2026, trimmed
(tests/fixtures/agenda: the agenda fetch's Cellar queries, the EP API's sittings and two sittings' draft agendas); the
build tests add invented planned steps to the invented build fixture (tests/fixtures/build)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pipeline.analysis.scheduled import (
    HOME_BADGE,
    home_items,
    home_subtitle,
    meeting_name,
    scheduled_by_dossier,
)
from pipeline.build import build
from pipeline.http import EP_API, HttpError
from pipeline.models.entities import DocRef, PlannedStep, SourceRef
from pipeline.snapshot import read_records
from pipeline.sources.agenda import (
    build_planned,
    build_plenary,
    council_doc,
    document_facts,
    fetch,
    upcoming_sittings,
)

FIX = Path(__file__).parent / "fixtures" / "agenda"
BUILD_FIX = Path(__file__).parent / "fixtures" / "build"
TODAY = "2026-11-05"
RETRIEVED = "2026-11-05T15:12:16Z"
# the Council documents of the answer that answered on data.consilium.europa.eu on 5 November 2026 (the others: 404)
PUBLIC = {"CM 4825 2026 INIT", "PE 34 2026 INIT", "ST 15156 2026 INIT", "ST 15180 2026 INIT"}


def sparql_rows(name: str) -> list[dict[str, str]]:
    """A SPARQL JSON answer as Http.sparql returns it."""
    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    return [{k: v["value"] for k, v in b.items()} for b in doc["results"]["bindings"]]


def api_data(name: str) -> list[dict]:
    return json.loads((FIX / name).read_text(encoding="utf-8"))["data"]


def planned_steps() -> list[PlannedStep]:
    facts = document_facts(sparql_rows("documents.sparql.json"))
    public = {r: f"https://data.consilium.europa.eu/doc/document/{council_doc(r)[1]}/EN/pdf" for r in PUBLIC}
    steps, _ = build_planned(sparql_rows("planned.sparql.json"), RETRIEVED, facts, public)
    return steps


def labels() -> dict[str, str]:
    return {r["c"]: r["label"] for r in sparql_rows("labels.sparql.json")}


def plenary_steps(sitting: str) -> list[PlannedStep]:
    return build_plenary(api_data(f"foreseen-{sitting}.json"), sitting, RETRIEVED, labels())[0]


# ------------------------------------------------------------------------------------------- Cellar
def test_council_document_references_are_cited_as_the_council_prints_them():
    assert council_doc("CM 4825 2026 INIT") == (
        "CM 4825/26",
        "CM-4825-2026-INIT",
    )  # agenda header: "CM 4825/26"
    assert council_doc("PE 34 2026 INIT") == (
        "PE-CONS 34/26",
        "PE-34-2026-INIT",
    )  # its first page: "PE-CONS 34/26"
    assert council_doc("CM 4750 2026 COR 1") == ("CM 4750/26 COR 1", "CM-4750-2026-COR-1")
    assert council_doc("ST  9999 2026 REV 1") == ("ST 9999/26 REV 1", "ST-9999-2026-REV-1")
    assert council_doc("COM(2023) 279") is None


def test_planned_events_one_per_event_with_the_authority_labels_verbatim():
    by = {s.id: s for s in planned_steps()}
    # 12 rows (one per event and document named) are 9 events
    assert len(by) == 9
    adoption = by["cellar:2023_169.2026-11-19_APR_R1_byCONSIL"]
    assert (adoption.reference, adoption.date, adoption.institution) == (
        "2023/0169(COD)",
        "2026-11-19",
        "Council",
    )
    assert (
        adoption.label
        == "Approval of the EP's first reading position by the Council (adoption of the legislative act)"
    )
    assert (adoption.phase_code, adoption.phase) == ("PROC_END", "End of procedure")
    # the meeting is the one its agenda names, as titled in Cellar; the documents are linked where public
    assert adoption.meeting == "COUNCIL OF THE EUROPEAN UNION (General Affairs)"
    assert [(d.id, d.kind, d.url) for d in adoption.documents] == [
        ("CM 4825/26", "agenda", "https://data.consilium.europa.eu/doc/document/CM-4825-2026-INIT/EN/pdf"),
        ("PE-CONS 34/26", "act", "https://data.consilium.europa.eu/doc/document/PE-34-2026-INIT/EN/pdf"),
    ]
    assert adoption.source.url == (
        "https://publications.europa.eu/resource/procedure-event/2023_169.2026-11-19_APR_R1_byCONSIL"
    )
    assert (
        adoption.source.institution == "EUR-Lex"
        and adoption.source.identifier == "2023_169.2026-11-19_APR_R1_byCONSIL"
    )
    coreper = by["cellar:2025_399.2026-11-06_DELIB_COREPER_byCONSIL"]
    assert (
        coreper.label == "Deliberations in Coreper"
        and coreper.meeting == "PERMANENT REPRESENTATIVES COMMITTEE (Part 1)"
    )
    # ST 14751/26, a Council note, had no public copy (404): named, not linked
    assert [(d.id, d.kind, d.url is not None) for d in coreper.documents] == [
        ("ST 14751/26", "other", False), ("ST 15180/26", "agenda", True)]  # fmt: skip
    mandate = by["cellar:2026_169.2026-11-06_ADP_MAND_NGT_INST_COREPER_byCONSIL"]
    assert mandate.label == "Adoption of negotiating mandate by Coreper"
    assert mandate.meeting == "PERMANENT REPRESENTATIVES COMMITTEE (Part 2)"
    # no document named: no meeting either (never guessed from the date)
    deliberation = by["cellar:2025_391.2026-11-19_DELIB_byCONSIL"]
    assert (deliberation.label, deliberation.meeting, deliberation.documents) == (
        "Deliberations in Council",
        None,
        [],
    )
    vote = by["cellar:2023_131.2026-11-25_VOTE_byEP"]
    assert (vote.institution, vote.label, vote.phase) == ("EP", "Vote in EP plenary", "Second reading")


def test_a_planned_step_on_a_part_of_a_split_procedure_is_kept():
    """Cellar records the parts of a split procedure as "2023/0077B/COD" (the Council adopted that part's act on 21 May
    2024 by an event of that reference); such a planned step was counted as having no reference and left out."""
    rows = sparql_rows("planned.sparql.json")
    vote = next(r for r in rows if r["ref"] == "2023/0167/COD" and r["type"].endswith("VOTE_byEP"))
    part = {**vote, "ev": vote["ev"] + "b", "same": vote["same"].replace("2023_167.", "2023_77B."), "ref": "2023/0077B/COD"}
    steps, skipped = build_planned([part], RETRIEVED)
    assert [s.reference for s in steps] == ["2023/0077B(COD)"] and skipped["no_reference"] == 0


def test_a_planned_event_without_its_label_or_not_planned_is_left_out():
    rows = sparql_rows("planned.sparql.json")
    vote = next(r for r in rows if r["ref"] == "2023/0167/COD" and r["type"].endswith("VOTE_byEP"))
    unlabelled = {k: v for k, v in vote.items() if k != "label"}
    done = {
        **vote,
        "ev": vote["ev"] + "x",
        "status": "http://publications.europa.eu/resource/authority/event-status/DONE",
    }
    other = {**vote, "ev": vote["ev"] + "y", "inst": "http://publications.europa.eu/resource/authority/corporate-body/EESC",
             "type": "http://publications.europa.eu/resource/authority/event/OPINION_byEESC"}  # fmt: skip
    steps, skipped = build_planned([unlabelled, done, other], RETRIEVED)
    assert steps == [] and skipped == {
        "no_reference": 0,
        "no_label": 1,
        "other_institution": 1,
        "not_planned": 1,
    }


# ------------------------------------------------------------------------------------------- Parliament
def test_the_sittings_of_the_coming_weeks():
    rows = api_data("meetings-2026.json")
    sittings = upcoming_sittings(rows, TODAY)
    assert sittings[0] == ("MTG-PL-2026-11-11", "2026-11-11")
    assert sittings[-1] == ("MTG-PL-2026-12-17", "2026-12-17")  # 42 days ahead, the last day included
    assert all(TODAY <= d for _, d in sittings) and len(sittings) == 10
    assert [d for _, d in upcoming_sittings(rows, TODAY, 21)][-1] == "2026-11-26"


def test_plenary_agenda_items_one_per_procedure_named():
    by = {s.id: s for s in plenary_steps("MTG-PL-2026-11-25")}
    # V-9 ("Texts on which debate is closed") and D-10 (a topical debate) name no procedure
    assert set(by) == {
        "ep:MTG-PL-2026-11-25-OJ-ITM-V-60:2023-0132", "ep:MTG-PL-2026-11-25-OJ-ITM-V-61:2023-0131",
        "ep:MTG-PL-2026-11-25-OJ-ITM-V-71:2025-0405", "ep:MTG-PL-2026-11-25-OJ-ITM-V-72:2025-0162",
    }  # fmt: skip
    second = by["ep:MTG-PL-2026-11-25-OJ-ITM-V-60:2023-0132"]
    assert (second.reference, second.date, second.institution) == ("2023/0132(COD)", "2026-11-25", "EP")
    assert (second.event_type, second.label, second.phase) == (
        "VOTE_byEP",
        "Vote in EP plenary",
        "Second reading",
    )
    assert second.item == "Union code relating to medicinal products for human use"
    assert (
        second.source.url
        == f"{EP_API}/meetings/MTG-PL-2026-11-25/foreseen-activities?format=application%2Fld%2Bjson"
    )
    assert second.source.identifier == "MTG-PL-2026-11-25-OJ-ITM-V-60"
    assert second.source.label == "Parliament's draft agenda for 25 November 2026 (EP Open Data API)"
    swiss = by["ep:MTG-PL-2026-11-25-OJ-ITM-V-72:2025-0162"]
    assert swiss.reference == "2025/0162(NLE)" and swiss.phase is None
    assert [(d.label, d.url) for d in swiss.documents] == [
        ("A10-0236/2026", "https://www.europarl.europa.eu/doceo/document/A-10-2026-0236_EN.html")]  # fmt: skip
    debates = {s.id: s for s in plenary_steps("MTG-PL-2026-11-12") if s.event_type == "DEBATE_byEP"}
    assert [(s.reference, s.label) for s in debates.values()] == [("2026/2949(RSP)", "Debate in EP plenary")]


def test_an_item_whose_type_has_no_label_is_left_out():
    items = api_data("foreseen-MTG-PL-2026-11-25.json")
    steps, unlabelled = build_plenary(items, "MTG-PL-2026-11-25", RETRIEVED, {})
    assert steps == [] and unlabelled == 4


# ------------------------------------------------------------------------------------------- fetch
class Sources:
    """The official answers of 5 November 2026 (fixtures); `down`: the parts that fail ("cellar", "meetings", or a
    sitting id); `errors`: Council documents whose request fails other than with 404."""

    def __init__(self, down: tuple[str, ...] = (), errors: tuple[str, ...] = ()):
        self.down, self.errors, self.requests = down, errors, []

    def sparql(self, query: str, use_cache: bool = True) -> list[dict[str, str]]:
        self.requests.append("sparql")
        if "event_legal_projected" in query:
            if "cellar" in self.down:
                raise HttpError("sparql", 503, "Service Unavailable")
            return sparql_rows("planned.sparql.json")
        if "work_id_document" in query:
            return sparql_rows("documents.sparql.json")
        return sparql_rows("labels.sparql.json")

    def get(self, url: str, params: dict | None = None, **kw) -> bytes:
        self.requests.append(url)
        if url.startswith("https://data.consilium.europa.eu/"):
            assert kw.get("use_cache") is False  # PDFs are not kept in the cache
            ref = url.split("/document/")[1].split("/")[0]
            if any(ref == council_doc(e)[1] for e in self.errors):
                raise HttpError(url, 503, "Service Unavailable")
            if not any(ref == council_doc(p)[1] for p in PUBLIC):
                raise HttpError(url, 404, "Not Found")
            return b"%PDF-1.7"
        assert url.startswith(EP_API) and kw.get("use_cache") is False  # the agenda changes until the sitting
        path = url.removeprefix(EP_API)
        if path == "/meetings":
            if "meetings" in self.down:
                raise HttpError(url, 500, "Internal Server Error")
            if "meetings-empty" in self.down:  # an answer without the year's sittings
                return b'{"data": []}'
            return (FIX / "meetings-2026.json").read_bytes() if params["year"] == "2026" else b""
        sitting = path.split("/")[2]
        if sitting in self.down:
            raise HttpError(url, 503, "Service Unavailable")
        fixture = FIX / f"foreseen-{sitting}.json"
        return fixture.read_bytes() if fixture.exists() else b""  # HTTP 204: not published yet


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    import pipeline.snapshot as snap

    monkeypatch.setattr(snap, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    monkeypatch.delenv("EU_INTEL_FETCH_DEADLINE", raising=False)
    return tmp_path


def test_fetch_writes_both_schedules(snapshot):
    http = Sources()
    status = fetch(http, today=TODAY)
    assert status.status == "ok", status.note
    planned = read_records("agenda", "planned", PlannedStep)
    plenary = read_records("agenda", "plenary", PlannedStep)
    assert (
        status.records == {"planned": len(planned), "plenary": len(plenary)} == {"planned": 9, "plenary": 8}
    )
    assert "4 of 6 Council documents named have a public copy" in status.note
    assert "on the agendas of 2 of the 10 plenary sittings of the next 42 days" in status.note
    # each Council document is requested once, though CM 4825/26 is named by three events
    assert sum("CM-4825-2026-INIT" in r for r in http.requests) == 1


def test_a_schedule_that_cannot_be_read_keeps_its_previous_file(snapshot):
    fetch(Sources(), today=TODAY)
    status = fetch(Sources(down=("cellar",)), today=TODAY)
    assert status.status == "partial" and "Cellar planned events not read" in status.note
    assert len(read_records("agenda", "planned", PlannedStep)) == 9 and status.records == {"plenary": 8}
    status = fetch(Sources(down=("meetings",)), today=TODAY)
    assert status.status == "partial" and len(read_records("agenda", "plenary", PlannedStep)) == 8
    # no sitting listed at all, past ones included, is no recess: the agenda read before is kept
    status = fetch(Sources(down=("meetings-empty",)), today=TODAY)
    assert status.status == "partial" and "no plenary sittings listed for 2026" in status.note
    assert len(read_records("agenda", "plenary", PlannedStep)) == 8
    with pytest.raises(RuntimeError, match="not read"):
        fetch(Sources(down=("cellar", "meetings")), today=TODAY)


def test_a_sitting_whose_agenda_cannot_be_read_keeps_its_earlier_records(snapshot):
    fetch(Sources(), today=TODAY)
    status = fetch(Sources(down=("MTG-PL-2026-11-25",)), today=TODAY)
    assert (
        status.status == "partial"
        and "1 sittings not read (MTG-PL-2026-11-25), 4 of their earlier records kept" in status.note
    )
    assert sorted({s.date for s in read_records("agenda", "plenary", PlannedStep)}) == [
        "2026-11-12",
        "2026-11-25",
    ]


def test_a_council_document_not_checked_is_not_linked_and_the_run_is_partial(snapshot):
    status = fetch(Sources(errors=("CM 4825 2026 INIT",)), today=TODAY)
    assert (
        status.status == "partial"
        and "1 Council documents not checked for a public copy (CM 4825 2026 INIT)" in status.note
    )
    docs = {d.id: d for s in read_records("agenda", "planned", PlannedStep) for d in s.documents}
    assert docs["CM 4825/26"].url is None and docs["PE-CONS 34/26"].url


# ------------------------------------------------------------------------------------------- for the site
def test_meeting_names():
    assert (
        meeting_name("COUNCIL OF THE EUROPEAN UNION (General Affairs)")
        == "Council of the European Union (General Affairs)"
    )
    assert (
        meeting_name("PERMANENT REPRESENTATIVES COMMITTEE (Part 1)")
        == "Permanent Representatives Committee (Part 1)"
    )
    assert meeting_name("Working Party on Competitiveness and Growth (Public Procurement)") == (
        "Working Party on Competitiveness and Growth (Public Procurement)")  # fmt: skip
    assert meeting_name(None) is None


def test_steps_joined_to_files_after_the_build_date_one_step_from_both_schedules():
    steps = [*plenary_steps("MTG-PL-2026-11-12"), *plenary_steps("MTG-PL-2026-11-25"), *planned_steps()]
    files = {"2023/0167(COD)": "2023-0167", "2023/0169(COD)": "2023-0169", "2023/0131(COD)": "2023-0131"}
    out = scheduled_by_dossier(steps, files.get, TODAY)
    assert set(out) == set(files.values())  # steps on files outside the site's scope are left out
    vote, adoption = out["2023-0167"]
    # Parliament's agenda and Cellar give the same vote: one step, Parliament's agenda first, its report kept
    assert (vote["date"], vote["institution"], vote["label"], vote["phase"]) == (
        "2026-11-12", "EP", "Vote in EP plenary", "First reading")  # fmt: skip
    assert [s["institution"] for s in vote["sources"]] == ["EP", "EUR-Lex"]
    assert [d["label"] for d in vote["documents"]] == ["A9-0162/2024"]
    # "End of procedure" is what the adoption's own label says: not given as a reading
    assert (
        "phase" not in adoption and adoption["meeting"] == "Council of the European Union (General Affairs)"
    )
    assert [d["id"] for d in adoption["documents"]] == ["CM 4825/26"]
    # only steps dated after the build's date: the vote of 12 November is not given on that day or later
    later = scheduled_by_dossier(steps, files.get, "2026-11-12")
    assert [s["date"] for s in later["2023-0167"]] == ["2026-11-19"]
    assert scheduled_by_dossier(steps, files.get, "2026-11-25") == {}


def test_home_items_of_the_next_three_weeks():
    steps = [*plenary_steps("MTG-PL-2026-11-12"), *planned_steps()]
    files = {"2023/0167(COD)": "2023-0167", "2023/0169(COD)": "2023-0169", "2025/0391(COD)": "2025-0391"}
    sched = scheduled_by_dossier(steps, files.get, TODAY)
    summaries = {pid: {"title": f"File {pid}", "featured": pid == "2023-0169"} for pid in files.values()}
    items = home_items(sched, summaries, TODAY, days=18)
    assert [(i["date"], i["dossier_id"]) for i in items] == [
        ("2026-11-12", "2023-0167"), ("2026-11-19", "2023-0169"), ("2026-11-19", "2023-0167"),
        ("2026-11-19", "2025-0391")]  # fmt: skip
    assert {i["badge"] for i in items} == {HOME_BADGE} == {"Planned"}
    assert items[1]["subtitle"] == (
        "Approval of the EP's first reading position by the Council (adoption of the legislative act) – Council of "
        "the European Union (General Affairs)")  # fmt: skip
    assert (
        home_subtitle({"label": "Vote in EP plenary", "phase": "Second reading"})
        == "Vote in EP plenary (second reading)"
    )


# ------------------------------------------------------------------------------------------- the build
def step(**kw) -> PlannedStep:
    base = {"institution": "Council", "event_type": "APR_R1_byCONSIL",
            "label": "Approval of the EP's first reading position by the Council (adoption of the legislative act)",
            "source": SourceRef(institution="EUR-Lex", url="https://example.invalid/ev", retrieved_at=RETRIEVED)}  # fmt: skip
    return PlannedStep(**{**base, **kw})


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """The build fixture (TODAY 2026-10-22) with planned steps on two of its files, one outside the site and one on the
    build's own date."""
    from pipeline.models.entities import SourceStatus
    from pipeline.snapshot import _dump

    base = tmp_path_factory.mktemp("agenda-build")
    shutil.copytree(BUILD_FIX / "snapshot", base / "snapshot")
    planned = [
        step(id="cellar:a", reference="2099/0001(COD)", date="2026-11-05", meeting="COUNCIL OF THE EUROPEAN UNION (General Affairs)",
             documents=[DocRef(id="CM 4825/26", kind="agenda", url="https://example.invalid/cm")]),
        step(id="cellar:b", reference="2099/0002(CNS)", date="2026-10-29", institution="EP", event_type="VOTE_byEP",
             label="Vote in EP plenary", phase_code="RDG1", phase="First reading"),
        step(id="cellar:c", reference="2099/0002(CNS)", date="2026-10-22"),  # the build's date: may have taken place
        step(id="cellar:d", reference="2098/0001(COD)", date="2026-10-30"),  # no such file on the site
        # joined by the full reference, never the number alone: a Parliament report on 2099/0001 has a procedure of its
        # own, and 2099/0002 is a consultation procedure
        step(id="cellar:e", reference="2099/0001R(COD)", date="2026-10-30"),
        step(id="cellar:f", reference="2099/0002(COD)", date="2026-10-31"),
    ]  # fmt: skip
    plenary = [step(id="ep:x", reference="2099/0002(CNS)", date="2026-10-29", institution="EP", event_type="VOTE_byEP",
                    label="Vote in EP plenary", item="Test gadgets",
                    source=SourceRef(institution="EP", url="https://example.invalid/agenda", retrieved_at=RETRIEVED))]  # fmt: skip
    (base / "snapshot" / "agenda").mkdir()
    for name, recs in (("planned", planned), ("plenary", plenary)):
        text = "[\n" + ",\n".join(_dump(r) for r in recs) + "\n]\n"
        (base / "snapshot" / "agenda" / f"{name}.json").write_text(text, encoding="utf-8")
    manifest = json.loads((base / "snapshot" / "_manifest.json").read_text(encoding="utf-8"))
    manifest["agenda"] = SourceStatus(source="agenda", status="ok", fetched_at="2099-01-01T00:00:00Z",
                                      attempted_at="2099-01-01T00:00:00Z", records={"planned": 6, "plenary": 1}).model_dump()  # fmt: skip
    (base / "snapshot" / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    out = base / "public"
    assert build(out=out, snapshot=base / "snapshot", curated=BUILD_FIX / "curated", state=base / "state",
                 today="2026-10-22", strict=True) == 0  # fmt: skip
    return out


def load(out: Path, rel: str):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def test_the_build_gives_each_file_its_scheduled_steps(built):
    d1, d2 = load(built, "dossiers/2099-0001.json"), load(built, "dossiers/2099-0002.json")
    assert d1["scheduled"] == [{
        "date": "2026-11-05", "institution": "Council",
        "label": "Approval of the EP's first reading position by the Council (adoption of the legislative act)",
        "meeting": "Council of the European Union (General Affairs)",
        "documents": [{"id": "CM 4825/26", "label": None, "kind": "agenda", "date": None, "url": "https://example.invalid/cm"}],
        "sources": [{"institution": "EUR-Lex", "url": "https://example.invalid/ev", "label": None, "identifier": None,
                     "retrieved_at": RETRIEVED, "published": None}],
    }]  # fmt: skip
    # one vote from both schedules (Parliament's agenda first); nothing dated on the build's own date
    (vote,) = d2["scheduled"]
    assert (vote["date"], vote["phase"], [s["url"] for s in vote["sources"]]) == (
        "2026-10-29", "First reading", ["https://example.invalid/agenda", "https://example.invalid/ev"])  # fmt: skip
    assert "scheduled" not in load(built, "dossiers/2099-0003.json")


def test_the_home_page_lists_them_and_about_names_the_source(built):
    home = {x["id"]: x for x in load(built, "home.json")["lists"]}
    assert [(i["date"], i["dossier_id"], i["badge"]) for i in home["scheduled"]["items"]] == [
        ("2026-10-29", "2099-0002", "Planned"), ("2026-11-05", "2099-0001", "Planned")]  # fmt: skip
    assert "Planned dates can change" in home["scheduled"]["description"]
    assert len(home["scheduled"]["description"].split()) <= 40
    meta = load(built, "meta.json")
    agenda = next(s for s in meta["sources"] if s["id"] == "agenda")
    assert agenda["status"] == "ok" and agenda["stale_after_days"] == 9 and agenda["core"] is False
    assert "2 legislative files covered here have a step scheduled" in agenda["summary"]
    assert any(n.startswith("Scheduled steps: the dates") for n in meta["coverage_notes"])


def test_the_built_steps_match_the_public_data_contract(built):
    from pipeline.contract import Contract, check_public

    assert check_public(built, Contract.load()).lines() == []


def test_without_the_source_nothing_is_scheduled(tmp_path):
    """The frozen test data has no agenda files: the build works, no file has a scheduled step and the home page's
    list is empty."""
    shutil.copytree(BUILD_FIX / "snapshot", tmp_path / "snapshot")
    out = tmp_path / "public"
    assert build(out=out, snapshot=tmp_path / "snapshot", curated=BUILD_FIX / "curated", state=tmp_path / "state",
                 today="2026-10-22", strict=True) == 0  # fmt: skip
    assert not any(
        "scheduled" in load(out, f"dossiers/{d['id']}.json") for d in load(out, "dossiers/index.json")
    )
    assert next(x for x in load(out, "home.json")["lists"] if x["id"] == "scheduled")["items"] == []
    agenda = next(s for s in load(out, "meta.json")["sources"] if s["id"] == "agenda")
    assert agenda["status"] == "unavailable" and agenda["summary"].startswith(
        "Not retrieved for this release"
    )
    assert any(n.startswith("Scheduled steps: the Council's and Parliament's planned dates were not retrieved")
               for n in load(out, "meta.json")["coverage_notes"])  # fmt: skip


def test_the_source_is_registered_everywhere_sources_are():
    from pipeline.__main__ import SOURCES as FETCHED
    from pipeline.build import SOURCES
    from pipeline.freshness import CORE_SOURCES, STALE_AFTER_DAYS
    from pipeline.validate import FILES, MIN_RECORDS

    assert FETCHED["agenda"] == "pipeline.sources.agenda" and "agenda" in SOURCES
    assert STALE_AFTER_DAYS["agenda"] == 9 and "agenda" not in CORE_SOURCES
    assert {(s, n, m) for s, n, m, _ in FILES if s == "agenda"} == {
        ("agenda", "planned", "PlannedStep"), ("agenda", "plenary", "PlannedStep")}  # fmt: skip
    # no floor: a schedule can be empty (a recess), and absent until first retrieved
    assert not any(s == "agenda" for s, _ in MIN_RECORDS)


def test_validate_checks_the_agenda_files(tmp_path):
    from pipeline.validate import check

    shutil.copytree(BUILD_FIX / "snapshot", tmp_path / "snapshot")
    rep = check(tmp_path / "snapshot", today="2026-10-22")
    assert not [e for e in rep.errors if "agenda" in e]  # absent: not yet retrieved
    (tmp_path / "snapshot" / "agenda").mkdir()
    bad = step(id="cellar:a", reference="2099/0001(COD)", date="2026-11-05").model_dump(mode="json")
    (tmp_path / "snapshot" / "agenda" / "planned.json").write_text(
        json.dumps([bad, {**bad, "date": "5 Nov"}]), encoding="utf-8"
    )
    rep = check(tmp_path / "snapshot", today="2026-10-22")
    assert rep.errors_by_source["agenda"]  # a malformed date and a duplicate id
