"""Tests for pipeline.sources.ep_people.

Offline tests use real, trimmed EP Open Data API responses in tests/fixtures/ep_people/
(Di Rupo 1294, Gál 28150, Kofod 124870, Hlaváček 197526). Snapshot invariants run on
data/snapshot/ep_people/*.json when present. Live checks are marked `network`.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from pipeline import snapshot
from pipeline.models.entities import Mep, Organization
from pipeline.sources import ep_people as E

FIX = Path(__file__).parent / "fixtures" / "ep_people"
NOW = "2026-10-22T00:00:00Z"


def fixture(name: str) -> list[dict]:
    return json.loads((FIX / name).read_text(encoding="utf-8"))["data"]


PEOPLE = {p["identifier"]: p for p in fixture("meps_detail.json")}
BODIES = {o["identifier"]: o for o in fixture("corporate_bodies.json")}
TERM_LISTS = {9: {"28150", "124870", "197526"}, 10: {"1294", "28150", "197526"}}  # as listed by /meps


def mep(i: str, active: bool = False) -> Mep:
    return E.parse_mep(PEOPLE[i], active, {t for t, ids in TERM_LISTS.items() if i in ids}, NOW)


def groups(m: Mep) -> list[tuple[str, str | None, str | None, int | None]]:
    return [(x.org_id, x.start, x.end, x.term) for x in m.memberships if x.kind == "group"]


# ------------------------------------------------------------------------------------------ parsing
def test_term_of_boundaries():
    assert E.term_of("2019-07-01") is None
    assert E.term_of("2019-07-02") == 9
    assert E.term_of("2024-07-15") == 9
    assert E.term_of("2024-07-16") == 10
    assert E.term_of(None) is None


def test_names_country_terms_and_urls():
    m = mep("1294", active=True)
    assert m.name == "Elio Di Rupo" and m.sort_label == "DIRUPO"
    assert m.country == "BE" and m.active
    assert m.terms == [3, 10]  # all terms from the EP mandates; memberships only for terms 9-10
    assert {x.term for x in m.memberships} == {10}
    assert m.official_url == "https://www.europarl.europa.eu/meps/en/1294" and m.photo_url is None
    assert m.source.institution == "EP" and m.source.identifier == "1294"
    assert mep("197526").name == "Martin Hlaváček" and mep("197526").country == "CZ"


def test_group_history_preserved_with_dates():
    # Fidesz MEPs left the EPP group in March 2021 (EP records NI from 2021-03-05), PfE in term 10.
    assert groups(mep("28150", active=True)) == [
        ("5153", "2019-07-02", "2021-03-04", 9),
        ("5152", "2021-03-05", "2024-07-15", 9),
        ("7150", "2024-07-16", None, 10),
    ]


def test_roles_and_kinds():
    m = mep("1294", active=True)
    roles = {(x.org_id, x.role) for x in m.memberships if x.kind == "committee"}
    assert ("6562", "MEMBER") in roles and ("6586", "MEMBER_SUBSTITUTE") in roles  # AFET, LIBE
    assert {x.kind for x in m.memberships} == {"group", "party", "committee"}  # delegations etc. skipped
    gal_pfe = [x for x in mep("28150").memberships if x.org_id == "7150"]
    assert gal_pfe[0].role is None  # source omits the role on this membership


def test_mandate_without_org_and_missing_party():
    kofod = mep("124870")  # one-day 2019 mandate has no organization in the source
    assert kofod.terms == [8, 9] and groups(kofod) == [("5154", "2019-07-02", "2019-07-02", 9)]
    hlavacek = mep("197526")  # source has no national-party membership for his short term-10 mandate
    assert [x.term for x in hlavacek.memberships if x.kind == "party"] == [9]
    assert groups(hlavacek)[-1] == ("7150", "2024-07-16", "2024-07-31", 10)


def test_parse_org_codes():
    o = {i: E.parse_org(b, NOW) for i, b in BODIES.items()}
    assert (o["5153"].kind, o["5153"].code) == ("group", "EPP")
    assert o["7038"].code == "S&D" and o["7150"].code == "PfE" and o["5704"].code == "Renew"
    assert o["5151"].code == "GUE/NGL" and o["5151"].end == "2020-12-17"  # pre-rename group kept as is
    assert o["6259"].code == "The Left" and o["6259"].start == "2020-12-18"
    assert o["7150"].label == "Patriots for Europe Group"
    ps = o["6758"]
    assert (ps.kind, ps.code, ps.label, ps.country, ps.start) == (
        "party",
        "PS",
        "Parti Socialiste",
        "BE",
        "2024-07-16",
    )
    assert o["5355"].code is None and o["5355"].label == "ANO 2011"  # no separate acronym in the source
    assert (o["6562"].kind, o["6562"].code, o["6562"].label) == (
        "committee",
        "AFET",
        "Committee on Foreign Affairs",
    )
    assert o["7911"].code == "SEDE" and o["7911"].country is None


class FakeHttp:
    """Serves the fixtures for the API paths ep_people requests."""

    def __init__(self):
        self.calls: list[str] = []

    def get_json(self, url: str, params: dict | None = None):
        path = urlparse(url).path.removeprefix("/api/v2")
        self.calls.append(path)
        params = params or {}
        if params.get("offset"):
            return {"data": []}
        if path == "/meps":
            ids = TERM_LISTS[params["parliamentary-term"]]
            return {"data": [r for r in fixture("meps_term.json") if r["identifier"] in ids]}
        if path == "/meps/show-current":
            return {"data": fixture("show_current.json")}
        kind, ids = path.strip("/").split("/")
        src = PEOPLE if kind == "meps" else BODIES
        return {"data": [src[i] for i in ids.split(",") if i in src]}


def test_fetch_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    http = FakeHttp()
    status = E.fetch(http)
    assert status.status == "ok", status.note
    assert status.records == {
        "meps": 4,
        "orgs": len(json.loads((tmp_path / "ep_people/orgs.json").read_text())),
    }
    meps = [Mep.model_validate(x) for x in json.loads((tmp_path / "ep_people/meps.json").read_text())]
    assert [m.id for m in meps] == ["1294", "28150", "124870", "197526"]
    assert {m.id for m in meps if m.active} == {"1294", "28150"}
    orgs = {o["id"] for o in json.loads((tmp_path / "ep_people/orgs.json").read_text())}
    assert {x.org_id for m in meps for x in m.memberships} == orgs
    assert sum(c.startswith("/meps/") and "," in c for c in http.calls) == 1  # one batched detail request


def _files(root: Path) -> dict[str, str]:
    return {n: (root / "ep_people" / f"{n}.json").read_text(encoding="utf-8") for n in ("meps", "orgs")}


def test_fetch_keeps_records_a_batch_did_not_return(tmp_path, monkeypatch):
    """MEPs missing from a /meps/{ids} answer used to be left out of meps.json (their votes' ballots then name
    unknown MEPs); they keep their stored record and the run is 'partial'."""
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    E.fetch(FakeHttp())
    before = _files(tmp_path)

    class Short(FakeHttp):
        def get_json(self, url: str, params: dict | None = None):
            d = super().get_json(url, params)
            if "," in url:  # a detail batch that lacks one MEP and one organization
                d = {"data": [r for r in d["data"] if r["identifier"] not in ("197526", "7911")]}
            return d

    status = E.fetch(Short())
    assert _files(tmp_path) == before
    assert status.status == "partial"
    assert "MEP 197526 not returned (previous record kept)" in status.note
    assert "org 7911 not returned (previous record kept)" in status.note


@pytest.mark.parametrize("empty_term", [9, 10])
def test_fetch_does_not_overwrite_with_a_short_list(tmp_path, monkeypatch, empty_term):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    E.fetch(FakeHttp())
    before = _files(tmp_path)

    class EmptyTerm(FakeHttp):  # /meps?parliamentary-term=N answers with no records
        def get_json(self, url: str, params: dict | None = None):
            if (params or {}).get("parliamentary-term") == empty_term:
                return {"data": []}
            return super().get_json(url, params)

    with pytest.raises(RuntimeError, match="not overwriting"):  # the source fails; its files stay
        E.fetch(EmptyTerm())
    assert _files(tmp_path) == before


@pytest.mark.parametrize("current", [[], ["1294"]], ids=["empty", "cut-short"])
def test_fetch_does_not_overwrite_with_a_short_list_of_current_members(tmp_path, monkeypatch, current):
    """/meps/show-current answering HTTP 200 with fewer sitting MEPs used to mark the missing ones as former
    MEPs, with status "ok" (an empty answer: 0 sitting MEPs on the site); now the source fails, keeping its files."""
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    E.fetch(FakeHttp())
    before = _files(tmp_path)

    class ShortCurrent(FakeHttp):
        def get_json(self, url: str, params: dict | None = None):
            d = super().get_json(url, params)
            if url.endswith("/meps/show-current"):
                d = {"data": [r for r in d["data"] if r["identifier"] in current]}
            return d

    with pytest.raises(RuntimeError, match="lists .* sitting MEPs against 2 active in the snapshot; not overwriting"):
        E.fetch(ShortCurrent())
    assert _files(tmp_path) == before


def test_an_empty_list_of_current_members_is_not_an_empty_answer():
    """The API answers an empty page with HTTP 204 (checked 2026-10-23: show-current at offset=1000); Http accepts
    only 200, so it is a failure, never an empty list."""
    import httpx

    from pipeline.http import Http, HttpError

    http = Http(cache_dir=None, min_interval_s=0.0, transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    with pytest.raises(HttpError) as e:
        E._list(http, "/meps/show-current")
    assert e.value.status == 204


def test_fetch_starts_no_batch_after_its_time_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "SNAPSHOT", tmp_path)
    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    E.fetch(FakeHttp())
    before = _files(tmp_path)
    monkeypatch.setenv("EU_INTEL_FETCH_BUDGET_S", "0")
    http = FakeHttp()
    status = E.fetch(http)
    assert not [c for c in http.calls if c.startswith(("/meps/1", "/corporate-bodies"))]  # no detail request
    assert _files(tmp_path) == before
    assert status.status == "partial" and "time budget reached" in status.note


# ------------------------------------------------------------------------------ snapshot invariants
SNAP = snapshot.SNAPSHOT / "ep_people"


@pytest.fixture(scope="module")
def snap() -> tuple[list[Mep], dict[str, Organization]]:
    if not (SNAP / "meps.json").exists() or not (SNAP / "orgs.json").exists():
        pytest.skip("no ep_people snapshot")
    meps = snapshot.read_records("ep_people", "meps", Mep)
    orgs = {o.id: o for o in snapshot.read_records("ep_people", "orgs", Organization)}
    return meps, orgs


def test_snapshot_counts(snap):
    meps, orgs = snap
    assert len({m.id for m in meps}) == len(meps)
    assert 690 <= sum(m.active for m in meps) <= 720  # 720 seats in the 10th term, minus vacancies
    assert sum(9 in m.terms for m in meps) > 800 and sum(10 in m.terms for m in meps) >= 720
    assert all(10 in m.terms for m in meps if m.active)
    assert {o.code for o in orgs.values() if o.kind == "group"} >= {
        "EPP",
        "S&D",
        "Renew",
        "Greens/EFA",
        "ECR",
        "PfE",
    }


def test_snapshot_one_current_group_per_active_mep(snap):
    meps, _ = snap
    for m in meps:
        current = [x for x in m.memberships if x.kind == "group" and x.end is None]
        assert len(current) == (1 if m.active else 0), m.id


def test_snapshot_memberships_reference_orgs(snap):
    meps, orgs = snap
    for m in meps:
        for x in m.memberships:
            o = orgs[x.org_id]
            assert o.kind == x.kind, (m.id, x)
            if x.kind == "party":
                assert o.country, (m.id, x)
            assert x.term in (9, 10)
            assert x.start and (x.end is None or x.start <= x.end), (m.id, x)


def test_snapshot_group_timelines_do_not_overlap(snap):
    meps, _ = snap
    for m in meps:
        gs = sorted((x.start, x.end or "9999-12-31") for x in m.memberships if x.kind == "group")
        assert all(a[1] < b[0] for a, b in zip(gs, gs[1:], strict=False)), m.id


# --------------------------------------------------------------------------------------------- live
@pytest.mark.network
@pytest.mark.parametrize("day", ["2021-03-05", "2024-01-29"])
def test_live_group_at_date_matches_api(snap, day):
    """The API's own group-at-date (show-current?mandate-date=) must equal our membership timeline."""
    from pipeline.http import EP_API, default_http

    meps, orgs = snap
    by_id = {m.id: m for m in meps}
    rows = default_http().get_json(
        f"{EP_API}/meps/show-current", params={**E.FMT, "mandate-date": day, "offset": 0, "limit": 1000}
    )["data"]
    assert len(rows) > 690
    for r in rows:
        m = by_id[r["identifier"]]
        got = [
            orgs[x.org_id].code
            for x in m.memberships
            if x.kind == "group" and x.start <= day <= (x.end or "9")
        ]
        label = r.get("api:political-group")
        assert got == ([E.GROUP_CODES.get(label, label)] if label else []), r["identifier"]
