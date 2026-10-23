"""An empty or much smaller /decisions (or /vote-results) answer must not delete a sitting's stored votes (or
their procedure links)."""

from __future__ import annotations

from collections import Counter

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


def test_empty_vote_results_keep_the_stored_procedure_links(fetch_env, monkeypatch):  # noqa: F811
    """/vote-results answering 204 (read as "no records") while /decisions works: the same votes come back but
    without what their vote items gave: in MTG-PL-2024-03-13 all 13 subjects (vote 166051: "Artificial
    Intelligence Act ***I") and the link of 166656 to 2024/0028(COD) (the other links are found again through
    the item documents of earlier runs, kept in _state.json; without them 11 of 13 links are lost). The vote
    count did not notice; now the stored votes are kept and the sitting stays pending."""
    from pipeline import snapshot

    monkeypatch.setattr(ev, "_out_of_time", lambda _deadline: False)
    ev.fetch(FixtureHttp())
    before = {v.id: v for v in read_records(ev.SOURCE_ID, "votes", EpVote)}
    sitting = "MTG-PL-2024-03-13"
    stored = ev.sitting_counts(before.values())
    assert (stored["votes"][sitting], stored["linked"][sitting], stored["with a subject"][sitting]) == (13, 13, 13)

    class NoItems(FixtureHttp):
        def get(self, url, params=None, **kw):
            if url.endswith(f"/meetings/{sitting}/vote-results"):
                self.requests.append(url)
                return b""
            return super().get(url, params, **kw)

    monkeypatch.setenv("EU_INTEL_FULL_REFRESH", "1")
    status = ev.fetch(NoItems())
    after = {v.id: v for v in read_records(ev.SOURCE_ID, "votes", EpVote)}
    assert after == before
    assert status.status == "partial" and "far fewer votes, procedure links or subjects (MTG-PL-2024-03-13" in (
        status.note
    )
    assert snapshot.read_state(ev.SOURCE_ID)["pending"] == [sitting]
    # the same answer is let through when only the vote count is compared (the guard before)
    without_items = [v.model_copy(update={"subject": None}) for v in before.values()]
    res = ev.Result(without_items, [], Counter(), {}, 0)
    assert ev._shrunk_sittings({sitting}, res, {"votes": stored["votes"]}) == set()
    assert ev._shrunk_sittings({sitting}, res, stored) == {sitting}
    monkeypatch.delenv("EU_INTEL_FULL_REFRESH")
    assert ev.fetch(FixtureHttp()).status == "ok"  # answers again: the sitting is replaced as usual


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
