#!/usr/bin/env bash
# Ralph loop harness.
# Usage: ./ralph/loop.sh [max_iterations]
# Stop early: touch ralph/STOP (checked before each iteration), or Ctrl+C.
#
# Runs on a dedicated branch (RALPH_BRANCH, default "ralph/loop"), pushing
# and keeping a PR against RALPH_BASE_BRANCH (default "main") up to date
# after every iteration, so progress is reviewable on GitHub as it happens.

set -uo pipefail

MAX_ITERATIONS="${1:-10}"
PROMISE="<promise>RALPH_DONE</promise>"
BRANCH="${RALPH_BRANCH:-ralph/loop}"
BASE_BRANCH="${RALPH_BASE_BRANCH:-main}"

# Repo root = parent of this script's directory
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPT_FILE="$ROOT/ralph/PROMPT.md"
STOP_FILE="$ROOT/ralph/STOP"
LOG_DIR="$ROOT/ralph/logs"

cd "$ROOT"
mkdir -p "$LOG_DIR"
rm -f "$STOP_FILE"

# --- Preflight checks -------------------------------------------------------
command -v claude >/dev/null 2>&1 || { echo "ERROR: 'claude' CLI not found in PATH."; exit 1; }
[ -f "$PROMPT_FILE" ] || { echo "ERROR: $PROMPT_FILE not found."; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "ERROR: not a git repo. Run 'git init && git add -A && git commit -m init' first."
  echo "(Git history is the harness's memory and your rollback mechanism — don't skip it.)"
  exit 1
}
command -v gh >/dev/null 2>&1 || { echo "ERROR: 'gh' CLI not found in PATH."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh not authenticated. Run: gh auth login"; exit 1; }
git remote get-url origin >/dev/null 2>&1 || { echo "ERROR: no 'origin' remote configured."; exit 1; }

# --- Branch setup ------------------------------------------------------------
if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH"
fi

# Push the current commit and make sure a PR exists against BASE_BRANCH.
sync_and_pr() {
  git push -u origin "$BRANCH" || { echo "WARNING: push failed."; return 1; }
  if ! gh pr view "$BRANCH" >/dev/null 2>&1; then
    gh pr create --base "$BASE_BRANCH" --head "$BRANCH" \
      --title "Ralph loop: $BRANCH" \
      --body "Automated PR from the Ralph loop. Each commit is one PRD.md task — see PROGRESS.md for the running log of what was done, verified, and learned." \
      || echo "WARNING: PR creation failed (may already exist under a different state)."
  fi
}

echo "Ralph loop starting: max $MAX_ITERATIONS iterations."
echo "Branch: $BRANCH -> $BASE_BRANCH | Logs: $LOG_DIR | Stop: touch $STOP_FILE"
echo

for i in $(seq 1 "$MAX_ITERATIONS"); do
  if [ -f "$STOP_FILE" ]; then
    echo "STOP file found — halting."
    break
  fi

  LOG_FILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S)-iter${i}.log"
  echo "=== Iteration $i/$MAX_ITERATIONS — $(date) ==="

  # Fresh process, fresh context, every iteration. This is the whole trick.
  cat "$PROMPT_FILE" | claude -p \
    --dangerously-skip-permissions \
    --output-format text \
    2>&1 | tee "$LOG_FILE"

  EXIT_CODE=${PIPESTATUS[1]}
  echo "--- iteration $i exit code: $EXIT_CODE ---"

  sync_and_pr

  if grep -qF "$PROMISE" "$LOG_FILE"; then
    echo
    echo "Completion promise detected after $i iteration(s). Done."
    exit 0
  fi

  if [ "$EXIT_CODE" -ne 0 ]; then
    echo "WARNING: claude exited non-zero. Pausing 30s before retry."
    sleep 30
  else
    sleep 2
  fi
done

echo
echo "Loop finished without completion promise. Check PROGRESS.md and $LOG_DIR."
exit 1
