"""scripts/prerender-routes.mjs on crafted data. The page shells it writes carry text from the sources (a file's title and
reference, a vote's title, a name, a topic) in <title>, the meta description and the feed link's title: that text must
stay text, whatever it holds. The ids it writes them under come from the sources too: none may write outside dist/."""

from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "prerender-routes.mjs"
SITE = "EU Legislative Intelligence"
SHELL = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>EU Legislative Intelligence</title>
    <meta name="description" content="Site description." />
    <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'" />
    <link rel="icon" href="data:image/svg+xml,%3Csvg%3E%3C/svg%3E" />
    <link rel="alternate" type="application/atom+xml" title="EU legislation updates" href="/eu-intel/data/feeds/updates.xml" />
    <script type="module" crossorigin src="/eu-intel/assets/index.js"></script>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
"""
# each tries to leave the text it is put in: an element, a double- or single-quoted attribute, a comment; or to be read
# as a replacement pattern by String.prototype.replace; or to be unescaped twice
BREAKOUTS = [
    "</title><script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "' onmouseover='alert(1)",
    "$& $' $` $$ $1 $<n>",
    "&amp; &lt;b&gt; &#34;",
    '<!-- </head><meta http-equiv="refresh" content="0;url=https://evil.example/">',
]


class Page(HTMLParser):
    """The elements of a page, in order, with their attributes, and the text of its <title>."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.titles: list[str] = []
        self._in_title = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        if tag == "title":
            self._in_title = True
            self.titles.append("")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.titles[-1] += data

    def handle_comment(self, data):
        self.elements.append(("!--", {"text": data}))

    def first(self, tag: str, **attrs: str) -> dict[str, str | None]:
        found = [a for t, a in self.elements if t == tag and all(a.get(k) == v for k, v in attrs.items())]
        assert len(found) == 1, (tag, attrs, found)
        return found[0]


def prerender(tmp_path: Path, data: dict[str, object], site_url: str = "https://example.org/eu-intel") -> tuple[Path, int, str]:
    """Run the script in a directory holding a built shell and `data` (paths under dist/data); returns dist/."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    work = tmp_path / "work"
    dist = work / "dist"
    (dist / "data").mkdir(parents=True)
    (dist / "index.html").write_text(SHELL, encoding="utf-8")
    (work / "src" / "lib").mkdir(parents=True)
    shutil.copy(ROOT / "src" / "lib" / "format.ts", work / "src" / "lib" / "format.ts")  # the country names it reads
    for rel, value in data.items():
        (dist / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
        (dist / "data" / rel).write_text(json.dumps(value), encoding="utf-8")
    r = subprocess.run(["node", str(SCRIPT)], cwd=work, capture_output=True, text=True, env={"PATH": shutil.os.environ["PATH"], "SITE_URL": site_url})
    return dist, r.returncode, r.stdout + r.stderr


def crafted(text: str) -> dict[str, object]:
    return {
        "dossiers/index.json": [{"id": "2099-0001", "title": f"Act {text}", "ref": f"2099/0001(COD) {text}", "status_label": "x",
                                 "short": f"Short {text}"}],
        "votes/index.json": [{"id": "1", "display_title": f"Vote {text}", "date": "2026-10-22", "for": 3, "against": 2,
                              "abstain": 1, "kind_label": text}],
        "people/meps.json": [{"id": "2", "name": f"Name {text}", "active": True, "country": "FI"}],
        "people/groups.json": [{"id": "g", "code": "G", "name": f"Group {text}", "active": True, "terms": [10]}],
        "people/parties/3.json": {"id": "3", "label": f"Party {text}", "country": "AT", "terms": [10]},
        "countries/index.json": [{"code": "AT", "name": f"Country {text}"}],
        "topics.json": [{"slug": "tech", "label": f"Topic {text}"}],
    }  # fmt: skip


@pytest.mark.parametrize("text", BREAKOUTS)
def test_text_from_a_source_stays_text_in_every_page_shell(tmp_path, text):
    dist, code, out = prerender(tmp_path, crafted(text))
    assert code == 0, out
    shell = Page(SHELL)
    pages = {
        "legislation/2099-0001": (f"Act {text} (2099/0001(COD) {text}) – {SITE}", f"Short {text}"),
        "votes/1": (f"Vote {text} (22 Oct 2026) – {SITE}", "European Parliament vote of 22 Oct 2026: 3 for, 2 against, 1 abstention."),
        "people/meps/2": (f"Name {text} – {SITE}", None),
        "people/groups/g": (f"G – Group {text} – {SITE}", None),
        "people/parties/3": (f"Party {text} (Austria) – {SITE}", None),
        "countries/AT": (f"Country {text} – {SITE}", f"Country {text} in the EU: MEPs, Council votes and implementation of EU law."),
    }  # fmt: skip
    for route, (title, description) in pages.items():
        page = Page((dist / route / "index.html").read_text(encoding="utf-8"))
        assert page.titles == [title], route
        if description:
            assert page.first("meta", name="description")["content"] == description, route
        # nothing but the shell's elements, the canonical link and (a file's page) its feed link
        added = [e for e in page.elements if e not in shell.elements and e[0] != "title" and e[1].get("name") != "description"]
        canonical = ("link", {"rel": "canonical", "href": f"https://example.org/eu-intel/{route}/"})
        feed = ("link", {"rel": "alternate", "type": "application/atom+xml", "id": "page-feed",
                         "title": f"2099/0001(COD) {text}: updates (Atom)", "href": "/eu-intel/data/feeds/dossiers/2099-0001.xml"})  # fmt: skip
        assert added == ([canonical, feed] if route.startswith("legislation/") else [canonical]), (route, added)
    redirect = Page((dist / "topics" / "tech" / "index.html").read_text(encoding="utf-8"))
    assert redirect.titles == [f"Topic {text} – Legislation – {SITE}"]
    assert [t for t, _ in redirect.elements].count("script") == 0
    assert redirect.first("meta", **{"http-equiv": "refresh"})["content"] == "0; url=../../legislation/?topic=tech"


def ids_with(kind: str, bad: str) -> dict[str, object]:
    data = crafted("x")
    if kind == "dossier":
        data["dossiers/index.json"][0]["id"] = bad
    elif kind == "vote":
        data["votes/index.json"][0]["id"] = bad
    elif kind == "mep":
        data["people/meps.json"][0]["id"] = bad
    elif kind == "group":
        data["people/groups.json"][0]["id"] = bad
    elif kind == "party":
        data["people/parties/3.json"]["id"] = bad
    elif kind == "country":
        data["countries/index.json"][0]["code"] = bad
    elif kind == "topic":
        data["topics.json"][0]["slug"] = bad
    return data


@pytest.mark.parametrize("kind", ["dossier", "vote", "mep", "group", "party", "country", "topic"])
@pytest.mark.parametrize("bad", ["../../../escaped", "..", "/tmp/escaped-abs", "a/../../../../escaped"])
def test_an_id_from_a_source_cannot_write_outside_dist(tmp_path, kind, bad):
    if bad.startswith("/"):
        bad = str(tmp_path / "escaped-abs")
    dist, code, out = prerender(tmp_path, ids_with(kind, bad))
    outside = [p for p in tmp_path.rglob("index.html") if dist not in p.parents]
    assert outside == [], outside
    # and the build stops, naming the id, rather than leave that page out
    assert code != 0 and "not a safe path segment" in out, out
    # nor did it overwrite a page of the site itself (".." under legislation/ is legislation/../index.html)
    assert not (dist / "index.html").read_text(encoding="utf-8").count("Act x")
