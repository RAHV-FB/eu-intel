"""CLI entry point.

    python -m pipeline fetch [SOURCE ...]   # network: refresh data/snapshot/<source>/ (per-source, failure-safe)
    python -m pipeline build                # offline: data/snapshot + data/curated -> public/data
    python -m pipeline validate             # offline: schema + invariant checks on the snapshot
    python -m pipeline validate --list-failing
                                            # same checks; prints the sources with structural errors
    python -m pipeline restore-manifest --previous FILE SOURCE ...
                                            # put back those sources' entries of a previous manifest

Each source module in pipeline/sources/ exposes:
    SOURCE_ID: str
    def fetch(http: Http) -> SourceStatus   # writes its own snapshot files via pipeline.snapshot.write_records
A source that raises is recorded as "failed" in the manifest and its previous files are left untouched.

Time limits: EU_INTEL_FETCH_BUDGET_S (seconds per source) and EU_INTEL_FETCH_DEADLINE (epoch seconds, the
whole fetch run; see pipeline.http). A source that has not started when the run deadline passes is not
started; an interrupt (SIGINT, e.g. from `timeout --signal=INT`) stops the current source, aborts its
pending requests and records it, so the checkpoints already written can be committed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import re
import signal
import sys
import traceback
from pathlib import Path

from pipeline.http import default_http
from pipeline.models.entities import SourceStatus
from pipeline.snapshot import global_deadline, not_refreshed, now_iso, past, update_manifest

# Order matters: later sources may read earlier snapshot files (e.g. votes -> procedures).
SOURCES: dict[str, str] = {
    "ep_people": "pipeline.sources.ep_people",
    "ep_procedures": "pipeline.sources.ep_procedures",
    "ep_votes": "pipeline.sources.ep_votes",
    "eurlex": "pipeline.sources.eurlex",
    "council": "pipeline.sources.council",
    "implementation": "pipeline.sources.implementation",
    "optouts": "pipeline.sources.optouts",
    "train": "pipeline.sources.legislative_train",
}
SOURCE_NAME_RE = re.compile(r"^[a-z_]+$")


def cmd_fetch(names: list[str]) -> int:
    names = names or list(SOURCES)
    for name in names:
        if name not in SOURCES:
            print(f"unknown source {name!r}; known: {', '.join(SOURCES)}", file=sys.stderr)
            return 2
    http = default_http()
    hard = global_deadline()
    failures = 0

    def on_sigint(signum, frame):  # noqa: ANN001 - signal handler signature
        http.abort()  # worker threads' requests fail at once instead of finishing their queues
        raise KeyboardInterrupt

    try:
        previous_handler = signal.signal(signal.SIGINT, on_sigint)
    except ValueError:  # not the main thread: keep the default handler
        previous_handler = None
    try:
        for name in names:
            attempted = now_iso()
            if past(hard):
                status = not_refreshed(
                    name, attempted, "Not refreshed in this run: the fetch deadline passed before it started."
                )
                failures += 1
                update_manifest(status)
                logging.warning("%s: skipped (fetch deadline passed)", name)
                continue
            try:
                mod = importlib.import_module(SOURCES[name])
                status: SourceStatus = mod.fetch(http)
            except KeyboardInterrupt:
                update_manifest(
                    not_refreshed(
                        name,
                        attempted,
                        "Interrupted at the fetch time limit: checkpoints already written are kept, the rest "
                        "resumes next run.",
                    )
                )
                logging.warning("%s: interrupted; later sources not started", name)
                return 130
            except Exception as e:  # noqa: BLE001 - record and continue with other sources
                traceback.print_exc()
                status = SourceStatus(
                    source=name, status="failed", attempted_at=attempted, note=repr(e)[:500]
                )
                failures += 1
            update_manifest(status)
            logging.info("%s: %s %s", name, status.status, status.records)
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)
    return 1 if failures else 0


def cmd_validate(list_failing: bool) -> int:
    from pipeline.validate import validate, validate_by_source

    if not list_failing:
        return validate()
    failing = validate_by_source(out=sys.stderr)
    bad = [s for s in failing if not SOURCE_NAME_RE.match(s)]
    if bad:  # cannot be restored per source (e.g. errors in the built public output)
        print(f"validate: errors outside a source directory: {bad}", file=sys.stderr)
        return 1
    for source in failing:
        print(source)
    return 0


def cmd_restore_manifest(previous: Path, sources: list[str], reason: str | None) -> int:
    from pipeline.snapshot import restore_manifest_entries

    bad = [s for s in sources if not SOURCE_NAME_RE.match(s)]
    if bad:
        print(f"invalid source names: {bad}", file=sys.stderr)
        return 2
    try:
        prev = json.loads(previous.read_text(encoding="utf-8")) if previous.exists() else {}
    except ValueError:
        prev = {}
    if not isinstance(prev, dict):
        prev = {}
    done = restore_manifest_entries(
        sources,
        prev,
        reason or f"The data fetched on {now_iso()[:10]} failed validation and was discarded.",
    )
    logging.info("manifest entries restored: %s", ", ".join(done) or "none")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("sources", nargs="*")
    sub.add_parser("build")
    v = sub.add_parser("validate")
    v.add_argument(
        "--list-failing",
        action="store_true",
        help="print the sources whose snapshot files have structural errors (one per line; report on stderr)",
    )
    r = sub.add_parser("restore-manifest")
    r.add_argument("--previous", type=Path, required=True, help="manifest to take the entries from")
    r.add_argument("--reason", default=None)
    r.add_argument("sources", nargs="+")
    a = p.parse_args(argv)
    if a.cmd == "fetch":
        return cmd_fetch(a.sources)
    if a.cmd == "build":
        from pipeline.build import build

        return build()
    if a.cmd == "validate":
        return cmd_validate(a.list_failing)
    if a.cmd == "restore-manifest":
        return cmd_restore_manifest(a.previous, a.sources, a.reason)
    return 2


if __name__ == "__main__":
    sys.exit(main())
