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


def write_records(
    source: str, name: str, records: Iterable[BaseModel], key: Callable[[BaseModel], object] | None = None
) -> Path:
    recs = list(records)
    if key is not None:
        recs.sort(key=key)
    path = SNAPSHOT / source / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write("[\n")
        for i, r in enumerate(recs):
            f.write(_dump(r))
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
