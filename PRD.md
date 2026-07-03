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
Anki app. The loop may write and validate `fly.toml`/Dockerfiles but must
never run `fly deploy` itself — that's a real infrastructure change Dylan
runs manually.

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

- [ ] **6. Google OAuth + session auth.** FastAPI routes
  `/auth/google/login` and `/auth/google/callback`. Callback rejects any
  email other than `ALLOWED_EMAIL`, otherwise stores tokens and sets a signed
  session cookie. A `require_auth` dependency protects all other routes.
  Tests mock the token exchange and cover both the rejected and accepted
  email paths. Verify: tests pass.

- [ ] **7. Claude agent core.** `backend/app/agent/`: tool schemas +
  dispatcher wiring tasks 3–5's clients as callable tools, a system prompt
  describing the agent's job (per Overview), and `run_turn(history, message)`
  driving the `anthropic` SDK's tool-use loop to completion. Tests mock the
  Anthropic client with canned `tool_use` → `end_turn` sequences and assert
  the dispatcher invokes the right underlying client function with the right
  arguments. Verify: tests pass.

- [ ] **8. Workflow spec persistence + tools.** `save_workflow_spec`,
  `load_workflow_spec`, `list_workflow_specs` tools backed by the
  `WorkflowSpec` table from task 2; `run_turn` surfaces known specs at the
  start of a conversation so the agent can offer to reuse one. Tests cover
  save/load round-trip and listing. Verify: tests pass.

- [ ] **9. Chat API.** `POST /api/chat` (send a message, get the agent's
  response plus any structured payloads — proposed cards, audio options — for
  the frontend to render) and `GET /api/chat/history`. Non-streaming JSON for
  v1. Tests use FastAPI's `TestClient` with the agent core mocked. Verify: tests pass.

- [ ] **10. Frontend chat UI.** Next.js page: "Sign in with Google" button
  redirecting to the backend login route; a chat thread that posts to
  `/api/chat` and renders responses, with dedicated components for a
  candidate-card payload (JP cloze, furigana, English, note, approve/edit)
  and an audio-options payload (3 players + pick button), both rendered
  inline in the chat. Verify: `npm run build` and `npm run lint` pass; note
  in PROGRESS.md that appearance/UX needs your manual check in a browser.

- [ ] **11. Headless Anki deployment config.** `fly.toml` + any Dockerfile
  needed for the `ankimcp/headless-anki` image as its own Fly app with a
  persistent volume. Document the one-time manual VNC login step to AnkiWeb
  in AGENTS.md. Add a small smoke-test script that calls AnkiConnect's
  `version` action against a configurable URL. Verify: smoke-test script
  runs correctly against a local mock/stub AnkiConnect server in a test;
  running it against the real deployed instance is a manual step for you
  once the VNC login is done.

- [ ] **12. Backend/frontend deployment config.** `fly.toml` for the
  backend (env vars from Requirements wired as Fly secrets placeholders,
  `ANKICONNECT_URL` pointed at the Anki app's `.internal` address, SQLite
  volume mounted) and for the frontend. Verify: `fly config validate` (or
  equivalent structural check) passes on both configs. Do not run `fly deploy`.

- [ ] **13. Manual end-to-end verification checklist.** Write
  `docs/manual_verification.md`: log in with Google, start a chat, point the
  agent at the real lesson doc, confirm it discovers your note type and
  fields, propose a card, generate audio, pick one, create the note, confirm
  it appears on your phone after sync. Verify: the document exists and
  accurately reflects the built system's actual flow (cross-check against
  tasks 1–12) — running the checklist itself is your manual job, not the loop's.

## Out of scope

- Any source type other than the one Google Doc (no generic connector
  framework).
- Multi-user support or any auth beyond the single allowlisted email.
- A no-code/UI workflow builder — flexibility comes from the agent's
  reasoning over tools, not a visual configuration surface.
- The loop performing interactive OAuth consent, VNC logins, or `fly deploy`
  — these are one-time or infrastructure-affecting actions Dylan runs himself.
- Real (non-mocked) calls to Google, Anthropic, ElevenLabs, or AnkiConnect
  from automated tests.
- Streaming chat responses (SSE/WebSocket) — v1 is request/response.
