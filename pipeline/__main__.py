"""CLI entry point.

    python -m pipeline fetch [SOURCE ...]   # network: refresh data/snapshot/<source>/ (per-source, failure-safe)
    python -m pipeline build                # offline: data/snapshot + data/curated -> public/data
    python -m pipeline validate             # offline: schema + invariant checks on the snapshot

Each source module in pipeline/sources/ exposes:
    SOURCE_ID: str
    def fetch(http: Http) -> SourceStatus   # writes its own snapshot files via pipeline.snapshot.write_records
A source that raises is recorded as "failed" in the manifest and its previous files are left untouched.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import traceback

from pipeline.http import default_http
from pipeline.models.entities import SourceStatus
from pipeline.snapshot import now_iso, update_manifest

# Order matters: later sources may read earlier snapshot files (e.g. votes -> procedures).
SOURCES: dict[str, str] = {
    "ep_people": "pipeline.sources.ep_people",
    "ep_procedures": "pipeline.sources.ep_procedures",
    "ep_votes": "pipeline.sources.ep_votes",
    "eurlex": "pipeline.sources.eurlex",
    "council": "pipeline.sources.council",
    "implementation": "pipeline.sources.implementation",
    "train": "pipeline.sources.legislative_train",
}


def cmd_fetch(names: list[str]) -> int:
    http = default_http()
    failures = 0
    for name in names or list(SOURCES):
        if name not in SOURCES:
            print(f"unknown source {name!r}; known: {', '.join(SOURCES)}", file=sys.stderr)
            return 2
        attempted = now_iso()
        try:
            mod = importlib.import_module(SOURCES[name])
            status: SourceStatus = mod.fetch(http)
        except Exception as e:  # noqa: BLE001 - record and continue with other sources
            traceback.print_exc()
            status = SourceStatus(source=name, status="failed", attempted_at=attempted, note=repr(e)[:500])
            failures += 1
        update_manifest(status)
        logging.info("%s: %s %s", name, status.status, status.records)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("sources", nargs="*")
    sub.add_parser("build")
    sub.add_parser("validate")
    a = p.parse_args(argv)
    if a.cmd == "fetch":
        return cmd_fetch(a.sources)
    if a.cmd == "build":
        from pipeline.build import build

        return build()
    if a.cmd == "validate":
        from pipeline.validate import validate

        return validate()
    return 2


if __name__ == "__main__":
    sys.exit(main())
