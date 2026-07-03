# Ralph Loop Harness

A minimal Ralph loop: a bash script that repeatedly launches a fresh Claude
Code process, which reads the PRD, does one task, verifies it, logs progress,
and commits. State lives in files and git — never in the agent's context.

## Layout

```
repo root/
  PRD.md          # work queue (task checklist) — the loop's input
  PROGRESS.md     # append-only log — the loop's memory
  AGENTS.md       # conventions + verification commands
  ralph/
    loop.sh       # the loop
    PROMPT.md     # prompt fed to every iteration
    logs/         # one log per iteration (gitignore if noisy)
    STOP          # create this file to halt the loop
```

## One-time setup (WSL)

**Important — OneDrive caveat:** this folder lives in OneDrive. Running an
autonomous agent + git against a OneDrive-synced path from WSL is slow and
sync can corrupt git state. Copy the harness to the WSL filesystem and develop
there; treat this OneDrive copy as the template.

```bash
# In WSL:
mkdir -p ~/projects/anki && cd ~/projects/anki
cp -r "/mnt/c/Users/dylan/OneDrive/Documents/Claude/Projects/Anki Card Creation/." .
chmod +x ralph/loop.sh
git init && git add -A && git commit -m "init: ralph harness"
claude --version   # confirm CLI available; `npm install -g @anthropic-ai/claude-code` if not
```

## Before each run

1. Fill in `PRD.md` (overview, requirements, small ordered verifiable tasks).
2. Update `AGENTS.md` verification commands if they've changed.
3. Commit any manual edits.

## Run

Requires the `gh` CLI installed and authenticated (`gh auth login`), and an
`origin` remote pointing at a GitHub repo you can push to.

```bash
./ralph/loop.sh 10        # at most 10 iterations
```

- The loop runs on branch `ralph/loop` (override with `RALPH_BRANCH`),
  targeting `main` (override with `RALPH_BASE_BRANCH`). It creates the branch
  from current HEAD if it doesn't exist yet, or resumes it if it does.
- After every iteration it pushes the branch and opens a PR against the base
  branch if one doesn't already exist — so you can watch progress and review
  commit-by-commit on GitHub as it works, not just after the fact.
- Watch the first few runs live — build intuition before going AFK.
- Halt: `touch ralph/STOP` (takes effect next iteration) or Ctrl+C.
- The loop exits 0 when an iteration prints `<promise>RALPH_DONE</promise>`
  (all PRD tasks checked), 1 otherwise. Either way the branch is pushed and
  the PR is up to date when it stops.

## After a run

- Check the PR on GitHub, or `git log --oneline` — one commit per completed
  task; revert any bad one.
- Read `PROGRESS.md` and the newest files in `ralph/logs/`.
- Bad output usually means a bad prompt or vague PRD task. Fix the files, not
  the agent: tighten the task, add a verification command, note the gotcha in
  AGENTS.md, re-run.
- When you're happy with the PR, merge it yourself on GitHub — the loop never
  merges its own work.

## Safety notes

- `--dangerously-skip-permissions` gives the agent full autonomy **within this
  directory**. Only run the loop in a dedicated repo you're happy to have
  rewritten; never in a folder with unrelated valuables.
- Always pass a max-iterations cap. Each iteration costs real tokens; a stuck
  loop burns money making the same mistake repeatedly.
- Start small: 5–10 iterations, tiny PRD, then scale.

## Tuning knobs (edit loop.sh)

- Pin a model: add `--model sonnet` (cheaper) or `--model opus` to the claude
  invocation.
- Budget cap per iteration: add `--max-turns 50`.
- Change the completion phrase: `PROMISE` variable + PROMPT.md together.

## References

- Original technique: https://ghuntley.com/ralph/
- Anthropic's plugin variant (in-session Stop hook):
  https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md
- PRD-driven reference implementation: https://github.com/snarktank/ralph
