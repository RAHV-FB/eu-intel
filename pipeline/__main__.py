"""CLI entry point.

    python -m pipeline fetch [SOURCE ...]   # network: refresh data/snapshot/<source>/ (per-source, failure-safe)
    python -m pipeline build                # offline: data/snapshot + data/curated -> public/data
    python -m pipeline build --strict       # same; exit 1 on a degraded result (also EU_INTEL_STRICT=1)
    python -m pipeline validate             # offline: schema + invariant checks on the snapshot, and on the
                                            # built output (public/data) if there is one; ratchet on warnings
    python -m pipeline validate --built     # same; a missing built output is an error (run after build)
    python -m pipeline validate --built --update-baseline
                                            # same; record the warning counts in pipeline/validate_baseline.json
    python -m pipeline validate --list-failing
                                            # the snapshot checks; prints the sources with structural errors
    python -m pipeline restore-manifest --previous FILE SOURCE ...
                                            # put back those sources' entries of a previous manifest
    python -m pipeline health [--meta FILE] [--problem KEY=TEXT ...] [--markdown | --json]
                                            # failed or stale sources (pipeline/freshness.py), the age of the
                                            # live site's data and the workflow's own findings; exit 1 if any

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
    "lawcontext": "pipeline.sources.lawcontext",  # reads the eurlex and ep_procedures snapshots
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


def cmd_validate(list_failing: bool, built: bool = False, update_baseline: bool = False) -> int:
    from pipeline.validate import validate, validate_by_source

    if not list_failing:
        return validate(built, update_baseline=update_baseline)
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


# ---------------------------------------------------------------- health (the "Data health" issue, watchdog.yml)


def cmd_health(
    manifest: Path | None, meta: Path | None, problems: list[str], max_age: float, fmt: str
) -> int:
    """Failed or stale sources (pipeline.freshness, from the manifest), the age of the newest data on the live site
    (`meta`: its data/meta.json) and the problems the workflow found itself (KEY=TEXT). Prints them (`fmt`: text,
    markdown for the issue body, json) and returns 1 if there is any."""
    from datetime import UTC, datetime

    from pipeline.freshness import source_health
    from pipeline.snapshot import MANIFEST

    now = datetime.now(UTC)
    found: list[dict[str, str]] = []
    for p in problems:
        key, _, text = p.partition("=")
        if not re.fullmatch(r"[a-z][a-z0-9:_-]*", key) or not text.strip():
            print(f"--problem takes KEY=TEXT (KEY: a-z, 0-9, ':', '_', '-'), not {p!r}", file=sys.stderr)
            return 2
        found.append({"key": key, "text": text.strip()})
    manifest = manifest or MANIFEST
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(entries, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as e:
        entries = {}
        found.append({"key": "manifest", "text": f"**The manifest** ({manifest}) could not be read: {e}"})
    sources = source_health(entries, now)
    for s in sources:
        flags = [f"failed in its last run on {(s['attempted_at'] or '?')[:10]}"] * (s["status"] == "failed")
        flags += ["stale"] * s["stale"]
        if flags:
            last = f"{s['fetched_at'][:10]}, {s['age_days']:g} days ago" if s["fetched_at"] else "never"
            text = f"{', '.join(flags)}; last successful retrieval {last} (stale after {s['stale_after_days']} days)"
            found.append({"key": f"source:{s['source']}", "text": f"**{s['source']}**: {text}"})
    site = None
    if meta is not None:
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            newest = max(x["fetched_at"] for x in m["sources"] if x.get("fetched_at"))
            age = (now - datetime.fromisoformat(newest.replace("Z", "+00:00"))).total_seconds() / 86400
            site = {"newest_fetched_at": newest, "built_at": m.get("built_at"), "age_days": round(age, 1)}
            if age > max_age:
                found.append({"key": "site", "text": (
                    f"**The live site's data is overdue**: its newest data was retrieved on {newest[:10]}, {age:.1f} "
                    f"days ago (more than {max_age:g}). No refresh has reached the site since: the schedule may "
                    "be late, dropped or disabled (GitHub disables it after 60 days without repository activity), or "
                    "the refresh or its deploy fails."
                )})  # fmt: skip
        except (OSError, ValueError, KeyError, TypeError) as e:
            found.append(
                {"key": "site", "text": f"**The live site's data/meta.json** could not be read: {e!r:.200}"}
            )
    checked = now.strftime("%Y-%m-%d %H:%M UTC")
    if fmt == "json":
        print(json.dumps({"healthy": not found, "checked_at": checked, "problems": found, "sources": sources,
                          "site": site}, indent=1))  # fmt: skip
    elif fmt == "markdown":
        out = [f"<!-- data-health: {','.join(p['key'] for p in found)} -->"]
        out += (
            [f"{len(found)} problem(s) as of {checked}:", ""]
            if found
            else [f"All checks pass as of {checked}."]
        )
        out += [f"- {p['text']}" for p in found]
        out += ["", "<details><summary>All sources</summary>", "",
                "| Source | Status | Last successful retrieval | Age (days) | Stale after (days) |",
                "| --- | --- | --- | --- | --- |"]  # fmt: skip
        out += [f"| {s['source']} | {s['status']} | {s['fetched_at'] or 'never'} | "
                f"{'-' if s['age_days'] is None else s['age_days']} | {s['stale_after_days']} |" for s in sources]  # fmt: skip
        if site:
            out += [
                "",
                f"Live site: built {site['built_at']}, newest data retrieved {site['newest_fetched_at']}.",
            ]
        print("\n".join([*out, "", "</details>"]))
    else:
        print("\n".join(p["text"] for p in found) or f"healthy ({checked})")
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("sources", nargs="*")
    bp = sub.add_parser("build")
    bp.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if a feature did not load, a curated file or entry was not applied, or a status or assessment "
        "fell back (also EU_INTEL_STRICT=1); all such problems are listed at the end",
    )
    v = sub.add_parser("validate")
    vmode = v.add_mutually_exclusive_group()
    vmode.add_argument(
        "--built",
        action="store_true",
        help="also require the built output (public/data): fail when it is missing instead of skipping its checks",
    )
    vmode.add_argument(
        "--list-failing",
        action="store_true",
        help="print the sources whose snapshot files have structural errors (one per line; report on stderr)",
    )
    v.add_argument(
        "--update-baseline",
        action="store_true",
        help="with --built: record this run's warning counts in pipeline/validate_baseline.json (the ratchet)",
    )
    r = sub.add_parser("restore-manifest")
    r.add_argument("--previous", type=Path, required=True, help="manifest to take the entries from")
    r.add_argument("--reason", default=None)
    r.add_argument("sources", nargs="+")
    h = sub.add_parser("health", help="failed or stale sources, overdue live data, the workflow's findings")
    h.add_argument("--manifest", type=Path, default=None, help="default: data/snapshot/_manifest.json")
    h.add_argument("--meta", type=Path, default=None, help="the live site's data/meta.json: check its age")
    h.add_argument("--max-age-days", type=float, default=8.0, help="for --meta (default: 8)")
    h.add_argument("--problem", action="append", default=[], metavar="KEY=TEXT", help="found elsewhere")
    hfmt = h.add_mutually_exclusive_group()
    hfmt.add_argument("--markdown", dest="fmt", action="store_const", const="markdown", default="text")
    hfmt.add_argument("--json", dest="fmt", action="store_const", const="json")
    a = p.parse_args(argv)
    if a.cmd == "health":
        return cmd_health(a.manifest, a.meta, a.problem, a.max_age_days, a.fmt)
    if a.cmd == "fetch":
        return cmd_fetch(a.sources)
    if a.cmd == "build":
        from pipeline.build import build

        return build(strict=True if a.strict else None)
    if a.cmd == "validate":
        if a.update_baseline and not a.built:
            p.error("validate --update-baseline needs --built (the baseline counts the built output's warnings too)")
        return cmd_validate(a.list_failing, a.built, a.update_baseline)
    if a.cmd == "restore-manifest":
        return cmd_restore_manifest(a.previous, a.sources, a.reason)
    return 2


if __name__ == "__main__":
    sys.exit(main())
