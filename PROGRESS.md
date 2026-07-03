# Progress Log

Append-only log written by loop iterations. Newest entry at the top.
Each entry:

```
## <date> — <task name>
- Did: <what was implemented>
- Verified: <commands run and results>
- Learned: <gotchas, decisions, things a future iteration must know>
```

Blocked tasks go under a `Blocked:` line with what was tried.

---

## 2026-07-03 — Task 1: Scaffold the repo
- Did: Created `backend/` as a `uv` project (Python 3.12) with FastAPI +
  uvicorn + sqlmodel + httpx + anthropic as deps, pytest/pytest-asyncio/respx
  as dev deps, `asyncio_mode = "auto"` in `[tool.pytest.ini_options]`. Package
  layout matches AGENTS.md: `app/{clients,agent,api}/__init__.py`,
  `app/main.py` with `GET /health`, `tests/test_health.py`. Created
  `frontend/` via `create-next-app` (TypeScript, Tailwind v4, App Router, ESLint,
  no src-dir, `@/*` import alias, npm). Added `.env.example` at repo root
  listing all six env vars from PRD Requirements.
- Verified: `cd backend && uv run pytest` → 1 passed. `cd frontend && npm run
  build && npm run lint` → build succeeds (static prerender of `/`), lint
  clean.
- Learned:
  - **Sandbox environment gotcha (not a project issue):** this WSL2 box's
    system DNS resolver hangs forever on `npm`/`npx`/`curl` for some domains,
    including `registry.npmjs.org` — glibc's getaddrinfo gets valid UDP
    answers for both A and AAAA queries, but for reasons specific to this
    VM's DNS proxy (10.255.255.254) then retries over TCP anyway and that
    TCP DNS query never gets a response. Fixed by running a small local
    CONNECT-proxy (`~/.local/share/anki-ai-cards/connect_proxy.py`, started
    via `~/.local/bin/ensure-npm-proxy.sh`) that does its own IPv4-only
    resolution, and pointing npm at it via `~/.npmrc` (`proxy`/`https-proxy`
    keys). Full detail is in AGENTS.md "Known constraints". If a future
    iteration sees `npm`/`npx` hang with no output, this is almost certainly
    it — run `~/.local/bin/ensure-npm-proxy.sh` (it's a no-op if already
    running) rather than debugging the project.
  - Neither `uv` nor a modern Node were preinstalled (system Node was v12,
    far too old for Next.js). Installed `uv` via astral's installer and Node
    24 LTS via `nvm`, then symlinked `node`/`npm`/`npx` into `~/.local/bin`
    (already on PATH) since `~/.bashrc`'s nvm sourcing only runs for
    interactive shells and this harness's Bash tool runs non-interactively.
  - AGENTS.md's verification commands section was already correct from a
    prior session (written before scaffolding existed) — no change needed
    there, only the new "Known constraints" bullet about the DNS proxy.
  - `create-next-app` generates its own `frontend/AGENTS.md` (points agents
    at bundled Next.js docs) and `frontend/CLAUDE.md` (`@AGENTS.md` import) —
    left both in place, they're scoped to the frontend subdir and don't
    conflict with the root AGENTS.md that the loop reads.
