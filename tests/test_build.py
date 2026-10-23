"""pipeline/build.py on the TEST-ONLY fixture in tests/fixtures/build/ (invented records)."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pipeline.build import (
    act_number,
    act_short_name,
    build,
    build_search_docs,
    clean_title,
    council_display_title,
    ep_term_label,
    group_slug,
    instrument_from_title,
    mark_after_end_of_validity,
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


def test_council_display_title_drops_legal_form_boilerplate():
    ep_and_council = "REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL"
    assert council_display_title(f"{ep_and_council} on asset recovery and confiscation", "act") == (
        "Regulation on asset recovery and confiscation"
    )
    assert council_display_title(
        "Directive of the European Parliament and of the Council amending Directive 2011/36/EU on preventing "
        "trafficking in human beings (first reading)",
        "act",
    ) == "Directive amending Directive 2011/36/EU on preventing trafficking in human beings (first reading)"
    # the kind of act is kept, also for Council-only acts; capitals are written normally
    assert council_display_title("COUNCIL DIRECTIVE amending Directive 2006/112/EC as regards VAT rules", "act") == (
        "Council Directive amending Directive 2006/112/EC as regards VAT rules"
    )
    assert council_display_title("COUNCIL IMPLEMENTING REGULATION amending Implementing Regulation (EU) No 282/2011") == (
        "Council Implementing Regulation amending Implementing Regulation (EU) No 282/2011"
    )
    assert council_display_title("REGULATION (EU) temporarily suspending autonomous tariff duties", "act") == (
        "Regulation (EU) temporarily suspending autonomous tariff duties"
    )
    assert council_display_title(
        "Proposal for a regulation of the European Parliament and of the Council on   detergents and surfactants"
    ) == "Regulation on detergents and surfactants"
    # doubled legal form or doubled "Council" in the published title
    assert council_display_title(
        "Regulation of the European Parliament and of the Council Regulation of the European Parliament and of "
        "the Council amending Protocol No 3 on the Statute"
    ) == "Regulation amending Protocol No 3 on the Statute"
    assert council_display_title(
        "Regulation of the European Parliament and of the Council Council establishing a screening framework"
    ) == "Regulation establishing a screening framework"


def test_council_display_title_first_reading_position_prefix_only_for_that_vote():
    title = (
        "Position of the Council at first reading with a view to the adoption of a REGULATION OF THE EUROPEAN "
        "PARLIAMENT AND OF THE COUNCIL on preventing plastic pellet losses"
    )
    # the list shows "Council position at first reading" separately for these votes
    assert council_display_title(title, "first_reading_position") == "Regulation on preventing plastic pellet losses"
    # otherwise the prefix says what was voted on, so it stays
    assert council_display_title(title, "act") == title
    assert council_display_title(title, None) == title


def test_council_display_title_keeps_titles_it_cannot_shorten_safely():
    for title in (
        "REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL",  # nothing would be left
        "Council Directive on fees",  # nothing to drop: unchanged
        "Joint text on the general budget of the European Union for 2026",
        "Amendments of the European Parliament to the Council's position on the draft budget for 2027",
        "EGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL on economic coercion",  # garbled: not guessed
        "Regulation of the European Parliament and of the Coucil amending Regulation (EU) 2018/1806",
        "Decisions on the budget",
    ):
        assert council_display_title(title, "act") == title
    assert council_display_title("  Council Decision\n on  the  signing of an agreement ") == (
        "Council Decision on the signing of an agreement"
    )
    assert council_display_title("") == ""


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
    # adopted when the Council adopted it (5 Nov), not at signature (20 Nov) or publication
    assert d1["adopted"] == "2024-11-05" and d1["next_date"] == "2027-01-01"
    assert d1["published"] == "2024-12-01"
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


def test_meta_scope_and_plain_source_summaries(out: Path):
    meta = load(out, "meta.json")
    scope = meta["scope"]
    assert scope["procedure_types"] == ["COD", "CNS", "APP"] and scope["procedures_from_year"] == 2014
    index = load(out, "dossiers/index.json")
    assert scope["dossiers_without_topic"] == sum(1 for d in index if not d["topics"])
    votes = load(out, "votes/index.json")
    assert (scope["ep_votes_from"], scope["ep_votes_to"]) == (min(v["date"] for v in votes), max(v["date"] for v in votes))
    vote_note = next(n for n in meta["coverage_notes"] if n.startswith("Parliament votes"))
    assert scope["ep_votes_from"][:4] in vote_note and scope["ep_votes_to"][:4] in vote_note
    assert ("amendments" in vote_note) == bool(scope["ep_roll_call_votes"])
    # every source has a reader-facing summary with no pipeline log syntax in it
    for s in meta["sources"]:
        assert s["summary"] and not any(c in s["summary"] for c in "{}[]="), s["summary"]
    home = load(out, "home.json")
    for f in home["featured"]:  # the human-readable procedure file, not only the API record
        assert f["oeil_url"] == load(out, f"dossiers/{f['dossier']['id']}.json")["oeil_url"]


def test_search_docs(out: Path):
    docs = load(out, "search.json")
    by = {(d["k"], d["id"]): d for d in docs}
    d1 = by[("dossier", "2099-0001")]
    assert "2099/0001(COD)" in d1["x"] and "32099R0001" in d1["x"] and "COM(2099)1" in d1["x"]
    assert "TWA" in d1["a"]
    assert "2099/1" in d1["x"].split()  # act number, as cited in the Official Journal
    # short title in the act's own title: a name of the file (here already its title, so not repeated)
    assert d1["t"] == "Test Widgets Act" and "Test Widgets Act" not in d1["a"].split(" | ")
    assert "gizmo" in by[("dossier", "2099-0003")]["x"]  # aliases.yaml rule embedded
    assert "Thingamajig rules" in by[("dossier", "2099-0003")]["a"]  # aliases.yaml name of one file
    assert "TEST gadgets" in by[("dossier", "2099-0002")]["a"]  # Legislative Train file name
    assert "Spanish" in by[("country", "ES")]["a"]
    assert "S&D" in by[("group", "s-d")]["a"]
    assert ("page", "council-voting") in by
    assert ("topic", "tech") in by
    assert all(d["u"].startswith("/") for d in docs)
    assert not any(d["k"] == "vote" for d in docs)  # votes are searched on /votes, not in search.json


def test_act_number():
    assert act_number("32024R1689", "Regulation (EU) 2024/1689 of the European Parliament and of the Council") == "2024/1689"
    assert act_number("32013R1316", "Regulation (EU) No 1316/2013 of the European Parliament") == "1316/2013"
    assert act_number("32014L0024", "Directive 2014/24/EU of the European Parliament and of the Council") == "2014/24"
    assert act_number("32014L0063", "Directive2014/63/EU of the European Parliament") == "2014/63"
    assert act_number("32014D0335", "2014/335/EU, Euratom: Council Decision of 26 May 2014") == "2014/335"
    assert act_number("32020D2053", "Council Decision (EU, Euratom) 2020/2053 of 14 December 2020") == "2020/2053"
    assert act_number("32022R2065") == "2022/2065"  # one numbering for all acts from 2015
    assert act_number("32013R1316") is None  # before 2015 the order differs by instrument


def test_act_short_name():
    t = ("Regulation (EU) 2024/2847 of the European Parliament and of the Council of 23 October 2024 on horizontal "
         "cybersecurity requirements for products with digital elements and amending Regulations (EU) No 168/2013 "
         "and (EU) 2019/1020 and Directive (EU) 2020/1828 (Cyber Resilience Act) (Text with EEA relevance)")  # fmt: skip
    assert act_short_name(t) == "Cyber Resilience Act"
    assert act_short_name("Regulation (EU) 2021/1119 of 30 June 2021 establishing ... (‘European Climate Law’)") == (
        "European Climate Law"
    )
    # an amending act ends with the short title of the act it amends
    visa = ("Regulation (EU) 2019/1155 of the European Parliament and of the Council of 20 June 2019 amending "
            "Regulation (EC) No 810/2009 establishing a Community Code on Visas (Visa Code)")  # fmt: skip
    assert act_short_name(visa) is None
    assert act_short_name("Directive (EU) 2024/1799 of 13 June 2024 on common rules promoting the repair of goods") is None


def test_search_docs_label_party_records_by_term():
    # EP open data has one party record per term: same-name records say which term they cover
    from types import SimpleNamespace as NS

    def mep(org, term):
        return NS(memberships=[NS(kind="party", org_id=org, term=term)])

    party = {
        "5369": {"label": "Alternative für Deutschland", "code": "AfD", "country": "DE", "members_active": 0},
        "6802": {"label": "Alternative für Deutschland", "code": "AfD", "country": "DE", "members_active": 15},
        "7000": {"label": "Solo Party", "code": None, "country": "DE", "members_active": 1},
    }
    b = NS(
        dossier_summary={}, proc={}, curated_of={}, acts_of={}, train_of={}, alias_rules=[], mep_summary={},
        group_summaries=[], party_summary=party, s=NS(meps=[mep("5369", 9), mep("6802", 10), mep("7000", 10)]),
        topic_list=[], topics_cur={}, resolve_ref=lambda ref: None,
    )  # fmt: skip
    docs = {d["id"]: d for d in build_search_docs(b) if d["k"] == "party"}
    assert docs["6802"]["s"] == "National party · Germany · 2024–2029 term"
    assert docs["5369"]["s"] == "National party · Germany · 2019–2024 term"
    assert docs["5369"]["w"] < docs["6802"]["w"]
    assert docs["7000"]["s"] == "National party · Germany"
    assert ep_term_label({9, 10}) == "2019–2024 and 2024–2029 terms"


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
        for r in det["status"].get("named_acts") or []:
            _check(r, "NamedAct", ifs, "status.named_acts")
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
    # the official title is kept next to the display title
    assert pl["council_votes"][0]["title"] == cv["title"] == "TEST Regulation on widgets"
    assert pl["council_votes"][0]["display_title"] == "TEST Regulation on widgets"


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


def test_curated_act_dates_replace_cellar_dates(tmp_path: Path):
    """data/curated/act_dates.yaml: dates checked against the act's text replace Cellar's in the build."""
    cur = tmp_path / "curated"
    shutil.copytree(FIX / "curated", cur)
    (cur / "act_dates.yaml").write_text(
        """
- celex: "32099R0001"
  reason: "Cellar records 1 June 2025; Article 99 sets 1 June 2026."
  application:
    - {date: "2026-06-01", partial: false, provisions: "The Regulation in general (Art. 99(2))"}
    - {date: "2027-01-01", partial: true, provisions: "Article 5 (Art. 99(3))"}
  sources:
    - {label: "Regulation 2099/1, Article 99", url: "https://eur-lex.europa.eu/eli/reg/2099/1/oj"}
  reviewed: "2026-10-01"
- celex: "32099L0003"
  application:
    - {date: 2026-01-01}
""",
        encoding="utf-8",
    )
    shutil.copytree(FIX / "snapshot", tmp_path / "snapshot")
    o = tmp_path / "public"
    assert build(out=o, snapshot=tmp_path / "snapshot", curated=cur, state=tmp_path / "state", today=TODAY) == 0
    d = load(o, "dossiers/2099-0001.json")
    app = d["application"]
    assert app["application_dates"] == ["2026-06-01", "2027-01-01"]
    assert app["partial_application_dates"] == ["2027-01-01"]
    assert [(x["date"], x["partial"]) for x in app["application_detail"]] == [("2026-06-01", False), ("2027-01-01", True)]
    assert app["dates_note"]["reason"].startswith("Cellar records 1 June 2025")
    titles = {e["date"]: (e["title"], e["docs"][0]["label"]) for e in d["timeline"] if e["kind"] == "application"}
    assert titles["2026-06-01"] == ("Started to apply: The Regulation in general (Art. 99(2))", "Regulation 2099/1, Article 99")
    assert titles["2027-01-01"][0] == "Starts to apply: Article 5 (Art. 99(3))"
    assert "2025-06-01" not in titles
    # an entry with an unquoted (non-string) date is ignored whole
    assert load(o, "dossiers/2099-0003.json")["application"].get("application_detail") in (None, [])


def test_act_label_from_title():
    from pipeline.build import act_label
    from pipeline.models.entities import LegalAct

    def a(title: str) -> LegalAct:
        return LegalAct(celex="32026R1744", act_type="regulation", title=title, eurlex_url="u",
                        source={"institution": "EUR-Lex", "url": "u", "retrieved_at": "2026-10-22T00:00:00Z"})  # fmt: skip

    assert act_label(a("Regulation (EU) 2026/1744 of the European Parliament and of the Council of 8 July 2026")) == (
        "Regulation (EU) 2026/1744"
    )
    assert act_label(a("Council Decision (EU, Euratom) 2018/994 of 13 July 2018 amending")) == (
        "Council Decision (EU, Euratom) 2018/994"
    )
    assert act_label(a("Something else")) == "32026R1744"


def test_procedure_event_titles_fit_the_procedure():
    from pipeline.build import Builder
    from pipeline.models.entities import DocRef, Event, EventKind, Procedure, SourceRef

    src = SourceRef(institution="EP", url="u", retrieved_at="2026-10-22T00:00:00Z")

    def ev(kind: EventKind, title: str, inst: str = "EP", docs=()) -> Event:
        return Event(id="e", date="2020-01-01", kind=kind, institution=inst, title=title,
                     docs=[DocRef(id=d) for d in docs], source=src)  # type: ignore[arg-type]  # fmt: skip

    def proc(ptype: str) -> Procedure:
        return Procedure(id="2018-0900", reference=f"2018/0900({ptype})", type=ptype, title="t", oeil_url="u", source=src)

    t = lambda p, e: (Builder.procedure_event(p, e).title, Builder.procedure_event(p, e).institution)  # noqa: E731
    assert t(proc("APP"), ev(EventKind.ep_position, "Parliament took its decision (first reading)")) == (
        "Parliament voted on consent", "EP")
    assert t(proc("CNS"), ev(EventKind.ep_position, "Parliament took its decision (first reading)"))[0] == (
        "Parliament delivered its opinion")
    assert t(proc("APP"), ev(EventKind.council_adoption, "Council adopted the act after consulting Parliament",
                             "Council"))[0] == "Council adopted the act after Parliament's consent"  # fmt: skip
    assert t(proc("COD"), ev(EventKind.ep_position, "Parliament took its decision (first reading)"))[0] == (
        "Parliament took its decision (first reading)")
    assert t(proc("APP"), ev(EventKind.proposal, "Commission published its legislative proposal", "Commission",
                             ["09425/2018"])) == ("Council text submitted to Parliament", "Council")  # fmt: skip
    assert t(proc("COD"), ev(EventKind.proposal, "Commission published its legislative proposal", "Commission",
                             ["COM(2021)0206"])) == ("Commission published its legislative proposal", "Commission")  # fmt: skip


def test_council_steps_dated_by_the_council_voting_result():
    """OEIL dates the Council's first-reading position by its publication; the status uses the vote date."""
    from types import SimpleNamespace

    from pipeline.build import Builder
    from pipeline.models.entities import Event, EventKind, Procedure, SourceRef

    src = SourceRef(institution="OEIL", url="u", retrieved_at="2026-10-22T00:00:00Z")
    pos = Event(id="e1", date="2026-10-01", kind=EventKind.council_position, institution="Council",
                title="Council adopted its first-reading position", source=src)  # fmt: skip
    p = Procedure(id="2023-0131", reference="2023/0131(COD)", type="COD", title="t", oeil_url="u", source=src,
                  events=[pos])  # fmt: skip
    me = SimpleNamespace(today="2026-10-22", council_of={"2023-0131": [
        {"date": "2026-09-28", "outcome": "adopted", "vote_on": "first_reading_position"}]})  # fmt: skip
    assert [e.date for e in Builder.council_dated(me, p).events] == ["2026-09-28"]  # type: ignore[arg-type]
    me.council_of["2023-0131"][0]["date"] = "2025-01-01"  # too far apart: a different vote
    assert Builder.council_dated(me, p).events[0].date == "2026-10-01"  # type: ignore[arg-type]


# ------------------------------------------------------------------------------- EP vote labels
# Labels exactly as Parliament published them (data/snapshot/ep_votes/votes.json, by vote id).
LABEL_164581 = (
    "Mise en œuvre de l’accord de partenariat économique (APE) UE-Communauté de développement de l’Afrique "
    "australe (CDAA) - Implementation of the EU-Southern African Development Community (SADC) Economic "
    "Partnership Agreement (EPA) - Umsetzung des Wirtschaftspartnerschaftsabkommens zwischen der EU und der "
    "Entwicklungsgemeinschaft des Südlichen Afrika - A9-0024/2024 - Joachim Schuster - Proposition de "
    "résolution (ensemble du texte)"
)
LABEL_164961 = (
    "Accord de partenariat économique entre l’Union européenne, d’une part, et la République du Kenya, membre "
    "de la Communauté de l’Afrique de l’Est, d’autre part - Economic Partnership Agreement between the European "
    "Union of the one part, and Republic of Kenya, Member of the East African Community of the other Part - "
    "Wirtschaftspartnerschaftsabkommen zwischen der EuropäischenUnion einerseits und der Republik Kenia, "
    "Mitglied der Ostafrikanischen Gemeinschaft, andererseits - A9-0012/2024 - Alessandra Mussolini - Projet "
    "de décision du Conseil"
)
LABEL_129284 = (
    "Orientations pour le budget 2022 - section III - Guidelines for the 2022 Budget - Section III - Leitlinien "
    "für den Haushaltsplan 2022 – Einzelplan III - A9-0046/2021 - Karlo Ressler - Am 19"
)
LABEL_163202 = (
    "Ordre du jour de mercredi - Demande des groupes PPE, S&D, Renew et Verts/ALE - Wednesday’s Agenda - Request "
    "from the PPE, S&D, Renew and Verts/ALE groups - Tagesordnung für Mittwoch - Antrag der Fraktionen PPE, S&D, "
    "Renew und Verts/ALE"
)
LABEL_199407 = (
    "Escalade des attaques des Houthis et implications pour la sécurité régionale - Escalation of Houthi attacks "
    "and implications for regional security - Eskalation der Huthi-Angriffe und Auswirkungen auf die regionale "
    "Sicherheit – Proposition de résolution (ensemble du texte)"
)
LABEL_199559 = (
    "Réduction des émissions de méthane dans le secteur énergétique: report de certaines obligations - "
    "Reduction of methane emissions in the energy sector: postponement of certain obligations - Verringerung "
    "der Methanemissionen im Energiesektor im Hinblick auf die Aufschiebung bestimmter Verpflichtungen – Demande "
    "de renvoi en commission"
)
_AGENDA_165176 = (
    "Ordre du jour de mercredi - Demande du groupe PPE (ajout de déclarations du Conseil et de la Commission) - "
    "Wednesday’s Agenda - Request from the PPE Group (addition of Council and Commission statements) - "
    "Tagesordnung für Mittwoch - Antrag der PPE-Fraktion (Aufnahme von Erklärungen des Rates und der Kommission)"
)
LABEL_165176 = _AGENDA_165176 + _AGENDA_165176  # published twice over, without a separator
LABEL_198292 = "A10-0264/2026 - Jacek Protas - Proposition de résolution"
LABEL_113161 = (
    "Final vote: Draft amending budget No 1/2020: Assistance to Greece in response to increased migration "
    "pressure - Immediate measures in the context of the COVID-19 outbreak - Support to post-earthquake "
    "reconstruction in Albania - Other adjustments C9-0101/2020 - (2020/2052(BUD))"
)


@pytest.mark.parametrize(
    ("label", "english"),
    [
        (LABEL_164581, "Implementation of the EU-Southern African Development Community (SADC) Economic "
                       "Partnership Agreement (EPA)"),
        (LABEL_164961, "Economic Partnership Agreement between the European Union of the one part, and Republic "
                       "of Kenya, Member of the East African Community of the other Part"),
        # a title with " - " of its own: three runs of two segments
        (LABEL_129284, "Guidelines for the 2022 Budget - Section III"),
        (LABEL_163202, "Wednesday’s Agenda - Request from the PPE, S&D, Renew and Verts/ALE groups"),
        # recent labels: no document reference, an en dash before the French tail (or no tail)
        (LABEL_199407, "Escalation of Houthi attacks and implications for regional security"),
        (LABEL_199559, "Reduction of methane emissions in the energy sector: postponement of certain obligations"),
    ],
)  # fmt: skip
def test_english_title_of_a_french_english_german_label(label, english):
    from pipeline.build import english_title

    assert english_title(label) == english


@pytest.mark.parametrize(
    "label",
    [
        LABEL_165176,  # the trilingual title twice over: the runs do not line up, so the label is kept
        LABEL_198292,  # French only
        LABEL_113161,  # English only
        "Implementation report on the EU Trust Funds and the Facility for Refugees in Turkey - A9-0255/2021 - "
        "Milan Zver, György Hölvényi, Janusz Lewandowski - Motion for a resolution (as a whole)",
        "A10-0011/2025 – Nicolás Pascual de la Parte – Motion for a resolution (as a whole)",
        None,
        "",
    ],
)
def test_english_title_leaves_other_labels_alone(label):
    from pipeline.build import english_title

    assert english_title(label) is None


def test_label_parts_mark_french_and_german_passages():
    from pipeline.build import label_parts

    parts = label_parts(LABEL_164581)
    assert "".join(t for _, t in parts) == LABEL_164581
    assert [lang for lang, _ in parts] == ["fr", None, "de", None, "fr"]
    assert parts[1][1].strip(" -").startswith("Implementation of the EU-Southern African")
    assert parts[3][1] == " - A9-0024/2024 - Joachim Schuster - "
    assert parts[4][1] == "Proposition de résolution (ensemble du texte)"
    # a run of several segments keeps its own separators
    assert label_parts(LABEL_129284)[0] == ["fr", "Orientations pour le budget 2022 - section III"]
    assert label_parts(LABEL_198292) == [
        [None, "A10-0264/2026 - Jacek Protas - "],
        ["fr", "Proposition de résolution"],
    ]
    # names, references and English wording are not marked
    for label in (
        LABEL_113161,
        "A9-0024/2020 - Cláudia Monteiro de Aguiar - Consent procedure",
        "A10-0011/2025 – Nicolás Pascual de la Parte – After § 1 – Am 66",
        "A9-0233/2022 - Jörgen Warborn - Amendments by the committee responsible - Am 9",
    ):
        assert label_parts(label) is None


# ------------------------------------------------------------------------------- EP votes (audit regressions)
def _vote(vid: str, date: str, kind: str, outcome: str, counts: tuple, refs: list[str], **kw) -> dict:
    n_for, n_against, n_abstain = counts
    return {
        "attendees": None, "committee": None, "date": date, "doc_ids": [], "event_id": f"TEST-DEC-{vid}",
        "has_ballots": False, "id": vid, "kind": kind, "majority_rule": "votes_cast",
        "method": "VOTE_ELECTRONIC_ROLLCALL", "n_abstain": n_abstain, "n_against": n_against, "n_for": n_for,
        "outcome": outcome, "outcome_basis": "published", "procedure_refs": refs, "reference_text": None,
        "source": {"identifier": vid, "institution": "EP", "label": f"TEST ONLY {vid}", "published": None,
                   "retrieved_at": "2099-01-01T00:00:00Z", "url": f"https://example.invalid/{vid}"},
        "term": 9 if date <= "2024-07-15" else 10, "title": f"TEST label {vid}", **kw,
    }  # fmt: skip


@pytest.fixture(scope="module")
def votes_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The build fixture plus TEST votes for the vote-accuracy rules (lapsed, motions, mandates, majorities)."""
    import pipeline.build as B

    base = tmp_path_factory.mktemp("build-votes")
    shutil.copytree(FIX / "snapshot", base / "snapshot")
    snap = base / "snapshot"
    votes = json.loads((snap / "ep_votes/votes.json").read_text(encoding="utf-8"))
    ballots = json.loads((snap / "ep_votes/ballots.json").read_text(encoding="utf-8"))
    votes += [
        # a whole-text decision that lapsed unheld, dated like the ep_position event and naming its document
        _vote("V9", "2024-04-10", "final", "lapsed", (None, None, None), ["2099/0001(COD)"],
              doc_ids=["TA-9-2099-0001"]),
        # objection to a delegated act outside the tracked files, decided by a majority of component Members
        _vote("V10", "2025-11-26", "motion", "rejected", (359, 188, 76), ["2025/2943(DEA)"],
              majority_rule="component_members", has_ballots=True, kind_detail="objection",
              subject="Objection pursuant to Rule 114(3): amending Delegated Regulation (EU) 2023/2429"),
        # motions to reject the Commission proposal: adopted (the proposal is rejected) and rejected
        _vote("V11", "2025-03-11", "motion", "adopted", (400, 200, 10), ["2099/0003(COD)"], has_ballots=True,
              kind_detail="reject_proposal"),
        _vote("V12", "2025-03-12", "motion", "rejected", (100, 500, 10), ["2099/0003(COD)"], has_ballots=True,
              kind_detail="reject_proposal"),
        # roll call confirming the committee's decision to enter into negotiations
        _vote("V13", "2025-02-10", "procedural", "adopted", (300, 200, 10), ["2099/0003(COD)"], has_ballots=True,
              kind_detail="negotiation_decision"),
        # labels as Parliament published them (votes 199407, 198292 and 113161), no subject, no tracked file
        _vote("V14", "2026-10-22", "resolution", "adopted", (500, 50, 20), ["2026/2939(RSP)"], has_ballots=True,
              title=LABEL_199407),
        _vote("V15", "2026-10-22", "resolution", "adopted", (400, 100, 50), ["2026/2054(INI)"], has_ballots=True,
              title=LABEL_198292),
        _vote("V16", "2020-04-17", "final", "adopted", (600, 50, 30), ["2020/2052(BUD)"], has_ballots=True,
              title=LABEL_113161),
    ]  # fmt: skip
    ballots += [{"abstain": [], "against": [], "favor": ["T1"], "intended_abstain": [], "intended_against": [],
                 "intended_favor": [], "vote_id": vid}
                for vid in ("V10", "V11", "V12", "V13", "V14", "V15", "V16")]  # fmt: skip
    for b in ballots:
        if b["vote_id"] == "V3":
            b["intended_abstain"] = ["T3"]  # T3 has no recorded vote on V3 but stated an intention
    (snap / "ep_votes/votes.json").write_text(json.dumps(votes), encoding="utf-8")
    (snap / "ep_votes/ballots.json").write_text(json.dumps(ballots), encoding="utf-8")
    procs = json.loads((snap / "ep_procedures/procedures.json").read_text(encoding="utf-8"))
    p3 = next(p for p in procs if p["id"] == "2099-0003")
    p3["events"].append({
        "date": "2025-02-10", "detail": None, "docs": [], "id": "2099-0003-ev-neg", "institution": "EP",
        "kind": "negotiation_mandate",
        "raw_type": "def/ep-activities/PLENARY_ENDORSE_COMMITTEE_INTERINSTITUTIONAL_NEGOTIATIONS",
        "source": {"identifier": "2099-0003-ev-neg", "institution": "EP", "label": "TEST ONLY", "published": None,
                   "retrieved_at": "2099-01-01T00:00:00Z", "url": "https://example.invalid/2099-0003-ev-neg"},
        "title": "Parliament confirmed the committee's mandate to negotiate with the Council",
    })  # fmt: skip
    (snap / "ep_procedures/procedures.json").write_text(json.dumps(procs), encoding="utf-8")
    o = base / "public"
    mp = pytest.MonkeyPatch()
    # the fixture has four MEPs; stand in for Parliament's membership records on the day of V10
    mp.setattr(B.Builder, "members_in_office", lambda self, d: 719)
    try:
        assert build(out=o, snapshot=snap, curated=FIX / "curated", state=base / "state", today=TODAY) == 0
    finally:
        mp.undo()
    return o


def test_lapsed_whole_text_vote_is_neither_listed_nor_linked(votes_out: Path):
    idx = {v["id"] for v in load(votes_out, "votes/index.json")}
    assert "V9" not in idx and not (votes_out / "votes/V9.json").exists()
    d1 = load(votes_out, "dossiers/2099-0001.json")
    assert [v["id"] for v in d1["ep_votes"]] == ["V1"]
    assert next(e for e in d1["timeline"] if e["kind"] == "ep_position")["vote_id"] == "V1"


def test_majority_of_component_members_counts_members_in_office(votes_out: Path):
    v10 = load(votes_out, "votes/V10.json")
    # 719 Members in office -> 360 needed (not 361 from the 720 statutory seats): fell 1 vote short
    assert (v10["margin"]["threshold"], v10["margin"]["distance"]) == (360, -1)
    assert v10["margin"]["component_members"] == 719 and v10["margin"]["label"] == "Fell 1 vote short"


def test_component_members_is_withheld_when_membership_records_are_implausible(
    monkeypatch: pytest.MonkeyPatch,
):
    import pipeline.build as B

    b = B.Builder.__new__(B.Builder)
    b.component_cache = {}
    for n, expected in ((719, 719), (721, None), (600, None)):  # 720 seats from 2024-07-16
        b.component_cache.clear()
        monkeypatch.setattr(B.Builder, "members_in_office", lambda self, d, n=n: n)
        assert b.component_members("2025-11-26") == expected


def test_vote_titles_say_what_was_voted_and_name_the_procedure(votes_out: Path):
    v10 = load(votes_out, "votes/V10.json")
    assert (
        v10["display_title"]
        == "Objection pursuant to Rule 114(3): amending Delegated Regulation (EU) 2023/2429"
    )
    assert v10["kind_label"] == "Vote on an objection to a Commission measure"
    assert (
        v10["outcome_note"]
        == "The objection was rejected: Parliament did not object to the Commission measure."
    )
    assert v10["dossier_id"] is None and v10["procedure_ref"] == "2025/2943(DEA)"
    assert v10["procedure_url"].endswith("procedure-file?reference=2025/2943(DEA)")
    v12 = load(votes_out, "votes/V12.json")
    assert v12["display_title"].endswith("— motion to reject the Commission proposal")
    assert v12["kind_label"] == "Vote on a motion to reject the Commission proposal"
    assert (
        v12["outcome_note"] == "The motion was rejected: Parliament did not reject the Commission proposal."
    )


def test_vote_titled_by_its_label_keeps_english_and_the_full_label(votes_out: Path):
    v14 = load(votes_out, "votes/V14.json")
    assert v14["display_title"] == (
        "Escalation of Houthi attacks and implications for regional security — vote on the resolution"
    )
    assert v14["title"] == LABEL_199407 and "display_title_parts" not in v14
    assert [lang for lang, _ in v14["title_parts"]] == ["fr", None, "de", None, "fr"]
    # a French label stays as published, with its French passage marked
    v15 = load(votes_out, "votes/V15.json")
    assert v15["display_title"] == v15["title"] == LABEL_198292
    assert v15["display_title_parts"] == [[None, "A10-0264/2026 - Jacek Protas - "], ["fr", "Proposition de résolution"]]
    idx = {v["id"]: v for v in load(votes_out, "votes/index.json")}
    assert idx["V15"]["display_title_parts"] == v15["display_title_parts"]
    assert "display_title_parts" not in idx["V14"]
    # a very long label is shortened for the heading; the full label stays in `title`
    v16 = load(votes_out, "votes/V16.json")
    assert v16["title"] == LABEL_113161
    assert v16["display_title"] == (
        "Final vote: Draft amending budget No 1/2020: Assistance to Greece in response to increased migration "
        "pressure - Immediate measures in the context of the COVID-19 outbreak - Support to…"
    )
    assert v16["title_parts"] is None


def test_home_rejected_list_reads_rejection_motions_correctly(votes_out: Path):
    lists = {x["id"]: x for x in load(votes_out, "home.json")["lists"]}
    rejected = {i.get("vote_id"): i for i in lists["rejected"]["items"]}
    assert "V12" not in rejected  # the motion to reject failed: the proposal was not rejected
    assert (
        rejected["V11"]["subtitle"]
        == "Parliament adopted the motion and so rejected the Commission proposal."
    )
    assert "V10" in rejected and rejected["V10"]["subtitle"].startswith("The objection was rejected")
    assert all(i.get("vote_id") != "V13" for i in lists["close_votes"]["items"])  # final votes only


def test_negotiation_decision_vote_is_listed_and_linked(votes_out: Path):
    v13 = load(votes_out, "votes/V13.json")
    assert v13["kind"] == "procedural" and v13["kind_detail"] == "negotiation_decision"
    assert v13["kind_label"] == "Vote on the committee's decision to enter into negotiations"
    d3 = load(votes_out, "dossiers/2099-0003.json")
    assert "V13" in [v["id"] for v in d3["ep_votes"]]
    neg = next(e for e in d3["timeline"] if e["id"] == "2099-0003-ev-neg")
    assert neg["vote_id"] == "V13"


def test_stated_intentions_without_a_recorded_vote_are_kept(votes_out: Path):
    v3 = load(votes_out, "votes/V3.json")
    assert [(x["mep"], x["intended"]) for x in v3["intentions"]] == [("T3", "abstain")]
    assert "T3" not in {b["mep"] for b in v3["ballots"]} and "T3" in v3["mep_names"]
    assert load(votes_out, "votes/V1.json")["intentions"] == []


def test_vote_outputs_match_the_contract(votes_out: Path):
    ifs = _interfaces()
    for v in load(votes_out, "votes/index.json"):
        _check(v, "EpVoteSummary", ifs, "votes/index.json")
        det = load(votes_out, f"votes/{v['id']}.json")
        _check(det, "EpVoteDetail", ifs, f"votes/{v['id']}.json")
        if det["margin"]:
            _check(det["margin"], "VoteMargin", ifs, "vote.margin")
        for x in det["intentions"]:
            _check(x, "VoteIntention", ifs, "vote.intentions")


def test_dates_after_the_end_of_validity_are_marked():
    # real EUR-Lex records (tests/fixtures/eurlex/validity_acts.json)
    from pipeline.models.entities import LegalAct

    acts = {
        a["celex"]: LegalAct.model_validate(a)
        for a in json.loads((FIX.parent / "eurlex" / "validity_acts.json").read_text(encoding="utf-8"))
    }
    designs = acts["32024R2822"]  # validity ended 2026-06-30; EUR-Lex: some provisions apply from 2026-07-01
    tl = [
        {"id": "act-32024R2822-entry_into_force-2024-12-08", "date": "2024-12-08"},
        {"id": "act-32024R2822-application-2026-07-01", "date": "2026-07-01"},
        {"id": "ev-2026-07-02", "date": "2026-07-02"},  # not the act's own entry
    ]
    mark_after_end_of_validity(tl, [designs])
    assert [e.get("after_end_of_validity") for e in tl] == [None, "2026-06-30", None]
    # Council Regulation 1377/2014 (18 December 2014): end of validity 2013-12-31, before the act itself
    own = acts["32014R1377"]
    tl = [{"id": "act-32014R1377-entry_into_force-2014-12-24", "date": "2014-12-24"}]
    assert "after_end_of_validity" not in mark_after_end_of_validity(tl, [own])[0]
