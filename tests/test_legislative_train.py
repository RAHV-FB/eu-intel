"""Parsing tests for pipeline.sources.legislative_train on real Legislative Train pages.

Fixtures in tests/fixtures/train/ are unmodified pages fetched from
https://www.europarl.europa.eu/legislative-train/ on 2026-10-22, stored gzip-compressed.
`manifest.json` records, for each fixture, its URL and the values visible on the page.
"""

from __future__ import annotations

import gzip
import json
from datetime import date
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


def test_theme_hints_on_real_theme_page():
    exp = MANIFEST["theme"]
    html = page(exp["fixture"])
    hints = lt.parse_theme_hints(html)
    assert set(hints) == {u for u, _ in lt.parse_theme(html)}
    assert {h.status for h in hints.values()} <= lt.STATUS_VOCABULARY
    assert not any(h.recently_updated for h in hints.values())


# ---------------------------------------------------------------- fetch: incremental, failure-safe
TODAY = date(2026, 10, 23)
RECENT_ICON = '<i class="erpl_icon icon-update-white ml-1"><span class="sr-only">Recently updated carriage</span></i>'


def fixture_files() -> dict[str, dict]:
    return MANIFEST["files"]


def theme_of(url: str) -> str:
    return url[len(lt.BASE) :].split("/file-")[0]


def make_site(statuses: dict[str, str] | None = None, recent: tuple[str, ...] = ()) -> dict[str, bytes]:
    """A one-term Legislative Train: synthetic schedule and theme pages listing the real file-page fixtures."""
    statuses = statuses or {}
    by_theme: dict[str, list[dict]] = {}
    for exp in fixture_files().values():
        by_theme.setdefault(theme_of(exp["url"]), []).append(exp)
    rows = "".join(
        f"<tr><td><a href='{t}' title='{t}'>{t}</a></td>"
        + "".join(f"<td class='tableValue'>{n}</td>" for n in [len(items), 0, 0, 0, 0, 0, 0])
        + "</tr>"
        for t, items in sorted(by_theme.items())
    )
    site = {f"{lt.BASE}schedule?pov=EC_PRIORITIES&commission=T1&reload=false": f"<table id='carriageTable'>{rows}</table>"}
    for t, items in by_theme.items():
        lis = "".join(
            f'<li class="row mb-2 timetable"><h3 class="erpl_title-h3">'
            f'<a href="/legislative-train/{t}/file-{lt.file_slug(e["url"])}" title="{e["title"]}">{e["title"]}</a>'
            f"{RECENT_ICON if e['url'] in recent else ''}</h3>"
            f'<p class="notification">Status: {statuses.get(e["url"], e["status"])}</p></li>'
            for e in items
        )
        site[lt.BASE + t] = f"<html><body><ul>{lis}</ul></body></html>"
    for name, exp in fixture_files().items():
        site[exp["url"]] = page(name)
    return {k: v.encode() for k, v in site.items()}


class FakeTrain:
    def __init__(self, site: dict[str, bytes], fail: dict[str, Exception | bytes] | None = None):
        self.site, self.fail = site, fail or {}
        self.calls: list[str] = []

    def get(self, url: str, headers=None, **kw) -> bytes:
        self.calls.append(url)
        if url in self.fail:
            if isinstance(self.fail[url], Exception):
                raise self.fail[url]
            return self.fail[url]
        if url not in self.site:
            raise lt.HttpError(url, 404, "not found")
        return self.site[url]

    def file_pages(self) -> list[str]:
        return [u for u in self.calls if "/file-" in u]


@pytest.fixture
def train_dir(tmp_path, monkeypatch):
    from pipeline import snapshot

    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.setattr(lt, "COMMISSION_TERMS", ("T1",))
    monkeypatch.setattr(lt, "_today", lambda: TODAY)
    monkeypatch.setattr(lt, "recheck_slot", lambda slug: -1)  # no periodic re-check unless a test says so
    for var in ("EU_INTEL_FULL_REFRESH", "EU_INTEL_FETCH_BUDGET_S", "EU_INTEL_FETCH_DEADLINE"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def stored(root: Path) -> dict[str, str]:
    lines = (root / "train" / "files.json").read_text().splitlines()
    return {json.loads(x.rstrip(","))["url"]: x for x in lines if x.startswith("{")}


def train_state(root: Path) -> dict:
    return json.loads((root / "train" / "_state.json").read_text())


QUIET = {e["url"] for e in MANIFEST["files"].values() if e["last_updated"] < "2026-07-01"}
ALL = {e["url"] for e in MANIFEST["files"].values()}


def test_first_run_reads_every_file(train_dir):
    http = FakeTrain(make_site())
    st = lt.fetch(http)
    assert st.status == "ok", st.note
    assert set(http.file_pages()) == ALL and set(stored(train_dir)) == ALL
    assert st.records == {"files": len(ALL), "fetched_this_run": len(ALL), "reused": 0, "pending": 0}


def test_unchanged_quiet_files_are_reused(train_dir):
    lt.fetch(FakeTrain(make_site()))
    before = stored(train_dir)
    http = FakeTrain(make_site())
    st = lt.fetch(http)
    assert st.status == "ok", st.note
    assert QUIET and set(http.file_pages()) == ALL - QUIET  # files updated in the monthly batch are re-read
    assert st.records["reused"] == len(QUIET)
    assert stored(train_dir) == before


def test_theme_page_signals_force_a_re_read(train_dir):
    lt.fetch(FakeTrain(make_site()))
    changed, flagged = sorted(QUIET)[:2]
    http = FakeTrain(make_site(statuses={changed: "Tabled"}, recent=(flagged,)))
    lt.fetch(http)
    assert {changed, flagged} <= set(http.file_pages())


def test_periodic_re_check_and_full_refresh(train_dir, monkeypatch):
    lt.fetch(FakeTrain(make_site()))
    monkeypatch.setattr(lt, "recheck_slot", lambda slug: lt.week_slot(TODAY))
    http = FakeTrain(make_site())
    lt.fetch(http)
    assert set(http.file_pages()) == ALL
    monkeypatch.setattr(lt, "recheck_slot", lambda slug: -1)
    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")
    http = FakeTrain(make_site())
    lt.fetch(http)
    assert set(http.file_pages()) == ALL


def test_recheck_rotation_covers_every_file():
    slots = {lt.recheck_slot(f"file-{i}") for i in range(200)}
    assert slots == set(range(lt.RECHECK_WEEKS))
    weeks = {lt.week_slot(date.fromordinal(TODAY.toordinal() + 7 * k)) for k in range(lt.RECHECK_WEEKS)}
    assert weeks == set(range(lt.RECHECK_WEEKS))


@pytest.mark.parametrize(
    "failure",
    [lt.HttpError("u", 403, "Request blocked"), b"", b"<html><body>Please wait</body></html>"],
    ids=["http-error", "empty-200", "page-without-status"],
)
def test_failed_file_page_keeps_the_stored_record(train_dir, failure):
    lt.fetch(FakeTrain(make_site()))
    before = stored(train_dir)
    victim = sorted(ALL - QUIET)[0]
    st = lt.fetch(FakeTrain(make_site(), fail={victim: failure}))
    assert st.status == "partial" and "previous records kept" in st.note
    assert stored(train_dir) == before  # nothing dropped, nothing changed
    assert train_state(train_dir)["pending"] == [victim]
    http = FakeTrain(make_site())
    st = lt.fetch(http)
    assert http.file_pages()[0] == victim  # the pending file is read first
    assert st.status == "ok" and train_state(train_dir)["pending"] == []


def test_waf_block_partway_keeps_every_file(train_dir):
    lt.fetch(FakeTrain(make_site()))
    before = stored(train_dir)
    blocked = {u: lt.HttpError(u, 202, "challenge") for u in sorted(ALL)[3:]}
    st = lt.fetch(FakeTrain(make_site(), fail=blocked))
    assert st.status == "partial"
    assert stored(train_dir) == before


def test_failed_theme_page_keeps_its_files(train_dir):
    lt.fetch(FakeTrain(make_site()))
    before = stored(train_dir)
    theme = theme_of(sorted(ALL)[0])
    st = lt.fetch(FakeTrain(make_site(), fail={lt.BASE + theme: lt.HttpError(lt.BASE + theme, 500, "down")}))
    assert st.status == "partial" and "stored files kept" in st.note
    assert stored(train_dir) == before


def test_empty_theme_page_keeps_its_files(train_dir):
    lt.fetch(FakeTrain(make_site()))
    before = stored(train_dir)
    theme = theme_of(sorted(ALL)[0])
    st = lt.fetch(FakeTrain(make_site(), fail={lt.BASE + theme: b"<html><body></body></html>"}))
    assert st.status == "partial" and "theme page lists no files" in st.note
    assert stored(train_dir) == before


def test_failed_schedule_uses_the_stored_theme_list(train_dir):
    lt.fetch(FakeTrain(make_site()))
    assert train_state(train_dir)["themes"]["T1"]
    url = f"{lt.BASE}schedule?pov=EC_PRIORITIES&commission=T1&reload=false"
    http = FakeTrain(make_site(), fail={url: lt.HttpError(url, 500, "down")})
    st = lt.fetch(http)
    assert st.status == "partial" and "used the" in st.note
    assert set(stored(train_dir)) == ALL


def test_failed_schedule_without_stored_themes_fails_cleanly(train_dir):
    url = f"{lt.BASE}schedule?pov=EC_PRIORITIES&commission=T1&reload=false"
    with pytest.raises(RuntimeError, match="unavailable"):
        lt.fetch(FakeTrain(make_site(), fail={url: lt.HttpError(url, 500, "down")}))


def test_shrink_guard_refuses_to_write(train_dir):
    lt.fetch(FakeTrain(make_site()))
    before = stored(train_dir)
    site = make_site()
    theme = theme_of(sorted(ALL)[0])
    # the theme page answers, but lists only one of its files (a truncated page)
    keep = next(u for u in sorted(ALL) if theme_of(u) == theme)
    title = MANIFEST["files"][next(n for n, e in MANIFEST["files"].items() if e["url"] == keep)]["title"]
    site[lt.BASE + theme] = (
        f'<html><body><a href="/legislative-train/{theme}/file-{lt.file_slug(keep)}" title="{title}">x</a>'
        "</body></html>"
    ).encode()
    st = lt.fetch(FakeTrain(site))
    assert len(ALL) - 1 < (1 - lt.MAX_SHRINK) * len(ALL)  # losing one of the 9 files is over the limit
    assert st.status == "failed" and "snapshot kept" in st.note
    assert stored(train_dir) == before


def test_deadline_stops_reading_and_resumes(train_dir, monkeypatch):
    import time

    lt.fetch(FakeTrain(make_site()))
    before = stored(train_dir)
    monkeypatch.setenv("EU_INTEL_FETCH_DEADLINE", str(time.time() - 1))
    http = FakeTrain(make_site())
    st = lt.fetch(http)
    assert http.file_pages() == []
    assert st.status == "partial" and stored(train_dir) == before
    monkeypatch.delenv("EU_INTEL_FETCH_DEADLINE")
    # the budget runs out after two file pages: the rest is carried forward and pending
    real_deadline, real_past = lt.fetch_deadline, lt.past
    http = FakeTrain(make_site())
    monkeypatch.setattr(lt, "fetch_deadline", lambda: 0.0)
    monkeypatch.setattr(lt, "past", lambda d: d is not None and len(http.file_pages()) >= 2)
    st = lt.fetch(http)
    pending = train_state(train_dir)["pending"]
    assert st.status == "partial" and "time budget reached" in st.note
    assert len(http.file_pages()) == 2 and set(pending) == ALL - QUIET - set(http.file_pages())
    assert stored(train_dir) == before
    monkeypatch.setattr(lt, "fetch_deadline", real_deadline)
    monkeypatch.setattr(lt, "past", real_past)
    http = FakeTrain(make_site())
    st = lt.fetch(http)
    assert set(http.file_pages()[: len(pending)]) == set(pending)  # pending files first
    assert st.status == "ok" and train_state(train_dir)["pending"] == []


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
