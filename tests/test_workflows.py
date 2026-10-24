"""The GitHub workflows run the checks the docs say they run (.github/workflows/*.yml)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def steps(workflow: str, job: str) -> list[dict]:
    return yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"][job]["steps"]


def index(job_steps: list[dict], command: str) -> int:
    found = [i for i, s in enumerate(job_steps) if re.search(rf"^\s*{re.escape(command)}\s*$", s.get("run") or "", re.M)]
    assert len(found) == 1, command
    return found[0]


@pytest.mark.parametrize(("workflow", "job"), [("ci.yml", "check"), ("pages.yml", "build"), ("refresh.yml", "refresh")])
def test_the_built_data_is_validated_after_every_build(workflow, job):
    # public/data is not committed, so a `pipeline validate` before the build skipped every built-output check
    # (a margin against its outcome, a withdrawn file with an act, Council adoption steps, step order, a veto
    # outside unanimity) in CI, the deploy and the refresh
    s = steps(workflow, job)
    assert index(s, "python -m pipeline validate --built") > index(s, "python -m pipeline build")


def test_the_refresh_commits_nothing_when_the_built_data_fails_validation():
    s = steps("refresh.yml", "refresh")
    check = s[index(s, "python -m pipeline validate --built")]
    commit = next(x for x in s if x.get("name") == "Commit and push snapshot")
    assert check["id"] == "validate_built" and check["if"] == "${{ !cancelled() && steps.build.outcome == 'success' }}"
    assert "steps.validate_built.outcome != 'failure'" in commit["if"]  # a failed build still commits the snapshot
    assert "steps.validate_built.outcome == 'success'" in commit["env"]["BUILD_OK"]  # data/state only after it


def test_vitest_fails_when_it_finds_no_tests():
    runs = [s["run"] for s in steps("ci.yml", "check") if "vitest" in (s.get("run") or "")]
    assert runs == ["npx vitest run"]  # with --passWithNoTests a broken include pattern was a green step


def test_actions_are_pinned_to_commit_shas():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), (path.name, step["uses"])


def test_the_site_build_gets_the_pages_url_for_the_canonical_links():
    # scripts/prerender-routes.mjs writes <link rel="canonical"> only when SITE_URL is set, so that a local or fork build
    # does not point at the owner's host; the deploy sets it from the Pages URL, as it does for the Atom feeds
    build = next(x for x in steps("pages.yml", "build") if "npm run build" in (x.get("run") or ""))
    assert build["env"]["SITE_URL"] == "${{ steps.pages.outputs.base_url }}/"
    assert "SITE_URL" not in str(next(x for x in steps("ci.yml", "check") if "npm run build" in (x.get("run") or "")))
