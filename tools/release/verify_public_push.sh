#!/usr/bin/env bash
# Verify a push to the public repo FROM A FRESH CLONE — run after every push
# of an export (release to main, or a preview branch).
#
# Why this exists (2026-09-26): a preview branch was pushed after checking the
# file count and running the new tests in the WORKING TREE of the publishing
# clone. A `git stash` / `git stash pop` in between had unstaged the modified
# files, so the commit carried only the 6 new files and none of the 33
# modifications — and the push was reported as checked. Checks on the machine
# that made the commit prove nothing about what was published. This script
# only looks at what the remote serves.
#
# Usage:
#   bash tools/release/verify_public_push.sh <export_dir> <repo_url> <branch> [base]
#     export_dir  the tree tools/release/export_public.sh produced for this push
#     repo_url    the public repository's clone URL (no default: this file is
#                 itself exported, and the leak gate keeps owner handles out)
#     branch      the branch just pushed (e.g. main, a preview branch)
#     base        what to diff against (default: main; for a push to main,
#                 pass the previous release tag, e.g. v0.1.1)
#
# Env: PYTHON (default: this repo's .venv/bin/python), SKIP_FRONTEND=1 to skip
# vitest (it needs an `npm ci` in the fresh clone, which is slow).
#
# Exits non-zero if the published tree differs from the export in any file,
# or any changed test fails. Prints the base..branch file count for the report.
set -euo pipefail

EXPORT_DIR="${1:?export_dir required}"
REPO_URL="${2:?repo_url required}"
BRANCH="${3:?branch required}"
BASE="${4:-main}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
EXPORT_DIR="$(cd "$EXPORT_DIR" && pwd)"

CLONE="$(mktemp -d "${TMPDIR:-/tmp}/uis-public-verify.XXXXXX")"
echo "[verify_public_push] fresh clone of $REPO_URL ($BRANCH) -> $CLONE"
git clone --quiet --no-tags --depth 50 --branch "$BRANCH" "$REPO_URL" "$CLONE"
cd "$CLONE"
git fetch --quiet --depth 50 origin "+refs/heads/$BASE:refs/remotes/origin/$BASE" 2>/dev/null \
  || git fetch --quiet --depth 50 origin "+refs/tags/$BASE:refs/tags/$BASE"
BASE_REF="$(git rev-parse --verify --quiet "origin/$BASE" || git rev-parse --verify "$BASE")"

echo "[verify_public_push] published: $(git log -1 --format='%h %s')"

# ── 1. The published tree must equal the export, file for file ─────────────
if ! diff -rq --exclude=.git "$EXPORT_DIR" "$CLONE"; then
    echo "[verify_public_push] FAIL: the published tree differs from the export (above)." >&2
    exit 1
fi
echo "[verify_public_push] OK: published tree == export tree ($(git ls-files | wc -l | tr -d ' ') files)"

# ── 2. What changed against the base ────────────────────────────────────────
CHANGED_COUNT="$(git diff --name-only "$BASE_REF" HEAD | wc -l | tr -d ' ')"
echo "[verify_public_push] $BASE..$BRANCH: $CHANGED_COUNT file(s) changed"
git diff --stat "$BASE_REF" HEAD | tail -1

# ── 3. Every added/modified test file passes in the fresh clone ─────────────
mapfile -t PY_TESTS < <(git diff --name-only --diff-filter=AM "$BASE_REF" HEAD -- 'tests/*test_*.py')
mapfile -t TS_TESTS < <(git diff --name-only --diff-filter=AM "$BASE_REF" HEAD -- 'ux-command-center/*.test.ts' 'ux-command-center/*.test.tsx')

if [ "${#PY_TESTS[@]}" -gt 0 ]; then
    echo "[verify_public_push] pytest on ${#PY_TESTS[@]} changed test file(s)"
    "$PYTHON" -m pytest -q -p no:cacheprovider "${PY_TESTS[@]}"
else
    echo "[verify_public_push] no changed Python test files"
fi

if [ "${#TS_TESTS[@]}" -gt 0 ] && [ "${SKIP_FRONTEND:-0}" != "1" ]; then
    echo "[verify_public_push] vitest on ${#TS_TESTS[@]} changed test file(s) (npm ci first)"
    (cd ux-command-center && npm ci --no-audit --no-fund --silent \
        && npx vitest run "${TS_TESTS[@]/#ux-command-center\//}")
elif [ "${#TS_TESTS[@]}" -gt 0 ]; then
    echo "[verify_public_push] SKIPPED vitest on ${#TS_TESTS[@]} changed file(s) (SKIP_FRONTEND=1) — say so in the report"
fi

echo "[verify_public_push] PASS — $CLONE"
