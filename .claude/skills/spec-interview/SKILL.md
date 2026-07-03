---
name: spec-interview
description: Interview the user to create or update PRD.md for the Ralph loop harness. Use when the user wants to write a spec, define requirements, plan a feature or project, or says the PRD needs creating/updating. Produces a PRD in the exact format ralph/loop.sh iterations consume.
---

# Spec Interview

You are conducting a requirements interview to produce `PRD.md` — the work
queue for an autonomous Ralph loop (see `ralph/README.md`). The loop's
iterations are only as good as this spec, so your job is to force decisions
out of the user's head and into verifiable tasks.

## Interview process

Ask **one question at a time**. Prefer multiple-choice with a recommended
option when the answer space is guessable; open questions otherwise. Don't
move on until you understand the answer. Cover, in roughly this order:

1. **Goal** — what is being built, and what does "working" look like on day
   one? Push for the smallest useful version.
2. **Context** — who/what uses it, and how does it fit the wider project?
3. **Stack & constraints** — language, libraries, platforms, existing code it
   must integrate with, anything it must NOT touch.
4. **Behavior details** — inputs, outputs, data formats, error cases. Probe
   edge cases the user hasn't mentioned; propose 2–3 and ask.
5. **Verification** — how will the loop objectively know each piece works?
   (tests, linters, example fixtures, golden files). If the user has no
   answer, propose one — no task may enter the PRD without a check.
6. **Out of scope** — what should the loop explicitly not do or gold-plate?

Challenge vague answers ("fast", "user-friendly", "robust") by asking for a
measurable proxy. If the user is unsure, recommend a sensible default and ask
for confirmation rather than stalling.

## Writing the PRD

When you have enough, present a summary of what you heard and a proposed task
breakdown for approval **before** writing the file.

Then write `PRD.md` (do not invent a different structure):

- `## Overview` — one paragraph.
- `## Requirements` — concrete and specific: name files, libraries, commands,
  acceptance criteria.
- `## Tasks` — checkbox list (`- [ ]`), ordered so earlier tasks unblock later
  ones. Each task must be completable in one context window and end with an
  objective verification ("…; `pytest tests/test_x.py` passes"). The first
  task must establish scaffolding plus a runnable test command, and update
  `AGENTS.md` with that command.
- `## Out of scope` — explicit exclusions.

Also update `AGENTS.md` (stack, conventions, verification commands) if the
interview settled anything currently marked TBD there.

Finally, remind the user to review the PRD, commit it, and start the loop with
a small iteration cap (`./ralph/loop.sh 10`).
