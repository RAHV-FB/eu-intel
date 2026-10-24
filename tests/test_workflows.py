"""The GitHub workflows run the checks the docs say they run (.github/workflows/*.yml)."""

from __future__ import annotations

import os
import re
import subprocess
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


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_code_is_deployed_only_after_ci_passes_on_main():
    # a push to main used to start the deploy alongside CI, so a commit whose tests failed was published anyway
    pages = workflow("pages.yml")
    on = pages.get("on", pages.get(True))  # YAML 1.1 reads the key `on` as true
    assert "push" not in on
    assert on["workflow_run"] == {"workflows": ["CI", "Data refresh"], "types": ["completed"], "branches": ["main"]}
    assert workflow("ci.yml")["name"] == "CI" and workflow("refresh.yml")["name"] == "Data refresh"
    condition = " ".join(pages["jobs"]["build"]["if"].split())
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    # CI also runs on pull requests (whose branch can be called main, in a fork) and by hand without the browser tests
    assert "github.event.workflow_run.name == 'Data refresh' || github.event.workflow_run.event == 'push'" in condition
    s = steps("pages.yml", "build")
    choose = next(i for i, x in enumerate(s) if x.get("name") == "Build the commit CI tested")
    assert s[choose]["env"]["CI_SHA"] == "${{ github.event.workflow_run.head_sha }}"
    assert 'git checkout --quiet --detach "$CI_SHA"' in s[choose]["run"]
    # main is built instead only when the commits since change nothing but the data a refresh commits
    assert "':(exclude)data/snapshot' ':(exclude)data/state'" in s[choose]["run"]
    assert s[choose - 1]["uses"].startswith("actions/checkout@")
    assert choose < index(s, "python -m pipeline build")


def test_the_deploy_after_ci_builds_main_only_when_main_added_nothing_but_data(tmp_path):
    # a data refresh can land on main while CI runs on a code commit: that deploy must not take the new data off the
    # site, nor publish code CI has not tested
    script = next(x for x in steps("pages.yml", "build") if x.get("name") == "Build the commit CI tested")["run"]

    def git(*args: str) -> str:
        cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", *args]
        return subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    def commit(files: dict[str, str], message: str) -> str:
        for name, body in files.items():
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text(body, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", message)
        return git("rev-parse", "HEAD")

    def build(ci_sha: str) -> str:  # the step as Actions runs it (bash -e), after checking out main
        subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, env={**os.environ, "CI_SHA": ci_sha}, check=True,
                       capture_output=True)  # fmt: skip
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    tested = commit({"src/app.ts": "1", "data/curated/a.yaml": "a"}, "code")
    refreshed = commit({"data/snapshot/x.json": "[1]", "data/state/s.json": "{}"}, "Data refresh")
    assert build(tested) == refreshed
    untested = commit({"data/curated/a.yaml": "b"}, "a curated correction")  # curated data is tested like code
    git("checkout", "-q", "main")
    assert build(refreshed) == refreshed and untested != refreshed
    git("checkout", "-q", "main")
    assert build(untested) == untested


def test_the_deploy_checks_the_dated_wording_of_the_built_data():
    # the refreshed data never met the vitest checks: format.test.ts's, which pin no snapshot values, now run on it
    s = steps("pages.yml", "build")
    check = index(s, "npx vitest run src/lib/format.test.ts")
    assert index(s, "python -m pipeline validate --built") < check < index(s, "npm run build")
