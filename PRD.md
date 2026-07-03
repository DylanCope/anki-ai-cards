# PRD — <project name>

<!--
This file is the loop's work queue. Each iteration picks the topmost unchecked
task, completes it, and checks it off. Write tasks that are:
- Small: completable in one iteration (one context window)
- Ordered: earlier tasks unblock later ones
- Verifiable: "tests in X pass" beats "works well"

Keep the Requirements section tight — vague specs waste iterations.
-->

## Overview

<One paragraph: what is being built and why.>

## Requirements

<Specific, concrete requirements. Name files, libraries, commands, and
acceptance criteria explicitly.>

## Tasks

<!-- The loop works top to bottom. First task should usually be project
scaffolding + a runnable test command, so every later task has verification. -->

- [ ] <Task 1 — e.g. "Scaffold project: pyproject.toml, src/ layout, pytest configured, one trivial passing test, update AGENTS.md with the test command">
- [ ] <Task 2>
- [ ] <Task 3>

## Out of scope

<Things the loop must NOT do. Be explicit — an autonomous agent will happily
gold-plate.>
