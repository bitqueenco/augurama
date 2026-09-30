#!/usr/bin/env bash
# Apply the delivered patch to the exact authorized branch, test, commit and push.
# Run from an authenticated local development environment. No force pushes or merge.
set -euo pipefail
TARGET=${1:?Usage: bash publish-to-github.sh /path/to/checkout /path/to/dreamina-director-rc1.patch}
PATCH=${2:?Supply the delivered patch path}
PATCH=$(cd "$(dirname "$PATCH")" && pwd)/$(basename "$PATCH")
BRANCH=release/dual-plugin-rc1
BASE=112f8f60d2e618ba100f3a514b0af6159a611c19
REMOTE=https://github.com/bohselecta/dreamina-director.git
if [[ ! -f "$PATCH" ]]; then echo 'Patch file is missing.' >&2; exit 2; fi
if [[ ! -d "$TARGET" ]]; then git clone --branch "$BRANCH" "$REMOTE" "$TARGET"; fi
cd "$TARGET"
URL=$(git remote get-url origin)
case "$URL" in
  https://github.com/bohselecta/dreamina-director|https://github.com/bohselecta/dreamina-director.git|git@github.com:bohselecta/dreamina-director.git) ;;
  *) echo 'Unexpected repository. Refusing to modify it.' >&2; exit 2;;
esac
if [[ -n $(git status --porcelain) ]]; then echo 'The checkout has unrelated or uncommitted work. Use a clean checkout.' >&2; exit 2; fi
git fetch origin "$BRANCH" main
if [[ $(git rev-parse "origin/$BRANCH") != "$BASE" ]]; then
  echo 'The remote release branch changed since this delivery. Inspect and rebase the patch; nothing was overwritten.' >&2; exit 2
fi
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then git switch "$BRANCH"; else git switch --create "$BRANCH" --track "origin/$BRANCH"; fi
if [[ $(git rev-parse HEAD) != "$BASE" ]]; then echo 'Local branch has independent work. Refusing to overwrite it.' >&2; exit 2; fi
git apply --check "$PATCH"
git apply --index "$PATCH"
git diff --cached --check
# Install the documented test environment before running this publisher.
# A failure deliberately leaves the staged patch for inspection; it is not discarded.
python3 -m pytest -q
python3 scripts/package_releases.py --out dist
python3 -m compileall -q src scripts
if [[ -n $(git diff --name-only) ]]; then echo 'Verification changed tracked files. Review them before committing.' >&2; exit 2; fi
git commit -m 'Build Dreamina Director dual-host release candidate'
git push --set-upstream origin "$BRANCH"
echo "Pushed review branch: ${REMOTE%.git}/tree/$BRANCH"
echo 'Main was not changed. Inspect GitHub Actions, then open/review a pull request.'
echo 'https://github.com/bohselecta/dreamina-director/compare/main...release/dual-plugin-rc1'
