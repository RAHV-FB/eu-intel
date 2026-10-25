#!/usr/bin/env python3
"""Politely spot-check official source links published in public/data (optional; not run in CI).

    python scripts/check_links.py                       # sample ~5 URLs per host, max 60
    python scripts/check_links.py --per-host 10 --max 150 --json link-report.json
    python scripts/check_links.py --host eur-lex.europa.eu --fail-on-broken

Every string value that is an http(s) URL anywhere under the data directory is a candidate. URLs are
deduplicated, grouped by host and sampled (seeded by ISO week so successive runs rotate through the set),
then requested one at a time with a per-host delay: HEAD first, falling back to a streamed GET (body not
read) when HEAD is refused or answers 404/410 (some servers, such as the EP Open Data API, answer HEAD with 404).

Classification
  ok            2xx after redirects
  unverifiable  the server answers scripts with a bot challenge instead of the page (EUR-Lex and the
                Council website return 202/403 to non-browser clients, and parts of europarl.europa.eu
                answer 202; also 401/403/429 elsewhere and responses carrying WAF challenge markers).
                Open these in a browser if in doubt; they are NOT counted as broken.
  broken        404/410 (or 400 for a malformed URL) — the link most likely needs fixing at the source
  error         5xx, timeouts, TLS/DNS/connection errors — transient or local; re-run before acting

Exit status is 0 unless --fail-on-broken is given and at least one sampled link is broken.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "eu-intel-linkcheck/0.1 (independent, non-commercial EU legislative explorer; occasional manual "
    "spot-check of published source links; +https://github.com/rahv-fb/eu-intel)"
)
# Hosts known to serve a JavaScript/bot challenge (HTTP 202 or 403) to scripted clients.
CHALLENGE_HOSTS = {
    "eur-lex.europa.eu",
    "www.consilium.europa.eu",
    "consilium.europa.eu",
    "data.consilium.europa.eu",
}
CHALLENGE_HEADERS = ("x-amzn-waf-action", "cf-mitigated", "x-datadome", "x-sucuri-block", "x-iinfo")


@dataclass
class Result:
    url: str
    host: str
    status: str  # ok | unverifiable | broken | error
    code: int | None
    final_url: str | None
    note: str
    found_in: str


def collect(data_dir: Path) -> dict[str, str]:
    """Map each distinct http(s) URL to the first file/JSON path where it occurs."""
    urls: dict[str, str] = {}
    for f in sorted(data_dir.rglob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"warning: cannot read {f}: {e}", file=sys.stderr)
            continue
        rel = f.relative_to(data_dir).as_posix()
        stack: list[tuple[object, str]] = [(doc, "$")]
        while stack:
            v, path = stack.pop()
            if isinstance(v, dict):
                stack.extend((x, f"{path}.{k}") for k, x in v.items())
            elif isinstance(v, list):
                stack.extend((x, f"{path}[{i}]") for i, x in enumerate(v))
            elif isinstance(v, str) and v.startswith(("http://", "https://")):
                urls.setdefault(v.strip(), f"{rel}:{path}")
    return urls


def sample(urls: dict[str, str], per_host: int, max_total: int, seed: int, hosts: set[str]) -> list[str]:
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in sorted(urls):
        h = (urlsplit(u).hostname or "").lower()
        if not hosts or h in hosts:
            by_host[h].append(u)
    rng = random.Random(seed)
    picked = {h: rng.sample(us, min(per_host, len(us))) for h, us in sorted(by_host.items())}
    out: list[str] = []
    # Round-robin across hosts so --max never starves a host.
    for i in range(per_host):
        for h in sorted(picked):
            if i < len(picked[h]):
                out.append(picked[h][i])
    return out[:max_total]


def looks_like_challenge(r: httpx.Response) -> bool:
    if any(h in r.headers for h in CHALLENGE_HEADERS):
        return True
    if r.status_code == 202 and int(r.headers.get("content-length") or 0) < 2048:
        return True
    return False


def classify(url: str, r: httpx.Response) -> tuple[str, str]:
    host = (urlsplit(url).hostname or "").lower()
    code = r.status_code
    if code == 202 and (host in CHALLENGE_HOSTS or looks_like_challenge(r)):
        return "unverifiable", "bot challenge (202) instead of content"
    if 200 <= code < 300:
        return "ok", ""
    if code in (401, 403, 429) or (code == 503 and looks_like_challenge(r)):
        why = (
            "bot challenge"
            if host in CHALLENGE_HOSTS or looks_like_challenge(r)
            else "access refused to scripts"
        )
        return "unverifiable", f"{why} ({code})"
    if code in (404, 410):
        return "broken", "not found"
    if code == 400:
        return "broken", "bad request (malformed URL?)"
    if code >= 500:
        return "error", "server error (retry later)"
    return "error", f"unexpected status {code}"


def check(client: httpx.Client, url: str) -> tuple[int | None, str | None, str, str]:
    try:
        r = client.head(url)
        if r.status_code in (403, 404, 405, 410, 501):
            # Some servers reject HEAD (or only allow GET for scripts), and the EP Open Data API answers HEAD with
            # 404 for records it serves to GET: retry with GET, body not downloaded.
            time.sleep(0.5)
            with client.stream("GET", url) as g:
                r = g
        status, note = classify(url, r)
        return r.status_code, str(r.url), status, note
    except httpx.TooManyRedirects:
        return None, None, "error", "too many redirects"
    except httpx.TimeoutException:
        return None, None, "error", "timeout"
    except httpx.HTTPError as e:
        return None, None, "error", type(e).__name__ + ": " + str(e)[:120]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--data", type=Path, default=ROOT / "public" / "data", help="data directory (default public/data)"
    )
    p.add_argument("--per-host", type=int, default=5, help="URLs sampled per host (default 5)")
    p.add_argument("--max", type=int, default=60, help="maximum URLs checked in total (default 60)")
    p.add_argument("--seed", type=int, default=None, help="sampling seed (default: ISO year*100+week)")
    p.add_argument("--host", action="append", default=[], help="only check this host (repeatable)")
    p.add_argument("--delay", type=float, default=1.5, help="seconds between requests to the same host")
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--json", type=Path, help="write the full report as JSON")
    p.add_argument("--fail-on-broken", action="store_true", help="exit 1 when a sampled link is broken")
    a = p.parse_args(argv)

    if not a.data.is_dir():
        print(f"{a.data} not found: run `python -m pipeline build` first", file=sys.stderr)
        return 2
    urls = collect(a.data)
    iso = date.today().isocalendar()
    seed = a.seed if a.seed is not None else iso.year * 100 + iso.week
    todo = sample(urls, a.per_host, a.max, seed, {h.lower() for h in a.host})
    hosts = {urlsplit(u).hostname for u in urls}
    print(f"{len(urls)} distinct URLs on {len(hosts)} hosts; checking {len(todo)} (seed {seed})\n")

    insecure = sorted(u for u in urls if u.startswith("http://"))
    results: list[Result] = []
    last: dict[str, float] = {}
    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        follow_redirects=True,
        max_redirects=10,
        timeout=httpx.Timeout(a.timeout, connect=10.0),
    ) as client:
        for u in todo:
            host = (urlsplit(u).hostname or "").lower()
            wait = a.delay - (time.monotonic() - last.get(host, -1e9))
            if wait > 0:
                time.sleep(wait)
            code, final, status, note = check(client, u)
            last[host] = time.monotonic()
            res = Result(u, host, status, code, final, note, urls[u])
            results.append(res)
            print(f"{status:<12} {code or '---':>3}  {u}" + (f"  [{note}]" if note else ""))

    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        counts[r.host][r.status] += 1
    print("\nSummary by host (ok / unverifiable / broken / error):")
    for h in sorted(counts):
        c = counts[h]
        print(f"  {h:<40} {c['ok']:>3} / {c['unverifiable']:>3} / {c['broken']:>3} / {c['error']:>3}")
    broken = [r for r in results if r.status == "broken"]
    if broken:
        print("\nBroken links (where they appear in the data):")
        for r in broken:
            print(f"  {r.code} {r.url}\n      in {r.found_in}")
    if insecure:
        print(f"\n{len(insecure)} URL(s) use plain http:// (prefer https), e.g. {insecure[0]}")
    if a.json:
        a.json.write_text(
            json.dumps(
                {"seed": seed, "candidates": len(urls), "results": [asdict(r) for r in results]},
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nreport written to {a.json}")
    return 1 if (a.fail_on_broken and broken) else 0


if __name__ == "__main__":
    sys.exit(main())
