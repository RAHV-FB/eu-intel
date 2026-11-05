"""The implementation tracker (pipeline/analysis/tracker.py): transposition.json and one Atom feed per Member State
(feeds/countries/<CC>.xml), built from the test fixture (tests/fixtures/build) with notification dates, a second
infringement decision and the Scoreboard's figures added; and the window the tracker applies."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pipeline.analysis import feeds, tracker
from pipeline.build import build
from pipeline.models.countries import MEMBER_STATES

FIX = Path(__file__).parent / "fixtures" / "build"
TODAY = "2026-10-22"
ATOM = "{http://www.w3.org/2005/Atom}"
EARLY, LATE = "32099L0003", "32099L0009"  # deadlines 21 February 2025 and 30 March 2027
SCOREBOARD = Path(__file__).parent / "fixtures" / "implementation" / "scoreboard_transposition_en.html"


def _rec(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, records: list[dict]) -> None:
    path.write_text("[\n" + ",\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n]\n", encoding="utf-8")


def _snapshot(base: Path, extra_es: int = 0) -> Path:
    """The fixture snapshot with what the tracker reads that the fixture lacks: notification dates (two of Spain's
    measures on one day, Germany's on another; `extra_es` more Spanish measures on as many earlier days), the Scoreboard's
    figures, and a second, closed case (Germany)."""
    snap = base / "snapshot"
    shutil.copytree(FIX / "snapshot", snap)
    imp = snap / "implementation"
    measures = _rec(imp / "measures.json")
    for m in measures:
        m["notified"] = {"ES": "2025-03-04", "DE": "2025-05-06"}[m["country"]]
    es = next(m for m in measures if m["country"] == "ES")
    measures.append({**es, "id": "M1b", "title": "TEST Real Decreto de prueba"})
    for i in range(extra_es):
        day = f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}"
        measures.append({**es, "id": f"MX{i}", "title": f"TEST Orden {i}", "notified": day})
    _write(imp / "measures.json", measures)
    cov = _rec(imp / "coverage.json")
    for c in cov:
        c["measures"] = sum(1 for m in measures if m["directive_celex"] == c["celex"])
    _write(imp / "coverage.json", cov)
    cases = _rec(imp / "infringements.json")
    fr = cases[0]
    cases.append({**fr, "id": "INFR(2099)0002", "country": "DE", "latest_stage": "Closing of the case",
                  "latest_decision_date": "2025-09-10", "status": "closed", "title": "TEST closed & <done>",
                  "source": {**fr["source"], "url": "https://example.invalid/INFR(2099)0002"}})  # fmt: skip
    _write(imp / "infringements.json", cases)
    from pipeline.sources.implementation import parse_scoreboard_transposition

    recs = parse_scoreboard_transposition(SCOREBOARD.read_text(encoding="utf-8"), "2099-01-01T00:00:00Z")
    _write(imp / "indicators.json", [r.model_dump() for r in recs])
    man = json.loads((snap / "_manifest.json").read_text(encoding="utf-8"))
    man["implementation"]["records"].update(measures=len(measures), infringements=len(cases), indicators=len(recs))
    (snap / "_manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return snap


def _build(base: Path, snap: Path, name: str = "public") -> Path:
    out = base / name
    assert build(out=out, snapshot=snap, curated=FIX / "curated", state=base / "state", today=TODAY) == 0
    return out


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("tracker")
    return _build(base, _snapshot(base))


def _feed(out: Path, code: str) -> ET.Element:
    return ET.parse(out / "feeds" / "countries" / f"{code}.xml").getroot()  # well-formed, or ParseError


def _entries(out: Path, code: str) -> list[ET.Element]:
    return _feed(out, code).findall(f"{ATOM}entry")


def _by_kind(out: Path, code: str, kind: str) -> list[ET.Element]:
    return [e for e in _entries(out, code) if e.find(f"{ATOM}category").get("term") == kind]


# ------------------------------------------------------------------------------------------ window
def test_the_window_is_three_years_back_and_twelve_months_ahead_on_the_day():
    assert tracker.window("2026-11-05") == ("2023-11-05", "2027-11-05")
    assert tracker.window("2026-11-05", margin_days=31) == ("2023-10-05", "2027-12-06")
    # a day the other year has not: its month's last day
    assert tracker.window("2028-02-29") == ("2025-02-28", "2029-02-28")
    assert tracker.window("2026-08-31") == ("2023-08-31", "2027-08-31")


# ----------------------------------------------------------------------------- transposition.json
def test_tracker_lists_the_directives_in_the_window_with_each_member_states_status(out: Path):
    t = json.loads((out / "transposition.json").read_text(encoding="utf-8"))
    assert t["built_on"] == TODAY and t["window"] == {"years_back": 3, "months_ahead": 12}
    assert [d["celex"] for d in t["directives"]] == [EARLY, LATE]  # by deadline
    early = t["directives"][0]
    assert early["deadline"] == "2025-02-21" and early["dossier_id"] and early["act"] == "Directive (EU) 2099/3"
    assert [c["country"] for c in early["countries"]] == sorted(MEMBER_STATES)
    row = {c["country"]: c for c in early["countries"]}
    assert row["ES"] == {"country": "ES", "status": "measures_notified", "measures": 2,
                         "latest_notification": "2025-03-04"}  # fmt: skip
    assert row["IT"] == {"country": "IT", "status": "none_found", "measures": 0}
    # open cases only, at their latest decision, with the register's link
    assert row["FR"]["cases"] == [{"id": "INFR(2099)0001", "stage": "Letter of formal notice", "date": "2025-04-01",
                                   "non_communication": True, "url": "https://example.invalid/INFR(2099)0001"}]  # fmt: skip
    assert "cases" not in row["DE"]  # its case is closed
    # the later directive: its deadline is ahead; Denmark did not take part in adopting it (the fixture's Council vote)
    late = {c["country"]: c["status"] for c in t["directives"][1]["countries"]}
    assert late.pop("DK") == "not_participating" and set(late.values()) == {"deadline_not_reached"}


def test_tracker_statuses_are_those_of_the_directives_own_page(out: Path):
    t = json.loads((out / "transposition.json").read_text(encoding="utf-8"))
    for d in t["directives"]:
        page = json.loads((out / "dossiers" / f"{d['dossier_id']}.json").read_text(encoding="utf-8"))
        table = next(x for x in [page["implementation"], *page.get("implementation_more", [])] if x["celex"] == d["celex"])
        assert [(c["country"], c["status"], c["measures"]) for c in d["countries"]] == [
            (c["country"], c["status"], c["measures"]) for c in table["countries"]
        ]


# ----------------------------------------------------------------------------------- country feeds
def test_every_member_state_has_a_well_formed_feed(out: Path):
    files = sorted((out / "feeds" / "countries").glob("*.xml"))
    assert [f.stem for f in files] == sorted(MEMBER_STATES)
    for f in files:
        root = ET.parse(f).getroot()
        code = f.stem
        assert root.findtext(f"{ATOM}id") == f"{feeds.TAG_BASE}/feeds/countries/{code}.xml"
        assert root.findtext(f"{ATOM}title") == f"{MEMBER_STATES[code]}: applying EU directives – {feeds.TITLE}"
        assert root.find(f"{ATOM}link[@rel='self']").get("href").endswith(f"data/feeds/countries/{code}.xml")
        assert root.find(f"{ATOM}link[@rel='alternate']").get("href").endswith(f"countries/{code}/")
        assert root.find(f"{ATOM}author/{ATOM}name") is not None and root.findtext(f"{ATOM}updated")
        ids = [e.findtext(f"{ATOM}id") for e in root.findall(f"{ATOM}entry")]
        assert len(ids) == len(set(ids))
        for e in root.findall(f"{ATOM}entry"):
            for tag in ("id", "title", "updated", "summary"):
                assert (e.findtext(f"{ATOM}{tag}") or "").strip(), (code, tag)


def test_measures_are_one_entry_per_directive_per_notification_date(out: Path):
    es = _by_kind(out, "ES", "measures")
    assert len(es) == 1  # two measures notified on one day
    e = es[0]
    assert e.findtext(f"{ATOM}id") == f"{feeds.TAG_BASE}/countries/ES/measures/{EARLY}/2025-03-04"
    assert e.findtext(f"{ATOM}updated") == "2025-03-04T00:00:00Z"  # the notification's date, not the build's
    assert e.findtext(f"{ATOM}title").startswith("Spain notified 2 national measures for Directive (EU) 2099/3")
    summary = e.findtext(f"{ATOM}summary")
    assert "“TEST Ley de prueba”; “TEST Real Decreto de prueba”" in summary
    assert "does not show that transposition is complete or correct" in summary
    link = e.find(f"{ATOM}link[@rel='alternate']").get("href")
    assert link.endswith("/?country=ES#national") and "/legislation/" in link
    assert "1 national measure for" in _by_kind(out, "DE", "measures")[0].findtext(f"{ATOM}title")


def test_infringement_decisions_carry_the_stage_verbatim_the_date_and_the_register_link(out: Path):
    (fr,) = _by_kind(out, "FR", "infringement")
    assert fr.findtext(f"{ATOM}id") == (f"{feeds.TAG_BASE}/countries/FR/infringements/INFR%282099%290001/"
                                        "letter-of-formal-notice/2025-04-01")  # fmt: skip
    assert fr.findtext(f"{ATOM}title") == "Letter of formal notice: TEST failure to notify (INFR(2099)0001)"
    assert fr.findtext(f"{ATOM}updated") == "2025-04-01T00:00:00Z"
    assert fr.find(f"{ATOM}link[@rel='alternate']").get("href") == "https://example.invalid/INFR(2099)0001"
    assert fr.find(f"{ATOM}link[@rel='related']").get("href").endswith("/?country=FR#national")
    summary = fr.findtext(f"{ATOM}summary")
    assert "“Letter of formal notice”" in summary and "not a ruling of the Court of Justice" in summary
    assert "failure to notify transposition measures" in summary and "lists the case as open" in summary
    # text the feed escapes
    (de,) = _by_kind(out, "DE", "infringement")
    assert de.findtext(f"{ATOM}title") == "Closing of the case: TEST closed & <done> (INFR(2099)0002)"
    assert "lists the case as closed" in de.findtext(f"{ATOM}summary")


def test_a_new_decision_on_a_case_is_a_new_entry(tmp_path: Path):
    snap = _snapshot(tmp_path)
    before = {e.findtext(f"{ATOM}id") for e in _by_kind(_build(tmp_path, snap, "a"), "FR", "infringement")}
    cases = _rec(snap / "implementation" / "infringements.json")
    cases[0].update(latest_stage="Reasoned opinion Art. 258 TFEU", latest_decision_date="2025-10-02")
    _write(snap / "implementation" / "infringements.json", cases)
    after = {e.findtext(f"{ATOM}id") for e in _by_kind(_build(tmp_path, snap, "b"), "FR", "infringement")}
    assert len(before) == len(after) == 1 and before != after
    assert after.pop().endswith("/INFR%282099%290001/reasoned-opinion-art-258-tfeu/2025-10-02")


def test_deadlines_reached_only_for_directives_that_bind_the_country(out: Path, tmp_path: Path):
    (it,) = _by_kind(out, "IT", "deadline")  # the 2027 deadline is not reached
    assert it.findtext(f"{ATOM}id") == f"{feeds.TAG_BASE}/countries/IT/deadlines/{EARLY}/2025-02-21"
    assert it.findtext(f"{ATOM}updated") == "2025-02-21T00:00:00Z"
    assert it.findtext(f"{ATOM}title").startswith("Transposition deadline: Directive (EU) 2099/3")
    assert it.find(f"{ATOM}link[@rel='alternate']").get("href").endswith("/?country=IT#national")
    # the later directive's deadline moved to 30 March 2026, passed: Italy's feed has it; Denmark's does not, as the
    # fixture's Council vote records Denmark as not taking part in adopting it (not bound)
    snap = _snapshot(tmp_path)
    acts = _rec(snap / "eurlex" / "acts.json")
    next(a for a in acts if a["celex"] == LATE)["transposition_deadlines"] = ["2026-03-30"]
    _write(snap / "eurlex" / "acts.json", acts)
    moved = _build(tmp_path, snap)
    assert [e.findtext(f"{ATOM}id").rsplit("/", 2)[1] for e in _by_kind(moved, "IT", "deadline")] == [LATE, EARLY]
    assert [e.findtext(f"{ATOM}id").rsplit("/", 2)[1] for e in _by_kind(moved, "DK", "deadline")] == [EARLY]


def test_ids_do_not_depend_on_the_site_address(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    snap = _snapshot(tmp_path)
    monkeypatch.delenv("SITE_URL", raising=False)
    a = _build(tmp_path, snap, "a")
    monkeypatch.setenv("SITE_URL", "https://eu-intel.example.org/")
    b = _build(tmp_path, snap, "b")
    ids = lambda o: [e.findtext(f"{ATOM}id") for e in _entries(o, "FR")]  # noqa: E731
    assert ids(a) and ids(a) == ids(b)
    assert _feed(b, "FR").find(f"{ATOM}link[@rel='alternate']").get("href") == "https://eu-intel.example.org/countries/FR/"


def test_a_feed_keeps_the_newest_entries(tmp_path: Path):
    out = _build(tmp_path, _snapshot(tmp_path, extra_es=150))
    es = _entries(out, "ES")
    assert len(es) == feeds.FEED_LIMIT
    dates = [e.findtext(f"{ATOM}updated") for e in es]
    assert dates == sorted(dates, reverse=True)
    # 152 entries: the notification of 4 March 2025, the deadline of 21 February 2025 and 150 notifications in 2024
    assert dates[:2] == ["2025-03-04T00:00:00Z", "2025-02-21T00:00:00Z"]
    assert "2024-01-01T00:00:00Z" not in dates and "2024-06-10T00:00:00Z" in dates
    assert _feed(out, "ES").findtext(f"{ATOM}updated") == dates[0]  # the newest entry's date, not the build's


# ------------------------------------------------------------------------- the Scoreboard's figures
def test_each_country_page_has_its_own_scoreboard_figure(out: Path):
    es = json.loads((out / "countries" / "ES.json").read_text(encoding="utf-8"))
    (ind,) = es["indicators"]
    assert (ind["indicator"], ind["value"], ind["unit"]) == ("sm_directives_not_notified", 27, "directives")
    assert ind["period"].startswith("Notifications made by 5 December 2025")
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    note = next(n for n in meta["coverage_notes"] if n.startswith("Single Market Scoreboard:"))
    assert "on that country's page only" in note and "not a ranking" in note
    impl = next(s for s in meta["sources"] if s["id"] == "implementation")
    assert impl["name"].endswith(", infringements and indicators")
