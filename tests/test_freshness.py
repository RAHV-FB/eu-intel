from datetime import UTC, datetime

from pipeline.freshness import CORE_SOURCES, STALE_AFTER_DAYS, oldest_core_fetch, source_health
from pipeline.models.entities import SourceStatus

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def test_stale_after_threshold_from_last_success_not_last_attempt():
    manifest = {
        "train": {"status": "failed", "fetched_at": "2026-09-29T00:00:00Z", "attempted_at": "2026-11-02T13:51:20Z"},
        "ep_votes": {"status": "ok", "fetched_at": "2026-11-02T13:40:49Z", "attempted_at": "2026-11-02T13:39:55Z"},
    }
    h = {e["source"]: e for e in source_health(manifest, NOW)}
    assert h["train"]["stale"] is True  # 37 days > 35, although it was attempted 3 days ago
    assert h["train"]["age_days"] == 37.5
    assert h["ep_votes"]["stale"] is False
    assert h["ep_votes"]["core"] is True and h["train"]["core"] is False


def test_never_retrieved_is_stale_and_unknown_source_gets_default():
    h = source_health({"new_source": {"status": "failed", "fetched_at": None}}, NOW)
    assert h[0]["stale"] is True and h[0]["age_days"] is None and h[0]["stale_after_days"] == 14


def test_accepts_manifest_models_and_every_source_has_a_threshold():
    st = SourceStatus(source="council", status="ok", attempted_at="2026-11-02T13:42:52Z",
                      fetched_at="2026-11-02T13:42:55Z")  # fmt: skip
    assert source_health({"council": st}, NOW)[0]["stale"] is False
    from pipeline.__main__ import SOURCES

    assert set(SOURCES) <= set(STALE_AFTER_DAYS)
    assert set(CORE_SOURCES) <= set(SOURCES)


def test_oldest_core_fetch_ignores_non_core_sources():
    manifest = {
        "train": {"fetched_at": "2026-10-22T17:53:03Z"},
        "eurlex": {"fetched_at": "2026-11-02T13:42:52Z"},
        "ep_votes": {"fetched_at": "2026-11-02T13:40:49Z"},
    }
    assert oldest_core_fetch(manifest) == "2026-11-02T13:40:49Z"
    assert oldest_core_fetch({"train": {"fetched_at": "2026-10-22T17:53:03Z"}}) is None
