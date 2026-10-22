"""Parsing tests for pipeline.sources.legislative_train on real Legislative Train pages.

Fixtures in tests/fixtures/train/ are unmodified pages fetched from
https://www.europarl.europa.eu/legislative-train/ on 2026-10-22, stored gzip-compressed.
`manifest.json` records, for each fixture, its URL and the values visible on the page.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from pipeline.models.entities import TrainFile
from pipeline.sources import legislative_train as lt

FIX = Path(__file__).resolve().parent / "fixtures" / "train"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))


def page(name: str) -> str:
    return gzip.decompress((FIX / name).read_bytes()).decode("utf-8")


FILE_CASES = [(name, exp) for name, exp in MANIFEST["files"].items()]


@pytest.mark.parametrize(("name", "expected"), FILE_CASES, ids=[n for n, _ in FILE_CASES])
def test_parse_file_page(name, expected):
    p = lt.parse_file_page(page(name))
    assert p.status == expected["status"]
    assert p.title == expected["title"]
    assert p.procedure_refs == expected["procedure_refs"]
    assert p.theme == expected["theme"]
    assert p.last_updated == expected["last_updated"]
    assert p.blocking_institution == expected["blocking_institution"]


def test_blocking_institution_parsed_verbatim():
    # Single badge, and several badges joined with ", " in page order.
    assert lt.parse_file_page(page("file_blocked.html.gz")).blocking_institution == "COUNCIL"
    two = lt.parse_file_page(page("file_blocked_two_institutions.html.gz"))
    assert two.status == "Blocked"
    assert two.blocking_institution == "COUNCIL, PARLIAMENT"
    # Only "Blocked" files name a blocking institution.
    for name in MANIFEST["files"]:
        p = lt.parse_file_page(page(name))
        if p.status != "Blocked":
            assert p.blocking_institution is None, name
    rec = lt.build_record(MANIFEST["files"]["file_blocked.html.gz"]["url"], "t", two, "2026-10-22T00:00:00Z")
    assert TrainFile.model_validate(rec.model_dump()).blocking_institution == "COUNCIL, PARLIAMENT"


def test_fixture_statuses_cover_vocabulary():
    # Invariant: every parsed status belongs to the observed vocabulary, and the fixtures
    # exercise every value of it.
    seen = {lt.parse_file_page(page(name)).status for name in MANIFEST["files"]}
    assert seen <= lt.STATUS_VOCABULARY
    assert seen == lt.STATUS_VOCABULARY


def test_schedule_lists_themes_with_counts():
    exp = MANIFEST["schedule"]
    rows = lt.parse_schedule(page(exp["fixture"]))
    assert [r.slug for r in rows] == exp["themes"]
    for r in rows:
        assert set(r.counts) == set(lt.SCHEDULE_COLUMNS)
    assert {r.slug: sum(r.counts.values()) for r in rows} == exp["file_counts"]


def test_theme_page_lists_all_files():
    exp = MANIFEST["theme"]
    files = lt.parse_theme(page(exp["fixture"]))
    # the theme page lists exactly as many files as the schedule counts for that theme
    assert len(files) == exp["n_files"] == MANIFEST["schedule"]["file_counts"][exp["slug"]]
    assert len({u for u, _ in files}) == len(files)
    for url, title in files:
        assert url.startswith(lt.BASE + exp["slug"] + "/file-")
        assert title
    assert files[0] == tuple(exp["first"])


def test_build_record_round_trip():
    name, expected = FILE_CASES[0]
    url = expected["url"]
    rec = lt.build_record(url, "listed title", lt.parse_file_page(page(name)), "2026-10-22T00:00:00Z")
    rec = TrainFile.model_validate(rec.model_dump())
    assert rec.status == expected["status"]
    assert rec.source.institution == "LegislativeTrain"
    assert rec.source.identifier == lt.file_slug(url)
    assert rec.source.published == expected["last_updated"]


def test_file_slug_and_user_agent():
    assert lt.file_slug(lt.BASE + "theme-x/file-digital-omnibus-on-ai") == "digital-omnibus-on-ai"
    ua = lt.train_user_agent("eu-intel-pipeline/0.1 (independent; +https://github.com/rahv-fb/eu-intel)")
    assert ua == "Mozilla/5.0 (compatible; eu-intel-pipeline/0.1; +https://github.com/rahv-fb/eu-intel)"


def test_snapshot_statuses_in_vocabulary():
    # Invariant on the committed snapshot (skipped until `python -m pipeline fetch train` has run).
    path = Path(__file__).resolve().parent.parent / "data" / "snapshot" / "train" / "files.json"
    if not path.exists():
        pytest.skip("no train snapshot")
    recs = [TrainFile.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    assert recs
    assert {r.status for r in recs} <= lt.STATUS_VOCABULARY
    assert len({r.url for r in recs}) == len(recs)
    for r in recs:
        for ref in r.procedure_refs:
            assert lt._PROC_RE.fullmatch(ref), ref
        if r.blocking_institution is not None:
            assert r.status == "Blocked", r.url
