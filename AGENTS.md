# AGENTS.md — project conventions

Read by every loop iteration. Keep it short and current — this file and
PROGRESS.md are the only "memory" between iterations.

## Verification commands

- Backend tests: `cd backend && uv run pytest`
- Frontend build/lint: `cd frontend && npm run build && npm run lint`

## Conventions

- Language/stack: Python (`uv`, FastAPI, SQLModel, httpx, `anthropic` SDK) in
  `backend/`; Next.js + TypeScript + Tailwind in `frontend/`.
- Commit style: one task per commit, imperative message, reference the PRD task number.
- Structure: `backend/app/{clients,agent,api,models.py}`, `backend/tests/`;
  `frontend/` standard Next.js App Router layout.
- All outbound HTTP (ElevenLabs, AnkiConnect, Google Docs, Anthropic) goes
  through `httpx`; tests mock it with `respx` (or mock the `anthropic` SDK
  client directly) — never hit real services from a test.
- Secrets are env vars only, documented in `.env.example`, never committed.
  See PRD.md Requirements for the full list.

## Known constraints

- Two distinct agents exist in this project: the Ralph loop (builds this
  code) and the inner agent (the runtime Claude tool-use agent this code
  implements, defined in `backend/app/agent/`). Don't conflate them.
- The loop must never attempt interactive OAuth consent, VNC logins to the
  headless Anki instance, or `fly deploy` — these are one-time or
  infrastructure-affecting steps Dylan runs manually. Prepare configs/docs
  for them, don't execute them.
- No test may make a real network call to Google, Anthropic, ElevenLabs, or
  AnkiConnect. Mock everything at the `httpx`/SDK-client boundary.
- The app is single-user: access is gated to one Google account via
  `ALLOWED_EMAIL`. Don't add multi-user/auth-provider abstractions.
- UI appearance/UX correctness can't be verified by the loop — flag it in
  PROGRESS.md for Dylan's manual review instead of claiming it "works."
