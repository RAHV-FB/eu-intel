#!/usr/bin/env bash
# Whether the code of commit $1 has passed CI, before a workflow deploys it (refresh.yml, rebuild.yml) or releases its
# data (release-data.yml): a successful CI run for a push to main (ci.yml: the tests on the frozen data, the browser
# tests) on a commit with the same files outside data/snapshot and data/state. The data passes its own gate in those
# workflows (and again in the deploy).
#
#   scripts/ci-passed.sh <commit>            # writes deploy=true or deploy=false
#   scripts/ci-passed.sh <commit> release    # writes release=true or release=false
#
# Writes the answer to $GITHUB_OUTPUT and says why (also in the step summary). Run from the repository's root, in a
# clone with the commits and trees of main (filter: blob:none is enough), with `gh` (GH_TOKEN, actions: read).
set -euo pipefail
sha=$1
what=${2:-deploy}
out=${GITHUB_OUTPUT:-/dev/null}
summary=${GITHUB_STEP_SUMMARY:-/dev/null}

case "$what" in
  deploy)
    from_branch="the github-pages environment deploys from main only. Deploy main by hand (Actions -> Deploy to GitHub Pages -> Run workflow on main)."
    yes="deploying $sha"
    no="not deployed now. The deploy that follows the next successful CI run on main publishes it."
    ;;
  release)
    from_branch="a data release is made by main's workflow only. Run Actions -> Data release -> Run workflow on main."
    yes="releasing its data"
    no="no data release now. The next scheduled run, or a manual one once CI has passed, releases it."
    ;;
  *)
    echo "usage: scripts/ci-passed.sh <commit> [release]" >&2
    exit 2
    ;;
esac

if [ "${GITHUB_REF:-refs/heads/main}" != refs/heads/main ]; then
  echo "::warning::Started from $GITHUB_REF: $from_branch"
  echo "$what=false" >> "$out"
  exit 0
fi
tested=$(gh run list --workflow ci.yml --branch main --event push --status success --limit 30 \
  --json headSha --jq '.[].headSha')
for ci in $tested; do
  if git merge-base --is-ancestor "$ci" "$sha" 2>/dev/null &&
    git diff --quiet --no-renames "$ci" "$sha" -- . ':(exclude)data/snapshot' ':(exclude)data/state'; then
    echo "CI passed on $ci, which has the code of $sha: $yes." | tee -a "$summary"
    echo "$what=true" >> "$out"
    exit 0
  fi
done
echo "::warning::CI has not passed (yet) on the code of $sha: $no"
echo "$what=false" >> "$out"
