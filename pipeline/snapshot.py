"""Read/write the committed normalized snapshot (data/snapshot/<source>/<name>.json).

Writes are atomic and diff-friendly: a JSON array with one record per line, keys sorted,
records sorted by a stable key. A source that fails must NOT call `write_records` for
the affected files, so previously validated data stays in place.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from pipeline.models.entities import SourceStatus

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "snapshot"
CURATED = ROOT / "data" / "curated"
MANIFEST = SNAPSHOT / "_manifest.json"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dump(obj: BaseModel) -> str:
    return json.dumps(obj.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_IDENTITY_FIELDS = ("id", "vote_id", "celex", "url")


def _identity(d: dict) -> object:
    for f in _IDENTITY_FIELDS:
        if d.get(f) is not None:
            return (f, d[f])
    return None


def _strip_retrieved(x: object) -> object:
    if isinstance(x, dict):
        return {k: _strip_retrieved(v) for k, v in x.items() if k != "retrieved_at"}
    if isinstance(x, list):
        return [_strip_retrieved(v) for v in x]
    return x


def write_records(
    source: str, name: str, records: Iterable[BaseModel], key: Callable[[BaseModel], object] | None = None
) -> Path:
    """Write records atomically, one per line.

    Provenance stability: if a record is identical to the previously written one apart from
    `retrieved_at` timestamps, the previous line is kept verbatim. `retrieved_at` therefore means
    "first retrieved in this exact form"; the manifest's `fetched_at` says when the source was last
    checked. This keeps git diffs and activity detection limited to substantive changes.
    """
    recs = list(records)
    if key is not None:
        recs.sort(key=key)
    path = SNAPSHOT / source / f"{name}.json"
    previous: dict[object, tuple[object, str]] = {}
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.rstrip(",")
                if line.startswith("{"):
                    d = json.loads(line)
                    if (ident := _identity(d)) is not None:
                        previous[ident] = (_strip_retrieved(d), line)
        except (OSError, ValueError):
            previous = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write("[\n")
        for i, r in enumerate(recs):
            line = _dump(r)
            if previous:
                d = json.loads(line)
                prev = previous.get(_identity(d))
                if prev is not None and prev[0] == _strip_retrieved(d):
                    line = prev[1]
            f.write(line)
            f.write(",\n" if i < len(recs) - 1 else "\n")
        f.write("]\n")
    tmp.replace(path)
    return path


def read_records[M: BaseModel](source: str, name: str, model: type[M]) -> list[M]:
    path = SNAPSHOT / source / f"{name}.json"
    if not path.exists():
        return []
    return [model.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def read_manifest() -> dict[str, SourceStatus]:
    if not MANIFEST.exists():
        return {}
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {k: SourceStatus.model_validate(v) for k, v in raw.items()}


def update_manifest(status: SourceStatus) -> None:
    """Record a fetch attempt. On failure, keep the previous successful fetched_at/records."""
    m = read_manifest()
    prev = m.get(status.source)
    if status.status in ("failed", "unavailable") and prev and prev.fetched_at:
        status = status.model_copy(update={"fetched_at": prev.fetched_at, "records": prev.records})
    m[status.source] = status
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps({k: v.model_dump(mode="json") for k, v in sorted(m.items())}, indent=1, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------- incremental / resumable fetching
#
# The committed snapshot is the checkpoint. A source can fetch in chunks and upsert each chunk as soon as it
# is complete, so an interrupted run (crash, CI timeout, rate limit) keeps everything already downloaded and
# the next run continues from `_state.json` instead of starting over. No HTTP cache is required.


def upsert_records[M: BaseModel](
    source: str,
    name: str,
    model: type[M],
    records: Iterable[M],
    id_of: Callable[[M], object],
    key: Callable[[M], object] | None = None,
) -> int:
    """Merge `records` into data/snapshot/<source>/<name>.json by id (same id => replaced). Returns total count."""
    merged: dict[object, M] = {id_of(r): r for r in read_records(source, name, model)}
    for r in records:
        merged[id_of(r)] = r
    write_records(source, name, merged.values(), key=key or id_of)
    return len(merged)


def read_state(source: str) -> dict:
    """Resumable fetch state (cursor, pending ids, last full sync) committed next to the source's snapshot."""
    path = SNAPSHOT / source / "_state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_state(source: str, state: dict) -> None:
    path = SNAPSHOT / source / "_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def fetch_deadline() -> float | None:
    """Monotonic deadline from EU_INTEL_FETCH_BUDGET_S (seconds); sources stop starting new chunks after it."""
    import os
    import time

    budget = os.environ.get("EU_INTEL_FETCH_BUDGET_S")
    return time.monotonic() + float(budget) if budget else None
