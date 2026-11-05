"""scripts/check_privacy.mjs, the gate behind the site's "no third-party requests" promise (/privacy), on crafted builds:
what it must refuse (a request to another origin, in each form a build can make one) and what it must let through
(plain links to official sources)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "check_privacy.mjs"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'"
)


def page(head: str = "", body: str = "", csp: str | None = CSP) -> str:
    meta = f'<meta http-equiv="Content-Security-Policy" content="{csp}" />' if csp is not None else ""
    return (
        f'<!doctype html><html lang="en"><head><meta charset="UTF-8" />{meta}<title>t</title>'
        f'<script type="module" crossorigin src="/eu-intel/assets/index.js"></script>'
        f'<link rel="stylesheet" crossorigin href="/eu-intel/assets/index.css">{head}</head>'
        f'<body><div id="root"></div>{body}</body></html>'
    )


def check(tmp_path: Path, files: dict[str, str]) -> tuple[int, str]:
    """Run the check on a build made of `files` (paths under dist/ or src/), from a directory with nothing else."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    work = tmp_path / "site"
    base = {"dist/index.html": page(), "dist/assets/index.js": "console.log(1);", "dist/assets/index.css": "a{color:red}",
            "src/main.tsx": "export {};"}  # fmt: skip
    for name, text in (base | files).items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(text, encoding="utf-8")
    r = subprocess.run(["node", str(CHECK), "--dist", "dist", "--src", "src"], cwd=work, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_a_clean_build_passes(tmp_path):
    code, out = check(tmp_path, {
        # links to official sources are fine: following one is the reader's choice
        "dist/legislation/x/index.html": page(body='<a href="https://eur-lex.europa.eu/eli/reg/2024/1689/oj">EUR-Lex</a>'),
        "dist/assets/a.js": 'p.jsx("a",{href:"https://eur-lex.europa.eu/x",target:"_blank",rel:"noopener noreferrer"});'
                            'fetch(`${base}data/meta.json`);var Qv=new URL("http://localhost");',
        # a data block is not a script (CSP does not apply to it)
        "dist/about/index.html": page(head='<script type="application/ld+json">{"@context":"https://schema.org"}</script>'),
    })  # fmt: skip
    assert code == 0, out


THIRD_PARTY = [
    # a remote font
    ("font in CSS", {"dist/assets/a.css": '@font-face{font-family:x;src:url(https://fonts.example.org/x.woff2) format("woff2")}'},
     "third-party url() in CSS"),
    ("font @import", {"dist/assets/a.css": '@import "https://fonts.example.org/css2?family=Inter";'}, "third-party @import"),
    # a remote image
    ("img in HTML", {"dist/index.html": page(body='<img src="https://img.example.org/a.png" alt="">')}, "third-party URL in <img>"),
    ("img in the bundle", {"dist/assets/a.js": 'p.jsx("img",{src:"https://img.example.org/a.png",alt:""})'},
     "resource element with a third-party URL"),
    ("image beacon", {"dist/assets/a.js": '(new Image).src="https://t.example.org/p.gif?u="+u'}, "third-party URL assigned to .src"),
    # prefetch, preconnect: the CSP governs neither preconnect nor dns-prefetch, so this check is all that stops them
    ("preconnect in HTML", {"dist/index.html": page(head='<link rel="preconnect" href="https://cdn.example.org">')},
     "third-party URL in <link>"),
    ("dns-prefetch in HTML", {"dist/index.html": page(head='<link rel="dns-prefetch" href="//cdn.example.org">')},
     "third-party URL in <link>"),
    ("prefetch in HTML", {"dist/index.html": page(head='<link rel="prefetch" href="https://cdn.example.org/x.js">')},
     "third-party URL in <link>"),
    ("preconnect element in the bundle", {"dist/assets/a.js": 'p.jsx("link",{rel:"preconnect",href:"https://cdn.example.org"})'},
     "resource element with a third-party URL"),
    ("React preconnect()", {"dist/assets/a.js": 'Se.preconnect("https://cdn.example.org",{crossOrigin:""})'},
     "resource hint to a third-party URL"),
    ("React prefetchDNS()", {"dist/assets/a.js": 'o.prefetchDNS("https://cdn.example.org")'}, "resource hint to a third-party URL"),
    ("React preload()", {"dist/assets/a.js": 'o.preload("https://cdn.example.org/f.woff2",{as:"font"})'},
     "resource hint to a third-party URL"),
    ("React preinit()", {"dist/assets/a.js": 'o.preinit("https://cdn.example.org/x.js",{as:"script"})'},
     "resource hint to a third-party URL"),
    ("preconnect() in the source", {"src/x.tsx": 'import { preconnect } from "react-dom";\npreconnect("https://cdn.example.org");'},
     "resource hint to a third-party URL"),
    # a fetch to another origin
    ("fetch()", {"dist/assets/a.js": 'fetch("https://api.example.org/x")'}, "fetch() to a literal third-party URL"),
    ("fetch(new URL())", {"dist/assets/a.js": 'fetch(new URL("https://api.example.org/x"))'}, "fetch() to a literal third-party URL"),
    ("new Request()", {"dist/assets/a.js": 'fetch(new Request("https://api.example.org/x",{method:"POST"}))'},
     "fetch() to a literal third-party URL"),
    ("XMLHttpRequest", {"dist/assets/a.js": 'x.open("GET","https://api.example.org/x")'}, "XMLHttpRequest to a third-party URL"),
    ("sendBeacon", {"dist/assets/a.js": 'navigator.sendBeacon("/x",d)'}, "navigator.sendBeacon"),
]  # fmt: skip


@pytest.mark.parametrize(("case", "files", "rule"), THIRD_PARTY, ids=[c[0] for c in THIRD_PARTY])
def test_a_request_to_another_origin_fails_the_check(tmp_path, case, files, rule):
    code, out = check(tmp_path, files)
    assert code == 1 and rule in out, out


CSP_BLOCKED = [
    # what the page's CSP would refuse in the browser, silently: the build must not ship it, nor loosen the policy for it
    ("inline script", page(body="<script>window.x=1</script>"), "inline script (blocked by the CSP)"),
    ("inline module script", page(body='<script type="module">import("./a.js")</script>'), "inline script (blocked by the CSP)"),
    ("inline event handler", page(body='<img src="a.png" alt="" onerror="x()">'), "inline event handler (blocked by the CSP)"),
    ("javascript: URL", page(body='<a href="javascript:void(0)">x</a>'), "javascript: URL (blocked by the CSP)"),
    ("inline style", page(body='<p style="color:red">x</p>'), "inline style (blocked by the CSP)"),
    ("no CSP", page(csp=None), "missing Content-Security-Policy"),
    ("unsafe-inline", page(csp=CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")), "allows 'unsafe-inline'"),
    ("a third-party script source", page(csp=CSP.replace("script-src 'self'", "script-src 'self' https://cdn.example.org")),
     "allows a non-self source"),
    # a <meta> policy covers only what comes after it in the document
    ("CSP after a script", page().replace('<meta http-equiv="Content-Security-Policy"', '<script src="/a.js"></script><meta http-equiv="Content-Security-Policy"'),
     "Content-Security-Policy <meta> after"),
]  # fmt: skip


@pytest.mark.parametrize(("case", "html", "rule"), CSP_BLOCKED, ids=[c[0] for c in CSP_BLOCKED])
def test_what_the_csp_blocks_fails_the_check(tmp_path, case, html, rule):
    code, out = check(tmp_path, {"dist/404.html": html})
    assert code == 1 and rule in out, out
