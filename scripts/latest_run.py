"""The latest run of a workflow on main that did its work, for the watchdog (.github/workflows/watchdog.yml).

    python scripts/latest_run.py WORKFLOW [--job NAME] [--event EVENT] [--cancelled-if-last]

Prints "<conclusion> <run id> <url> <commit>" of the newest completed run of WORKFLOW (its file name, e.g.
refresh.yml) on main, or nothing. Left out:

- a run in which job NAME was skipped by its `if`: it did nothing, concludes "success" and must not hide an earlier
  failure (a scheduled refresh its plan skipped; a deploy after a CI run that deploys nothing);
- a run that was skipped, or cancelled (a newer push cancels CI, a newer deploy replaces a pending one), except with
  --cancelled-if-last when no later run of the workflow has started since it: then it is the latest word.

Uses the `gh` CLI (GH_TOKEN, GH_REPO), with `actions: read`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def gh(*args: str) -> object:
    out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else None


def latest(workflow: str, job: str | None, event: str | None, cancelled_if_last: bool) -> str:
    listing = ["run", "list", "--workflow", workflow, "--branch", "main", "--limit", "20"]
    runs = gh(
        *listing, *(["--event", event] if event else []), "--json", "databaseId,status,conclusion,url,headSha"
    )
    for i, run in enumerate(runs or []):  # newest first
        if run["status"] != "completed" or run["conclusion"] == "skipped":
            continue
        if run["conclusion"] == "cancelled" and not (cancelled_if_last and i == 0):
            continue
        if job:
            jobs = (gh("run", "view", str(run["databaseId"]), "--json", "jobs") or {}).get("jobs", [])
            if any(j.get("name") == job and j.get("conclusion") == "skipped" for j in jobs):
                continue
        return f"{run['conclusion']} {run['databaseId']} {run['url']} {run['headSha']}"
    return ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="latest_run.py", description=__doc__.splitlines()[0])
    p.add_argument("workflow")
    p.add_argument("--job", default=None, help="leave out runs in which this job was skipped")
    p.add_argument("--event", default=None, help="only runs for this event (e.g. push)")
    p.add_argument(
        "--cancelled-if-last", action="store_true", help="a cancelled run counts when nothing followed it"
    )
    a = p.parse_args(argv)
    line = latest(a.workflow, a.job, a.event, a.cancelled_if_last)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
