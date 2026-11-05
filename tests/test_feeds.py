"""The Atom feeds (pipeline/analysis/feeds.py) and how activity items read (pipeline/analysis/changes.py): full file
titles, a status change told with the step that gave the status, summaries with the status and the next step, one feed
per file, stable entry ids and well-formed Atom with its required elements."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.analysis import changes, feeds
from pipeline.analysis.activity import short_title
from pipeline.build import build

FIX = Path(__file__).parent / "fixtures" / "build"
# within 120 days of the fixture's latest steps (5 November 2024, a vote of 15 January 2025), so that activity.json lists them
TODAY = "2025-01-20"
ATOM = "{http://www.w3.org/2005/Atom}"
SITE = "https://rahv-fb.github.io/eu-intel/"
# 2026/0078(COD) as built on 5 November 2026: the act entered into force on 4 November, which made the file "In force"
LONG = ("Establishing the Programme for agile and rapid defence innovation (AGILE) and amending Regulations (EU) 2021/697 "
        "and (EU) 2023/1525 as regards the financing of defence innovation")  # fmt: skip
SHORT = short_title(LONG)
EUR_LEX = {"institution": "EUR-Lex", "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R2387",
           "label": "EUR-Lex / Cellar – CELEX 32026R2387"}  # fmt: skip
EP_PUB = {"institution": "EP", "url": "https://data.europarl.europa.eu/api/v2/events/2026-0078-PUB-2026-11-03",
          "label": "Machine-readable record (EP Open Data API)"}  # fmt: skip
DETECTED = "2026-11-05T09:26:44Z"


def _item(id: str, date: str, kind: str, title: str, source: dict | None = None, detected: str | None = DETECTED,
          dossier: str | None = "2026-0078", vote: str | None = None) -> dict:  # fmt: skip
    return {"id": id, "date": date, "detected_at": detected, "kind": kind, "title": title, "dossier_id": dossier,
            "vote_id": vote, "source": source}  # fmt: skip


TIMELINE = [
    {"id": "act-32026R2387-signature-2026-10-21", "date": "2026-10-21", "kind": "signature", "state": "done", "key": True,
     "title": "Signed by the Presidents of Parliament and Council"},
    {"id": "2026-0078-PUB-2026-11-03", "date": "2026-11-03", "kind": "publication", "state": "done", "key": True,
     "title": "Final act published in the Official Journal"},
    {"id": "act-32026R2387-entry_into_force-2026-11-04", "date": "2026-11-04", "kind": "entry_into_force", "state": "done",
     "key": True, "title": "Entered into force"},
]  # fmt: skip
STATUS = _item("chg:2026-0078:stage:in_force:2026-11-04", "2026-11-04", "status_change",
               f"{SHORT}: status now “In force” (previously “Published, not yet in force”)", EUR_LEX)  # fmt: skip
ENTRY = _item("chg:2026-0078:ev:act-32026R2387-entry_into_force-2026-11-04", "2026-11-04", "publication",
              f"{SHORT}: Entered into force", EUR_LEX)  # fmt: skip
PUB = _item("chg:2026-0078:ev:2026-0078-PUB-2026-11-03", "2026-11-03", "publication",
            f"{SHORT}: Final act published in the Official Journal", EP_PUB)  # fmt: skip
OTHER_FILE = _item("ev:2025-0542-DEC-ADCP-2026-11-04", "2026-11-04", "milestone",
                   "Union support for internal security: Parliament committee adopted its report",
                   {"institution": "EP", "url": "https://data.europarl.europa.eu/api/v2/events/2025-0542-DEC-ADCP-2026-11-04"},
                   None, "2025-0542")  # fmt: skip
FILES = {
    "2026-0078": {"title": LONG, "status_label": "In force", "ref": "2026/0078(COD)", "timeline": TIMELINE,
                  "next_step": {"text": "The regulation applies directly; no national transposition is needed."}},
    "2025-0542": {"title": "Union support for internal security", "status_label": "Committee decided to negotiate",
                  "ref": "2025/0542(COD)", "timeline": [], "next_step": {"text": "Not available."}},
}  # fmt: skip


def _b() -> SimpleNamespace:
    return SimpleNamespace(dossier_detail=FILES, today="2026-11-05")


def _entries(xml: str) -> list[ET.Element]:
    return ET.fromstring(xml).findall(f"{ATOM}entry")


def _atom(items: list[dict], **kw) -> str:
    return feeds.atom("t", "s", "feeds/updates.xml", items, SITE, "2026-11-05T00:00:00Z", feeds.file_info(_b()), **kw)


# ------------------------------------------------------------------------------- how items read
def test_event_is_the_headline_without_the_file_title():
    assert SHORT.endswith("…") and len(SHORT) <= 110
    assert changes.event_of(ENTRY, LONG) == "Entered into force"
    assert changes.event_of(STATUS, LONG) == "Status now “In force” (previously “Published, not yet in force”)"
    assert changes.event_of(_item("chg:x:new", "2026-11-02", "new_dossier", f"New file: {SHORT}"), LONG) == "New file"
    # a vote's headline names what was voted on, not the file: read whole
    vote = _item("vote:1", "2026-10-21", "ep_vote", "Parliament adopted: Objection pursuant to Rule 115(2)", dossier=None)
    assert changes.event_of(vote, None) is None
    # a motion to reject: what became of the text, and what tells the motion apart
    motion = _item("vote:2", "2026-07-09", "ep_vote", f"Parliament did not reject the Council's position: {SHORT} (amendments 1, 2 and 7)")
    assert changes.event_of(motion, LONG) == "Parliament did not reject the Council's position (amendments 1, 2 and 7)"


def test_a_headline_recorded_under_an_earlier_title_is_read_through_its_step():
    # 2026/0340(COD) was "Asylum and Migration: digitalisation of case management …" when its proposal was recorded on
    # 2 November 2026, and is "Digitalisation of case management …" now: the step it reports says where the title ends
    item = _item("chg:2026-0078:ev:2026-0078-PUB-2026-11-03", "2026-11-03", "publication",
                 "Asylum and Migration: AGILE: Final act published in the Official Journal")  # fmt: skip
    assert changes.event_of(item, LONG, TIMELINE) == "Final act published in the Official Journal"
    assert changes.full_headline(item, LONG, TIMELINE) == f"{LONG}: Final act published in the Official Journal"
    # an earlier title that was shortened ends with "…"
    old = _item("chg:2026-0078:stage:in_force:2026-11-04", "2026-11-04", "status_change", "AGILE old title…: status now “In force”")
    assert changes.full_headline(old, LONG) == f"{LONG}: status now “In force”"
    assert changes.status_parts(old) == ("In force", None)


def test_full_headline_gives_the_file_full_title():
    assert "…" not in changes.full_headline(ENTRY, LONG)
    assert changes.full_headline(ENTRY, LONG) == f"{LONG}: Entered into force"
    assert changes.full_headline(_item("chg:x:new", "2026-11-02", "new_dossier", f"New file: {SHORT}"), LONG) == f"New file: {LONG}"
    assert changes.full_headline(OTHER_FILE, "Union support for internal security") == OTHER_FILE["title"]


def test_a_status_change_is_paired_with_the_step_that_gave_the_status():
    items = changes.annotate([STATUS, ENTRY, PUB, OTHER_FILE], _b())
    by = {i["id"]: i for i in items}
    # the same record cited: the act's entry into force (EUR-Lex), not the day before's publication
    assert by[STATUS["id"]]["step_id"] == ENTRY["id"]
    assert [i["id"] for i in items] == [STATUS["id"], ENTRY["id"], PUB["id"], OTHER_FILE["id"]]  # nothing added or dropped
    assert "step_id" not in by[ENTRY["id"]] and "event" not in STATUS  # copies; the items themselves are unchanged
    # different records of the same step: the EP's record of the publication, the status citing the act's EUR-Lex record
    status = _item("chg:2026-0078:stage:published:2026-11-03", "2026-11-03", "status_change",
                   f"{SHORT}: status now “Published, not yet in force” (previously “Signed, awaiting publication”)", EUR_LEX)  # fmt: skip
    paired = changes.annotate([status, PUB], _b())
    assert paired[0]["step_id"] == PUB["id"]
    # a step of another day, or of a kind that does not date the status, is not its cause
    assert "step_id" not in changes.annotate([status, {**PUB, "date": "2026-11-02"}], _b())[0]
    sign = _item("chg:2026-0078:ev:act-32026R2387-signature-2026-10-21", "2026-11-03", "publication", f"{SHORT}: Signed …")
    assert "step_id" not in changes.annotate([status, sign], _b())[0]


# ------------------------------------------------------------------------------- feeds
def test_feed_titles_are_full_and_a_status_change_is_one_entry_with_its_step():
    items = changes.annotate([STATUS, ENTRY, PUB, OTHER_FILE], _b())
    entries = _entries(_atom(items, as_of="2026-11-05"))
    titles = [e.findtext(f"{ATOM}title") for e in entries]
    assert titles == [
        f"{LONG}: Entered into force — status now “In force”",
        f"{LONG}: Final act published in the Official Journal",
        OTHER_FILE["title"],
    ]
    assert not any("…" in t for t in titles)
    merged = entries[0]
    assert merged.findtext(f"{ATOM}id") == f"{feeds.TAG_BASE}/activity/{STATUS['id']}"
    assert [c.get("term") for c in merged.findall(f"{ATOM}category")] == ["status_change", "publication"]
    assert merged.find(f"{ATOM}link[@rel='via']").get("href") == EUR_LEX["url"]
    assert merged.find(f"{ATOM}link[@rel='alternate']").get("href") == f"{SITE}legislation/2026-0078/"


def test_entry_ids_stay_the_same_and_none_is_new():
    """Feed readers know an entry by its id: telling a status change with its step keeps the status change's id, which
    feeds already published, and mints none (the step's own entry is no longer listed; readers keep their copy)."""
    before = {e.findtext(f"{ATOM}id") for e in _entries(feeds.atom("t", "s", "feeds/updates.xml", [STATUS, ENTRY, PUB, OTHER_FILE], SITE, "x"))}
    after = [e.findtext(f"{ATOM}id") for e in _entries(_atom(changes.annotate([STATUS, ENTRY, PUB, OTHER_FILE], _b())))]
    assert set(after) <= before and len(after) == len(set(after)) == 3
    assert all(i.startswith("tag:rahv-fb.github.io,2026:eu-intel/activity/") for i in after)
    # the same entry has the same id in the site-wide feed and in its file's own feed
    own = feeds.atom("t", "s", "feeds/dossiers/2026-0078.xml", changes.annotate([STATUS, ENTRY, PUB], _b()), SITE, "x",
                     feeds.file_info(_b()), "legislation/2026-0078/", "2026-11-05", feeds.FILE_FEED_LIMIT, state_on_latest=True)  # fmt: skip
    assert [e.findtext(f"{ATOM}id") for e in _entries(own)] == after[:2]


def test_summaries_state_what_happened_the_new_status_and_the_next_step():
    items = changes.annotate([STATUS, ENTRY, OTHER_FILE], _b())
    merged, other = (e.findtext(f"{ATOM}summary") for e in _entries(_atom(items, as_of="2026-11-05")))
    assert merged == (
        "4 November 2026: Entered into force. Status now “In force” (previously “Published, not yet in force”). Next step "
        "as recorded on 5 November 2026: The regulation applies directly; no national transposition is needed."
    )
    # another file: its status as recorded; a next step that says nothing is left out
    assert other == (
        "4 November 2026: Parliament committee adopted its report. Status as recorded on 5 November 2026: “Committee decided "
        "to negotiate”. (Recorded in the official source; detection time not tracked.)"
    )


def test_a_file_feed_states_the_status_and_next_step_on_its_newest_entry_only():
    items = changes.annotate([STATUS, ENTRY, PUB], _b())
    xml = feeds.atom("t", "s", "feeds/dossiers/2026-0078.xml", items, SITE, "x", feeds.file_info(_b()),
                     "legislation/2026-0078/", "2026-11-05", feeds.FILE_FEED_LIMIT, state_on_latest=True)  # fmt: skip
    newest, older = (e.findtext(f"{ATOM}summary") for e in _entries(xml))
    assert "Next step" in newest and "Next step" not in older and "Status as recorded" not in older
    assert ET.fromstring(xml).find(f"{ATOM}link[@rel='alternate']").get("href") == f"{SITE}legislation/2026-0078/"


def test_text_a_feed_cannot_hold_is_left_out():
    bad = {**OTHER_FILE, "title": "Union support\x07 for internal security\x1b: Parliament <committee> & co"}
    root = ET.fromstring(_atom([bad]))
    assert root.find(f"{ATOM}entry/{ATOM}title").text == "Union support for internal security: Parliament <committee> & co"


def test_a_feed_links_only_to_web_addresses_and_text_never_leaves_its_element():
    # The site opens a source's address only if it is http(s) (src/lib/format.ts safeUrl); the feeds linked whatever a
    # record gave: an item with no page on the site linked its source's address as the entry's own link, so a
    # javascript: or data: address from a source was a link in every feed reader.
    breakout = '</title></entry><entry><title>forged</title>"><script>alert(1)</script>'
    no_page = {**OTHER_FILE, "id": "ev:council-x", "dossier_id": None, "title": f"Council vote {breakout}",
               "source": {"institution": "Council", "url": "javascript:alert(document.domain)"}}  # fmt: skip
    via = {**PUB, "source": {**EP_PUB, "url": " JaVa\tScRiPt:alert(1)"}}
    data = {**OTHER_FILE, "source": {"institution": "EP", "url": "data:text/html,<script>alert(1)</script>"}}
    quoted = {**ENTRY, "source": {**EUR_LEX, "url": 'https://eur-lex.europa.eu/x?a="><script>alert(1)</script>'}}
    root = ET.fromstring(_atom([no_page, via, data, quoted]))  # well-formed: nothing broke out of its element
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 4 and [e.findtext(f"{ATOM}title") for e in entries].count("forged") == 0
    assert entries[0].findtext(f"{ATOM}title").endswith(breakout)  # the crafted title is text, as given
    hrefs = [link.get("href") for link in root.iter(f"{ATOM}link")]
    assert all(h.startswith(("https://", "http://")) for h in hrefs), hrefs
    # the entry with no page and no web address links the site; an attribute keeps its quotes and brackets as text
    assert entries[0].find(f"{ATOM}link[@rel='alternate']").get("href") == SITE
    assert entries[0].find(f"{ATOM}link[@rel='via']") is None
    assert entries[3].find(f"{ATOM}link[@rel='via']").get("href") == quoted["source"]["url"]


# ------------------------------------------------------------------------------- the built feeds
@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("feeds")
    shutil.copytree(FIX / "snapshot", base / "snapshot")
    o = base / "public"
    assert build(out=o, snapshot=base / "snapshot", curated=FIX / "curated", state=base / "state", today=TODAY) == 0
    return o


REQUIRED_FEED = ("id", "title", "updated")  # RFC 4287, 4.1.1: atom:feed
REQUIRED_ENTRY = ("id", "title", "updated")  # 4.1.2: atom:entry (atom:author is the feed's)


def _check_atom(path: Path) -> list[str]:
    root = ET.parse(path).getroot()  # well-formed, or ParseError
    assert root.tag == f"{ATOM}feed", path
    for tag in REQUIRED_FEED:
        assert (root.findtext(f"{ATOM}{tag}") or "").strip(), (path, tag)
    assert root.find(f"{ATOM}author/{ATOM}name") is not None, path
    # its own address: data/feeds/… under the site
    assert root.find(f"{ATOM}link[@rel='self']").get("href").endswith("data/" + path.as_posix().rsplit("/public/", 1)[1])
    ids = []
    for e in root.findall(f"{ATOM}entry"):
        for tag in REQUIRED_ENTRY:
            assert (e.findtext(f"{ATOM}{tag}") or "").strip(), (path, tag)
        assert e.find(f"{ATOM}link[@rel='alternate']").get("href").startswith("https://"), path
        ids.append(e.findtext(f"{ATOM}id"))
    assert len(ids) == len(set(ids)), path  # an id once per feed
    return ids


def test_every_built_feed_is_well_formed_atom(out: Path):
    import json

    index = json.loads((out / "dossiers/index.json").read_text(encoding="utf-8"))
    files = sorted((out / "feeds/dossiers").glob("*.xml"))
    # one feed per file, named as its page and its data file are
    assert {f.stem for f in files} == {d["id"] for d in index}
    ids = {}
    for f in [out / "feeds/updates.xml", *sorted((out / "feeds").glob("*.xml")), *files]:
        ids[f] = _check_atom(f)
    # a file's entries are entries of the site-wide feed too, with the same ids
    site_wide = set(ids[out / "feeds/updates.xml"])
    assert site_wide and any(set(v) & site_wide for k, v in ids.items() if k.parent.name == "dossiers")
    feed = ET.parse(files[0]).getroot()
    assert feed.findtext(f"{ATOM}id") == f"{feeds.TAG_BASE}/feeds/dossiers/{files[0].name}"
    assert len(feed.findall(f"{ATOM}entry")) <= feeds.FILE_FEED_LIMIT


def test_activity_json_says_what_happened_without_the_file_title(out: Path):
    import json

    items = json.loads((out / "activity.json").read_text(encoding="utf-8"))
    assert items and any(i.get("event") for i in items)
    for i in items:
        if i.get("event") and i["kind"] not in ("ep_vote", "new_dossier", "status_change"):
            assert i["title"].endswith(f": {i['event']}"), i
        if i.get("step_id"):
            assert i["kind"] == "status_change" and any(j["id"] == i["step_id"] for j in items), i
