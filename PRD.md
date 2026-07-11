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

- [x] **15. Fix AnkiConnect connectivity in production, verified end to
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

- [x] **16. Bug report backend: capture unhandled errors from a chat turn.**
  Dylan tried creating a card and it failed generating audio — right now any
  unhandled exception during `POST /api/chat` (e.g. `elevenlabs.py`'s
  `response.raise_for_status()` raising on a bad ElevenLabs response) just
  propagates to a bare FastAPI 500 with no detail captured anywhere except
  `fly logs`. Add a `BugReport` table (`backend/app/models.py`): `id`,
  `created_at`, `message` (short, e.g. `str(exception)`), `detail` (full
  `traceback.format_exc()` output, plus the user's message text for
  context). In `backend/app/api/chat.py`'s `post_chat`, wrap the
  `agent_core.run_turn(...)` call in a `try/except Exception`: on failure,
  save a `BugReport` row, then raise `HTTPException(500, detail={"error":
  "...", "bug_report_id": <id>})` — a short message only, never the full
  traceback, since this response can reach a browser. Add two new routes
  (reuse `require_auth` so `DEV_API_KEY` works): `GET /api/bug-reports`
  (most recent ~20, id/created_at/message only, newest first) and `GET
  /api/bug-reports/{id}` (full record including `detail`). Verify:
  `cd backend && uv run pytest` — mock a tool raising (e.g. monkeypatch
  `elevenlabs.generate_audio_options` to raise), assert a `BugReport` row is
  created, the chat endpoint returns 500 with a `bug_report_id` in the body
  (not a raw traceback), and both GET routes return the expected shape and
  require auth.

- [x] **17. Bug report frontend: surface the report inline in the chat UI.**
  No separate bug-reports page (deliberately out of scope — single-user app,
  the API is enough for browsing history by hand) — just make the existing
  generic "Something went wrong..." error in `frontend/app/components/
  ChatApp.tsx` actually useful. When `POST /api/chat` returns non-ok, parse
  the JSON body for `bug_report_id`/`error` (task 16's shape) and show
  something like "Something went wrong — bug report #7 filed." instead of
  the current fixed string. Update `frontend/app/lib/types.ts` if a type is
  needed for the error body shape. Verify: `cd frontend && npm run build &&
  npm run lint`; note in PROGRESS.md that the actual rendered appearance
  needs Dylan's manual check in a browser.

- [x] **18. Scope furigana correctly: a per-workflow display choice, but
  mandatory for accurate audio.** Dylan clarified that furigana appearing on
  the visible Anki card is his call per source/workflow (something a saved
  `save_workflow_spec` can already capture) — the system prompt currently
  states it as a blanket rule ("turn each one into an Anki Cloze card with
  furigana", `backend/app/agent/prompts.py`), which overclaims. The one
  place furigana is *always* needed regardless of card preference: deriving
  an accurate reading before calling `generate_audio`, since ElevenLabs
  sometimes misreads bare kanji. Update `SYSTEM_PROMPT` to (a) stop
  presenting furigana-on-card as mandatory — frame it as a per-source
  preference to settle with Dylan and record via `save_workflow_spec`, same
  as field mapping/cloze conventions already are, and (b) explicitly
  instruct the agent to always work out the correct reading for any
  Japanese text and pass reading-informed text into `generate_audio`
  (not bare kanji) specifically to avoid mispronunciation, independent of
  whatever the card itself displays. This is a prompt-wording change, not
  new code — there's no `generate_audio` schema change implied unless task
  19's actual fix needs one. Verify: `cd backend && uv run pytest` still
  passes (no regressions); this task's real verification is the prompt text
  itself matching the above — note in PROGRESS.md that the prompt's
  effectiveness in a live conversation is a judgment call, not something
  pytest checks.

- [x] **19. Fix the actual audio-generation bug, using the new bug-report
  system to diagnose it.** Blocked on task 16 (need the bug-report capture
  in place) and informed by task 18 (the fix should produce reading-accurate
  text for ElevenLabs, not just patch whatever the immediate error is).
  Reproduce for real: use `DEV_API_KEY` (`fly ssh console -a
  anki-ai-cards-backend -C "printenv DEV_API_KEY"` if you need the value,
  per task 15's PROGRESS entry) and either `backend/scripts/
  smoke_test_chat.py` or a direct call to ask the deployed agent to generate
  audio for a piece of Japanese text containing a commonly-misread kanji —
  no need to go through the full doc-parsing flow, `generate_audio` is a
  standalone tool the agent can call directly from a simple request. Check
  `GET /api/bug-reports` (task 16) and `fly logs -a anki-ai-cards-backend`
  for the actual captured error/traceback — don't guess at the cause;
  `backend/app/clients/elevenlabs.py`'s request body has no `model_id`
  (ElevenLabs defaults this server-side, and the default model's language
  support is worth checking directly against ElevenLabs' actual current API
  docs/response rather than assumed) and no error handling around the HTTP
  call — but confirm what ElevenLabs' response actually says before
  assuming that's the fix. Verify: unit tests in `backend/tests/` covering
  the real failure mode found (mocked via `respx`) plus the success path;
  **and** the authoritative real-infra check — the same reproduction call
  now returns real audio (an `audio_options` payload with non-empty base64
  data, not an error/bug report), and the bug report captured during
  reproduction is still visible via `GET /api/bug-reports` as a historical
  record. If you exhaust reasonable attempts, do not mark this done — record
  what you tried and ruled out in PROGRESS.md under "Blocked" instead.

### UI overhaul (tasks 20-32)

Dylan's current frontend works but is rough: broken scroll regions, plain
text messages, a single-line input, structured payloads that vanish on
reload, and default/unstyled Tailwind look-and-feel. This batch of tasks
fixes those explicit bugs, then layers on a design-system pass modeled on a
reference app (`shadow-renshuu`, screenshots reviewed during the interview:
dark theme, purple-600 accent, kanji branding mark, rounded-xl cards, Inter +
Noto Sans JP fonts), plus conversation management and a manual workflow-spec
editor. Ordered so bug fixes land first (style-agnostic), then the design
system, then everything that consumes it.

**Deploy-and-verify convention for tasks 20-32:** beyond each task's local
`npm run build && npm run lint` (and `uv run pytest` for backend-touching
tasks), also `fly deploy` the app(s) the task touched — `frontend/` for
frontend-only tasks, `backend/` for backend-only tasks, both for tasks that
touch both — then confirm `fly status -a anki-ai-cards-frontend` and/or
`fly status -a anki-ai-cards-backend` shows the machine started/healthy and
skim `fly logs -a <app>` for startup or runtime errors. This is in addition
to, not a replacement for, the manual browser check Dylan still needs to do
for visual/UX correctness — it just catches real deploy breakage (bad build,
crash-on-boot, missing env var) that local checks can't, per AGENTS.md's
"Autonomous deploy/debug access" (already-standing authorization to run `fly
deploy`/`fly logs`/`fly status` against all three apps). Note the outcome of
this step in PROGRESS.md for every task in this range.

- [x] **20. Fix independent pane scrolling.** `frontend/app/layout.tsx`,
  `frontend/app/page.tsx`, `frontend/app/components/ChatApp.tsx`: rework the
  layout to a fixed-height flex tree (`h-dvh` on the outermost container) so
  `ConversationSidebar` and the model-selector bar stay pinned and only the
  message list (and, independently, the sidebar's conversation list) scrolls
  via its own `overflow-y-auto` region — growing the composer or the
  transcript must never push the sidebar out of view. Verify: `cd frontend
  && npm run build && npm run lint` pass; deploy-and-verify per the note
  above; note in PROGRESS.md that Dylan should confirm in a browser by
  sending enough messages to overflow the transcript.

- [x] **21. Composer: auto-resizing textarea, Enter/Shift+Enter, IME-safe.**
  `frontend/app/components/ChatApp.tsx`: replace the single-line `<input>`
  with a `<textarea>` that grows with content up to a max height (then
  scrolls internally), where Enter submits and Shift+Enter inserts a
  newline. Must check `event.nativeEvent.isComposing` (and/or `keyCode ===
  229`) and skip submission on Enter while an IME composition is in progress
  — this matters because Dylan sometimes types Japanese directly into the
  chat, and Enter is also used to confirm kana→kanji conversion. Verify: `cd
  frontend && npm run build && npm run lint` pass; deploy-and-verify; note
  in PROGRESS.md that Dylan should confirm the IME behavior himself (an IME
  isn't something a headless build/lint step can exercise) by typing
  Japanese with an IME enabled and confirming Enter-to-convert doesn't send.

- [x] **22. Markdown rendering for chat messages.** Add `react-markdown` +
  `remark-gfm` to `frontend/package.json`; update
  `frontend/app/components/MessageBubble.tsx` to render message text through
  them instead of as plain text, with Tailwind styling for headings, lists,
  links, inline code, code blocks, and tables that works in both light and
  dark mode (fine to use plain utility classes for now — task 26 will
  restyle everything to the new design system). Verify: `cd frontend && npm
  run build && npm run lint` pass; deploy-and-verify; note in PROGRESS.md
  that Dylan should eyeball a message containing a list/code block/table in
  a browser.

- [x] **23. Backend: persist structured payloads across history reloads.**
  `backend/app/api/chat.py`: `_extract_payloads` currently only ever runs
  over a single turn's `new_messages` inside `post_chat` — `GET
  /api/chat/history` calls `_display_text` only and never re-derives
  payloads, so `AudioOptionsCard`/`CardPayloadCard` data is silently dropped
  on reload. Refactor so payload extraction can run over the full stored
  history (reuse the same tool_use/tool_result matching logic across all
  rows, not just the newest ones), and change `get_chat_history`'s response
  shape to return payloads alongside each turn instead of a flat
  `{role, text}` list — e.g. `{role, text, payloads}` per entry. Verify: `cd
  backend && uv run pytest backend/tests/test_chat.py` covering a
  conversation with a `generate_audio` and a `create_anki_note` tool call,
  reloading history, and confirming both payload types come back correctly
  shaped; deploy-and-verify per the note above (backend only).

- [x] **24. Frontend: consume persisted payloads on history load.** Depends
  on task 23. `frontend/app/lib/types.ts`: update `ChatHistoryEntry`/add
  whatever type matches task 23's new history response shape.
  `frontend/app/components/ChatApp.tsx`: the history-loading effect
  (currently `setTurns(history.map((message) => ({ message, payloads: []
  })))`) must populate `payloads` from the response instead of hardcoding an
  empty array. Verify: `cd frontend && npm run build && npm run lint` pass;
  deploy-and-verify (both apps, since this pairs with task 23's backend
  shape); note in PROGRESS.md that Dylan should confirm by triggering an
  audio-options or card payload, reloading the page, and seeing it still
  render.

- [ ] **25. Design-system foundation.** Add `lucide-react` to
  `frontend/package.json`. `frontend/app/layout.tsx`: swap the Geist fonts
  for Inter (general text) and Noto Sans JP (Japanese text, via
  `next/font/google`), matching the reference app. `frontend/app/globals.css`:
  define the new token set — purple-600 accent, gray-950/900 dark surfaces,
  gray-100 dark-mode text, gray-200/800 borders, `rounded-xl` for cards and
  `rounded-lg` for buttons/inputs as the standing convention going forward.
  Add a persisted light/dark theme toggle: a small client-side
  `ThemeProvider`/context that reads/writes `localStorage`, applies a `dark`
  class on `<html>` (don't rely solely on `prefers-color-scheme` anymore —
  Dylan wants an explicit, persisted toggle like the reference app's
  sun/moon icon), and a toggle button component using a `lucide-react` icon.
  This task only builds the foundation (tokens, fonts, toggle) — it does not
  need to restyle every existing component yet (task 26 does). Verify: `cd
  frontend && npm run build && npm run lint` pass; deploy-and-verify; note
  in PROGRESS.md that Dylan should confirm the toggle flips themes and
  survives a reload.

- [ ] **26. Visual overhaul of the chat surface.** Depends on task 25.
  Restyle `frontend/app/components/{MessageBubble,AudioOptionsCard,
  CardPayloadCard,SignIn,ConversationSidebar,ModelSelector}.tsx` and
  `frontend/app/components/ChatApp.tsx`'s header/composer chrome using the
  task 25 token set: rounded-xl cards, purple-600 primary buttons as solid
  pills, gray-950/900 dark surfaces. Add a small kanji/branding mark next to
  the app name in the header, matching the reference screenshots' layout
  (icon + bold app name + subtitle). Verify: `cd frontend && npm run build
  && npm run lint` pass; deploy-and-verify; note in PROGRESS.md that this is
  a primarily-visual change requiring Dylan's manual browser review across
  both light and dark mode.

- [ ] **27. Typing indicator + toast-style errors.** Depends on task 25 for
  consistent styling. `frontend/app/components/ChatApp.tsx`: show an
  animated "assistant is composing" indicator (e.g. bouncing dots) in the
  message list while `sending` is true, instead of only disabling the
  composer. Replace the current bare `<p className="text-red-500">{error}</p>`
  with a small dismissible toast/banner component, styled with the new
  tokens, that doesn't block or disable the composer while shown. Verify:
  `cd frontend && npm run build && npm run lint` pass; deploy-and-verify;
  note in PROGRESS.md that Dylan should trigger a failed request (e.g.
  briefly stop the backend or use dev tools to force a non-200) to confirm
  the toast appears and is dismissible.

- [ ] **28. Backend: conversation rename + cascade delete.**
  `backend/app/api/chat.py`: extend `UpdateConversationRequest` /
  `update_conversation` (`PATCH /api/conversations/{id}`) to accept an
  optional `title` alongside the existing `model` field. Add `DELETE
  /api/conversations/{id}` that deletes the `Conversation` row and cascades
  to delete all its `ConversationMessage` rows (hard delete — this is a
  single-user personal app, no soft-delete/undo needed). Verify: `cd backend
  && uv run pytest backend/tests/test_chat.py` covering rename and
  delete-cascades-messages; deploy-and-verify per the note above (backend
  only).

- [ ] **29. Frontend: conversation rename + delete UI.** Depends on task 28.
  `frontend/app/components/ConversationSidebar.tsx`: add an inline-rename
  affordance (e.g. an edit icon that turns the title into an editable field
  on click) and a delete icon with a confirm-before-destructive-action
  step (a plain `window.confirm` is fine — this is a hard-to-reverse cascade
  delete). `frontend/app/components/ChatApp.tsx`: wire both through new
  handlers calling task 28's endpoints; if the currently-active conversation
  is deleted, switch to another existing conversation or create a fresh one,
  same as `startNewChat`. Verify: `cd frontend && npm run build && npm run
  lint` pass; deploy-and-verify (both apps); note in PROGRESS.md that Dylan
  should confirm rename/delete/delete-of-active-conversation in a browser.

- [ ] **30. Mobile-responsive sidebar.** Depends on tasks 25 (icon) and 29
  (avoid touching `ConversationSidebar.tsx` concurrently with unrelated
  work). Below a Tailwind breakpoint (e.g. `md`), collapse
  `ConversationSidebar` behind a hamburger/menu icon that opens it as an
  overlay instead of an always-visible fixed-width column. Verify: `cd
  frontend && npm run build && npm run lint` pass; deploy-and-verify; note
  in PROGRESS.md that Dylan should confirm by resizing the browser or using
  devtools' device toolbar, since this can't be exercised headlessly.

- [ ] **31. Backend: workflow spec REST endpoints.** `backend/app/agent/
  workflow_specs.py`: add a `delete_workflow_spec(name)` helper alongside
  the existing `save_workflow_spec`/`load_workflow_spec`/
  `list_workflow_specs` (none of which are exposed over HTTP today — only
  the agent calls them as tools). Add a new router (e.g.
  `backend/app/api/workflows.py`, registered in `backend/app/main.py`
  alongside the existing routers) exposing `GET /api/workflow-specs` (list,
  name + timestamps + full `spec` text), `GET /api/workflow-specs/{name}`,
  `PUT /api/workflow-specs/{name}` (create-or-update the freeform `spec`
  text — this is a plain-text editor over the same data the agent already
  writes, not a structured field-mapping form, see the Out-of-scope
  amendment below), and `DELETE /api/workflow-specs/{name}`, all behind
  `require_auth` like the existing routers. Verify: `cd backend && uv run
  pytest backend/tests/test_workflow_specs.py` (or a new
  `test_workflows_api.py`) covering all four endpoints including the
  create-or-update-by-name semantics and delete-then-404; deploy-and-verify
  per the note above (backend only).

- [ ] **32. Frontend: Workflows page.** Depends on tasks 31 and 25. New
  route `frontend/app/workflows/page.tsx` listing saved workflow specs as
  cards (name, updated_at, truncated preview) using the task 25 design
  system, each opening into a plain `<textarea>` editor with Save/Delete, and
  a "+ New workflow" control (name input + blank textarea) that calls task
  31's `PUT` endpoint. Reachable via a small icon/link in the chat page's
  header (next to the theme toggle). Verify: `cd frontend && npm run build
  && npm run lint` pass; deploy-and-verify (both apps); note in PROGRESS.md
  that Dylan should confirm creating, editing, and deleting a workflow spec
  in a browser, and that the agent still sees it via `list_workflow_specs`
  in a live chat.

## Out of scope

- Any source type other than the one Google Doc (no generic connector
  framework).
- Multi-user support or any auth beyond the single allowlisted email.
- A no-code/UI *field-mapping* workflow builder — flexibility for *how a
  workflow spec's content is derived* still comes from the agent's
  reasoning over tools, not a visual configuration surface. Tasks 31/32's
  Workflows page is narrower than this and explicitly in scope: a plain
  freeform-text list/view/create/edit/delete UI over the exact same
  `spec` string the agent already reads and writes via
  `save_workflow_spec`/`load_workflow_spec` — no structured fields, no
  field-mapping logic gets hardcoded anywhere.
- Ruby/furigana-aware markdown rendering and copy-to-clipboard on messages —
  considered during the UI-overhaul interview (tasks 20-32) but Dylan didn't
  pick them; task 22's markdown support is plain `react-markdown`/
  `remark-gfm` only.
- The loop performing interactive OAuth consent or VNC logins — these remain
  one-time actions Dylan runs himself. (`fly deploy` and other fly commands
  are now in scope for the loop — see AGENTS.md's "Autonomous deploy/debug
  access".)
- A dedicated bug-reports page/UI (task 17) — inline surfacing in the chat
  error message plus the `GET /api/bug-reports` API (task 16) is enough for
  a single-user app; Dylan can hit the API directly to browse history.
- A fixed, system-wide rule for whether furigana appears on the visible
  card (task 18) — that's a per-source preference Dylan settles via
  `save_workflow_spec`, not something to hardcode. Only the
  `generate_audio` input is unconditionally required to be reading-accurate.
- Real (non-mocked) calls to Google, Anthropic, ElevenLabs, or AnkiConnect
  from the automated `pytest` suite (the manual/loop-invoked smoke-test
  scripts are a deliberate exception — see AGENTS.md).
- Streaming chat responses (SSE/WebSocket) — v1 is request/response.
