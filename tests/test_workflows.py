"""The GitHub workflows run the checks the docs say they run (.github/workflows/*.yml)."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
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


def test_the_browser_tests_install_their_browser_with_bounded_retries(tmp_path):
    # `playwright install --with-deps` downloads the browsers' OS packages from the Ubuntu mirror (WebKit: 181); on 5 Nov
    # 2026 two e2e jobs were cancelled at their 20-minute limit mid-install, and a refresh deploys only after a green CI
    # run. The Playwright image avoided the install but resolved the site's fonts differently (81-character lines,
    # Firefox target-size findings), so the job stays on the runner image: bounded attempts that resume, a longer limit.
    w = workflow("ci.yml")
    e2e = w["jobs"]["e2e"]
    assert "container" not in e2e and e2e["runs-on"] == "ubuntu-24.04" and e2e["timeout-minutes"] >= 40
    s = e2e["steps"]
    step = s[named(s, "Install ${{ matrix.browser }} for Playwright")]
    assert step["env"]["BROWSER"] == "${{ matrix.browser }}"
    assert "timeout 600 npx playwright install --with-deps \"$BROWSER\"" in step["run"]
    assert named(s, "Install ${{ matrix.browser }} for Playwright") < named(s, "Run Playwright")
    # the packages apt downloaded are kept between runs (the mirror once served WebKit's 114 MB at about 50 KB/s)
    cache = s[named(s, "Restore the browsers' OS packages")]
    assert re.fullmatch(r"actions/cache@[0-9a-f]{40}", cache["uses"])  # pinned, like every action here
    assert cache["with"]["path"] == "~/apt-archives" and "${{ matrix.browser }}" in cache["with"]["key"]
    assert "hashFiles('package-lock.json')" in cache["with"]["key"]
    assert named(s, "Restore the browsers' OS packages") < named(s, "Install ${{ matrix.browser }} for Playwright")

    # the attempts, with stand-ins: an npx that fails twice, then succeeds, is tried three times; one that always fails,
    # fails. A `sudo` that only logs: the step must not touch this machine's apt.
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    count, log, home = tmp_path / "count", tmp_path / "log", tmp_path / "home"
    home.mkdir()
    (bin_ / "npx").write_text(f"#!/bin/sh\necho npx >> {log}\necho x >> {count}\n[ $(wc -l < {count}) -ge 3 ]\n")
    (bin_ / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (bin_ / "sudo").write_text(f'#!/bin/sh\necho "sudo $*" >> {log}\n[ "$1" = tee ] && cat > "{tmp_path}/apt.conf"\nexit 0\n')
    for f in ("npx", "sleep", "sudo"):
        (bin_ / f).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(home), "BROWSER": "webkit",
           "APT_CONF": step["env"]["APT_CONF"]}  # fmt: skip
    run = lambda: subprocess.run(["bash", "-eo", "pipefail", "-c", step["run"]], env=env, capture_output=True)  # noqa: E731
    assert run().returncode == 0
    assert count.read_text().count("x") == 3
    conf = (tmp_path / "apt.conf").read_text()
    assert f'Dir::Cache::Archives "{home}/apt-archives/";' in conf and "Acquire::Retries" in conf
    assert (home / "apt-archives" / "partial").is_dir()
    calls = log.read_text().splitlines()
    # a timed-out attempt's apt-get (run with sudo) kept dpkg's lock, so the next attempts failed at once (5 Nov 2026):
    # before each retry it is stopped and dpkg finishes its work
    first, second = calls.index("npx"), calls.index("npx", calls.index("npx") + 1)
    between = calls[first + 1 : second]
    assert "sudo pkill -x apt-get" in between and "sudo dpkg --configure -a" in between
    assert between.index("sudo pkill -x apt-get") < between.index("sudo dpkg --configure -a")
    assert calls[-1].startswith("sudo chown -R ") and calls[-1].endswith(f"{home}/apt-archives")  # the cache can read them
    count.write_text("")
    (bin_ / "npx").write_text("#!/bin/sh\nexit 1\n")
    assert run().returncode == 1


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
    assert "--event push" in CI_PASSED.read_text(encoding="utf-8")  # the refresh's and the rebuild's deploy check


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


FAKE_CURL = r"""#!/usr/bin/env python3
# The public site: HTML for the routes, data/meta.json whose built_at becomes the new one after SWITCH_AFTER requests.
import json, os, sys
args, out = sys.argv[1:], None
if "--output" in args:
    out = args[args.index("--output") + 1]
url = [a for a in args if a.startswith("http")][-1]
with open(os.environ["CURL_LOG"], "a") as log:
    log.write(url + "\n")
if "data/meta.json" in url:
    count_file = os.environ["CURL_LOG"] + ".meta"
    n = int(open(count_file).read()) + 1 if os.path.exists(count_file) else 1
    open(count_file, "w").write(str(n))
    built = os.environ["NEW_BUILT_AT"] if n > int(os.environ["SWITCH_AFTER"]) else "2026-01-01T00:00:00Z"
    body = json.dumps({"built_at": built, "counts": {"dossiers": 1, "ep_votes": 1}})
else:
    body = "<html><title>EU Legislative Intelligence</title>Data insights</html>"
if out:
    open(out, "w").write(body)
else:
    sys.stdout.write(body)
"""


def test_a_deploy_fails_unless_the_public_url_serves_what_it_built(tmp_path):
    # the check passed on whatever the public URL served, the previous deployment included (Pages caches 10 minutes)
    w = workflow("pages.yml")
    assert w["jobs"]["build"]["outputs"]["built_at"] == "${{ steps.record.outputs.built_at }}"
    build = w["jobs"]["build"]["steps"]
    upload = next(i for i, x in enumerate(build) if x.get("uses", "").startswith("actions/upload-pages-artifact@"))
    assert named(build, "Smoke-test the site on its own data (Chromium)") < named(build, "Record what is deployed") < upload
    verify = steps("pages.yml", "deploy")[named(steps("pages.yml", "deploy"), "Verify published site and deep links")]
    assert verify["env"]["BUILT_AT"] == "${{ needs.build.outputs.built_at }}"
    bin_dir, log = tmp_path / "bin-curl", tmp_path / "curl.log"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(FAKE_CURL, encoding="utf-8")
    (bin_dir / "curl").chmod(0o755)

    def verify_with(switch_after: int) -> bool:
        for f in (log, Path(f"{log}.meta")):
            f.unlink(missing_ok=True)
        log.write_text("", encoding="utf-8")
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "CURL_LOG": str(log),
               "PAGE_URL": "https://example.org/eu-intel/", "BUILT_AT": "2026-11-05T14:19:00Z",
               "NEW_BUILT_AT": "2026-11-05T14:19:00Z", "SWITCH_AFTER": str(switch_after), "GITHUB_RUN_ID": "5",
               "GITHUB_RUN_ATTEMPT": "1", "VERIFY_ATTEMPTS": "4", "VERIFY_SLEEP": "0", "COMMIT": "9" * 40,
               "GITHUB_STEP_SUMMARY": os.devnull}  # fmt: skip
        return subprocess.run(["bash", "-e", "-c", verify["run"]], cwd=tmp_path, env=env, capture_output=True).returncode == 0

    assert verify_with(switch_after=3)  # the old deployment twice more (the routes' check fetched it once), then this one
    urls = log.read_text(encoding="utf-8").splitlines()
    assert "https://example.org/eu-intel/data/meta.json?deploy=5-1-2" in urls  # each attempt past the cache
    assert not verify_with(switch_after=10)  # never served: the release fails


def test_the_deployed_site_names_the_commit_it_was_built_from(tmp_path):
    # GitHub records a refresh's deploy under the commit the refresh started from (github.sha in the called workflow),
    # e.g. 43342c0 for the data of 9aba253 on 5 Nov 2026: meta.json and the job summaries say what was built
    s = steps("pages.yml", "build")
    build = s[strict_build(s)]["run"]
    assert build.index("EU_INTEL_COMMIT=$(git rev-parse HEAD)") < build.index("export EU_INTEL_COMMIT") < build.index(
        "python -m pipeline build"
    )
    assert named(s, "Build the newest data on the tested code") < strict_build(s)  # after the checkout of main, if any
    assert workflow("pages.yml")["jobs"]["build"]["outputs"]["commit"] == "${{ steps.record.outputs.commit }}"
    record = s[named(s, "Record what is deployed")]["run"]
    work = tmp_path / "repo"
    work.mkdir()
    git, commit = git_repo(work)
    sha = commit({"src/app.ts": "1"}, "code")
    (work / "dist" / "data").mkdir(parents=True)
    summary = tmp_path / "summary.md"

    def run(meta_commit: str | None) -> dict[str, str]:
        meta = {"built_at": "2026-11-05T14:19:00Z", "commit": meta_commit}
        (work / "dist" / "data" / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return run_step(record, work, {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_EVENT_NAME": "workflow_dispatch"})

    assert run(sha) == {"built_at": "2026-11-05T14:19:00Z", "commit": sha}
    assert f"Built commit `{sha}`" in summary.read_text(encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError):  # a build that did not record its commit is not uploaded
        run(None)
    verify = steps("pages.yml", "deploy")[named(steps("pages.yml", "deploy"), "Verify published site and deep links")]
    assert verify["env"]["COMMIT"] == "${{ needs.build.outputs.commit }}" and "Deployed commit" in verify["run"]


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


CI_PASSED = ROOT / "scripts" / "ci-passed.sh"


def with_ci_passed_script(work: Path) -> None:
    """scripts/ci-passed.sh in a test repository (untracked), where the steps that call it run."""
    (work / "scripts").mkdir(exist_ok=True)
    shutil.copy(CI_PASSED, work / "scripts" / "ci-passed.sh")


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
    assert script == 'scripts/ci-passed.sh "$SHA"'  # shared with the daily rebuild (rebuild.yml)
    assert "gh run list --workflow ci.yml --branch main --event push --status success" in CI_PASSED.read_text()
    work = tmp_path / "repo"
    work.mkdir()
    git, commit = git_repo(work)
    with_ci_passed_script(work)
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


def test_the_refresh_pushes_with_a_token_it_never_stores_and_reapplies_its_data_on_a_moved_main(tmp_path):
    # the checkout kept the push token in .git/config for the whole job, which runs npm packages (npm ci, vitest, the
    # site build) since the data gate moved into it
    s = steps("refresh.yml", "refresh")
    assert s[0]["uses"].startswith("actions/checkout@") and s[0]["with"]["persist-credentials"] is False
    step = s[named(s, "Commit and push snapshot")]
    assert step["env"] == {"PUSH_TOKEN": "${{ github.token }}"}
    assert all("PUSH_TOKEN" not in str(x.get("env", {})) for x in s if x is not step)

    def sh(*args: str, cwd: Path = tmp_path) -> str:
        cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", *args]
        return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    origin = tmp_path / "origin.git"
    sh("init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    seed.mkdir()
    _, commit = git_repo(seed)
    manifest = {"a": {"fetched_at": "1"}, "b": {"fetched_at": "1"}}
    commit({"data/snapshot/_manifest.json": json.dumps(manifest), "data/snapshot/a/x.json": "1",
            "data/snapshot/b/y.json": "1", "src/app.ts": "1"}, "base")  # fmt: skip
    sh("push", "-q", str(origin), "HEAD:main", cwd=seed)
    job, other = tmp_path / "job", tmp_path / "other"
    for clone in (job, other):
        sh("clone", "-q", str(origin), str(clone))
    # this run refreshed source a
    (job / "data/snapshot/a/x.json").write_text("2", encoding="utf-8")
    (job / "data/snapshot/_manifest.json").write_text(json.dumps(manifest | {"a": {"fetched_at": "2"}}), encoding="utf-8")
    # meanwhile main moved: source b by hand, and code
    (other / "data/snapshot/b/y.json").write_text("3", encoding="utf-8")
    (other / "data/snapshot/_manifest.json").write_text(json.dumps(manifest | {"b": {"fetched_at": "3"}}), encoding="utf-8")
    (other / "src/app.ts").write_text("3", encoding="utf-8")
    sh("commit", "-q", "-am", "moved", cwd=other)
    sh("push", "-q", "origin", "HEAD:main", cwd=other)
    # a `git` that logs its arguments, then runs git
    shim, log = tmp_path / "shim", tmp_path / "git.log"
    shim.mkdir()
    real = subprocess.run(["sh", "-c", "command -v git"], capture_output=True, text=True, check=True).stdout.strip()
    (shim / "git").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec {real} "$@"\n', encoding="utf-8")
    (shim / "git").chmod(0o755)
    env = {"PUSH_TOKEN": "t0ken", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r",
           "GITHUB_RUN_ID": "1", "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"}  # fmt: skip

    pushed = run_step(step["run"], job, env)["sha"]

    show = lambda path: sh("show", f"main:{path}", cwd=origin)  # noqa: E731
    assert sh("rev-parse", "main", cwd=origin) == pushed
    assert (show("data/snapshot/a/x.json"), show("data/snapshot/b/y.json"), show("src/app.ts")) == ("2", "3", "3")
    assert json.loads(show("data/snapshot/_manifest.json")) == {"a": {"fetched_at": "2"}, "b": {"fetched_at": "3"}}
    header = "http.https://github.com/.extraheader=AUTHORIZATION: basic " + base64.b64encode(b"x-access-token:t0ken").decode()
    calls = log.read_text(encoding="utf-8").splitlines()
    subcommand = lambda call: call.replace(f"-c {header}", "").split()[0]  # noqa: E731
    with_token = sorted({subcommand(c) for c in calls if header in c})
    assert with_token == ["fetch", "push", "reset"]  # the push, and the re-apply's fetch and reset
    assert {subcommand(c) for c in calls if header not in c} >= {"add", "commit", "config"}
    assert "t0ken" not in (job / ".git" / "config").read_text(encoding="utf-8")


def test_the_daily_rebuild_deploys_main_once_its_code_passed_ci_and_commits_nothing(tmp_path):
    # statuses are written at build time while their explanations follow the reader's date: between weekly refreshes
    # 2025/0380 read "Published, not yet in force" beside "It entered into force on 17 November 2026"
    w = workflow("rebuild.yml")
    text = (WORKFLOWS / "rebuild.yml").read_text(encoding="utf-8")
    assert w["name"] == "Daily rebuild" and "workflow_dispatch" in triggers("rebuild.yml")
    minute, hour, *rest = triggers("rebuild.yml")["schedule"][0]["cron"].split()
    assert rest == ["*", "*", "*"] and minute.isdigit() and int(minute) not in (0, 30)
    assert int(hour) not in range(13, 18)  # not 06-09 in the Pacific (13-16 UTC in summer, 14-17 in winter)
    assert w["permissions"] == {"contents": "read"} and w["concurrency"] == {"group": "rebuild", "cancel-in-progress": False}
    assert "contents: write" not in text and "git push" not in text and "git commit" not in text  # it commits nothing
    plan, deploy = w["jobs"]["plan"], w["jobs"]["deploy"]
    assert plan["permissions"] == {"contents": "read", "actions": "read"}
    assert plan["steps"][0]["with"]["persist-credentials"] is False and plan["steps"][0]["with"]["ref"] == "main"
    assert deploy["uses"] == "./.github/workflows/pages.yml" and deploy["with"] == {"ref": "${{ needs.plan.outputs.sha }}"}
    assert deploy["if"] == "${{ needs.plan.outputs.deploy == 'true' }}" and deploy["needs"] == "plan"
    assert deploy["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    step = plan["steps"][named(plan["steps"], "Deploy only if no refresh is running and CI has passed on main's code")]
    work = tmp_path / "repo"
    work.mkdir()
    _, commit = git_repo(work)
    older = commit({"src/app.ts": "1"}, "code")
    main = commit({"src/app.ts": "2", "data/snapshot/x.json": "[1]"}, "code and data")
    data_only = commit({"data/snapshot/x.json": "[2]"}, "Data refresh")
    with_ci_passed_script(work)

    def decide(refresh_statuses: list[str], ci_passed_on: list[str], sha: str = data_only) -> str:
        runs = {"refresh.yml": [{"status": s} for s in refresh_statuses], "ci.yml": [{"headSha": c} for c in ci_passed_on]}
        env, _ = gh_serving(tmp_path, {"runs": runs, "jobs": {}})
        return run_step(step["run"], work, {**env, "SHA": sha, "GITHUB_REF": "refs/heads/main"})["deploy"]

    assert decide(["completed"], [main]) == "true"  # main = CI's commit plus a data refresh
    assert decide(["in_progress", "completed"], [main]) == "false"  # that refresh deploys
    assert decide(["queued"], [main]) == "false"
    assert decide([], [older]) == "false"  # main's code has not passed CI (yet)
    assert decide([], []) == "false"


# ---------------------------------------------------------------- schedules


def test_the_refresh_schedule_retries_and_runs_a_monthly_full_refresh(tmp_path):
    # the Monday cron started up to 8 h late, and a full refresh ran only by hand
    crons = [c["cron"] for c in triggers("refresh.yml")["schedule"]]
    assert len(crons) == 3 and all(not c.startswith("0 ") for c in crons)
    w = workflow("refresh.yml")
    assert w["concurrency"] == {"group": "refresh", "cancel-in-progress": False}
    assert w["jobs"]["refresh"]["needs"] == "plan" and w["jobs"]["refresh"]["if"] == "${{ needs.plan.outputs.run == 'true' }}"
    fetch = steps("refresh.yml", "refresh")[named(steps("refresh.yml", "refresh"), "Fetch official sources")]
    assert fetch["env"]["EU_INTEL_FULL_REFRESH"] == "${{ needs.plan.outputs.full }}"
    plan_step = steps("refresh.yml", "plan")[0]
    script = plan_step["run"]
    from pipeline.freshness import CORE_SOURCES

    assert plan_step["env"]["CORE_SOURCES"].split() == list(CORE_SOURCES)
    now = datetime.now(UTC)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

    def plan(event: str, manifest: dict | None, full_input: str = "", schedule: str = "") -> dict[str, str]:
        # `gh api` answers with main's manifest; None: it fails
        env = fake_gh(tmp_path, json.dumps(manifest)) if manifest is not None else failing_gh(tmp_path)
        env |= {"EVENT": event, "FULL_INPUT": full_input, "RECENT_HOURS": "20", "GITHUB_REPOSITORY": "o/r",
                "SCHEDULE": (schedule or crons[0]) if event == "schedule" else "",  # a Monday run by default
                **{k: plan_step["env"][k] for k in ("CORE_SOURCES", "LIGHT_SCHEDULE", "LIGHT_SOURCES")}}  # fmt: skip
        return run_step(script, tmp_path, env)

    def manifest(core_hours: float, **other_hours: float) -> dict:
        ages = {s: core_hours for s in CORE_SOURCES} | other_hours
        return {s: {"status": "ok", "fetched_at": iso(now - timedelta(hours=h))} for s, h in ages.items()}

    first_week = "1" if now.day <= 7 else ""
    assert plan("schedule", manifest(3)) == {"run": "false"}
    assert plan("schedule", manifest(30)) == {"run": "true", "full": first_week}
    # a commit of other data (a manual refresh of one source, a restore) no longer stops the weekly run
    assert plan("schedule", manifest(30, train=1, optouts=1)) == {"run": "true", "full": first_week}
    assert plan("schedule", manifest(3, train=24 * 14)) == {"run": "false"}  # the Train failing does not keep it going
    # one core source that failed in the first run (it keeps its old retrieval): the second run retries
    retry = manifest(3) | {"council": {"status": "failed", "fetched_at": iso(now - timedelta(days=7))}}
    assert plan("schedule", retry) == {"run": "true", "full": first_week}
    assert plan("schedule", manifest(3) | {"eurlex": {"status": "failed", "fetched_at": None}})["run"] == "true"
    assert plan("schedule", {}) == {"run": "true", "full": first_week}
    assert plan("schedule", None) == {"run": "true", "full": first_week}  # the API failed: run rather than skip a week
    assert plan("workflow_dispatch", manifest(1)) == {"run": "true", "full": ""}
    assert plan("workflow_dispatch", manifest(0), full_input="true") == {"run": "true", "full": "1"}
    assert plan("schedule", manifest(30), schedule=crons[1]) == {"run": "true", "full": first_week}  # the Monday retry


def test_a_friday_run_refreshes_the_core_sources_and_the_planned_dates_only(tmp_path):
    # 97.7% of Parliament's recorded votes fall Tuesday to Thursday: with Mondays only, a vote reached the site after
    # about 5 days on average. The Friday run fetches the core sources and the planned dates (agenda), never in full.
    from pipeline.__main__ import SOURCES
    from pipeline.freshness import CORE_SOURCES

    crons = [c["cron"] for c in triggers("refresh.yml")["schedule"]]
    plan_step = steps("refresh.yml", "plan")[0]
    light, light_sources = plan_step["env"]["LIGHT_SCHEDULE"], plan_step["env"]["LIGHT_SOURCES"].split()
    assert plan_step["env"]["SCHEDULE"] == "${{ github.event.schedule }}"
    assert light in crons and light.split()[4] == "5" and light not in crons[:2]
    assert set(CORE_SOURCES) <= set(light_sources) and "agenda" in light_sources
    # the fetch takes them in the registry's order (later sources read earlier ones' snapshot files)
    assert light_sources == [s for s in SOURCES if s in light_sources]
    fetch = steps("refresh.yml", "refresh")[named(steps("refresh.yml", "refresh"), "Fetch official sources")]
    assert fetch["env"]["SOURCES"] == "${{ inputs.sources || needs.plan.outputs.sources }}"
    assert workflow("refresh.yml")["jobs"]["plan"]["outputs"]["sources"] == "${{ steps.plan.outputs.sources }}"

    # a `date` that says it is the 3rd of the month: a Monday run then is a full refresh, a Friday run never is
    bin_dir = tmp_path / "bin-date"
    bin_dir.mkdir()
    real_date = shutil.which("date")
    (bin_dir / "date").write_text(
        f'#!/bin/sh\nif [ "$*" = "-u +%-d" ]; then echo 3; else exec {real_date} "$@"; fi\n', encoding="utf-8"
    )
    (bin_dir / "date").chmod(0o755)
    now = datetime.now(UTC)

    def plan(core_hours: float, schedule: str) -> dict[str, str]:
        fetched = (now - timedelta(hours=core_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        env = fake_gh(tmp_path, json.dumps({s: {"status": "ok", "fetched_at": fetched} for s in CORE_SOURCES}))
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env |= {"EVENT": "schedule", "SCHEDULE": schedule, "FULL_INPUT": "", "RECENT_HOURS": "20",
                "GITHUB_REPOSITORY": "o/r",
                **{k: plan_step["env"][k] for k in ("CORE_SOURCES", "LIGHT_SCHEDULE", "LIGHT_SOURCES")}}  # fmt: skip
        return run_step(plan_step["run"], tmp_path, env)

    assert plan(30, light) == {"run": "true", "full": "", "sources": " ".join(light_sources)}
    assert plan(30, crons[0]) == {"run": "true", "full": "1"}  # Monday, first week: every source, in full
    assert plan(3, light) == {"run": "false"}  # a refresh in the last 20 h (e.g. by hand on Thursday): skipped


def failing_gh(tmp_path: Path) -> dict[str, str]:
    """A `gh` on PATH that fails whatever it is asked (an API error)."""
    bin_dir = tmp_path / "bin-failing"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "gh").write_text("#!/bin/sh\necho 'HTTP 502' >&2\nexit 1\n", encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


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
    assert on["workflow_run"]["workflows"] == ["CI", "Data refresh", "Deploy to GitHub Pages", "Daily rebuild"]
    assert on["workflow_run"]["types"] == ["completed"] and on["workflow_run"]["branches"] == ["main"]
    s = steps("watchdog.yml", "health")
    check = s[named(s, "Check")]["run"]
    assert '"${site%/}/data/meta.json?watchdog=$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"' in check
    assert "python -m pipeline health" in check
    assert 'latest refresh.yml --job "Fetch, validate, gate, commit"' in check and "latest ci.yml --event push" in check
    assert 'latest pages.yml --job "Build site" --cancelled-if-last' in check and "latest rebuild.yml --job Deploy" in check
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
    assert [p["key"] for p in report["problems"]] == ["source:council:stale", "source:train"]  # stale; failed, not stale
    assert main(["health", "--manifest", str(manifest), "--meta", str(meta), "--problem", "ci=CI fails", "--markdown"]) == 1
    body = capsys.readouterr().out
    # main's ep_votes (1 day old) is newer than the live site's (10 days): not deployed
    assert body.startswith("<!-- data-health: ci,source:council:stale,source:train,site,undeployed -->\n")
    assert "- CI fails" in body and "**The live site's data is overdue**" in body
    healthy = tmp_path / "healthy.json"
    healthy.write_text(json.dumps({"ep_votes": {"status": "partial", "fetched_at": iso(now)}}), encoding="utf-8")
    assert main(["health", "--manifest", str(healthy), "--meta", str(meta), "--max-age-days", "11"]) == 0
    assert main(["health", "--manifest", str(healthy), "--problem", "not a key=x"]) == 2


FAKE_GH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
data = json.load(open(os.environ["FAKE_GH_DATA"]))
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
jq = args[args.index("--jq") + 1] if "--jq" in args else None
if args[:2] == ["run", "list"]:
    out = data["runs"].get(args[args.index("--workflow") + 1], [])
elif args[:2] == ["run", "view"]:
    out = {"jobs": data["jobs"].get(args[2], [])}
elif args[:1] == ["api"]:
    out = data.get("api", {})
else:
    out = {}
text = json.dumps(out)
if jq:
    text = subprocess.run(["jq", "-r", jq], input=text, capture_output=True, text=True, check=True).stdout
sys.stdout.write(text if text.endswith("\n") else text + "\n")
"""


def gh_serving(tmp_path: Path, data: dict) -> tuple[dict[str, str], Path]:
    """A `gh` on PATH that answers `run list`, `run view` and `api` from `data` (applying --jq with jq); and its log."""
    bin_dir, log, fixture = tmp_path / "bin-gh", tmp_path / "gh.log", tmp_path / "gh.json"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    fixture.write_text(json.dumps(data), encoding="utf-8")
    log.write_text("", encoding="utf-8")
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_DATA": str(fixture), "FAKE_GH_LOG": str(log)}
    return env, log


def run_(i: int, conclusion: str, status: str = "completed") -> dict:
    return {"databaseId": i, "status": status, "conclusion": conclusion, "url": f"https://x/runs/{i}", "headSha": f"{i:040d}"}


def test_the_watchdog_judges_the_latest_run_that_did_its_work(tmp_path):
    # the 22:37 run its plan skips concludes "success" and hid a failed 05:17 run; deploys after CI were not watched
    refresh_job, build_job = "Fetch, validate, gate, commit", "Build site"
    skipped = lambda name: [{"name": "Plan", "conclusion": "success"}, {"name": name, "conclusion": "skipped"}]  # noqa: E731
    ran = lambda name, c="failure": [{"name": "Plan", "conclusion": "success"}, {"name": name, "conclusion": c}]  # noqa: E731
    data = {
        "runs": {
            "refresh.yml": [run_(9, "success"), run_(8, "cancelled"), run_(7, "failure"), run_(6, "success")],
            "ci.yml": [run_(19, "cancelled"), run_(18, "failure")],
            "pages.yml": [run_(29, "", "in_progress"), run_(28, "cancelled"), run_(27, "success")],
        },
        "jobs": {"9": skipped(refresh_job), "7": ran(refresh_job), "28": ran(build_job, "cancelled"), "27": ran(build_job, "success")},
    }
    env, log = gh_serving(tmp_path, data)

    def latest(*args: str) -> str:
        cmd = ["python", str(ROOT / "scripts" / "latest_run.py"), *args]
        return subprocess.run(cmd, env={**os.environ, **env}, check=True, capture_output=True, text=True).stdout.strip()

    assert latest("refresh.yml", "--job", refresh_job).split()[:2] == ["failure", "7"]  # not 9 (skipped), not 8
    assert latest("ci.yml", "--event", "push").split()[:2] == ["failure", "18"]
    assert "--event push" in log.read_text(encoding="utf-8")
    # a deploy replaced by a later one (29, still running) is not a failure; the last word is the success before it
    assert latest("pages.yml", "--job", build_job, "--cancelled-if-last").split()[:2] == ["success", "27"]
    data["runs"]["pages.yml"] = data["runs"]["pages.yml"][1:]  # nothing came after the cancelled deploy
    env, _ = gh_serving(tmp_path, data)
    assert latest("pages.yml", "--job", build_job, "--cancelled-if-last").split()[:2] == ["cancelled", "28"]
    # a deploy run after a CI run that deploys nothing (a manual one) concludes "success" having done nothing: it does
    # not hide the failed deploy before it
    data["runs"]["pages.yml"] = [run_(30, "success"), run_(26, "failure")]
    data["jobs"]["30"] = skipped(build_job)
    env, _ = gh_serving(tmp_path, data)
    assert latest("pages.yml", "--job", build_job, "--cancelled-if-last").split()[:2] == ["failure", "26"]
    data["runs"]["refresh.yml"] = [run_(5, "success")]
    data["jobs"]["5"] = ran(refresh_job, "success")
    env, _ = gh_serving(tmp_path, data)
    assert latest("refresh.yml", "--job", refresh_job).split()[:2] == ["success", "5"]
    # a failed plan skips the refresh job too, but a failed run is always the latest word
    data["runs"]["refresh.yml"] = [run_(4, "failure"), run_(3, "success")]
    data["jobs"]["4"] = [{"name": "Plan", "conclusion": "failure"}, {"name": refresh_job, "conclusion": "skipped"}]
    env, _ = gh_serving(tmp_path, data)
    assert latest("refresh.yml", "--job", refresh_job).split()[:2] == ["failure", "4"]
    data["runs"] = {}
    env, _ = gh_serving(tmp_path, data)
    assert latest("refresh.yml", "--job", refresh_job) == ""


def test_a_source_getting_worse_gets_a_new_key_so_the_issue_notifies(tmp_path, capsys):
    # the Train failing, then stale (the site says "not up to date"), then its "blocked" labels withdrawn: one key,
    # source:train, throughout, so the issue was only edited and nobody was told
    from pipeline.__main__ import main
    from pipeline.freshness import LABELS_EXPIRE_AFTER_DAYS, STALE_AFTER_DAYS

    now = datetime.now(UTC)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

    def key(days: float) -> list[str]:
        manifest = tmp_path / "m.json"
        entry = {"status": "failed", "fetched_at": iso(now - timedelta(days=days)), "attempted_at": iso(now)}
        manifest.write_text(json.dumps({"train": entry}), encoding="utf-8")
        main(["health", "--manifest", str(manifest), "--json"])
        return [p["key"] for p in json.loads(capsys.readouterr().out)["problems"]]

    stale, expire = STALE_AFTER_DAYS["train"], LABELS_EXPIRE_AFTER_DAYS["train"]
    assert stale < expire
    assert key(stale - 1) == ["source:train"]  # the key the live issue already lists: no comment on the upgrade
    assert key(stale + 1) == ["source:train:stale"]
    assert key(expire + 1) == ["source:train:labels-expired"]
    # the watchdog comments on each key the issue did not list (watchdog.yml): each step is a new one
    issue = steps("watchdog.yml", "health")[named(steps("watchdog.yml", "health"), "Open, update or close the issue")]["run"]
    assert 'contains("," + $k + ",")' in issue


def test_the_health_check_reports_data_on_main_the_live_site_lacks(tmp_path, capsys):
    from pipeline.__main__ import main
    from pipeline.freshness import CORE_SOURCES

    now = datetime.now(UTC)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    on_main = {s: {"status": "ok", "fetched_at": iso(now - timedelta(hours=10))} for s in CORE_SOURCES}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(on_main), encoding="utf-8")

    def keys(live_hours: float, *args: str) -> list[str]:
        sources = [{"id": s, "fetched_at": iso(now - timedelta(hours=live_hours))} for s in CORE_SOURCES]
        meta = tmp_path / "meta.json"
        meta.write_text(json.dumps({"built_at": iso(now), "sources": sources}), encoding="utf-8")
        main(["health", "--manifest", str(manifest), "--meta", str(meta), "--json", *args])
        return [p["key"] for p in json.loads(capsys.readouterr().out)["problems"]]

    assert keys(10) == []  # the live site has main's data
    assert keys(7 * 24) == ["undeployed"]  # main refreshed 10 h ago, the site still has last week's
    assert keys(7 * 24, "--deploy-grace-hours", "12") == []  # within the grace period
    assert keys(5) == []  # the site is newer than main's manifest (a deploy of a later commit)


def watchdog_check(tmp_path: Path, data: dict, live_days: float) -> tuple[dict[str, str], list[dict], str]:
    """The watchdog's Check step, as the job runs it: its sparse checkout (the pipeline, main's manifest with the core
    sources retrieved 10 h ago, the run picker), `gh` answering from `data`, `curl` serving a live meta.json whose
    sources are `live_days` old. Returns its outputs, the problems it found and the URLs curl was asked for."""
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    from pipeline.freshness import CORE_SOURCES

    s = steps("watchdog.yml", "health")
    work = tmp_path / "checkout"
    shutil.copytree(ROOT / "pipeline", work / "pipeline", ignore=shutil.ignore_patterns("__pycache__"))
    (work / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "latest_run.py", work / "scripts" / "latest_run.py")
    now = datetime.now(UTC)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    fresh = {s: {"status": "ok", "fetched_at": iso(now - timedelta(hours=10))} for s in CORE_SOURCES}
    (work / "data" / "snapshot").mkdir(parents=True)
    (work / "data" / "snapshot" / "_manifest.json").write_text(json.dumps(fresh), encoding="utf-8")
    live = {"built_at": iso(now - timedelta(days=live_days)),
            "sources": [{"id": s, "fetched_at": iso(now - timedelta(days=live_days))} for s in CORE_SOURCES]}  # fmt: skip
    meta_src, curl_log, bin_dir = tmp_path / "live-meta.json", tmp_path / "curl.log", tmp_path / "bin-curl"
    meta_src.write_text(json.dumps(live), encoding="utf-8")
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(
        f'#!/bin/sh\nfor a; do echo "$a" >> "{curl_log}"; done\nwhile [ "$1" != -o ]; do shift; done\ncp "{meta_src}" "$2"\n',
        encoding="utf-8",
    )
    (bin_dir / "curl").chmod(0o755)
    env, _ = gh_serving(tmp_path, data)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    env |= {k: str(v) for k, v in workflow("watchdog.yml")["env"].items()} | {
        "RUNNER_TEMP": str(runner_temp), "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": "o/r",
        "RUN_URL": "https://x/runs/77", "SITE_URL": ""}  # fmt: skip
    out = run_step(s[named(s, "Check")]["run"], work, env)
    report = json.loads((runner_temp / "health.json").read_text(encoding="utf-8"))
    return out, report["problems"], curl_log.read_text(encoding="utf-8")


def ran_job(name: str, conclusion: str, *failed_steps: str) -> list[dict]:
    return [{"name": name, "conclusion": conclusion, "steps": [{"name": f, "conclusion": "failure"} for f in failed_steps]}]


def test_the_watchdog_check_reports_a_failed_deploy_and_undeployed_data(tmp_path):
    data = {
        "runs": {"refresh.yml": [run_(9, "success")], "ci.yml": [run_(18, "success")], "pages.yml": [run_(28, "failure")]},
        "jobs": {"9": ran_job("Fetch, validate, gate, commit", "success"),
                 "28": ran_job("Build site", "failure", "Smoke-test the site on its own data (Chromium)")},
        "api": {"size": 1000},
    }  # fmt: skip
    out, problems, curl_log = watchdog_check(tmp_path, data, live_days=3)
    assert out == {"healthy": "false", "site_ok": "true"}
    assert [p["key"] for p in problems] == ["deploy", "undeployed"]
    assert "(failure, [run 28](https://x/runs/28)" in problems[0]["text"]
    assert "Smoke-test the site on its own data (Chromium)" in problems[0]["text"]
    assert "data/meta.json?watchdog=77-1" in curl_log  # past the CDN's 10-minute cache
    data["runs"]["pages.yml"] = [run_(29, "success"), run_(28, "failure")]
    data["jobs"]["29"] = ran_job("Build site", "success")
    out, problems, _ = watchdog_check(tmp_path / "again", data, live_days=10 / 24)
    assert out == {"healthy": "true", "site_ok": "true"} and problems == []


def test_red_ci_says_to_rerun_the_known_webkit_flake_once_and_that_refreshed_data_waits(tmp_path):
    webkit = "E2E + accessibility (Playwright, webkit)"
    data = {
        "runs": {"refresh.yml": [], "ci.yml": [run_(18, "failure")], "pages.yml": []},
        "jobs": {"18": ran_job(webkit, "failure", "Run Playwright")},
        "api": {"size": 1000},
    }
    _, problems, _ = watchdog_check(tmp_path, data, live_days=10 / 24)
    assert [p["key"] for p in problems] == ["ci"]
    text = problems[0]["text"]
    assert f"{webkit} (Run Playwright)" in text and "Refused to apply a stylesheet because its hash" in text
    assert "re-run the failed jobs once" in text
    assert "a refresh deploys its data only once CI has passed on main's code" in text
    data["jobs"]["18"] = ran_job("Lint, test, build", "failure", "Pytest (offline; network tests deselected)")
    _, problems, _ = watchdog_check(tmp_path / "pytest", data, live_days=10 / 24)
    assert "re-run" not in problems[0]["text"] and "once CI has passed on main's code" in problems[0]["text"]


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
