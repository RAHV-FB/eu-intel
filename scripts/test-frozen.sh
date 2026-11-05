#!/usr/bin/env bash
# Run the tests that read real data on the frozen test data (tests/frozen-data.txt), as CI does: pytest, the data
# build as of the frozen moment, vitest, the site build and the Playwright tests (Chromium).
#
# This working tree is left alone: the tests run in a temporary git worktree of HEAD, plus this checkout's uncommitted
# changes and untracked files outside data/snapshot and data/state, whose data/snapshot and data/state are those of the
# frozen commit. It is removed afterwards, or kept (and its path printed) when a step fails.
#
#   scripts/test-frozen.sh               # everything
#   scripts/test-frozen.sh --no-e2e      # without the browser tests (about 10 minutes of the run)
#   scripts/test-frozen.sh --keep        # keep the temporary worktree in any case
#   scripts/test-frozen.sh -- ARGS       # extra arguments for `npx playwright test`, e.g. -- tests/e2e/pages.spec.ts
#
# Needs the Python dev dependencies (pip install -e '.[dev]'), node_modules (npm ci) and, for the browser tests,
# Playwright's Chromium (npx playwright install chromium). PYTHON overrides the interpreter (default: python).
set -euo pipefail

e2e=1
keep=0
pw_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-e2e) e2e=0 ;;
    --keep) keep=1 ;;
    --) shift; pw_args=("$@"); break ;;
    -h | --help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
py=${PYTHON:-python}

root=$(git rev-parse --show-toplevel)
cd "$root"
spec=tests/frozen-data.txt
commit=$(sed -n 's/^commit=//p' "$spec")
built_at=$(sed -n 's/^built_at=//p' "$spec")
if ! [[ "$commit" =~ ^[0-9a-f]{40}$ && "$built_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
  echo "$spec: expected the lines commit=<full commit sha> and built_at=YYYY-MM-DDTHH:MM:SSZ" >&2
  exit 1
fi
if [ ! -d node_modules ]; then
  echo "node_modules is missing: run npm ci first" >&2
  exit 1
fi
git cat-file -e "$commit^{commit}" 2>/dev/null || git fetch --quiet --no-tags origin "$commit"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/eu-intel-frozen.XXXXXX")
rmdir "$tmp" # git worktree add creates it
cleanup() {
  local rc=$?
  if [ "$keep" = 1 ] || [ "$rc" -ne 0 ]; then
    echo "The temporary worktree is kept: $tmp (remove it with: git worktree remove --force $tmp)" >&2
  else
    git -C "$root" worktree remove --force "$tmp"
  fi
  exit "$rc"
}
trap cleanup EXIT
git worktree add --quiet --detach "$tmp" HEAD

# this checkout's code as it stands (staged, unstaged and untracked), without its data/snapshot and data/state
outside=(-- . ':(exclude)data/snapshot' ':(exclude)data/state')
if ! git diff --quiet HEAD "${outside[@]}"; then
  git diff --binary HEAD "${outside[@]}" | git -C "$tmp" apply --whitespace=nowarn
fi
git ls-files -z --others --exclude-standard "${outside[@]}" | while IFS= read -r -d '' f; do
  mkdir -p "$tmp/$(dirname "$f")"
  cp -p "$f" "$tmp/$f"
done
# no-overlay: files the frozen commit does not have are removed
git -C "$tmp" restore --source="$commit" --staged --worktree -- data/snapshot data/state
ln -s "$root/node_modules" "$tmp/node_modules"
cd "$tmp"

step() { printf '\n== %s\n' "$*"; }
step "Frozen test data: data/snapshot and data/state of $commit, built as of $built_at (in $tmp)"

step "pytest"
"$py" -m pytest -q

step "Build site data (EU_INTEL_TODAY=${built_at:0:10} EU_INTEL_BUILT_AT=$built_at)"
if ! EU_INTEL_TODAY=${built_at:0:10} EU_INTEL_BUILT_AT=$built_at "$py" -m pipeline build >build.log 2>&1; then
  tail -n 40 build.log
  exit 1
fi
tail -n 1 build.log

step "vitest"
npx vitest run

if [ "$e2e" = 1 ]; then
  step "Site build (BASE_PATH=/eu-intel/)"
  BASE_PATH=/eu-intel/ npm run build >site-build.log 2>&1 || { tail -n 40 site-build.log; exit 1; }
  tail -n 1 site-build.log

  # free ports, so that a server already running elsewhere (Playwright reuses one outside CI) is not tested instead
  read -r preview_port pages_port < <("$py" -c '
import socket
s = [socket.socket() for _ in range(2)]
for x in s:
    x.bind(("127.0.0.1", 0))
print(*(x.getsockname()[1] for x in s))
')
  step "Playwright (Chromium)"
  E2E_PREVIEW_PORT=${E2E_PREVIEW_PORT:-$preview_port} E2E_PAGES_PORT=${E2E_PAGES_PORT:-$pages_port} \
    npx playwright test --project=chromium ${pw_args[@]+"${pw_args[@]}"}
fi

step "The frozen test data passes."
