"""European Parliament plenary votes with individual roll-call ballots (EP Open Data API v2).

Work in progress: fetching layer only (classification and output added below).
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pipeline.http import EP_API, Http

SOURCE_ID = "ep_votes"
FMT = {"format": "application/ld+json"}
FIRST_SITTING = "2019-07-02"  # first sitting of the 9th term
WORKERS = 2  # the API is shared with other sources and allows 500 requests / 5 min per endpoint
MIN_GAP_S = 1.5  # per worker, between two requests that actually hit the network
FRESH_DAYS = 30  # sittings this recent are always re-fetched (late corrections, newly published votes)
PROCESS_TYPES = (
    "ACI APP AVC BUD CNS COD DEC NLE SYN BUI COS DEA DCE IMM INI INL INS REG RPS RSO RSP GBD".split()
)


class _Pacer:
    """Keeps each worker under MIN_GAP_S between network requests; cache hits are not slowed down."""

    def __init__(self, gap_s: float):
        self.gap_s = gap_s
        self._local = threading.local()

    def get(self, http: Http, url: str, **kw: Any) -> bytes:
        last = getattr(self._local, "last", 0.0)
        t0 = time.monotonic()
        body = http.get(url, **kw)
        if time.monotonic() - t0 > 0.05:  # went to the network (cache hits return in ~1 ms)
            wait = self.gap_s - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._local.last = time.monotonic()
        return body


_PACER = _Pacer(MIN_GAP_S)


def _get_data(http: Http, path: str, *, use_cache: bool = True, **params: Any) -> list[dict]:
    """GET an API list resource; 204 (no content) and 404 (unknown sitting) mean "no records"."""
    body = _PACER.get(
        http, f"{EP_API}{path}", params={**FMT, **params}, use_cache=use_cache, ok_statuses=(200, 204, 404)
    )
    if not body:
        return []
    d = json.loads(body)
    return d.get("data", []) if isinstance(d, dict) else []


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def list_sittings(http: Http, today: str | None = None) -> list[dict]:
    """Plenary sittings of the 9th and 10th terms up to today: [{id, date, term}] sorted by date."""
    today = today or _today()
    out: dict[str, dict] = {}
    for year in range(int(FIRST_SITTING[:4]), int(today[:4]) + 1):
        offset, page = 0, 100
        while True:
            rows = _get_data(
                http, "/meetings", year=year, offset=offset, limit=page, use_cache=year < int(today[:4])
            )
            for r in rows:
                sid = r.get("activity_id") or str(r.get("id", "")).rsplit("/", 1)[-1]
                term = str(r.get("parliamentary_term") or "").rsplit("-", 1)[-1]
                day = sid[7:17]  # MTG-PL-YYYY-MM-DD
                if r.get("had_activity_type") != "def/ep-activities/PLENARY_SITTING" or not term.isdigit():
                    continue
                if FIRST_SITTING <= day <= today and int(term) >= 9:
                    out[sid] = {"id": sid, "date": day, "term": int(term)}
            if len(rows) < page:
                break
            offset += page
    return sorted(out.values(), key=lambda s: s["id"])


def fetch_sitting(http: Http, sitting: dict, today: str | None = None) -> tuple[list[dict], list[dict]]:
    """(decisions, vote items) of one sitting, as returned by the API."""
    today = today or _today()
    fresh = date.fromisoformat(sitting["date"]) >= date.fromisoformat(today) - timedelta(days=FRESH_DAYS)
    decisions = _get_data(http, f"/meetings/{sitting['id']}/decisions", use_cache=not fresh)
    items = _get_data(http, f"/meetings/{sitting['id']}/vote-results", use_cache=not fresh)
    return decisions, items


def fetch_all_sittings(http: Http, sittings: list[dict], today: str | None = None) -> dict[str, tuple]:
    with ThreadPoolExecutor(WORKERS) as ex:
        results = ex.map(lambda s: fetch_sitting(http, s, today), sittings)
        return {s["id"]: r for s, r in zip(sittings, results, strict=True)}


def fetch_procedure_labels(http: Http) -> dict[str, str]:
    """EP process id ("2021-0106") -> official reference ("2021/0106(COD)") for every EP procedure."""
    out: dict[str, str] = {}
    for ptype in PROCESS_TYPES:
        offset, page = 0, 1000
        while True:
            rows = _get_data(http, "/procedures", **{"process-type": ptype}, offset=offset, limit=page)
            for r in rows:
                if r.get("process_id") and r.get("label"):
                    out[r["process_id"]] = r["label"]
            if len(rows) < page:
                break
            offset += page
    return out
