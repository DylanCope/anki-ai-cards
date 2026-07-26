#!/bin/bash
# Boots the persistent dev-agent: relocates Claude Code's own state onto the
# volume so OAuth login survives restarts, clones/preserves the repo
# checkout, then supervises `claude remote-control` (the headless/server-mode
# subcommand, not the interactive `--remote-control` flag) inside a detached
# tmux session — never in the bare foreground — so Dylan can `fly ssh
# console` in and `tmux attach -t devagent` to complete or renew the
# interactive OAuth login (Remote Control cannot use
# ANTHROPIC_API_KEY/setup-token; see AGENTS.md). `--continue` resumes the
# most recent session in this directory on every respawn (crash, platform
# blip, redeploy) instead of starting a blank conversation each time — the
# transcripts it resumes from live in $CLAUDE_CONFIG_DIR on the persistent
# volume, so they survive the same restarts. It exits non-zero with "No
# recent session found" rather than falling back gracefully when none
# exists yet (confirmed empirically, undocumented) — hence the `||` fallback
# to a plain session below, needed on the very first launch and any time the
# volume's session history is otherwise absent. `--continue` cannot be
# combined with `--spawn` at all (hard error) — so `--spawn=same-dir` only
# goes on the fallback branch, where it heads off a one-time interactive
# prompt a from-scratch launch otherwise asks (worktree-per-session vs.
# sharing this checkout — same-dir matches this setup, a single persistent
# /data/repo checkout, not per-session worktrees). `--name` keeps the
# claude.ai/code sidebar entry stable instead of it re-titling itself from
# whatever the new conversation opens with. Deliberately never runs with
# --dangerously-skip-permissions: Dylan is the human approving tool calls via
# Remote Control, same as any other Claude Code session.
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
    "cd $REPO_DIR && while true; do claude remote-control --name anki-devagent --continue || claude remote-control --name anki-devagent --spawn=same-dir; echo \"claude exited (\$?), restarting in 5s...\"; sleep 5; done"

exec tail -f /dev/null
