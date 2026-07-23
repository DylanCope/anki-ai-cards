#!/bin/bash
# Boots the persistent dev-agent: relocates Claude Code's own state onto the
# volume so OAuth login survives restarts, clones/preserves the repo
# checkout, then supervises `claude --remote-control` inside a detached tmux
# session — never in the bare foreground — so Dylan can `fly ssh console` in
# and `tmux attach -t devagent` to complete or renew the interactive OAuth
# login (Remote Control cannot use ANTHROPIC_API_KEY/setup-token; see
# AGENTS.md). Deliberately never runs with --dangerously-skip-permissions:
# Dylan is the human approving tool calls via Remote Control, same as any
# other Claude Code session.
set -euo pipefail

export CLAUDE_CONFIG_DIR=/data/claude-config
mkdir -p "$CLAUDE_CONFIG_DIR"

REPO_DIR=/data/repo
if [ ! -d "$REPO_DIR/.git" ]; then
    git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/DylanCope/anki-ai-cards.git" "$REPO_DIR"
else
    # Never auto-reset/pull — the agent may be mid-task on some branch with
    # uncommitted work; a restart of this container must not clobber it.
    git -C "$REPO_DIR" fetch --all || true
fi

git config --global user.email "dylanr.cope@gmail.com"
git config --global user.name "Dylan Cope"

tmux new-session -d -s devagent \
    "cd $REPO_DIR && while true; do claude --remote-control anki-devagent; echo \"claude exited (\$?), restarting in 5s...\"; sleep 5; done"

exec tail -f /dev/null
