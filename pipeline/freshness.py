"""How old each source's data may get before readers and the maintainers are told it is stale.

One table, used by the build (the site's freshness notes, `meta.json`) and by the workflows (the "Data health"
issue, the daily watchdog), so that the site and the alerts never disagree on what counts as stale.

Age is measured from a source's last *successful* retrieval (`fetched_at` in `data/snapshot/_manifest.json`), not
from the last attempt: a source that fails every week keeps its old `fetched_at` and becomes stale.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

# Weekly sources: one week plus two days of slack for GitHub's delayed schedules (the Monday cron has started up to
# 8 hours late) and one retried run. Slower-moving sources: about five weeks.
STALE_AFTER_DAYS: dict[str, int] = {
    "ep_votes": 9,
    "ep_procedures": 9,
    "eurlex": 9,
    "council": 9,
    "ep_people": 14,
    "implementation": 35,
    "optouts": 35,
    "train": 35,
}
DEFAULT_STALE_AFTER_DAYS = 14

# Official classifications a source gives (the Legislative Train's "Blocked") are no longer shown as current once
# the copy is older than this on the reader's date (src/lib/freshness.ts): about six weeks without a new one. Longer
# than the source's staleness threshold above, so readers are first told the source is not up to date.
LABELS_EXPIRE_AFTER_DAYS: dict[str, int] = {"train": 42}

# Sources whose staleness makes the whole site's "data refreshed" date misleading: the status of a file, its votes
# and its acts come from these. The others are shown with their own date where they are used.
CORE_SOURCES: tuple[str, ...] = ("ep_procedures", "ep_votes", "eurlex", "council")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _get(entry: Any, field: str) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(field)
    return getattr(entry, field, None)


def source_health(manifest: Mapping[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """One entry per source in the manifest (dicts or SourceStatus models), sorted by name.

    `stale` is true when the last successful retrieval is older than the source's threshold, or there is none.
    """
    now = now or datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for name in sorted(manifest):
        entry = manifest[name]
        fetched = _get(entry, "fetched_at")
        limit = STALE_AFTER_DAYS.get(name, DEFAULT_STALE_AFTER_DAYS)
        age = (now - _parse(fetched)).total_seconds() / 86400 if fetched else None
        out.append(
            {
                "source": name,
                "status": _get(entry, "status"),
                "fetched_at": fetched,
                "attempted_at": _get(entry, "attempted_at"),
                "age_days": round(age, 1) if age is not None else None,
                "stale_after_days": limit,
                "stale": age is None or age > limit,
                "core": name in CORE_SOURCES,
            }
        )
    return out


def oldest_core_fetch(manifest: Mapping[str, Any]) -> str | None:
    """The oldest last-successful retrieval among the core sources present: the date up to which the site's
    statuses, votes and acts are all current. None if no core source has been retrieved."""
    dates = [f for name in CORE_SOURCES if name in manifest and (f := _get(manifest[name], "fetched_at"))]
    return min(dates) if dates else None
