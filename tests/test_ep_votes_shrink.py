"""An empty or much smaller /decisions answer must not delete a sitting's stored votes."""

from __future__ import annotations

from pipeline.models.entities import EpBallots, EpVote
from pipeline.snapshot import read_records
from pipeline.sources import ep_votes as ev
from tests.test_ep_votes import FixtureHttp, fetch_env  # noqa: F401 - fixture


def test_empty_decisions_keep_the_stored_votes(fetch_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    ev.fetch(FixtureHttp())
    before = {v.id: v for v in read_records(ev.SOURCE_ID, "votes", EpVote)}
    ballots_before = read_records(ev.SOURCE_ID, "ballots", EpBallots)
    sitting = "MTG-PL-2026-07-08"
    assert any(ev._sitting_of(v) == sitting for v in before.values())

    class NoContent(FixtureHttp):  # /decisions answers 204 (read as "no records")
        def get(self, url, params=None, **kw):
            if url.endswith(f"/meetings/{sitting}/decisions"):
                self.requests.append(url)
                return b""
            return super().get(url, params, **kw)

    status = ev.fetch(NoContent())
    after = {v.id: v for v in read_records(ev.SOURCE_ID, "votes", EpVote)}
    assert after == before
    assert read_records(ev.SOURCE_ID, "ballots", EpBallots) == ballots_before
    assert status.status == "partial" and "stored votes kept for 1 sittings" in status.note
    from pipeline import snapshot

    assert sitting in snapshot.read_state(ev.SOURCE_ID)["pending"]
    assert ev.fetch(FixtureHttp()).status == "ok"  # answers again: replaced as usual


def test_retry_wait_respects_the_deadline(monkeypatch):
    import time

    from pipeline.http import HttpError

    class Down:
        def get(self, url, **kw):
            raise HttpError(url, 500, "down")

    slept = []
    monkeypatch.setattr(ev.time, "sleep", lambda s: slept.append(s))
    data, failed = ev._fetch_sittings(
        Down(),  # type: ignore[arg-type]
        [{"id": "MTG-PL-2026-07-08", "date": "2026-07-08", "term": 10}],
        "2026-10-22",
        deadline=time.monotonic() + 1,
    )
    assert data == [] and len(failed) == 1 and slept == []
