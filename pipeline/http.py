"""Shared HTTP access for all source adapters.

Every network request made by the pipeline goes through `Http`. It provides:
- timeouts, retries with exponential backoff (and Retry-After handling on 429/503),
- a polite per-host minimum interval between requests,
- an optional on-disk response cache (development speed + idempotent re-runs),
- a SPARQL helper for the Publications Office Cellar endpoint,
- an optional run-wide deadline (EU_INTEL_FETCH_DEADLINE, epoch seconds) that bounds wall time:
  with it set, one call (all attempts and waits) takes at most CALL_CAP_S; after the deadline a call
  gets a single short attempt (no retries, no backoff); LATE_GRACE_S after it, no request is started
  (DeadlineReached). Without the variable, requests behave as before.

Source modules must not create their own httpx clients.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger("pipeline.http")

USER_AGENT = (
    "eu-intel-pipeline/0.1 (independent, non-commercial EU legislative explorer; "
    "+https://github.com/rahv-fb/eu-intel)"
)
CELLAR_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EP_API = "https://data.europarl.europa.eu/api/v2"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / ".cache" / "http"

# Minimum seconds between requests per host (per process). The EP Open Data API documents a cap of
# 500 requests per 5 minutes (~1.67/s); stay below it.
HOST_MIN_INTERVAL: dict[str, float] = {
    "data.europarl.europa.eu": 0.65,
    "www.europarl.europa.eu": 1.0,
    "publications.europa.eu": 0.5,
}


# Run-wide fetch deadline (set by the refresh workflow; unset = no limit).
FETCH_DEADLINE_ENV = "EU_INTEL_FETCH_DEADLINE"
CALL_CAP_S = 240.0  # with a deadline: most wall time one call may take, all attempts and waits included
LATE_TIMEOUT_S = 30.0  # after the deadline: timeout of the single attempt a call still gets
LATE_GRACE_S = 300.0  # this long after the deadline, no new request is started at all


def fetch_deadline_epoch() -> float | None:
    """EU_INTEL_FETCH_DEADLINE as epoch seconds (time.time()), or None when unset or malformed."""
    raw = os.environ.get(FETCH_DEADLINE_ENV, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        log.warning("ignoring %s=%r (expected epoch seconds)", FETCH_DEADLINE_ENV, raw)
        return None


def _now() -> float:  # wall clock; monkeypatched in tests
    return time.time()


class HttpError(RuntimeError):
    """Raised when a request fails permanently (after retries)."""

    def __init__(self, url: str, status: int | None, message: str):
        super().__init__(f"{status or 'ERR'} {url}: {message}")
        self.url = url
        self.status = status


class DeadlineReached(HttpError):
    """The run's fetch deadline leaves no time to start this request."""


_FROM_ENV: Any = object()


class Http:
    def __init__(
        self,
        *,
        cache_dir: Path | None = DEFAULT_CACHE,
        cache_ttl_s: float | None = None,
        min_interval_s: float = 0.25,
        timeout_s: float = 60.0,
        max_retries: int = 5,
        deadline: float | None = _FROM_ENV,
        transport: httpx.BaseTransport | None = None,
    ):
        """
        cache_dir: directory for cached responses; None disables caching.
        cache_ttl_s: max age of a cached response; None = never expires (dev). Set
            EU_INTEL_CACHE_TTL (seconds) or EU_INTEL_NO_CACHE=1 to override in CI.
        deadline: run-wide fetch deadline in epoch seconds; defaults to EU_INTEL_FETCH_DEADLINE.
        transport: httpx transport (tests use httpx.MockTransport).
        """
        if os.environ.get("EU_INTEL_NO_CACHE") == "1":
            cache_dir = None
        if os.environ.get("EU_INTEL_CACHE_TTL"):
            cache_ttl_s = float(os.environ["EU_INTEL_CACHE_TTL"])
        self.cache_dir = cache_dir
        self.cache_ttl_s = cache_ttl_s
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.deadline: float | None = fetch_deadline_epoch() if deadline is _FROM_ENV else deadline
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=20.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            http2=False,
            transport=transport,
        )
        self._host_last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._abort = threading.Event()

    def abort(self) -> None:
        """Make every pending and future request fail at once (used when the fetch is interrupted)."""
        self._abort.set()

    def _wait(self, seconds: float) -> bool:
        """Sleep; False if the fetch was interrupted meanwhile."""
        return not self._abort.wait(seconds)

    # ------------------------------------------------------------------ cache
    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.bin"

    def _cache_get(self, key: str) -> bytes | None:
        p = self._cache_path(key)
        if not p or not p.exists():
            return None
        if self.cache_ttl_s is not None and time.time() - p.stat().st_mtime > self.cache_ttl_s:
            return None
        return p.read_bytes()

    def _cache_put(self, key: str, body: bytes) -> None:
        p = self._cache_path(key)
        if not p:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(body)
        tmp.replace(p)

    # --------------------------------------------------------------- request
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._lock:
            last = self._host_last.get(host, 0.0)
            interval = max(self.min_interval_s, HOST_MIN_INTERVAL.get(host, 0.0))
            wait = interval - (time.monotonic() - last)
            self._host_last[host] = time.monotonic() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
        ok_statuses: tuple[int, ...] = (200,),
        retries: int | None = None,
    ) -> bytes:
        """`retries` overrides max_retries for this call (0: a single attempt, e.g. when the caller has a
        cheaper fallback than waiting, such as asking for a smaller page)."""
        key = json.dumps([method, url, params, data, json_body, headers], sort_keys=True, default=str)
        if use_cache:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        if self._abort.is_set():
            raise HttpError(url, None, "fetch interrupted")
        attempts = (self.max_retries if retries is None else retries) + 1
        # With a run deadline: `call_end` bounds this call, `retry_end` bounds the start of another attempt.
        call_end = retry_end = None
        if self.deadline is not None:
            start = _now()
            if start >= self.deadline + LATE_GRACE_S:
                raise DeadlineReached(url, None, "fetch deadline passed; request not started")
            if start >= self.deadline:
                attempts, call_end = 1, start + min(self.timeout_s, LATE_TIMEOUT_S)
            else:
                call_end, retry_end = start + CALL_CAP_S, min(start + CALL_CAP_S, self.deadline)
        last_err = ""
        status: int | None = None
        tried = 0
        for attempt in range(attempts):
            timeout: dict[str, Any] = {}
            if call_end is not None:
                left = call_end - _now()
                if left < 1.0:
                    break
                timeout = {"timeout": httpx.Timeout(min(self.timeout_s, left), connect=min(20.0, left))}
            self._throttle(url)
            tried += 1
            try:
                r = self._client.request(
                    method, url, params=params, data=data, json=json_body, headers=headers, **timeout
                )
                status = r.status_code
                if status in ok_statuses:
                    body = r.content
                    if use_cache:
                        self._cache_put(key, body)
                    return body
                if status in (429, 500, 502, 503, 504):
                    ra = r.headers.get("Retry-After")
                    delay = float(ra) if ra and ra.isdigit() else min(2**attempt, 60)
                    last_err = f"retryable status {status}"
                    kind = f"HTTP {status}"
                else:
                    # 202 from EU WAF challenge pages, 403 bot checks, 404 etc. are permanent here
                    raise HttpError(url, status, r.text[:300].replace("\n", " "))
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_err = repr(e)
                delay = min(2**attempt, 60)
                kind = f"transport error {e}"
            if attempt == attempts - 1:
                break
            if retry_end is not None and _now() + delay >= retry_end:
                last_err += "; no time left for another attempt before the fetch deadline/call limit"
                break
            log.warning("%s for %s (attempt %d), sleeping %.1fs", kind, url, attempt + 1, delay)
            if not self._wait(delay):
                raise HttpError(url, status, "fetch interrupted")
        raise HttpError(url, status, f"gave up after {tried} attempt(s): {last_err}")

    def get(self, url: str, **kw: Any) -> bytes:
        return self.request("GET", url, **kw)

    def get_json(self, url: str, **kw: Any) -> Any:
        return json.loads(self.get(url, **kw))

    # ---------------------------------------------------------------- SPARQL
    def sparql(
        self, query: str, *, endpoint: str = CELLAR_SPARQL, use_cache: bool = True
    ) -> list[dict[str, str]]:
        """Run a SELECT query; returns rows as {var: value} (literal/URI values as plain strings)."""
        body = self.request(
            "POST",
            endpoint,
            data={"query": query, "format": "application/sparql-results+json"},
            headers={"Accept": "application/sparql-results+json"},
            use_cache=use_cache,
        )
        d = json.loads(body)
        return [{k: v["value"] for k, v in b.items()} for b in d["results"]["bindings"]]

    def close(self) -> None:
        self._client.close()


_default: Http | None = None


def default_http() -> Http:
    global _default
    if _default is None:
        _default = Http()
    return _default
