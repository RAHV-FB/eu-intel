"""Schema and editorial-rule checks for data/curated/{featured,topics,aliases}.yaml."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

CURATED = Path(__file__).resolve().parent.parent / "data" / "curated"

FEATURED_KEYS = {
    "id",
    "reference",
    "celex",
    "short_title",
    "what",
    "why",
    "aliases",
    "topics",
    "featured",
    "feature_order",
    "sources",
    "reviewed",
}
TOPICS = {
    "tech": "Technology & AI",
    "economy": "Economy & Trade",
    "environment": "Environment & Energy",
    "migration": "Migration & Borders",
    "agriculture": "Agriculture & Food",
    "rights": "Rights & Justice",
    "security": "Security & Defence",
    "transport": "Transport",
    "social": "Employment & Social Policy",
    "health": "Health & Consumers",
}
# Evaluative or promotional wording not allowed in what/why (docs/EDITORIAL.md, "Writing standards").
BANNED_WORDS = [
    "landmark",
    "groundbreaking",
    "ground-breaking",
    "historic",
    "revolutionary",
    "game-changer",
    "game changer",
    "controversial",
    "draconian",
    "flagship",
    "ambitious",
    "crucial",
    "unprecedented",
    "world-first",
    "world first",
]
# Status / next-step wording that belongs to computed data, not to curated text.
STATUS_WORDS = [
    "in force",
    "entered into force",
    "was adopted",
    "has been adopted",
    "next step",
    "is expected to",
    "will be voted",
]

# EP process ids may carry a split suffix, e.g. "2016-0224A" / "2016/0224A(COD)".
ID_RE = re.compile(r"^\d{4}-\d{4}[A-Z]?$")
REF_RE = re.compile(r"^(\d{4})/(\d{4}[A-Z]?)\(([A-Z]{3})\)$")
SNAPSHOT_PROCEDURES = CURATED.parent / "snapshot" / "ep_procedures" / "procedures.json"
CELEX_RE = re.compile(r"^3\d{4}[RLD]\d{4}$")


def load(name: str):
    return yaml.safe_load((CURATED / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def featured() -> list[dict]:
    return load("featured.yaml")


@pytest.fixture(scope="module")
def topics() -> list[dict]:
    return load("topics.yaml")


# ------------------------------------------------------------------------------ featured.yaml


def test_featured_size_and_keys(featured):
    assert 20 <= len(featured) <= 30
    for item in featured:
        assert set(item) == FEATURED_KEYS, item.get("id")


def test_featured_ids_unique_and_consistent(featured):
    ids = [i["id"] for i in featured]
    assert len(ids) == len(set(ids))
    for item in featured:
        assert ID_RE.match(item["id"]), item["id"]
        m = REF_RE.match(item["reference"])
        assert m, item["reference"]
        assert f"{m.group(1)}-{m.group(2)}" == item["id"]


def test_featured_celex(featured):
    for item in featured:
        assert isinstance(item["celex"], list)
        for c in item["celex"]:
            assert CELEX_RE.match(c), (item["id"], c)


def _is_withdrawn_text(item: dict) -> bool:
    return item["what"].startswith("The Commission proposed") and "withdrew" in item["what"]


def test_proposals_are_described_as_proposals(featured):
    for item in featured:
        if not item["celex"]:
            if _is_withdrawn_text(item):
                # withdrawn proposals are described in the past tense and cite the withdrawal notice
                assert item["why"].startswith("The proposal did not become law"), item["id"]
                assert any("Withdrawal of Commission proposals" in s["label"] for s in item["sources"]), item[
                    "id"
                ]
            else:
                assert item["what"].startswith("Proposal would"), item["id"]
                assert item["why"].startswith("If adopted"), item["id"]
        else:
            assert not item["what"].lower().startswith("proposal"), item["id"]


def test_featured_ids_match_ep_snapshot(featured):
    # Offline cross-check against the EP procedure snapshot, when present: the id must be the
    # procedure that records the final act (split procedures carry their own id, e.g. 2016-0224A).
    if not SNAPSHOT_PROCEDURES.exists():
        pytest.skip("no ep_procedures snapshot")
    procs = {p["id"]: p for p in json.loads(SNAPSHOT_PROCEDURES.read_text(encoding="utf-8"))}
    for item in featured:
        if item["id"] not in procs:
            continue  # the snapshot may not cover every procedure; the live test checks existence
        p = procs[item["id"]]
        assert p["reference"] == item["reference"], item["id"]
        if p.get("celex_refs") and item["celex"]:
            assert set(item["celex"]) <= set(p["celex_refs"]), (item["id"], p["celex_refs"])


def test_oeil_sources_match_reference(featured):
    for item in featured:
        for s in item["sources"]:
            if "oeil.europarl.europa.eu" in s["url"]:
                assert s["url"].endswith("reference=" + item["reference"]), (item["id"], s["url"])


def test_featured_text_is_neutral_and_free_of_status(featured):
    for item in featured:
        text = f"{item['what']} {item['why']}".lower()
        for w in BANNED_WORDS:
            assert w not in text, (item["id"], w)
        for w in STATUS_WORDS:
            assert w not in text, (item["id"], w)
        for field in ("what", "why"):
            n_words = len(item[field].split())
            assert 10 <= n_words <= 75, (item["id"], field, n_words)


def test_homepage_selection(featured):
    feats = [i for i in featured if i["featured"] is True]
    assert 5 <= len(feats) <= 6
    assert sorted(i["feature_order"] for i in feats) == list(range(1, len(feats) + 1))
    for i in featured:
        assert isinstance(i["featured"], bool)
        if not i["featured"]:
            assert i["feature_order"] is None, i["id"]
    # mixed states: at least one adopted act and one pending proposal on the homepage
    assert any(i["celex"] for i in feats) and any(not i["celex"] for i in feats)


def test_featured_topics_exist(featured, topics):
    slugs = {t["slug"] for t in topics}
    for item in featured:
        assert item["topics"], item["id"]
        assert set(item["topics"]) <= slugs, item["id"]


def test_featured_sources_and_review(featured):
    for item in featured:
        assert item["sources"], item["id"]
        for s in item["sources"]:
            assert set(s) == {"label", "url"}, item["id"]
            assert s["label"].strip()
            assert s["url"].startswith("https://"), s["url"]
            assert re.match(r"https://[a-z0-9.-]*europa\.eu/|https://www\.bundestag\.de/", s["url"]), s["url"]
        date.fromisoformat(item["reviewed"])
        # adopted acts cite the act itself
        for c in item["celex"]:
            year, num = int(c[1:5]), int(c[6:])
            kind = {"R": "reg", "L": "dir", "D": "dec"}[c[5]]
            assert any(f"/eli/{kind}/{year}/{num}/oj" in s["url"] for s in item["sources"]), (item["id"], c)


def test_featured_aliases(featured):
    for item in featured:
        assert item["aliases"], item["id"]
        assert all(isinstance(a, str) and a.strip() == a and a for a in item["aliases"]), item["id"]
        assert len({a.lower() for a in item["aliases"]}) == len(item["aliases"]), item["id"]


def test_contested_alias_is_documented():
    # A contested common name may only be attached with a justification comment in the YAML.
    raw = (CURATED / "featured.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s*#.*\"chat control\".*$", raw, re.M)


# -------------------------------------------------------------------------------- topics.yaml


def test_topics_exact(topics):
    assert {t["slug"]: t["label"] for t in topics} == TOPICS
    for t in topics:
        assert set(t) == {"slug", "label", "description", "ep_subjects", "search_aliases"}
        assert t["description"].strip() and "\n" not in t["description"]
        assert t["ep_subjects"] and t["search_aliases"]
        for code in t["ep_subjects"]:
            assert re.match(r"^\d(\.\d{2}){0,3}$", code), (t["slug"], code)


# ------------------------------------------------------------------------------- aliases.yaml


def test_aliases_shape():
    aliases = load("aliases.yaml")
    assert aliases
    seen: set[str] = set()
    procedures: set[str] = set()
    for entry in aliases:
        if "procedure" in entry:
            # names of one legislative file
            assert set(entry) == {"procedure", "names"}
            assert re.fullmatch(r"\d{4}/\d{4}[A-Z]?\([A-Z]{3}\)", entry["procedure"]), entry["procedure"]
            assert entry["procedure"] not in procedures, f"duplicate entry for {entry['procedure']}"
            procedures.add(entry["procedure"])
            assert entry["names"], entry["procedure"]
            assert all(isinstance(n, str) and n and n.strip() == n for n in entry["names"]), entry["procedure"]
            assert len({n.lower() for n in entry["names"]}) == len(entry["names"]), entry["procedure"]
            continue
        assert set(entry) == {"terms", "expands_to"}
        assert entry["terms"] and entry["expands_to"]
        for t in entry["terms"] + entry["expands_to"]:
            assert t == t.lower().strip() and t, t
        for t in entry["terms"]:
            assert t not in seen, f"duplicate alias term {t!r}"
            seen.add(t)


def test_file_names_cite_official_sources():
    # Every {procedure, names} entry is preceded by "# source:" comments citing an official page
    # (EUR-Lex, Commission, Parliament / Legislative Train) that uses the names for that file.
    lines = (CURATED / "aliases.yaml").read_text(encoding="utf-8").splitlines()
    entries = [i for i, line in enumerate(lines) if re.match(r"^- \{procedure:", line)]
    assert entries
    for i in entries:
        j = i - 1
        cited = []
        while j >= 0 and (lines[j].startswith("# source:") or lines[j].startswith("- {procedure:")):
            if lines[j].startswith("# source:"):
                cited.append(lines[j])
            j -= 1
        assert cited, f"no source comment for: {lines[i]}"
        for c in cited:
            assert re.match(r"# source: https://[a-z0-9.-]*europa\.eu/", c), c


# ----------------------------------------------------------------------------- live (opt-in)


@pytest.mark.network
def test_featured_ids_exist_in_ep_api(featured):
    from pipeline.http import EP_API, default_http

    http = default_http()
    for item in featured:
        d = http.get_json(f"{EP_API}/procedures/{item['id']}?format=application%2Fld%2Bjson")
        assert d["data"][0]["process_id"] == item["id"]
