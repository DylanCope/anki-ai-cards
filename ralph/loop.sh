#!/usr/bin/env bash
# Ralph loop harness.
# Usage: ./ralph/loop.sh [max_iterations]
# Stop early: touch ralph/STOP (checked before each iteration), or Ctrl+C.

set -uo pipefail

MAX_ITERATIONS="${1:-10}"
PROMISE="<promise>RALPH_DONE</promise>"

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

echo "Ralph loop starting: max $MAX_ITERATIONS iterations."
echo "Logs: $LOG_DIR | Stop: touch $STOP_FILE"
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
