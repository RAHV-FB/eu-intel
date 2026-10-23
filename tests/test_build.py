"""pipeline/build.py on the TEST-ONLY fixture in tests/fixtures/build/ (invented records)."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pipeline.build import (
    build,
    clean_title,
    group_slug,
    instrument_from_title,
    short_names,
)

FIX = Path(__file__).parent / "fixtures" / "build"
TODAY = "2026-10-22"

REQUIRED = [
    "meta.json", "home.json", "dossiers/index.json", "votes/index.json", "council/index.json",
    "people/meps.json", "people/groups.json", "people/parties.json", "countries/index.json",
    "topics.json", "search.json", "activity.json", "feeds/updates.xml",
]  # fmt: skip


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("build")
    shutil.copytree(FIX / "snapshot", base / "snapshot")
    o = base / "public"
    assert (
        build(out=o, snapshot=base / "snapshot", curated=FIX / "curated", state=base / "state", today=TODAY)
        == 0
    )
    return o


def load(out: Path, rel: str):
    return json.loads((out / rel).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- pure helpers
def test_group_slug():
    assert group_slug("S&D") == "s-d"
    assert group_slug("Greens/EFA") == "greens-efa"
    assert group_slug("EPP") == "epp"
    assert group_slug("The Left") == "the-left"


def test_clean_title_strips_boilerplate_only_when_meaningful():
    assert (
        clean_title(
            "Proposal for a Regulation of the European Parliament and of the Council laying down harmonised rules on "
            "artificial intelligence"
        )
        == "Harmonised rules on artificial intelligence"
    )
    assert clean_title("Directive (EU) 2019/904 of the European Parliament and of the Council of 5 June 2019 on the "
                       "reduction of the impact of certain plastic products on the environment") == (
        "Reduction of the impact of certain plastic products on the environment")  # fmt: skip
    # too little left -> keep the original
    assert clean_title("Regulation (EU) 2023/1 on fees") == "Regulation (EU) 2023/1 on fees"
    assert clean_title("Regulation (EU) 2023/1 amending Regulation (EU) No 1308/2013") == (
        "Amending Regulation (EU) No 1308/2013"
    )
    assert clean_title("Artificial Intelligence Act") == "Artificial Intelligence Act"
    assert instrument_from_title("Proposal for a Directive on test") == "directive"


def test_short_names_skip_names_of_other_acts():
    assert short_names("Rules on AI (Artificial Intelligence Act) and amending certain acts") == [
        "Artificial Intelligence Act"
    ]
    assert short_names("Amending Regulation (EU) 2016/679 (General Data Protection Regulation)") == []


# ------------------------------------------------------------------------------- outputs
def test_all_contract_files_exist_and_are_compact(out: Path):
    for rel in REQUIRED:
        assert (out / rel).exists(), rel
    text = (out / "dossiers/index.json").read_text(encoding="utf-8")
    assert "\n" not in text
    assert text == json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))


def test_build_is_deterministic(tmp_path: Path, out: Path):
    shutil.copytree(FIX / "snapshot", tmp_path / "snapshot")
    o2 = tmp_path / "public"
    build(
        out=o2, snapshot=tmp_path / "snapshot", curated=FIX / "curated", state=tmp_path / "state", today=TODAY
    )
    for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "meta.json"):
        rel = f.relative_to(out)
        assert (o2 / rel).read_bytes() == f.read_bytes(), rel


def test_dossier_linking_by_identifier_only(out: Path):
    idx = {d["id"]: d for d in load(out, "dossiers/index.json")}
    assert set(idx) == {"2099-0001", "2099-0002", "2099-0003", "2099-0009"}
    d1 = load(out, "dossiers/2099-0001.json")
    assert d1["title"] == "Test Widgets Act"  # curated short title
    assert d1["celex"] == ["32099R0001"]
    assert d1["featured"] is True and d1["topics"] == ["tech"]
    assert d1["type_label"] == "Ordinary legislative procedure"
    assert d1["adopted"] == "2024-11-20" and d1["next_date"] == "2027-01-01"
    assert [v["id"] for v in d1["ep_votes"]] == ["V1"]  # amendments are not indexed
    assert [c["id"] for c in d1["council_votes"]] == ["C1"]
    assert d1["has_ep_votes"] and d1["has_council_votes"]
    # EUR-Lex-only dossier: built from the act record, no invented EP events
    d9 = load(out, "dossiers/2099-0009.json")
    assert d9["ref"] == "2099/0009(COD)" and d9["celex"] == ["32099L0009"]
    # no EP events; the only Council event is the Council's own voting result (C2)
    assert {e["institution"] for e in d9["timeline"]} == {"EUR-Lex", "Council"}
    assert [e["source"]["url"] for e in d9["timeline"] if e["institution"] == "Council"] == [
        "https://example.invalid/C2"
    ]
    # cleaned official title when not curated; instrument kept separately
    assert idx["2099-0003"]["title"] == "Test thingamajigs"
    assert idx["2099-0003"]["instrument"] == "directive"
    assert idx["2099-0009"]["title"] == "Test doohickeys"
    assert idx["2099-0002"]["topics"] == ["migration"]


def test_timeline_marks_scheduled_dates_and_links_votes(out: Path):
    tl = load(out, "dossiers/2099-0001.json")["timeline"]
    assert [e["date"] for e in tl] == sorted(e["date"] for e in tl)
    future = [e for e in tl if e["date"] > TODAY]
    assert future and all(e["state"] == "scheduled" for e in future)
    assert all(e["state"] == "done" for e in tl if e["date"] <= TODAY)
    app = [e for e in tl if e["kind"] == "application"]
    assert {e["title"] for e in app} == {
        "Further provisions started to apply (date recorded by EUR-Lex)",
        "Further provisions start to apply (date recorded by EUR-Lex)",
    }
    pos = next(e for e in tl if e["kind"] == "ep_position")
    assert pos["vote_id"] == "V1" and pos["key"] is True


def test_vote_breakdowns_use_membership_on_vote_date(out: Path):
    v1 = load(out, "votes/V1.json")
    groups = {g["group"]: g for g in v1["groups"]}
    # T1 was Greens/EFA on 2024-04-10 (moved to S&D only in term 10)
    assert groups["greens-efa"]["for"] == 1 and "s-d" not in groups
    assert groups["epp"]["for"] == 1 and groups["epp"]["against"] == 1
    assert v1["reconciliation"]["matches"] is True
    # real pipeline.analysis.ep_margin: 2 for / 1 against, majority of votes cast -> threshold 2
    assert v1["margin"]["threshold"] == 2 and v1["margin"]["distance"] == 0
    assert v1["margin"]["rule_label"].startswith("Majority of votes cast")
    assert v1["display_title"] == "Test Widgets Act — final vote on the text"
    v3 = load(out, "votes/V3.json")
    assert v3["reconciliation"]["matches"] is False  # 1 official abstention, none recorded
    assert v3["abstain"] == 1  # official total shown; missing ballots never relabelled
    assert sum(1 for b in v3["ballots"] if b["pos"] == "abstain") == 0
    t4 = next(b for b in v3["ballots"] if b["mep"] == "T4")
    assert t4["pos"] == "against" and t4["intended"] == "for"
    idx = [v["id"] for v in load(out, "votes/index.json")]
    assert idx == ["V3", "V1", "V4"] and not (out / "votes/V2.json").exists()
    v4 = load(out, "votes/V4.json")
    assert v4["outcome"] == "unknown" and v4["margin"] is None  # never "Passed by N" without a known outcome
    assert v4["has_ballots"] is False and v4["ballots"] == [] and v4["for"] == 300


def test_groups_merge_across_terms_and_people_files(out: Path):
    groups = {g["id"]: g for g in load(out, "people/groups.json")}
    assert groups["epp"]["terms"] == [9, 10] and groups["epp"]["members"] == 2  # T2, T4 (T3 inactive)
    assert groups["greens-efa"]["active"] is False
    assert groups["s-d"]["code"] == "S&D"
    t1 = load(out, "people/meps/T1.json")
    assert t1["group"] == "s-d" and [x["vote_id"] for x in t1["votes"]] == ["V3", "V1"]
    t2 = load(out, "people/meps/T2.json")
    assert t2["rapporteur_for"][0]["dossier_id"] == "2099-0001"
    epp = load(out, "people/groups/epp.json")
    assert {v["vote_id"] for v in epp["votes"]} == {"V1", "V3"}
    party = load(out, "people/parties/P2.json")
    assert party["members_total"] == 2 and party["members_active"] == 1


def test_countries_and_transposition_status(out: Path):
    es = load(out, "countries/ES.json")
    tr = {t["celex"]: t for t in es["transposition"]}
    assert tr["32099L0003"]["status"] == "measures_notified"
    assert tr["32099L0009"]["status"] == "deadline_not_reached"  # queried, 0 measures, deadline 2027
    fr = {t["celex"]: t for t in load(out, "countries/FR.json")["transposition"]}
    assert fr["32099L0003"]["status"] == "none_found"  # queried, 0 measures, deadline passed
    assert load(out, "countries/FR.json")["open_infringements"] == 1
    hu = load(out, "countries/HU.json")
    assert hu["council_positions"]["against"] == 1
    impl = load(out, "dossiers/2099-0003.json")["implementation"]
    fr_row = next(c for c in impl["countries"] if c["country"] == "FR")
    assert fr_row["infringements"][0]["id"] == "INFR(2099)0001"  # linked via legal_basis
    assert "not, by itself, evidence" in impl["note"]
    assert load(out, "dossiers/2099-0001.json")["implementation"] is None  # regulations: none


def test_council_no_veto_outside_unanimity(out: Path):
    for cv in load(out, "council/index.json"):
        a = cv.get("assessment")
        if a and cv["voting_rule"] != "unanimity":
            assert a["single_state_veto_possible"] is False


def test_home_lists_only_from_real_data(out: Path):
    home = load(out, "home.json")
    assert [f["dossier"]["id"] for f in home["featured"]] == ["2099-0001"]
    lists = {x["id"]: x for x in home["lists"]}
    assert set(lists) == {
        "recently_adopted",
        "under_debate",
        "close_votes",
        "rejected",
        "stalled",
        "upcoming",
    }
    stalled = lists["stalled"]["items"]
    assert stalled and stalled[0]["dossier_id"] == "2099-0002"
    assert "amendment is not a rejected law" in lists["rejected"]["description"]
    assert all(i.get("vote_id") != "V2" for i in lists["rejected"]["items"])  # amendment rejections excluded
    upcoming = lists["upcoming"]["items"]
    assert upcoming and all(TODAY < i["date"] <= "2027-10-22" for i in upcoming)


def test_meta_sources_and_counts(out: Path):
    meta = load(out, "meta.json")
    assert {s["id"] for s in meta["sources"]} == {
        "ep_people",
        "ep_procedures",
        "ep_votes",
        "eurlex",
        "council",
        "implementation",
        "train",
    }
    assert all(s["licence"] for s in meta["sources"])
    assert meta["counts"]["dossiers"] == 4 and meta["counts"]["ep_votes"] == 3
    assert meta["snapshot_at"] == "2099-01-01T00:00:00Z"
    assert any("Country indicators" in n for n in meta["coverage_notes"])


def test_search_docs(out: Path):
    docs = load(out, "search.json")
    by = {(d["k"], d["id"]): d for d in docs}
    d1 = by[("dossier", "2099-0001")]
    assert "2099/0001(COD)" in d1["x"] and "32099R0001" in d1["x"] and "COM(2099)1" in d1["x"]
    assert "TWA" in d1["a"]
    assert "gizmo" in by[("dossier", "2099-0003")]["x"]  # aliases.yaml rule embedded
    assert "Spanish" in by[("country", "ES")]["a"]
    assert "S&D" in by[("group", "s-d")]["a"]
    assert ("page", "council-voting") in by
    assert ("topic", "tech") in by
    assert all(d["u"].startswith("/") for d in docs)


def test_feeds_are_valid_atom(out: Path):
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.parse(out / "feeds/updates.xml").getroot()
    assert root.tag == "{http://www.w3.org/2005/Atom}feed"
    assert root.find("a:id", ns) is not None and root.find("a:updated", ns) is not None
    for e in root.findall("a:entry", ns):
        for tag in ("id", "title", "updated"):
            assert e.find(f"a:{tag}", ns) is not None
        assert e.find("a:link", ns).get("href").startswith("https://rahv-fb.github.io/eu-intel/")
    assert (out / "feeds/tech.xml").exists()
    ET.parse(out / "feeds/tech.xml")


def test_missing_sources_build_empty_sections(tmp_path: Path):
    snap = tmp_path / "snapshot"
    shutil.copytree(FIX / "snapshot" / "ep_people", snap / "ep_people")
    o = tmp_path / "public"
    assert (
        build(out=o, snapshot=snap, curated=tmp_path / "nocurated", state=tmp_path / "state", today=TODAY)
        == 0
    )
    assert load(o, "dossiers/index.json") == []
    assert load(o, "votes/index.json") == []
    meta = load(o, "meta.json")
    assert all(s["status"] == "unavailable" for s in meta["sources"])
    assert any("Council votes: not available" in n for n in meta["coverage_notes"])
    assert len(load(o, "people/meps.json")) == 4


# ------------------------------------------------------------------------------- contract (src/types/data.ts)
DATA_TS = Path(__file__).resolve().parents[1] / "src" / "types" / "data.ts"


def _interfaces() -> dict[str, tuple[set[str], set[str]]]:
    """interface name -> (required keys, all keys), following `extends`."""
    import re

    text = DATA_TS.read_text(encoding="utf-8")
    raw: dict[str, tuple[list[str], set[str], set[str]]] = {}
    for m in re.finditer(r"export interface (\w+)(?: extends ([\w, ]+))? \{(.*?)\n\}", text, re.S):
        name, ext, body = m.group(1), m.group(2), m.group(3)
        req, keys = set(), set()
        depth = 0
        for line in body.split("\n"):
            s = line.split("//")[0].strip()
            if depth == 0:
                fm = re.match(r"^'?([\w]+)'?(\?)?:", s)
                if fm:
                    keys.add(fm.group(1))
                    if not fm.group(2):
                        req.add(fm.group(1))
            depth += s.count("{") - s.count("}")
        raw[name] = ([e.strip() for e in ext.split(",")] if ext else [], req, keys)

    def resolve(n: str) -> tuple[set[str], set[str]]:
        ext, req, keys = raw[n]
        req, keys = set(req), set(keys)
        for e in ext:
            r2, k2 = resolve(e)
            req |= r2
            keys |= k2
        return req, keys

    return {n: resolve(n) for n in raw}


def _check(obj: dict, iface: str, ifs: dict, where: str, extra_ok: set[str] = frozenset()) -> None:
    req, keys = ifs[iface]
    missing = req - set(obj)
    unknown = set(obj) - keys - set(extra_ok)
    assert not missing, f"{where}: missing {missing} for {iface}"
    assert not unknown, f"{where}: unknown keys {unknown} for {iface}"


def test_output_matches_data_ts_contract(out: Path):
    ifs = _interfaces()
    _check(load(out, "meta.json"), "Meta", ifs, "meta.json")
    for s in load(out, "meta.json")["sources"]:
        _check(s, "SourceStatusInfo", ifs, "meta.sources")
    home = load(out, "home.json")
    _check(home, "HomeData", ifs, "home.json")
    for f in home["featured"]:
        _check(f, "FeaturedItem", ifs, "home.featured")
        _check(f["dossier"], "DossierSummary", ifs, "home.featured.dossier")
    for lst in home["lists"]:
        for it in lst["items"]:
            _check(it, "HomeListItem", ifs, f"home.lists.{lst['id']}")
    for d in load(out, "dossiers/index.json"):
        _check(d, "DossierSummary", ifs, "dossiers/index.json")
        det = load(out, f"dossiers/{d['id']}.json")
        _check(det, "DossierDetail", ifs, f"dossiers/{d['id']}.json")
        _check(det["status"], "DossierStatus", ifs, "status")
        _check(det["next_step"], "NextStep", ifs, "next_step")
        if det["stall"]:
            _check(det["stall"], "Stall", ifs, "stall")
        if det["application"]:
            _check(det["application"], "ApplicationInfo", ifs, "application")
        for e in det["timeline"]:
            _check(e, "TimelineEvent", ifs, "timeline")
        for a in det["acts"]:
            _check(a, "LegalActSummary", ifs, "acts")
        if det["implementation"]:
            _check(det["implementation"], "DossierImplementation", ifs, "implementation")
        for c in det["changes"]:
            _check(c, "ActivityItem", ifs, "changes")
    for v in load(out, "votes/index.json"):
        _check(v, "EpVoteSummary", ifs, "votes/index.json")
        det = load(out, f"votes/{v['id']}.json")
        _check(det, "EpVoteDetail", ifs, f"votes/{v['id']}.json")
        for g in det["groups"]:
            _check(g, "GroupBreakdown", ifs, "vote.groups")
        for b in det["ballots"]:
            _check(b, "Ballot", ifs, "vote.ballots")
    extra = {"legal_basis", "states_against", "states_abstain", "states_not_participating"}
    for cv in load(out, "council/index.json"):
        _check(cv, "CouncilVote", ifs, "council/index.json")
        if cv["assessment"]:
            _check(cv["assessment"], "CouncilAssessment", ifs, "assessment", extra)
    for m in load(out, "people/meps.json"):
        _check(m, "MepSummary", ifs, "people/meps.json")
        _check(load(out, f"people/meps/{m['id']}.json"), "MepDetail", ifs, f"people/meps/{m['id']}.json")
    for g in load(out, "people/groups.json"):
        _check(g, "GroupSummary", ifs, "people/groups.json")
        _check(load(out, f"people/groups/{g['id']}.json"), "GroupDetail", ifs, "group detail")
    for p in load(out, "people/parties.json"):
        _check(p, "PartySummary", ifs, "people/parties.json")
        _check(load(out, f"people/parties/{p['id']}.json"), "PartyDetail", ifs, "party detail")
    for c in load(out, "countries/index.json"):
        _check(c, "CountrySummary", ifs, "countries/index.json")
        det = load(out, f"countries/{c['code']}.json")
        _check(det, "CountryDetail", ifs, f"countries/{c['code']}.json")
        for i in det["infringements"]:
            _check(i, "InfringementInfo", ifs, "infringements")
    for t in load(out, "topics.json"):
        _check(t, "Topic", ifs, "topics.json")
    for d in load(out, "search.json"):
        _check(d, "SearchDoc", ifs, "search.json")
    for a in load(out, "activity.json"):
        _check(a, "ActivityItem", ifs, "activity.json")


def test_close_votes_use_margin_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import pipeline.build as B

    def fake_margin(vote, component_members):  # stand-in for pipeline.analysis.ep_margin.margin
        cast = (vote.n_for or 0) + (vote.n_against or 0)
        thr = cast // 2 + 1
        return {"rule": "votes_cast", "rule_label": "TEST rule", "threshold": thr, "distance": vote.n_for - thr,
                "relative": (vote.n_for - thr) / cast, "label": "TEST label", "extra_field": 1}  # fmt: skip

    real_lazy = B._lazy
    monkeypatch.setattr(B, "_lazy", lambda m, a: fake_margin if a == "margin" else real_lazy(m, a))
    shutil.copytree(FIX / "snapshot", tmp_path / "snapshot")
    o = tmp_path / "public"
    build(
        out=o,
        snapshot=tmp_path / "snapshot",
        curated=FIX / "curated",
        state=tmp_path / "state",
        today="2025-01-20",
    )
    v1 = load(o, "votes/V1.json")
    assert v1["margin"]["threshold"] == 2 and "extra_field" not in v1["margin"]
    close = next(x for x in load(o, "home.json")["lists"] if x["id"] == "close_votes")["items"]
    assert [i["vote_id"] for i in close] == ["V1"]  # V3 is a resolution, not a final vote


def test_related_next_step_and_sources(out: Path):
    d1 = load(out, "dossiers/2099-0001.json")
    rel = {(r["relation"], r["id"]) for r in d1["related"]}
    assert ("Amended by", "32099R0077") in rel  # amending act not in the snapshot: id is its CELEX
    assert ("Amends", "2099-0003") in rel
    d3 = load(out, "dossiers/2099-0003.json")
    assert ("Amended by", "2099-0001") in {(r["relation"], r["id"]) for r in d3["related"]}
    srcs = [(x["institution"], x["url"], x.get("identifier")) for x in d1["sources"]]
    assert len(srcs) == len(set(srcs))
    for d in load(out, "dossiers/index.json"):
        det = load(out, f"dossiers/{d['id']}.json")
        if det["stage"] == "in_force":
            assert det["next_step"]["basis"] != "unknown", d["id"]


def test_council_votes(out: Path):
    cv = load(out, "council/index.json")[0]
    a = cv["assessment"]
    assert cv["dossier_id"] == "2099-0001" and cv["stage"] == "TEST adoption of the legislative act"
    assert a["rule"] == "qmv" and a["adopted_by_rule"] is True
    assert a["legal_basis"]  # linked procedure records a COM document -> proposal origin established
    assert 0 <= (a["population_for_pct"] or 0) <= 100
    assert a["single_state_veto_possible"] is False
    pl = load(out, "countries/PL.json")
    assert pl["council_positions"]["abstain"] == 1
    assert pl["council_votes"][0]["pos"] == "abstain" and pl["council_votes"][0]["dossier_id"] == "2099-0001"


def test_council_population_share_is_of_participating_states(out: Path):
    c2 = next(cv for cv in load(out, "council/index.json") if cv["id"] == "C2")  # Denmark not participating
    a = c2["assessment"]
    assert (a["states_participating"], a["states_not_participating"]) == (26, 1)
    assert a["population_for_pct"] == 100.0  # 26 of 26 participating states: 100% of THEIR population
    assert a["legal_basis"] is None and a["blocking_minority_min_states"] is None  # proposal origin not recorded
    c1 = next(cv for cv in load(out, "council/index.json") if cv["id"] == "C1")
    assert c1["assessment"]["legal_basis"] == "TEU Art. 16(4)" and c1["assessment"]["blocking_minority_min_states"] == 4


def _edit_snapshot(base: Path, rel: str, fn) -> None:
    p = base / "snapshot" / rel
    recs = json.loads(p.read_text(encoding="utf-8"))
    fn(recs)
    p.write_text(json.dumps(recs, ensure_ascii=False), encoding="utf-8")


def test_council_votes_date_the_council_steps_in_the_timeline(tmp_path: Path):
    shutil.copytree(FIX / "snapshot", tmp_path / "snapshot")
    src = {"institution": "OEIL", "url": "https://example.invalid/oeil", "label": "Legislative Observatory (OEIL) key events",
           "retrieved_at": "2099-01-01T00:00:00Z"}  # fmt: skip

    def council(recs):
        recs[0]["vote_on"] = "act"
        recs.append({**recs[0], "id": "C3", "date": "2024-06-01", "vote_on": "first_reading_position",
                     "written_procedure": True, "stage": "Adoption of the Council's position at first reading",
                     "source": {**recs[0]["source"], "url": "https://example.invalid/C3", "identifier": "C3"}})  # fmt: skip

    def oeil(recs):
        p = next(r for r in recs if r["id"] == "2099-0001")
        p["events"] += [
            {"id": "oeil-pos", "date": "2024-06-10", "kind": "council_position", "institution": "Council",
             "title": "Council adopted its first-reading position", "docs": [], "source": src},
            {"id": "oeil-adopt", "date": "2024-11-07", "kind": "council_adoption", "institution": "Council",
             "title": "Council adopted the act after Parliament's first reading", "docs": [], "source": src},
        ]  # fmt: skip

    _edit_snapshot(tmp_path, "council/votes.json", council)
    _edit_snapshot(tmp_path, "ep_procedures/procedures.json", oeil)
    o = tmp_path / "public"
    build(out=o, snapshot=tmp_path / "snapshot", curated=FIX / "curated", state=tmp_path / "state", today=TODAY)
    tl = [e for e in load(o, "dossiers/2099-0001.json")["timeline"] if e["institution"] == "Council"]
    assert [(e["date"], e["kind"], e["title"], e["key"]) for e in tl] == [
        ("2024-06-01", "council_position", "Council adopted its position at first reading (written procedure)", True),
        # OEIL's "Council position published" is the publication date, not the Council's vote
        ("2024-06-10", "council_position", "Council's first-reading position published", False),
        ("2024-11-05", "council_adoption", "Council adopted the act", True),
        # OEIL's own adoption date (2024-11-07) is replaced by the Council's voting result
    ]
    assert tl[0]["source"]["url"] == "https://example.invalid/C3"
    assert tl[2]["detail"] == "25 Member States in favour, 1 against, 1 abstained"
    pl = load(o, "countries/PL.json")
    assert {v["vote_id"]: v["vote_on"] for v in pl["council_votes"]} == {
        "C1": "act", "C2": None, "C3": "first_reading_position"
    }  # fmt: skip


def test_opt_out_countries_are_not_bound_rather_than_missing_measures(out: Path):
    # C2 records DK as not participating in the adoption of 32099L0009 (no measures notified by anyone):
    # DK must read "not_participating", never "none_found"; other states keep the deadline-based status.
    dk = {t["celex"]: t["status"] for t in load(out, "countries/DK.json")["transposition"]}
    ie = {t["celex"]: t["status"] for t in load(out, "countries/IE.json")["transposition"]}
    assert dk["32099L0009"] == "not_participating"
    assert ie["32099L0009"] == "deadline_not_reached"


def test_court_ruling_wording_never_overstates_scope():
    from types import SimpleNamespace

    from pipeline.build import provision_label, ruling_summary

    assert provision_label("A05P1") == "Article 5(1)"
    assert provision_label("A01PT3") == "Article 1, point 3"
    assert provision_label("A10A") == "Article 10a"
    r = SimpleNamespace(
        effect="annulment", provisions=["A05P1", "A05P2"], case_number="C-19/23", celex="62023CJ0019",
        date="2025-11-11", ecli=None, url="https://example.invalid/j",
    )  # fmt: skip
    s = ruling_summary(r)["summary"]
    assert "all or part of Article 5(1), Article 5(2)" in s and "temporal effects" in s
    inv = ruling_summary(SimpleNamespace(**{**vars(r), "effect": "invalidity", "provisions": []}))
    assert (
        inv["kind_label"] == "Preliminary ruling on validity" and "declared the act invalid" in inv["summary"]
    )
