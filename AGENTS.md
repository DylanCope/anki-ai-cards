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

## Headless Anki deployment (manual steps for Dylan)

Config lives at `deploy/anki-headless/fly.toml` (the `ankimcp/headless-anki`
image, no code from this repo — see that file's header comment for why no
public `[[services]]` are declared). The loop prepares/validates this config
but must never run `fly deploy` or perform the login below.

One-time AnkiWeb login via VNC, after `fly deploy --config
deploy/anki-headless/fly.toml` has been run manually:

1. `fly proxy 5900 -a anki-ai-cards-anki` (tunnels the app's VNC port to
   `localhost:5900` over Fly's private network — no public VNC port is ever
   exposed).
2. Connect a VNC client to `localhost:5900` (no VNC auth is configured by the
   image, so the tunnel itself is the only access control).
3. Inside the desktop, open Anki, go to the AnkiWeb login screen, and sign in
   with Dylan's real AnkiWeb account credentials.
4. Once logged in, Anki's sync state persists in the `/data` volume mount, so
   this step should not need repeating across deploys/restarts of the same
   app — only if the volume is ever recreated.
5. Verify AnkiConnect is up: run
   `uv run python -m scripts.smoke_test_ankiconnect --url http://localhost:8765`
   from `backend/` after also running `fly proxy 8765 -a anki-ai-cards-anki`
   in another terminal (or from another Fly app on the same private network,
   pointed at `anki-ai-cards-anki.internal:8765` directly, no proxy needed).

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
- **Environment DNS bug:** this WSL2 sandbox's DNS proxy corrupts responses
  for some domains (e.g. `registry.npmjs.org`), causing `npm`/`npx`/`curl` to
  hang forever (glibc retries over TCP after a bad UDP answer; the proxy
  doesn't answer TCP DNS). Workaround already applied: a local CONNECT proxy
  at `~/.local/share/anki-ai-cards/connect_proxy.py` (does its own IPv4-only
  resolution) is registered in `~/.npmrc` as `proxy`/`https-proxy`. If `npm`
  commands hang again, run `~/.local/bin/ensure-npm-proxy.sh` to restart it —
  it's a background process that doesn't survive a VM restart. This is a
  sandbox quirk, not a project dependency; nothing to fix in the repo.
