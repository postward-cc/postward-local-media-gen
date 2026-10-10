#!/usr/bin/env bash
# Update this skill from its git remote, then verify the result.
#
# There is no portable "install and auto-update" protocol across agent
# harnesses: each one has its own, and none of them is universal. Git plus an
# instruction inside the skill is the part that works everywhere, which is why
# this is a script rather than a registry entry.
#
# The update is verified. If the gate fails after the pull, the failure is
# reported with the exact commit that introduced it, and the working tree is
# left where it is for inspection.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: ./scripts/update.sh [--dry-run]

Fetches the remote, fast-forwards to the tracked branch, and runs the offline
gate. Exits non-zero if the gate fails.

Environment:
  GIT_REMOTE            Remote to pull from; default is origin.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

REMOTE="${GIT_REMOTE:-origin}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "ERROR: $ROOT is not a git checkout. Nothing to update." >&2
  echo "  Clone the repository first; see INSTALL.md." >&2
  exit 2
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  echo "ERROR: detached HEAD. Check out a branch before updating." >&2
  exit 2
fi

DIRTY="$(git status --porcelain)"
if [[ -n "$DIRTY" ]]; then
  echo "ERROR: the working tree has uncommitted changes, so a fast-forward may" >&2
  echo "       not apply cleanly. Commit, stash or discard them first:" >&2
  git status --short >&2
  exit 2
fi

BEFORE="$(git rev-parse HEAD)"
echo "Branch: $BRANCH at ${BEFORE:0:12}"

echo "Fetching $REMOTE"
git fetch --prune "$REMOTE"

BEHIND="$(git rev-list --count "HEAD..$REMOTE/$BRANCH" 2>/dev/null || echo 0)"
if (( BEHIND == 0 )); then
  echo
  echo "Already up to date."
  exit 0
fi

echo "$BEHIND commit(s) behind $REMOTE/$BRANCH:"
git log --oneline "HEAD..$REMOTE/$BRANCH" | sed 's/^/  /'

if (( DRY_RUN )); then
  echo
  echo "Dry run: nothing pulled. Run without --dry-run to update and verify."
  exit 0
fi

git merge --ff-only "$REMOTE/$BRANCH"
AFTER="$(git rev-parse HEAD)"
echo
echo "Updated to ${AFTER:0:12}"

# Anything that changes the resolved runtime means the environment no longer
# matches the repository, which is exactly the stale state verify-locks catches.
CHANGED="$(git diff --name-only "$BEFORE" "$AFTER" || true)"
RUNTIME_TOUCHED=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  case "$file" in
    bootstrap.sh|requirements-*|scripts/relock.sh|scripts/bootstrap_vibevoice.sh)
      echo "  runtime input changed: $file"
      RUNTIME_TOUCHED=1
      ;;
  esac
done <<< "$CHANGED"

echo
echo "Verifying with the offline gate"
if ! ./scripts/check.sh; then
  cat >&2 <<EOF

The gate failed after updating to ${AFTER:0:12}.

  The repository is checked out at the new commit and is not verified.
  To return to the previous state:

    git -C $ROOT checkout $BEFORE

  Then open an issue with the failure output above.
EOF
  exit 1
fi

if (( RUNTIME_TOUCHED )); then
  cat <<EOF

Runtime inputs changed. The local environment may no longer match the
repository, so re-run the bootstrap to reconcile it:

  ./bootstrap.sh

Whether it does is measurable rather than assumed:

  python scripts/doctor.py verify-locks
EOF
fi

echo
echo "Updated and verified."