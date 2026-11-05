"""The GitHub workflows run the checks the docs say they run (.github/workflows/*.yml)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
GATE = [  # the data gate: what data must pass before it reaches main (refresh) or the site (deploy), and in CI
    "python -m pipeline validate --built",
    "npx vitest run src/lib/format.test.ts",
    "node scripts/check_privacy.mjs",
]


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(name: str) -> dict:
    w = workflow(name)
    return w.get("on", w.get(True))  # YAML 1.1 reads the key `on` as true


def steps(name: str, job: str) -> list[dict]:
    return workflow(name)["jobs"][job]["steps"]


def find(job_steps: list[dict], command: str) -> list[int]:
    pattern = rf"^\s*{re.escape(command)}\s*$"
    return [i for i, s in enumerate(job_steps) if re.search(pattern, s.get("run") or "", re.M)]


def index(job_steps: list[dict], command: str) -> int:
    found = find(job_steps, command)
    assert len(found) == 1, command
    return found[0]


def named(job_steps: list[dict], name: str) -> int:
    found = [i for i, s in enumerate(job_steps) if s.get("name") == name]
    assert len(found) == 1, name
    return found[0]


def strict_build(job_steps: list[dict]) -> int:
    """The data build that must pass the data gate: strict (EU_INTEL_STRICT=1)."""
    found = [i for i in find(job_steps, "python -m pipeline build") if job_steps[i].get("env", {}).get("EU_INTEL_STRICT") == "1"]
    assert len(found) == 1
    return found[0]


def frozen() -> dict[str, str]:
    lines = (ROOT / "tests" / "frozen-data.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


# ---------------------------------------------------------------- the data gate


@pytest.mark.parametrize(("name", "job"), [("ci.yml", "check"), ("pages.yml", "build"), ("refresh.yml", "refresh")])
def test_the_data_that_is_deployed_passes_the_whole_data_gate(name, job):
    # public/data is not committed, so a `pipeline validate` before the build skipped every built-output check; the
    # refresh deployed after `validate --built` alone, and its deploy checked out the latest main, not its commit
    s = steps(name, job)
    build = strict_build(s)
    assert index(s, "python -m pipeline validate") < build  # the snapshot, before a build that would hide it
    assert build < index(s, "python -m pipeline validate --built") < index(s, "npx vitest run src/lib/format.test.ts")
    site = [i for i in find(s, "npm run build") if i > build]
    assert len(site) == 1 and index(s, "npx vitest run src/lib/format.test.ts") < site[0]
    assert site[0] < index(s, "node scripts/check_privacy.mjs")
    size = named(s, "Check Pages size limit")
    assert index(s, "node scripts/check_privacy.mjs") < size and "900000" in s[size]["run"]


def test_the_refresh_commits_nothing_before_its_data_has_passed_the_gate():
    # the refresh pushed to main after `validate --built` alone (the other checks ran later, in CI, as reports), so
    # data that failed them was live before anyone knew; it also committed the snapshot of a run whose build failed
    s = steps("refresh.yml", "refresh")
    build, push = strict_build(s), named(s, "Commit and push snapshot")
    assert s[build]["env"]["EU_INTEL_RECORD_ACTIVITY"] == "1"
    chain = [build, *(index(s, c) for c in GATE), named(s, "Check Pages size limit")]
    chain.insert(3, next(i for i in find(s, "npm run build")))  # site build, after the dated-wording check
    assert chain == sorted(chain) and chain[-1] < push
    # each step runs only once the one before it has passed, and the commit only once the last has
    for before, after in zip([named(s, "Validate snapshot per source (restore failing sources)"), *chain[:-1]], chain, strict=True):
        assert s[after]["if"] == f"${{{{ !cancelled() && steps.{s[before]['id']}.outcome == 'success' }}}}"
    assert s[push]["if"] == f"${{{{ !cancelled() && steps.{s[chain[-1]]['id']}.outcome == 'success' }}}}"
    assert "BUILD_OK" not in str(s[push]) and "paths+=(data/state)" in s[push]["run"]
    assert "TODO(quarantine" in (WORKFLOWS / "refresh.yml").read_text(encoding="utf-8")  # per-source quarantine


def test_every_deploy_opens_the_site_on_its_own_data_before_the_upload():
    # the browser tests ran only on the frozen test data, and the deploy's own check fetched six pages without running
    # them: no browser ever rendered the data being published (assessment Plan 1.5)
    job = workflow("pages.yml")["jobs"]["build"]
    s = job["steps"]
    smoke = named(s, "Smoke-test the site on its own data (Chromium)")
    assert s[smoke]["run"] == "npx playwright test --project=chromium"
    assert s[smoke]["env"] == {"E2E_LIVE": "1", "BASE_PATH": "${{ steps.pages.outputs.base_path }}/"}
    assert "if" not in s[smoke]  # a failure stops the job, so nothing is uploaded or deployed
    install = named(s, "Install Chromium for the smoke test")
    assert "npx playwright install chromium" in s[install]["run"] and "--with-deps" not in s[install]["run"]
    upload = next(i for i, x in enumerate(s) if x.get("uses", "").startswith("actions/upload-pages-artifact@"))
    assert named(s, "Check Pages size limit") < install < smoke < upload and "if" not in s[upload]
    assert job["runs-on"] == "ubuntu-24.04"  # Chromium's libraries are on that image: no apt step
    report = s[named(s, "Upload the smoke test's report")]
    assert report["if"] == "${{ failure() }}" and report["with"]["name"] == "live-smoke-report"


def test_the_live_smoke_test_runs_only_when_asked_for():
    # the browser tests on the frozen data leave it out (E2E_LIVE selects it, and only it)
    config = (ROOT / "playwright.config.ts").read_text(encoding="utf-8")
    assert "testMatch: LIVE ? LIVE_SPEC : '**/*.spec.ts'" in config and "testIgnore: LIVE ? [] : [LIVE_SPEC]" in config
    spec = (ROOT / "tests" / "e2e" / "live-smoke.spec.ts").read_text(encoding="utf-8")
    assert "test.use({ clockAtBuild: false })" in spec  # the reader's clock, not the build's
    playwright = ROOT / "node_modules" / ".bin" / "playwright"
    if not playwright.exists():
        pytest.skip("node_modules not installed")

    def listed(**env: str) -> list[str]:
        environ = {k: v for k, v in os.environ.items() if k not in ("E2E_LIVE", "CI")}
        out = subprocess.run([str(playwright), "test", "--list", "--project=chromium"], cwd=ROOT, check=True,
                             capture_output=True, text=True, env={**environ, **env}).stdout  # fmt: skip
        return sorted({m for m in re.findall(r"([\w-]+\.spec\.ts):\d+", out)})

    assert listed(E2E_LIVE="1") == ["live-smoke.spec.ts"]
    frozen_run = listed()
    assert "live-smoke.spec.ts" not in frozen_run and "smoke.spec.ts" in frozen_run


def test_vitest_fails_when_it_finds_no_tests():
    runs = [s["run"] for s in steps("ci.yml", "check") if "vitest" in (s.get("run") or "")]
    # with --passWithNoTests a broken include pattern was a green step
    assert runs == ["npx vitest run", "npx vitest run src/lib/format.test.ts"]


# ---------------------------------------------------------------- frozen test data


def test_the_frozen_test_data_names_a_commit_and_a_moment_of_its_day():
    f = frozen()
    assert re.fullmatch(r"[0-9a-f]{40}", f["commit"])
    built = datetime.fromisoformat(f["built_at"].replace("Z", "+00:00"))
    # the browser tests run in Europe/Brussels: the same calendar day as EU_INTEL_TODAY (the UTC date)
    assert f["built_at"].endswith("Z") and built.hour < 22


def test_ci_runs_the_tests_on_the_frozen_data_and_the_gate_on_the_current_data():
    # the tests that read real data pinned values of the committed snapshot, so a refresh turned main red most weeks,
    # and every Dependabot pull request with it
    s = steps("ci.yml", "check")
    use = named(s, "Use the frozen test data (tests/frozen-data.txt)")
    assert "tests/frozen-data.txt" in s[use]["run"]
    assert 'git restore --source="$commit" --staged --worktree -- data/snapshot data/state' in s[use]["run"]
    assert 'git fetch --quiet --depth=1 --no-tags origin "$commit"' in s[use]["run"]
    tests = [index(s, "python -m pytest -q"), index(s, "npx vitest run")]
    frozen_build = next(i for i in find(s, "python -m pipeline build") if i != strict_build(s))
    assert s[frozen_build]["env"] == {
        "EU_INTEL_TODAY": "${{ steps.frozen.outputs.today }}",
        "EU_INTEL_BUILT_AT": "${{ steps.frozen.outputs.built_at }}",
    }
    upload = next(i for i, x in enumerate(s) if x.get("uses", "").startswith("actions/upload-artifact@"))
    assert s[upload]["with"]["name"] == "site-dist"
    current = named(s, "Use this commit's data")
    assert "git restore --source=HEAD --staged --worktree -- data/snapshot data/state" in s[current]["run"]
    assert "rm -rf public/data dist" in s[current]["run"]
    assert use < tests[0] < frozen_build < tests[1] < upload < current < strict_build(s)
    assert "EU_INTEL_TODAY" not in str(s[current:])  # the current data is built as of today
    e2e = steps("ci.yml", "e2e")
    assert any(x.get("with", {}).get("name") == "site-dist" for x in e2e if "download-artifact" in x.get("uses", ""))
    # the local run reads the same file
    script = (ROOT / "scripts" / "test-frozen.sh").read_text(encoding="utf-8")
    assert "spec=tests/frozen-data.txt" in script and "git worktree add" in script


def test_ci_swaps_in_the_frozen_data_and_back(tmp_path):
    s = steps("ci.yml", "check")
    use_frozen = s[named(s, "Use the frozen test data (tests/frozen-data.txt)")]["run"]
    use_current = s[named(s, "Use this commit's data")]["run"]
    work = tmp_path / "repo"
    work.mkdir()
    git, commit = git_repo(work)
    old = commit({"data/snapshot/a.json": "old", "data/state/s.json": "1", "src/x.ts": "1"}, "Data refresh")
    spec = f"# the data the tests run on\ncommit={old}\nbuilt_at=2026-11-02T14:00:00Z\n"
    commit({"data/snapshot/a.json": "new", "data/snapshot/b.json": "added", "src/x.ts": "2",
            "tests/frozen-data.txt": spec}, "code and data")  # fmt: skip
    assert run_step(use_frozen, work, {}) == {"today": "2026-11-02", "built_at": "2026-11-02T14:00:00Z"}
    snapshot = work / "data" / "snapshot"
    assert (snapshot / "a.json").read_text() == "old" and not (snapshot / "b.json").exists()  # exactly that data
    assert (work / "src" / "x.ts").read_text() == "2"  # and this commit's code
    (work / "public" / "data").mkdir(parents=True)  # the frozen build
    run_step(use_current, work, {})
    assert (snapshot / "a.json").read_text() == "new" and (snapshot / "b.json").read_text() == "added"
    assert git("status", "--porcelain") == "" and not (work / "public" / "data").exists()
    (work / "tests" / "frozen-data.txt").write_text(f"commit={old[:12]}\n", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError):
        run_step(use_frozen, work, {})


def test_the_browser_tests_see_the_moment_the_data_was_built():
    fixtures = (ROOT / "tests" / "e2e" / "fixtures.ts").read_text(encoding="utf-8")
    assert "readFileSync('dist/data/meta.json'" in fixtures and "page.clock.install({ time: builtAt })" in fixtures


def test_ci_does_not_run_after_a_data_refresh():
    # with the tests on frozen data it would re-test the same code on the same data; the refresh gates its own data
    assert "workflow_run" not in triggers("ci.yml")
    assert workflow("ci.yml")["concurrency"]["group"] == (
        "ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.ref }}"
    )


def test_a_manual_ci_run_does_not_cancel_the_run_of_a_push():
    # both were in the group ci-CI-refs/heads/main: a manual run cancelled the push's run, the only kind that deploys
    # (pages.yml) and that a refresh's deploy waits for, and the watchdog ignores cancelled runs
    c = workflow("ci.yml")["concurrency"]
    assert c["cancel-in-progress"] is True and "${{ github.event_name }}" in c["group"]
    group = c["group"].replace("${{ github.workflow }}", "CI")

    def evaluate(event: str, ref: str, pr: str = "") -> str:  # the group's expression for one event
        return group.replace("${{ github.event_name }}", event).replace(
            "${{ github.event.pull_request.number || github.ref }}", pr or ref
        )

    assert evaluate("push", "refs/heads/main") != evaluate("workflow_dispatch", "refs/heads/main")
    assert evaluate("pull_request", "refs/pull/7/merge", "7") == evaluate("pull_request", "refs/pull/7/merge", "7")
    assert triggers("pages.yml")["workflow_run"]["workflows"] == ["CI"]
    assert "--event push" in steps("refresh.yml", "refresh")[named(steps("refresh.yml", "refresh"), "Deploy only code that CI has passed")]["run"]


# ---------------------------------------------------------------- paths to production


def test_code_is_deployed_only_after_ci_passes_on_main_and_a_refresh_deploys_its_own_commit():
    # a push to main used to start the deploy alongside CI; the refresh used to start it through workflow_run, which
    # built the latest main (untested code included) and ran alongside CI
    on = triggers("pages.yml")
    assert "push" not in on and "workflow_dispatch" in on
    assert on["workflow_run"] == {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]}
    assert on["workflow_call"]["inputs"]["ref"]["required"] is True
    assert workflow("ci.yml")["name"] == "CI" and workflow("refresh.yml")["name"] == "Data refresh"
    condition = " ".join(workflow("pages.yml")["jobs"]["build"]["if"].split())
    # CI also runs on pull requests (whose branch can be called main, in a fork) and by hand without the browser tests
    assert (
        "(github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.event == 'push')" in condition
    )
    assert "inputs.ref != ''" in condition  # in a called run, github.event_name is the refresh's own event
    checkout = steps("pages.yml", "build")[0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["ref"] == "${{ inputs.ref || github.event.workflow_run.head_sha || '' }}"
    # history without file contents: enough to compare with main (fetch-depth: 50 fetched every refresh's files)
    assert checkout["with"]["fetch-depth"] == 0 and checkout["with"]["filter"] == "blob:none"

    refresh = workflow("refresh.yml")["jobs"]
    deploy = refresh["deploy"]
    assert deploy["uses"] == "./.github/workflows/pages.yml"
    assert deploy["with"] == {"ref": "${{ needs.refresh.outputs.sha }}"}
    assert deploy["needs"] == "refresh" and deploy["if"] == "${{ needs.refresh.outputs.deploy == 'true' }}"
    assert deploy["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    assert refresh["refresh"]["outputs"] == {
        "sha": "${{ steps.push.outputs.sha }}",
        "deploy": "${{ steps.tested.outputs.deploy }}",
    }
    s = steps("refresh.yml", "refresh")
    assert named(s, "Commit and push snapshot") < named(s, "Deploy only code that CI has passed")
    assert 'echo "sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"' in s[named(s, "Commit and push snapshot")]["run"]


def git_repo(path: Path):
    def git(*args: str) -> str:
        cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", *args]
        return subprocess.run(cmd, cwd=path, check=True, capture_output=True, text=True).stdout.strip()

    def commit(files: dict[str, str], message: str) -> str:
        for name, body in files.items():
            (path / name).parent.mkdir(parents=True, exist_ok=True)
            (path / name).write_text(body, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", message)
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    return git, commit


def run_step(script: str, cwd: Path, env: dict[str, str]) -> dict[str, str]:
    """Run a step's script as Actions does (bash -e); returns what it wrote to $GITHUB_OUTPUT."""
    out = cwd.parent / f"{cwd.name}.github_output"  # outside the repository the step runs in
    out.write_text("", encoding="utf-8")
    environ = {**os.environ, "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": os.devnull, **env}
    subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=environ, check=True, capture_output=True)
    return dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines() if "=" in line)


def test_a_deploy_builds_main_only_when_main_added_nothing_but_data(tmp_path):
    # a data refresh can land on main while CI runs on a code commit: that deploy must not take the new data off the
    # site, nor publish code CI has not tested
    s = steps("pages.yml", "build")
    script = s[named(s, "Build the newest data on the tested code")]["run"]
    work = tmp_path / "repo"
    work.mkdir()
    git, commit = git_repo(work)

    assert s[named(s, "Build the newest data on the tested code")]["env"] == {"MAIN_SHA": "${{ github.sha }}"}

    def build(target: str, main: str) -> str:  # checkout of the commit to deploy; main as of the run's event
        git("checkout", "-q", "--detach", target)
        built = run_step(script, work, {"MAIN_SHA": main})["sha"]
        assert built == git("rev-parse", "HEAD")
        return built

    tested = commit({"src/app.ts": "1", "data/curated/a.yaml": "a"}, "code")
    refreshed = commit({"data/snapshot/x.json": "[1]", "data/state/s.json": "{}"}, "Data refresh")
    assert build(tested, refreshed) == refreshed  # CI's commit, then a refresh: the refreshed data
    assert build(refreshed, refreshed) == refreshed
    untested = commit({"data/curated/a.yaml": "b"}, "a curated correction")  # curated data is tested like code
    assert build(refreshed, untested) == refreshed  # the refresh's deploy, after a code push: not that code
    assert build(untested, untested) == untested
    git("checkout", "-q", "--orphan", "other")
    unrelated = commit({"src/app.ts": "2"}, "history rewritten")
    assert build(refreshed, unrelated) == refreshed


def fake_gh(tmp_path: Path, output: str) -> dict[str, str]:
    """A `gh` on PATH that prints `output` whatever it is asked."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "gh").write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\n", encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


def test_a_refresh_deploys_only_code_that_ci_has_passed(tmp_path):
    # the refresh deployed the latest main, including a code commit whose CI had failed or had not finished
    s = steps("refresh.yml", "refresh")
    script = s[named(s, "Deploy only code that CI has passed")]["run"]
    assert "gh run list --workflow ci.yml --branch main --event push --status success" in script
    work = tmp_path / "repo"
    work.mkdir()
    git, commit = git_repo(work)
    tested = commit({"src/app.ts": "1"}, "code")
    pushed = commit({"data/snapshot/x.json": "[1]"}, "Data refresh")

    def deploy(ci_passed_on: list[str], ref: str = "refs/heads/main") -> str:
        env = {**fake_gh(tmp_path, "\n".join(ci_passed_on)), "SHA": pushed, "GITHUB_REF": ref}
        return run_step(script, work, env)["deploy"]

    assert deploy([tested]) == "true"
    assert deploy([pushed]) == "true"
    assert deploy([]) == "false"
    assert deploy(["0" * 40]) == "false"  # unknown to this clone
    assert deploy([tested], ref="refs/heads/other") == "false"  # the github-pages environment takes main only
    git("checkout", "-q", "-b", "side", tested)
    other = commit({"src/app.ts": "2"}, "other code")
    assert deploy([other]) == "false"


# ---------------------------------------------------------------- schedules


def test_the_refresh_schedule_retries_and_runs_a_monthly_full_refresh(tmp_path):
    # the Monday cron started up to 8 h late, and a full refresh ran only by hand
    crons = [c["cron"] for c in triggers("refresh.yml")["schedule"]]
    assert len(crons) == 2 and all(not c.startswith("0 ") for c in crons)
    w = workflow("refresh.yml")
    assert w["concurrency"] == {"group": "refresh", "cancel-in-progress": False}
    assert w["jobs"]["refresh"]["needs"] == "plan" and w["jobs"]["refresh"]["if"] == "${{ needs.plan.outputs.run == 'true' }}"
    fetch = steps("refresh.yml", "refresh")[named(steps("refresh.yml", "refresh"), "Fetch official sources")]
    assert fetch["env"]["EU_INTEL_FULL_REFRESH"] == "${{ needs.plan.outputs.full }}"
    script = steps("refresh.yml", "plan")[0]["run"]
    now = datetime.now(UTC)

    def plan(event: str, last_change: datetime | None, full_input: str = "") -> dict[str, str]:
        stamp = last_change.strftime("%Y-%m-%dT%H:%M:%SZ") if last_change else ""
        env = {**fake_gh(tmp_path, stamp), "EVENT": event, "FULL_INPUT": full_input, "RECENT_HOURS": "20",
               "GITHUB_REPOSITORY": "o/r"}  # fmt: skip
        return run_step(script, tmp_path, env)

    first_week = "1" if now.day <= 7 else ""
    assert plan("schedule", now - timedelta(hours=3)) == {"run": "false"}
    assert plan("schedule", now - timedelta(hours=30)) == {"run": "true", "full": first_week}
    assert plan("schedule", None) == {"run": "true", "full": first_week}
    assert plan("workflow_dispatch", now - timedelta(hours=1)) == {"run": "true", "full": ""}
    assert plan("workflow_dispatch", now, full_input="true") == {"run": "true", "full": "1"}


# ---------------------------------------------------------------- alerting


def test_only_the_watchdog_writes_issues_and_it_writes_nothing_else():
    # failures were only ::warning lines: the repository had no issue, no alert of any kind
    for path in WORKFLOWS.glob("*.yml"):
        w = yaml.safe_load(path.read_text(encoding="utf-8"))
        grants = [w.get("permissions") or {}, *((j.get("permissions") or {}) for j in w["jobs"].values())]
        assert ("issues" in str(grants)) == (path.name == "watchdog.yml"), path.name
    w = workflow("watchdog.yml")
    assert w["permissions"] == {"contents": "read"}
    assert w["jobs"]["health"]["permissions"] == {"contents": "read", "issues": "write", "actions": "read"}
    on = triggers("watchdog.yml")
    minute, hour, *rest = on["schedule"][0]["cron"].split()
    assert rest == ["*", "*", "*"] and minute not in ("0", "00", "30") and hour.isdigit()  # daily, off the hour
    assert on["workflow_run"] == {"workflows": ["CI", "Data refresh"], "types": ["completed"], "branches": ["main"]}
    s = steps("watchdog.yml", "health")
    check = s[named(s, "Check")]["run"]
    assert '"${site%/}/data/meta.json"' in check and "python -m pipeline health" in check
    assert "latest refresh.yml" in check and "latest ci.yml push" in check
    issue = s[named(s, "Open, update or close the issue")]["run"]
    for command in ("gh issue create", "gh issue edit", "gh issue close", 'gh label create "$LABEL"'):
        assert command in issue


def test_the_health_check_lists_failed_and_stale_sources_and_the_workflows_problems(tmp_path, capsys):
    from pipeline.__main__ import main

    now = datetime.now(UTC)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "ep_votes": {"status": "ok", "fetched_at": iso(now - timedelta(days=1))},
        "train": {"status": "failed", "fetched_at": iso(now - timedelta(days=14)), "attempted_at": iso(now)},
        "council": {"status": "ok", "fetched_at": iso(now - timedelta(days=12))},
    }), encoding="utf-8")  # fmt: skip
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"built_at": iso(now), "sources": [{"id": "ep_votes", "fetched_at": iso(now - timedelta(days=10))}]}))

    assert main(["health", "--manifest", str(manifest), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert [p["key"] for p in report["problems"]] == ["source:council", "source:train"]  # stale; failed (not stale)
    assert main(["health", "--manifest", str(manifest), "--meta", str(meta), "--problem", "ci=CI fails", "--markdown"]) == 1
    body = capsys.readouterr().out
    assert body.startswith("<!-- data-health: ci,source:council,source:train,site -->\n")
    assert "- CI fails" in body and "**The live site's data is overdue**" in body
    healthy = tmp_path / "healthy.json"
    healthy.write_text(json.dumps({"ep_votes": {"status": "partial", "fetched_at": iso(now)}}), encoding="utf-8")
    assert main(["health", "--manifest", str(healthy), "--meta", str(meta), "--max-age-days", "11"]) == 0
    assert main(["health", "--manifest", str(healthy), "--problem", "not a key=x"]) == 2


# ---------------------------------------------------------------- supply chain


def test_actions_are_pinned_to_commit_shas():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].values():
            if "uses" in job:  # a reusable workflow: only this repository's own
                assert job["uses"].startswith("./.github/workflows/"), (path.name, job["uses"])
            for step in job.get("steps", []):
                if "uses" in step:
                    assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), (path.name, step["uses"])


def test_the_site_build_gets_the_pages_url_for_the_canonical_links():
    # scripts/prerender-routes.mjs writes <link rel="canonical"> only when SITE_URL is set, so that a local or fork build
    # does not point at the owner's host; the deploy sets it from the Pages URL, as it does for the Atom feeds
    build = next(x for x in steps("pages.yml", "build") if "npm run build" in (x.get("run") or ""))
    assert build["env"]["SITE_URL"] == "${{ steps.pages.outputs.base_url }}/"
    for name, job in [("ci.yml", "check"), ("refresh.yml", "refresh")]:
        assert "SITE_URL" not in str([x for x in steps(name, job) if "npm run build" in (x.get("run") or "")])


@pytest.mark.parametrize(
    ("name", "job"), [("refresh.yml", "refresh"), ("pages.yml", "build"), ("ci.yml", "check"), ("watchdog.yml", "health")]
)
def test_python_packages_are_installed_from_the_hashed_requirements(name, job):
    # the refresh holds a token that can push to main: it installs only the pinned files, as the deploy and CI do
    s = steps(name, job)
    index(s, "python -m pip install --require-hashes -r requirements.txt")
    if name != "ci.yml":  # nothing else: the pipeline runs from the checkout
        assert "pip install -e" not in "\n".join(x.get("run") or "" for x in s)


def test_the_hashed_requirements_pin_every_runtime_dependency_within_pyproject():
    from packaging.requirements import Requirement

    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    entries = [b for b in re.split(r"^(?=\S)", text, flags=re.M) if b and not b.startswith("#")]

    def norm(name: str) -> str:  # a distribution name as PEP 503 normalises it
        return re.sub(r"[-_.]+", "-", name).lower()

    pins = {}
    for entry in entries:
        m = re.match(r"([A-Za-z0-9_.-]+)==(\S+) \\\n", entry)
        assert m and "--hash=sha256:" in entry, entry.splitlines()[0]
        pins[norm(m[1])] = m[2]
    deps = re.search(r"^dependencies = \[(.*?)^\]", (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M | re.S)
    for dep in re.findall(r'"([^"]+)"', deps.group(1)):
        req = Requirement(dep)
        assert req.specifier.contains(pins[norm(req.name)]), dep


def test_dependabot_bumps_vite_with_its_react_plugin():
    # vite 8 needs @vitejs/plugin-react 6: separate pull requests each failed alone
    npm = next(u for u in yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())["updates"] if u["package-ecosystem"] == "npm")
    groups = list(npm["groups"].values())
    vite = [g for g in groups if "vite" in g.get("patterns", [])]
    assert len(vite) == 1 and "@vitejs/plugin-react" in vite[0]["patterns"]
    assert groups.index(vite[0]) < next(i for i, g in enumerate(groups) if "dependency-type" in g)  # first match wins
