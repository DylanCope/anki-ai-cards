# PRD — anki-ai-cards

## Overview

A personal web app that turns Japanese-lesson notes into Anki flashcards.
Dylan takes lessons in a Google Doc: his teacher pastes an English phrase,
Dylan writes a Japanese attempt, and the teacher corrects it, marking the
wrong parts in red text. Today Dylan manually turns the red-marked mistakes
into Cloze cards with furigana, an English translation, and ElevenLabs audio.
This app automates that: a chat UI backed by a Claude tool-using agent reads
the doc, proposes candidate cards, generates three ElevenLabs audio options
per card for Dylan to choose from, discovers Dylan's existing Anki note type
and its fields live via AnkiConnect (no hardcoded field mapping), and creates
the note. Cards reach Dylan's phone/desktop via a normal AnkiWeb sync — a
headless Anki + AnkiConnect instance runs on its own server and is logged
into his real AnkiWeb account, so no client reconfiguration is needed. Once
the agent and Dylan settle on how to handle a source, it saves that as a
named, reusable workflow spec so future sessions don't start from scratch.

Note the two distinct agents in this project: the **Ralph loop** (an
autonomous Claude instance that writes this codebase, iteration by iteration)
and the **inner agent** (the Claude tool-using agent *this codebase
implements*, which chats with Dylan at runtime about card creation). Tasks
below build the inner agent; they are not run by it.

## Requirements

**Repo layout:** `backend/` (Python) and `frontend/` (Next.js), monorepo.

**Backend stack:** Python + `uv` (pyproject.toml), FastAPI + uvicorn,
SQLModel over a SQLite file (path from `DATABASE_PATH` env var), `httpx` for
all outbound HTTP (ElevenLabs, AnkiConnect, Google Docs REST, and via the
`anthropic` SDK for Claude). Testing: `pytest` + `pytest-asyncio` + `respx`
for mocking `httpx` calls, `unittest.mock` for mocking the `anthropic` SDK.
**No test may make a real network call** to Google, Anthropic, ElevenLabs, or
AnkiConnect — all clients are unit-tested against mocked HTTP responses.

**Frontend stack:** Next.js (App Router, TypeScript), Tailwind CSS. Verified
via `npm run build` and `npm run lint` — visual/UX correctness cannot be
verified by the loop and needs manual browser review (say so explicitly in
PROGRESS.md when a UI task is done).

**Auth:** Google OAuth ("Sign in with Google") serves double duty — app login
and Docs API access (`openid`, `email`, `https://www.googleapis.com/auth/documents.readonly`
scopes). Only one email is allowed in (`ALLOWED_EMAIL` env var); reject
anyone else at the callback. Store tokens in the `OAuthToken` table.

**External services (all via env-var secrets, never committed):**
- `ANTHROPIC_API_KEY` — Claude tool-use agent.
- `ELEVENLABS_API_KEY` — TTS, 3 options per card.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — OAuth.
- `ALLOWED_EMAIL` — the one Google account allowed to use the app.
- `ANKICONNECT_URL` — base URL of the headless Anki instance.
- `DATABASE_PATH` — SQLite file location.
- `DEV_API_KEY` (optional) — bearer-token bypass for session-cookie auth, used
  by `backend/scripts/smoke_test_chat.py` and the Ralph loop to call the API
  without a browser OAuth flow. Unset disables the bypass entirely.

**Anki hosting:** headless Anki + AnkiConnect via the `ankimcp/headless-anki`
Docker image, deployed as its own Fly.io app with a persistent volume. Logged
into Dylan's real AnkiWeb account via a **one-time manual VNC step** — the
loop must never attempt this itself, only prepare the deployment and document
the manual step. The backend reaches it over Fly's private networking
(`<app>.internal:8765`). New notes are pushed to AnkiWeb via AnkiConnect's
`sync` action; Dylan's phone/desktop Anki apps pull them via their normal
existing AnkiWeb sync — no client reconfiguration.

**The inner agent's tools:** `fetch_google_doc`, `list_anki_note_types`,
`get_anki_note_type_fields`, `generate_audio`, `create_anki_note`,
`sync_anki`, `save_workflow_spec`, `load_workflow_spec`, `list_workflow_specs`.
The agent — not hardcoded logic — decides field mapping, cloze structure,
and when to ask Dylan a clarifying question.

**Deployment:** Fly.io for both the backend/frontend app and the headless
Anki app. The loop has standing authorization to run `fly deploy`/`fly
logs`/`fly status`/`fly apps restart`/`fly ssh console` against all three
apps (see AGENTS.md's "Autonomous deploy/debug access") — creating/extending
volumes, allocating IPs, and anything requiring interactive UI access (OAuth
consent, VNC login) remain Dylan's manual steps.

## Tasks

- [x] **1. Scaffold the repo.** `backend/`: `uv` project with FastAPI app
  exposing `GET /health`, `pytest` configured with one trivial passing test.
  `frontend/`: Next.js + TypeScript + Tailwind scaffold with a placeholder
  homepage. Add `.env.example` listing all env vars from Requirements. Update
  `AGENTS.md`'s verification commands to `cd backend && uv run pytest` and
  `cd frontend && npm run build && npm run lint`. Verify: both commands pass.

- [x] **2. Persistence layer.** `backend/app/models.py`: SQLModel tables
  `ConversationMessage`, `WorkflowSpec`, `ProcessingCursor`, `PendingCard`,
  `OAuthToken`. An `init_db()` creates tables at `DATABASE_PATH`. Tests
  round-trip a row through each table. Verify: `uv run pytest backend/tests/test_models.py` passes.

- [x] **3. AnkiConnect client.** `backend/app/clients/ankiconnect.py`: async
  `invoke(action, **params)` wrapper over the AnkiConnect HTTP protocol
  (version 6), plus `list_note_type_names()`, `get_note_type_fields(name)`,
  `create_note(...)`, `sync()`. Raise a clear exception when AnkiConnect's
  JSON response has a non-null `error`. Tests mock the HTTP layer with
  `respx`, covering both success and the error-surfacing case. Verify: tests pass.

- [x] **4. ElevenLabs client.** `backend/app/clients/elevenlabs.py`:
  `generate_audio_options(text: str, n: int = 3) -> list[bytes]`, varying
  voice settings slightly per option. API key from `ELEVENLABS_API_KEY`.
  Tests mock the HTTP call and assert 3 distinct requests are made and 3
  byte payloads returned. Verify: tests pass.

- [x] **5. Google Docs client.** `backend/app/clients/google_docs.py`: OAuth
  helpers (`build_authorize_url`, `exchange_code_for_tokens`,
  `refresh_access_token`), `fetch_document(document_id, access_token) -> dict`
  (raw Docs API JSON via REST), and `flatten_runs(doc_json) -> list[dict]`
  producing `{text, color}` spans per paragraph so the freeform layout can be
  handed to the agent as plain structured data instead of raw Docs JSON.
  Tests use a hand-written fixture Docs API response and assert red-colored
  spans are correctly identified. Verify: tests pass.

- [x] **6. Google OAuth + session auth.** FastAPI routes
  `/auth/google/login` and `/auth/google/callback`. Callback rejects any
  email other than `ALLOWED_EMAIL`, otherwise stores tokens and sets a signed
  session cookie. A `require_auth` dependency protects all other routes.
  Tests mock the token exchange and cover both the rejected and accepted
  email paths. Verify: tests pass.

- [x] **7. Claude agent core.** `backend/app/agent/`: tool schemas +
  dispatcher wiring tasks 3–5's clients as callable tools, a system prompt
  describing the agent's job (per Overview), and `run_turn(history, message)`
  driving the `anthropic` SDK's tool-use loop to completion. Tests mock the
  Anthropic client with canned `tool_use` → `end_turn` sequences and assert
  the dispatcher invokes the right underlying client function with the right
  arguments. Verify: tests pass.

- [x] **8. Workflow spec persistence + tools.** `save_workflow_spec`,
  `load_workflow_spec`, `list_workflow_specs` tools backed by the
  `WorkflowSpec` table from task 2; `run_turn` surfaces known specs at the
  start of a conversation so the agent can offer to reuse one. Tests cover
  save/load round-trip and listing. Verify: tests pass.

- [x] **9. Chat API.** `POST /api/chat` (send a message, get the agent's
  response plus any structured payloads — proposed cards, audio options — for
  the frontend to render) and `GET /api/chat/history`. Non-streaming JSON for
  v1. Tests use FastAPI's `TestClient` with the agent core mocked. Verify: tests pass.

- [x] **10. Frontend chat UI.** Next.js page: "Sign in with Google" button
  redirecting to the backend login route; a chat thread that posts to
  `/api/chat` and renders responses, with dedicated components for a
  candidate-card payload (JP cloze, furigana, English, note, approve/edit)
  and an audio-options payload (3 players + pick button), both rendered
  inline in the chat. Verify: `npm run build` and `npm run lint` pass; note
  in PROGRESS.md that appearance/UX needs your manual check in a browser.

- [x] **11. Headless Anki deployment config.** `fly.toml` + any Dockerfile
  needed for the `ankimcp/headless-anki` image as its own Fly app with a
  persistent volume. Document the one-time manual VNC login step to AnkiWeb
  in AGENTS.md. Add a small smoke-test script that calls AnkiConnect's
  `version` action against a configurable URL. Verify: smoke-test script
  runs correctly against a local mock/stub AnkiConnect server in a test;
  running it against the real deployed instance is a manual step for you
  once the VNC login is done.

- [x] **12. Backend/frontend deployment config.** `fly.toml` for the
  backend (env vars from Requirements wired as Fly secrets placeholders,
  `ANKICONNECT_URL` pointed at the Anki app's `.internal` address, SQLite
  volume mounted) and for the frontend. Verify: `fly config validate` (or
  equivalent structural check) passes on both configs. Do not run `fly deploy`.

- [x] **13. Manual end-to-end verification checklist.** Write
  `docs/manual_verification.md`: log in with Google, start a chat, point the
  agent at the real lesson doc, confirm it discovers your note type and
  fields, propose a card, generate audio, pick one, create the note, confirm
  it appears on your phone after sync. Verify: the document exists and
  accurately reflects the built system's actual flow (cross-check against
  tasks 1–12) — running the checklist itself is your manual job, not the loop's.

- [x] **14. Fix the backend's broken external reachability — this blocks
  everything below, do it first.** `anki-ai-cards-backend`'s own health
  check (`GET /health`) has been continuously `critical` for hours (`fly
  status -a anki-ai-cards-backend` shows `1 total, 1 critical`; `fly checks
  list -a anki-ai-cards-backend` shows it actively failing, not just a stale
  registration — confirmed by watching `fly apps restart` poll it live and
  time out with `context deadline exceeded`), and Fly's public proxy refuses
  to route to it at all (`fly logs` shows `"could not find a good candidate
  within 40 attempts at load balancing"` for both `/health` and `/api/chat`).
  This means **no external request reaches the backend right now** — this
  is very likely the actual reason Dylan's original "list Anki note types"
  request errored, independent of anything AnkiConnect-related in task 15.
  See the 2026-07-04 PROGRESS.md entry ("Blocked: backend external
  reachability") for the full investigation already done and ruled out
  before you start — read it before re-deriving any of this:
  - Internal 6PN reachability is fine (`http://anki-ai-cards-backend.
    internal:8000/health` returns 200 from a sibling Fly app), so the
    process itself is up and serving — this is specifically an
    external/public-path problem.
  - Ruled out: uvicorn's default event loop (uvloop) forcing an IPv6-only
    bind — `backend/Dockerfile`'s `CMD` already has `--loop asyncio` from
    this investigation and it made no difference (still refuses IPv4
    loopback, confirmed via `fly ssh console`).
  - Ruled out (partially): a hand-replicated copy of uvicorn's exact
    `bind_socket()` logic, run inside the same machine/namespace via `fly
    ssh console`, produced a working dual-stack socket (`IPV6_V6ONLY=0`,
    accepts both `127.0.0.1` and `::1`) — yet the real uvicorn process on
    port 8000 refuses `127.0.0.1` while accepting `::1`. This discrepancy
    was never explained — that's the open thread to pick up.
  - Not yet tried: temporarily reverting `--host ::` to `--host 0.0.0.0` to
    confirm/rule out the bind address as the deciding factor (would need to
    also verify it doesn't just re-break the frontend→backend 6PN path this
    app was built for in the first place — check both before deciding this
    is the fix, not just the public health check).
  You have standing authorization to run `fly deploy`/`fly logs`/`fly
  status`/`fly apps restart`/`fly ssh console` against all three apps (see
  AGENTS.md's "Autonomous deploy/debug access"). Verify: `curl https://anki-
  ai-cards-backend.fly.dev/health` (or `fly status`) shows the check
  passing, from outside any Fly app — this is verified against real infra,
  not mocks. If you exhaust reasonable attempts, do not mark this done —
  append to the "Blocked" entry in PROGRESS.md with what you additionally
  tried and ruled out.

- [ ] **15. Fix AnkiConnect connectivity in production, verified end to
  end.** Blocked on task 14 — the backend must be externally reachable
  before this can be tested at all. Dylan asked the deployed chat agent to
  list Anki note types and got an error. AGENTS.md's "Headless Anki
  deployment" section documents three layered fixes already attempted
  (Flycast routing, a socat relay, and a D-Bus daemon + retry logic for
  Anki's intermittent segfault) — none confirmed working end to end yet.
  Use `backend/scripts/smoke_test_chat.py` (`DEV_API_KEY=... uv run python
  -m scripts.smoke_test_chat`, from `backend/`) asking it to list note types
  as your reproduction case, and `fly logs -a anki-ai-cards-anki` / `fly
  logs -a anki-ai-cards-backend` to see what's actually failing. You have
  standing authorization to run `fly deploy`/`fly logs`/`fly status`/`fly
  apps restart`/`fly ssh console` against all three apps to iterate (see
  AGENTS.md's "Autonomous deploy/debug access") — you do not need to ask
  Dylan before deploying a fix attempt. Do not touch volumes, IPs, or
  anything requiring VNC/OAuth UI access. Verify: `smoke_test_chat.py`
  against the real production backend returns a reply that actually lists
  Dylan's real Anki note types (not an error) — this is verified against
  real infra rather than mocks; note the specific root cause and fix in
  PROGRESS.md. If you exhaust reasonable attempts without success, do not
  mark this done — record what you tried and ruled out in PROGRESS.md under
  "Blocked" instead.

## Out of scope

- Any source type other than the one Google Doc (no generic connector
  framework).
- Multi-user support or any auth beyond the single allowlisted email.
- A no-code/UI workflow builder — flexibility comes from the agent's
  reasoning over tools, not a visual configuration surface.
- The loop performing interactive OAuth consent or VNC logins — these remain
  one-time actions Dylan runs himself. (`fly deploy` and other fly commands
  are now in scope for the loop — see AGENTS.md's "Autonomous deploy/debug
  access".)
- Real (non-mocked) calls to Google, Anthropic, ElevenLabs, or AnkiConnect
  from the automated `pytest` suite (the manual/loop-invoked smoke-test
  scripts are a deliberate exception — see AGENTS.md).
- Streaming chat responses (SSE/WebSocket) — v1 is request/response.
