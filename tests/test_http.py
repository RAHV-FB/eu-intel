"""pipeline.http retries and the run-wide fetch deadline (offline: httpx.MockTransport, fake clock)."""

from __future__ import annotations

import httpx
import pytest

from pipeline import http as H

URL = "https://example.test/x"


class Clock:
    """Fake wall clock: waits and requests advance it instead of sleeping."""

    def __init__(self, t: float = 1_000_000.0):
        self.t = t
        self.waits: list[float] = []

    def now(self) -> float:
        return self.t

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.t += seconds
        return True


def make(monkeypatch, handler, *, deadline=None, request_s: float = 0.0, **kw) -> tuple[H.Http, Clock, list]:
    clock = Clock()
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        clock.t += min(request_s, request.extensions["timeout"]["read"])  # a slow server: bounded by timeout
        return handler(request)

    monkeypatch.setattr(H, "_now", clock.now)
    dl = None if deadline is None else clock.t + deadline
    http = H.Http(cache_dir=None, min_interval_s=0.0, deadline=dl, transport=httpx.MockTransport(respond), **kw)
    http._wait = clock.wait  # type: ignore[method-assign]
    return http, clock, calls


def always(status: int):
    return lambda request: httpx.Response(status, text="busy")


def test_without_deadline_retries_as_before(monkeypatch):
    monkeypatch.delenv(H.FETCH_DEADLINE_ENV, raising=False)
    http, clock, calls = make(monkeypatch, always(500))
    assert http.deadline is None
    with pytest.raises(H.HttpError) as e:
        http.get(URL)
    assert e.value.status == 500
    assert len(calls) == 6  # 1 + max_retries
    assert clock.waits == [1, 2, 4, 8, 16]  # exponential backoff between attempts


def test_success_after_retry(monkeypatch):
    answers = iter([httpx.Response(503), httpx.Response(200, content=b"ok")])
    http, clock, calls = make(monkeypatch, lambda r: next(answers), deadline=3600)
    assert http.get(URL) == b"ok"
    assert len(calls) == 2


def test_deadline_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv(H.FETCH_DEADLINE_ENV, "1234.5")
    assert H.Http(cache_dir=None).deadline == 1234.5
    monkeypatch.setenv(H.FETCH_DEADLINE_ENV, "soon")
    assert H.Http(cache_dir=None).deadline is None  # malformed: ignored


def test_no_retry_or_backoff_after_the_deadline(monkeypatch):
    http, clock, calls = make(monkeypatch, always(500), deadline=-1)  # deadline in the past
    with pytest.raises(H.HttpError) as e:
        http.get(URL)
    assert e.value.status == 500
    assert len(calls) == 1 and clock.waits == []


def test_late_call_gets_a_short_timeout(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.extensions["timeout"])
        return httpx.Response(200, content=b"ok")

    http, _, _ = make(monkeypatch, handler, deadline=-1)
    assert http.get(URL) == b"ok"
    assert seen["read"] <= H.LATE_TIMEOUT_S


def test_no_request_long_after_the_deadline(monkeypatch):
    http, _, calls = make(monkeypatch, always(200), deadline=-(H.LATE_GRACE_S + 1))
    with pytest.raises(H.DeadlineReached):
        http.get(URL)
    assert calls == []


def test_backoff_never_crosses_the_deadline(monkeypatch):
    # 10 s before the deadline: retries after 1, 2 and 4 s fit; the next 8 s wait would cross it
    http, clock, calls = make(monkeypatch, always(503), deadline=10)
    with pytest.raises(H.HttpError) as e:
        http.get(URL)
    assert "no time left" in str(e.value)
    assert clock.waits == [1, 2, 4] and len(calls) == 4
    assert clock.t < http.deadline


def test_long_retry_after_is_not_honoured_near_the_deadline(monkeypatch):
    http, clock, calls = make(
        monkeypatch, lambda r: httpx.Response(429, headers={"Retry-After": "3600"}), deadline=600
    )
    with pytest.raises(H.HttpError):
        http.get(URL)
    assert len(calls) == 1 and clock.waits == []


def test_total_time_per_call_is_capped(monkeypatch):
    # every attempt times out after 60 s: without a cap 6 attempts + 31 s of backoff = 6.5 min
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    http, clock, calls = make(monkeypatch, slow, deadline=3600, request_s=60.0)
    start = clock.t
    with pytest.raises(H.HttpError):
        http.get(URL)
    assert clock.t - start <= H.CALL_CAP_S
    assert len(calls) < 6


def test_attempt_timeout_shrinks_to_the_time_left(monkeypatch):
    timeouts = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(500)

    http, _, _ = make(monkeypatch, handler, deadline=3600, request_s=50.0)
    with pytest.raises(H.HttpError):
        http.get(URL)
    assert timeouts[0] == 60.0 and all(t <= H.CALL_CAP_S for t in timeouts)
    assert timeouts[-1] < 60.0


def test_abort_stops_requests(monkeypatch):
    http, _, calls = make(monkeypatch, always(200))
    http.abort()
    with pytest.raises(H.HttpError, match="interrupted"):
        http.get(URL)
    assert calls == []


def test_fetch_deadline_combines_budget_and_run_deadline(monkeypatch):
    import time

    from pipeline import snapshot

    monkeypatch.delenv("EU_INTEL_FETCH_BUDGET_S", raising=False)
    monkeypatch.delenv(H.FETCH_DEADLINE_ENV, raising=False)
    assert snapshot.fetch_deadline() is None
    monkeypatch.setenv("EU_INTEL_FETCH_BUDGET_S", "600")
    assert snapshot.fetch_deadline() == pytest.approx(time.monotonic() + 600, abs=5)
    monkeypatch.setenv(H.FETCH_DEADLINE_ENV, str(time.time() + 60))
    assert snapshot.fetch_deadline() == pytest.approx(time.monotonic() + 60, abs=5)  # the earlier one
    monkeypatch.setenv(H.FETCH_DEADLINE_ENV, str(time.time() - 1))
    assert snapshot.past(snapshot.fetch_deadline()) and snapshot.past(snapshot.global_deadline())
