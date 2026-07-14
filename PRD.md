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
- No env var is needed for `search_images` (task 41) — it calls Wikimedia
  Commons' public search API directly, which requires no API key/quota.
  (An earlier version, task 36, used `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ID`
  against Google Custom Search JSON API; that API turned out to be closed to
  new Google Cloud customers as of 2025 — confirmed 403 against the real API
  across two separate GCP projects and three separate keys, all otherwise
  correctly configured — and is being fully retired 2027-01-01. See task 41.)
- `FORVO_API_KEY` — Forvo's word-pronunciation API, used by
  `search_word_pronunciations` (task 45). Manual signup at Forvo's developer
  portal (Dylan's step, not the loop's) — same category as
  `ELEVENLABS_API_KEY`.
- No env var is needed for `search_example_sentences` (task 44, Tatoeba's
  public search API) or `search_dictionary` (task 46, Jisho.org's public API
  plus the local `wordfreq` package) — both keyless.

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
`sync_anki`, `save_workflow_spec`, `load_workflow_spec`, `list_workflow_specs`,
and, as of tasks 36-37, `search_images` and `generate_image` (each returning
3 candidate image ids for Dylan to pick from, same choice-then-attach pattern
`generate_audio` already established). `create_anki_note` accepts an optional
`picture` argument symmetric to its existing `audio` argument (task 35).
The agent — not hardcoded logic — decides field mapping, cloze structure,
and when to ask Dylan a clarifying question.

**Image support for cards (tasks 33-40):** three ways to attach an image to
a card — upload (stored as an opaque `ImageAsset`, referenced by id only;
the agent never sees the image's actual contents, mirroring how it never
"hears" a generated audio clip), search-and-pick (`search_images`, Google
Custom Search), and generate-and-pick (`generate_image`, Gemini). Also in
this batch: editing and resending the most-recent user message, disabled
once that message's turn has already created an Anki note.

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

- [x] **25. Design-system foundation.** Add `lucide-react` to
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

- [x] **26. Visual overhaul of the chat surface.** Depends on task 25.
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

- [x] **27. Typing indicator + toast-style errors.** Depends on task 25 for
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

- [x] **28. Backend: conversation rename + cascade delete.**
  `backend/app/api/chat.py`: extend `UpdateConversationRequest` /
  `update_conversation` (`PATCH /api/conversations/{id}`) to accept an
  optional `title` alongside the existing `model` field. Add `DELETE
  /api/conversations/{id}` that deletes the `Conversation` row and cascades
  to delete all its `ConversationMessage` rows (hard delete — this is a
  single-user personal app, no soft-delete/undo needed). Verify: `cd backend
  && uv run pytest backend/tests/test_chat.py` covering rename and
  delete-cascades-messages; deploy-and-verify per the note above (backend
  only).

- [x] **29. Frontend: conversation rename + delete UI.** Depends on task 28.
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

- [x] **30. Mobile-responsive sidebar.** Depends on tasks 25 (icon) and 29
  (avoid touching `ConversationSidebar.tsx` concurrently with unrelated
  work). Below a Tailwind breakpoint (e.g. `md`), collapse
  `ConversationSidebar` behind a hamburger/menu icon that opens it as an
  overlay instead of an always-visible fixed-width column. Verify: `cd
  frontend && npm run build && npm run lint` pass; deploy-and-verify; note
  in PROGRESS.md that Dylan should confirm by resizing the browser or using
  devtools' device toolbar, since this can't be exercised headlessly.

- [x] **31. Backend: workflow spec REST endpoints.** `backend/app/agent/
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

- [x] **32. Frontend: Workflows page.** Depends on tasks 31 and 25. New
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

### Edit-and-resend + image support for cards (tasks 33-40)

Two independent features. Edit-and-resend (33-34) lets Dylan fix a typo or
change his mind about his most recent message without retyping the whole
conversation. Image support (35-39) adds three ways to attach an image to a
card — upload, search-and-pick, and generate-and-pick — following the same
"agent has tools, chooses live" pattern already used for audio, plus a new
`ImageAsset` table and a `picture` argument on `create_anki_note` symmetric
to the existing `audio` argument. Ordered so shared infra (33 for edit; 35
for images) lands before what depends on it. Tasks 35-39 apply the same
deploy-and-verify convention as tasks 20-32 (see that section's note above
task 20) for whichever app(s) each task touches.

- [x] **33. Backend: edit-and-resend the last user message.** `backend/app/
  api/chat.py`: extend `ChatRequest` with an optional `edit: bool = False`.
  When `True`, before running the turn: load the conversation's messages,
  find the last row with `role == "user"`; if any row after it (up to the
  end of history) is an assistant message whose content contains a
  `tool_use` block named `create_anki_note` (reuse the same detection
  `_payloads_for_message` already uses to build `card` payloads), raise
  `HTTPException(409, ...)` — the frontend is expected to prevent this case
  via task 34's disabled state, but the backend must not silently allow
  rewriting history that already caused a real Anki side effect. Otherwise,
  delete that last user row and all rows after it, then proceed exactly like
  a normal turn using `body.message` as the replacement text (same
  `run_turn` call, persistence, and payload-extraction logic already in
  `post_chat` — no forked code path beyond the pre-check and delete). Note:
  any `AudioClip`/`ImageAsset` rows created by the discarded turn are simply
  left orphaned in the DB (same as any other superseded turn) — no cleanup
  needed, single-user low-volume SQLite. Verify: `cd backend && uv run
  pytest backend/tests/test_chat.py` covering (a) editing a turn with no
  card payload succeeds, replaces history, and returns a fresh reply; (b)
  editing a turn whose assistant reply included a `create_anki_note` call
  returns 409 and leaves history untouched; (c) editing when there is no
  prior user message at all returns a sensible error, not a crash.

- [x] **34. Frontend: inline edit UI for the last user message.** Depends on
  task 33. `frontend/app/components/MessageBubble.tsx`: for the last
  user-role turn only (a new prop from `ChatApp.tsx`, e.g.
  `isLastUserMessage`), show a pencil icon on hover (top-right of the
  bubble). Clicking it swaps the bubble's rendered markdown for an editable
  `<textarea>` pre-filled with the original text (reuse the composer's
  auto-resize + `isComposing`-safe Enter-to-save convention from
  `ChatApp.tsx`), with Save/Cancel controls. Determine editability
  client-side from data already in `turns`: disabled (greyed pencil) if the
  assistant turn immediately following this user message has any payload
  with `type === "card"` — hovering a disabled pencil shows a small floating
  tooltip near the cursor ("Can't edit — a card was already created from
  this message"). Save calls `POST /api/chat` with `{conversation_id,
  message: <edited text>, edit: true}` (task 33); on success, replace the
  trailing turns (the old user turn plus everything after it, including any
  audio/image-options payloads, which simply disappear) with the new user
  turn and the fresh assistant reply, mirroring how `sendMessage` already
  updates `turns`. On a 409 (should be unreachable given the disabled state,
  but handle defensively), show the existing toast error instead of
  crashing. Verify: `cd frontend && npm run build && npm run lint` pass;
  deploy-and-verify (both apps, since this pairs with task 33's backend);
  note in PROGRESS.md that Dylan should confirm in a browser: editing a
  plain last message resends correctly, and the pencil is disabled with a
  tooltip after a card-creating message.

- [x] **35. Backend: image storage + upload endpoint + `create_anki_note`
  picture support.** `backend/app/models.py`: add an `ImageAsset` table
  (`id`, `content_type`, `data: bytes`, `source: str` —
  `"upload"`/`"search"`/`"generate"`, `created_at`), same pattern as
  `AudioClip`. Add `POST /api/images` (multipart file upload, `require_auth`,
  in a new `backend/app/api/images.py` router registered in `main.py`) that
  stores the uploaded bytes as an `ImageAsset(source="upload")` and returns
  `{"image_id": <id>}` — validate `content_type` starts with `image/`,
  reject otherwise with 400. Extend `ChatRequest` (`backend/app/api/chat.py`)
  with an optional `image_id: int | None`; when present, `post_chat` appends
  a short machine-readable reference to the user's message before calling
  `run_turn`, e.g. `f"{body.message}\n\n(Attached image_id: {body.image_id}
  for use on a card.)"` — this keeps `run_turn`'s message shape a plain
  string (no multimodal/vision plumbing, per the earlier scoping decision)
  while still giving the agent a concrete id to reference. Extend
  `backend/app/clients/ankiconnect.py`'s `create_note` and
  `backend/app/agent/tools.py`'s `create_anki_note` tool schema + dispatcher
  with a `picture` param symmetric to the existing `audio` param
  (`{"image_id": <id>, "fields": [...]}` in the tool schema; resolves to an
  `ImageAsset` row, base64-encodes it, and passes AnkiConnect's
  `note["picture"] = [{"data": ..., "filename": ..., "fields": [...]}]` —
  confirm this exact shape against AnkiConnect's actual `addNote`
  documentation/response before assuming, same caution as task 19's audio
  fix, since `picture` here is unverified against a real response). Verify:
  `cd backend && uv run pytest` — new tests for `POST /api/images` (success
  + non-image rejection), `create_anki_note` dispatch with a `picture` input
  (mocked `respx`, asserting the AnkiConnect request body's `note.picture`
  shape), and `ChatRequest.image_id` producing the expected appended
  reference text in a mocked `run_turn` call.

- [x] **36. Backend: `search_images` tool via Google Custom Search.**
  Depends on task 35. `backend/app/clients/google_image_search.py`:
  `search_images(query: str, n: int = 3) -> list[bytes]` wrapping the Google
  Custom Search JSON API with `searchType=image` (`GET https://
  www.googleapis.com/customsearch/v1` with `key`, `cx`, `q`,
  `searchType=image`, `num=n`), downloading each result's image bytes via
  `httpx`. New env vars `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_ID`, documented
  in `.env.example` and `AGENTS.md`'s Conventions (`GOOGLE_CSE_ID` needs the
  one-time manual Programmable Search Engine setup noted in this file's
  Requirements section — Dylan's step, don't attempt it). Add a
  `search_images` tool to `TOOL_SCHEMAS`/`dispatch_tool` in `backend/app/
  agent/tools.py`: takes `query` (and optional `n`, default 3), calls the
  client, stores each result as an `ImageAsset(source="search")`, returns
  `{"image_ids": [...]}`. Tests mock the Custom Search HTTP call and the
  image-download calls with `respx`, covering success and a no-results case.
  Verify: `cd backend && uv run pytest` passes; deploy-and-verify (backend
  only).

- [x] **37. Backend: `generate_image` tool via Gemini.** Depends on task 35,
  independent of task 36. `backend/app/clients/gemini_images.py`:
  `generate_images(prompt: str, n: int = 3) -> list[bytes]` using the
  existing `GEMINI_API_KEY` / `google-genai` SDK setup already established in
  `backend/app/agent/providers/gemini_provider.py` (reuse its client
  construction rather than duplicating auth handling), calling an
  image-generation-capable Gemini model (confirm the current correct model
  id against Google's live API/docs the same way `model_registry.py`'s
  existing comments already did for chat models — don't assume a name from
  training data) `n` times to produce `n` distinct images for one prompt,
  mirroring `generate_audio_options`'s "call N times for N options" pattern.
  Add a `generate_image` tool to `TOOL_SCHEMAS`/`dispatch_tool`: takes
  `prompt` (and optional `n`, default 3), calls the client, stores each
  result as an `ImageAsset(source="generate")`, returns `{"image_ids":
  [...]}`. Tests mock the `google-genai` SDK client (same style as existing
  Gemini provider tests), covering success and an API-error case. Verify:
  `cd backend && uv run pytest` passes; deploy-and-verify (backend only).

- [x] **38. Frontend: `ImageOptionsCard` for search/generate results.**
  Depends on tasks 36 and 37. `backend/app/api/chat.py`'s
  `_payloads_for_message`: add handling for `search_images`/`generate_image`
  tool_use blocks, emitting a payload shaped like `{"type": "image_options",
  "query_or_prompt": ..., "image_ids": [...], "options": [<base64>, ...]}`
  (fetch the actual bytes from `ImageAsset` the same way `_collect_audio_clips`
  does for `AudioClip`, base64-encoded for inline `<img>` rendering) —
  refactor `_collect_audio_clips` into a more general helper if that keeps
  the duplication reasonable, but don't force a shared abstraction if the
  audio/image cases diverge enough that it reads worse than two small
  functions. `frontend/app/lib/types.ts`: add `ImageOptionsPayload` to the
  `ChatPayload` union. New `frontend/app/components/ImageOptionsCard.tsx`
  (mirrors `AudioOptionsCard.tsx`): renders each option as a thumbnail
  `<img>` with a "Pick" button that sends `` `Use image option ${index + 1}
  (image_id ${imageIds[index]}).` ``, same message-based hand-off pattern
  audio already uses. Wire it into `ChatApp.tsx`'s payload rendering
  alongside `AudioOptionsCard`/`CardPayloadCard`. Verify: `cd backend && uv
  run pytest backend/tests/test_chat.py` (new payload shape, covering both
  `search_images` and `generate_image` tool calls) and `cd frontend && npm
  run build && npm run lint` pass; deploy-and-verify (both apps); note in
  PROGRESS.md that Dylan should confirm rendering by asking the agent to
  search or generate images for a card in a live chat.

- [x] **39. Frontend: composer image upload.** Depends on task 35
  (independent of 36-38). `frontend/app/components/ChatApp.tsx`: add a
  paperclip/image attach icon (`lucide-react`) next to the composer, opening
  a hidden `<input type="file" accept="image/*">`. On file selection,
  immediately `POST /api/images` (multipart) and hold the returned
  `image_id` in state; show a small thumbnail preview with a remove ("x")
  button in the composer bar above the textarea until the message is sent or
  the attachment removed. `sendMessage` includes `image_id` in the `POST
  /api/chat` body when one is attached, then clears it after sending (same
  lifecycle as `input`). Disable the attach button while `sending`, same as
  the textarea/send button. Verify: `cd frontend && npm run build && npm run
  lint` pass; deploy-and-verify; note in PROGRESS.md that Dylan should
  confirm uploading an image, seeing the preview, sending it, and asking the
  agent to use it on a card, in a browser.

- [x] **40. Docs + verification checklist update for image support.**
  Depends on tasks 35-39. Update `docs/manual_verification.md` (task 13's
  checklist) with steps for all three image modes (upload, search-and-pick,
  generate-and-pick) ending in a card that has a visible image field, and
  confirm on a synced device. Confirm `.env.example` and `AGENTS.md`'s
  Conventions section list `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_ID`, and the
  Google Programmable Search Engine one-time manual setup step (Dylan's job,
  not the loop's) alongside the existing external-service list. Verify: the
  docs accurately reflect the built system (cross-check against tasks
  33-39); no code changes expected, so `cd backend && uv run pytest` and `cd
  frontend && npm run build && npm run lint` should still pass unchanged as
  a regression check.

- [x] **41. Backend: swap `search_images` from Google Custom Search to
  Wikimedia Commons.** Depends on task 36. Task 36's Google Custom Search
  JSON API client turned out to be a dead end: Google closed it to new
  Cloud customers as of 2025 (it's also being fully retired 2027-01-01), so
  every request 403'd with `"This project does not have the access to
  Custom Search JSON API"` regardless of project/billing/key state —
  confirmed directly against the real API via `fly ssh console`, across two
  separate GCP projects and three separate API keys, ruling out
  configuration error. Vertex AI Search was considered as a replacement but
  also ruled out: its image search requires "advanced website indexing",
  which requires verifying ownership of every indexed domain via Google
  Search Console — impossible for third-party sites like the ones the old
  Programmable Search Engine covered (`*.unsplash.com/*`,
  `*.pexels.com/*`, `*.pixabay.com/*`, `*.wikipedia.org/*`,
  `*.irasutoya.com/*`). Replaced `backend/app/clients/google_image_search.py`
  with `backend/app/clients/wikimedia_image_search.py`:
  `search_images(query: str, n: int = 3) -> list[bytes]` against Wikimedia
  Commons' public MediaWiki search API (`GET https://commons.wikimedia.org/
  w/api.php` with `action=query&generator=search&gsrnamespace=6` (File:) +
  `filetype:bitmap|drawing` to exclude audio/video/PDF, `prop=imageinfo&
  iiprop=url`), downloading each result via `httpx` — no API key/quota
  needed, per Dylan's call not to add another paid per-site API for the
  other four sites. Updated `TOOL_SCHEMAS`/`dispatch_tool` in `backend/app/
  agent/tools.py` to call the new client and describe the narrower coverage
  (well-known/reference subjects, not niche or branded content) so the
  agent can choose between `search_images` and `generate_image` sensibly.
  Removed `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ID` from `.env.example` and
  `AGENTS.md` (no longer needed) — the same-named Fly secrets on the
  deployed backend are now dead and can be unset. Tests: replaced
  `test_google_image_search.py` with `test_wikimedia_image_search.py`
  (mocked Commons search + image-download calls via `respx`, covering
  success, no-results, HTTP error, API-level error, and download-failure
  cases); updated `test_agent.py`'s `search_images` dispatch tests to patch
  the new client. Verify: `cd backend && uv run pytest` passes;
  deploy-and-verify (backend only) — confirm a real `search_images` call
  against Wikimedia Commons returns real image results in production.

- [x] **42. Backend: resolve the Google access token lazily, only when
  `fetch_google_doc` is actually invoked.** Found while verifying task 41:
  `backend/app/api/chat.py`'s `post_chat` used to call `_get_access_token`
  (which refreshes the stored Google OAuth token if expired) unconditionally
  on every turn, before running the agent at all — so a dead/expired Google
  refresh token (e.g. `invalid_grant` after the OAuth consent screen's
  Testing-mode 7-day refresh-token expiry) filed a bug report and blocked
  *every* tool, including ones with nothing to do with Google Docs like
  `search_images`. Changed `agent_core.run_turn` and `tools.dispatch_tool`
  to take a `get_access_token: Callable[[], Awaitable[str]] | None` instead
  of a plain `access_token: str`; `dispatch_tool` only calls it inside the
  `fetch_google_doc` branch, so `_get_access_token`'s DB lookup/refresh
  network call now only happens for a turn that actually calls that tool.
  `post_chat` passes `functools.partial(_get_access_token, email)` rather
  than an already-resolved token; removed the now-dead
  `except HTTPException: raise` special case this made obsolete (nothing in
  that `try` block raises `HTTPException` anymore — a lazy-resolution
  failure now surfaces as a normal `is_error` tool_result the agent can
  explain to Dylan, same as any other tool failure, via `run_turn`'s
  existing per-tool `except Exception` handling). Tests: updated
  `test_agent.py`'s `fetch_google_doc`/`run_turn` tests for the new
  callable-based signature; replaced `test_chat.py`'s
  `test_post_chat_refreshes_expired_access_token` with two tests — one
  confirming no refresh call happens when the turn's fake `run_turn` never
  calls `get_access_token` (the bug this fixes), one confirming a refresh
  still happens correctly when it does. Verify: `cd backend && uv run
  pytest` passes; deploy-and-verify (backend only).

### Tatoeba/Forvo/dictionary tools (tasks 43-47)

Three more tools for the inner agent, all in the same "real/native source
beats an LLM guess" spirit as tasks 36/37's image tools: real example
sentences and native audio from Tatoeba, real native pronunciation from
Forvo, and real dictionary meanings/frequency from Jisho + `wordfreq`,
instead of the agent inventing example sentences, relying solely on
ElevenLabs TTS, or trusting its own definition/frequency knowledge. All
three are Japanese-only for now (see Out of scope); no caching, no new
frontend UI — results surface via the agent's chat replies same as
`fetch_google_doc`, except audio which follows the existing
choice-then-attach `clip_id` pattern.

- [x] **43. Backend: generalize `AudioClip` with a `source` field.**
  Independent scaffolding task, unblocks tasks 44-45. `backend/app/
  models.py`: add `source: str` to `AudioClip` (values `"generate"` /
  `"tatoeba"` / `"forvo"`), following `ImageAsset.source`'s existing
  pattern. `voice` stays a required `str` (not made nullable) — for
  `"tatoeba"`/`"forvo"` clips it holds the sentence's/pronunciation's
  contributor or speaker attribution (Tatoeba username, Forvo username)
  when available, or a fixed placeholder like `"native"` when not, so no
  SQLite column-nullability migration is needed. Add the column via this
  project's existing no-migration-framework convention: an idempotent
  `ALTER TABLE audioclip ADD COLUMN source TEXT NOT NULL DEFAULT 'generate'`
  in `init_db()` (see the `conversation`/`conversationmessage` tables'
  existing `ALTER TABLE` calls in `app/models.py` for the pattern), so
  existing ElevenLabs clips backfill correctly. Update `tools.py`'s
  `generate_audio` dispatch to pass `source="generate"` explicitly. Tests:
  a new/updated `test_models.py` case confirming the column exists with the
  right default for pre-existing rows, and that `dispatch_tool`'s
  `generate_audio` path still stores `source="generate"`. Verify: `cd
  backend && uv run pytest` passes.

- [x] **44. Backend: `search_example_sentences` tool via Tatoeba.** Depends
  on task 43. `backend/app/clients/tatoeba.py`: `search_sentences(query:
  str, n: int = 5) -> list[dict]` against Tatoeba's public search API (`GET
  https://tatoeba.org/en/api_v0/search` — confirm the exact current
  endpoint/response shape against the real API rather than assuming from
  training data, the same way `gemini_images.py`'s model-id comment already
  did for a different API), filtered to Japanese sentences with English
  translations. Each result: `{"japanese": str, "english": str | None,
  "audio_id": int | None}` — `audio_id` is an `AudioClip(source="tatoeba")`
  id (`voice` set to the audio's Tatoeba contributor username if present,
  else `"native"`), set only when Tatoeba has native audio for that
  sentence, downloaded via `httpx`. Add a `search_example_sentences` tool to
  `TOOL_SCHEMAS`/`dispatch_tool`: takes `query` (and optional `n`, default
  5), returns `{"sentences": [...]}` with each sentence's `audio_id` (not
  raw audio) so a chosen sentence's audio can be attached via
  `create_anki_note`'s existing `audio` argument, same as
  `generate_audio`/`clip_id`. No API key required. Tests mock the Tatoeba
  HTTP call(s) with `respx`, covering: a sentence with audio, a sentence
  without audio, and a no-results query. Verify: `cd backend && uv run
  pytest` passes; deploy-and-verify (backend only) — confirm a real search
  against Tatoeba returns real sentences (and at least one with audio) in
  production.

- [x] **45. Backend: `search_word_pronunciations` tool via Forvo.** Depends
  on task 43, independent of task 44. New env var `FORVO_API_KEY` (Dylan's
  manual signup step at Forvo's developer portal — document in
  `.env.example` and `AGENTS.md`'s Conventions, same category as
  `ELEVENLABS_API_KEY`). `backend/app/clients/forvo.py`:
  `search_pronunciations(word: str, n: int = 3) -> list[bytes]` (mirroring
  `google_image_search`/`wikimedia_image_search`'s "return N raw options"
  shape) against Forvo's `word-pronunciations` API action, hardcoded to
  Japanese (`language=ja`), sorted by Forvo's vote/rating count descending,
  downloading the top `n` audio files via `httpx`. Surface each
  pronunciation's speaker username alongside its bytes so `dispatch_tool`
  can set `AudioClip(source="forvo", voice=<speaker_username or "native">)`.
  Add a `search_word_pronunciations` tool to `TOOL_SCHEMAS`/`dispatch_tool`:
  takes `word` (and optional `n`, default 3), stores each result as an
  `AudioClip(source="forvo")`, returns `{"clip_ids": [...]}` — same
  choice-then-attach pattern as `generate_audio`. Tests mock the Forvo HTTP
  call(s) with `respx` (`FORVO_API_KEY` set via `monkeypatch.setenv`),
  covering success, no-results, and an API-error case. Verify: `cd backend
  && uv run pytest` passes; deploy-and-verify (backend only) — confirm a
  real lookup against Forvo returns real pronunciation audio in production,
  once `FORVO_API_KEY` is set as a Fly secret (Dylan's manual step).

- [x] **46. Backend: `search_dictionary` tool via Jisho + wordfreq.**
  Independent of tasks 44-45. Add `wordfreq` to `backend/pyproject.toml` via
  `uv add wordfreq`. `backend/app/clients/dictionary.py`: `search_words(query:
  str, n: int = 3) -> list[dict]` against Jisho.org's public search API
  (`GET https://jisho.org/api/v1/search/words`), returning up to `n` entries
  shaped `{"word": str, "readings": [str, ...], "meanings": [str, ...],
  "parts_of_speech": [str, ...], "is_common": bool, "frequency": float}` —
  `frequency` is `wordfreq.zipf_frequency(word, "ja")` (local computation, no
  network call), computed per result using the entry's most common written
  form. No API key required. Add a `search_dictionary` tool to
  `TOOL_SCHEMAS`/`dispatch_tool`: takes `query` (and optional `n`, default
  3), returns `{"results": [...]}` directly — unlike the audio/image tools,
  this is data the agent reads and uses (e.g. to write an accurate
  definition field, or judge whether a word's worth a card), not media to
  pick-and-attach, so no ids/storage involved. Tests mock the Jisho HTTP
  call with `respx` and stub/monkeypatch `wordfreq.zipf_frequency` (real
  Japanese frequency computation is fine to leave un-mocked if it's fast and
  deterministic locally — confirm during implementation), covering a
  multi-result query and a no-results query. Verify: `cd backend && uv run
  pytest` passes; deploy-and-verify (backend only).

- [x] **47. Docs: system prompt + verification checklist for the new
  tools.** Depends on tasks 44-46. Update `backend/app/agent/prompts.py`'s
  `SYSTEM_PROMPT` "Your tools:" list to add `search_example_sentences`,
  `search_word_pronunciations`, and `search_dictionary` (following the
  existing bullet style task 42's rewrite established — see
  `search_images`/`generate_image`'s entries for the pattern), and mention
  in "General principles" that dictionary/frequency data is now available
  to inform definitions and word choice rather than relying on the model's
  own knowledge. Update `docs/manual_verification.md` with steps covering
  all three new tools, ending in cards that use a Tatoeba sentence, Forvo
  audio, and a dictionary-informed definition respectively. Confirm
  `.env.example` and `AGENTS.md`'s Conventions section list `FORVO_API_KEY`
  and the Forvo signup manual step (cross-check against task 45, same role
  task 40 played for tasks 36-39). Verify: the docs accurately reflect the
  built system (cross-check against tasks 43-46); no code changes expected,
  so `cd backend && uv run pytest` and `cd frontend && npm run build && npm
  run lint` should still pass unchanged as a regression check.

- [x] **48. Backend + frontend: fix `search_word_pronunciations`' missing
  audio picker, and make picking an option populate the composer instead of
  auto-sending.** Found via live testing after task 45. Two bugs: (1)
  `backend/app/api/chat.py`'s `_payloads_for_message` only matched tool name
  `"generate_audio"` to build an `audio_options` payload, so
  `search_word_pronunciations` results (identical `{"clip_ids": [...]}`
  shape) never got a playable UI card — fixed by matching both names, using
  `tool_input.get("word")` as the label for the latter. (2) `AudioOptionsCard`
  /`ImageOptionsCard`'s `onPick` called `sendMessage` directly, which fired
  a full new agent turn immediately — with two choice cards showing at once
  (e.g. pronunciation audio + a generated image in the same turn), picking
  the first advanced the conversation before the second could be picked,
  and in one observed case the agent then created the note using
  unconfirmed audio. Fixed by having `onPick` call a new
  `appendPickToComposer` helper (`frontend/app/components/ChatApp.tsx`) that
  appends the pick's text to the message composer via `setInput` instead of
  sending — same pattern `CardPayloadCard`'s "Request a change" already
  used — so Dylan can pick from multiple cards, review, and send once.
  Verified end-to-end against the deployed app (real session cookie minted
  via `create_session_cookie`, Playwright): confirmed both a
  `search_word_pronunciations` and a `search_images`/`generate_image` pick
  each independently render as expected, and confirmed via network
  monitoring that clicking "Pick" fires no `/api/chat` request. Tests: new
  `test_post_chat_extracts_audio_options_payload_for_search_word_pronunciations`
  in `test_chat.py`. Verify: `cd backend && uv run pytest` and `cd frontend
  && npm run build && npm run lint` pass; deploy-and-verify (both apps).

- [x] **49. Backend + frontend: explicit workflow-spec-check requirement,
  and a `workflow_loaded` UI card.** Found via live testing: the agent
  sometimes didn't check for/load a matching saved workflow spec before
  handling a card creation request, silently improvising instead. `backend/
  app/agent/prompts.py`'s `SYSTEM_PROMPT` "General principles" now requires
  checking `list_workflow_specs` (or the known-specs list already given at
  conversation start) before doing anything else on a card creation
  request — load the obvious single match via `load_workflow_spec` and say
  so, or ask Dylan if more than one could apply or it's unclear. `backend/
  app/agent/core.py`'s `_build_system_prompt` known-specs addendum
  reworded to point at this new requirement rather than the old "consider
  offering" phrasing. Added a UI surface for it: `_payloads_for_message`
  (`chat.py`) now turns a successful `load_workflow_spec` tool call into a
  `{"type": "workflow_loaded", "name": ..., "spec": ...}` payload (no
  payload when the name wasn't found — the agent's text reply already
  covers that); new `frontend/app/components/WorkflowLoadedCard.tsx` renders
  it as a small banner ("Workflow loaded: `<name>`") with a collapsible
  full-spec view, wired into `ChatApp.tsx` alongside the other payload
  cards. Tests: `test_post_chat_extracts_workflow_loaded_payload` and
  `test_post_chat_extracts_no_payload_when_workflow_spec_not_found` in
  `test_chat.py`. Verified visually against the deployed app (synthetic
  conversation seeded directly via `ConversationMessage` rows over `fly ssh
  console`, then deleted after screenshotting) — both the collapsed banner
  and the expanded spec view render correctly, including real multi-line
  spec text. Verify: `cd backend && uv run pytest` and `cd frontend && npm
  run build && npm run lint` pass; deploy-and-verify (both apps).

- [x] **50. Frontend: mobile UX fixes.** Found via live testing on a phone:
  four distinct bugs, all in `frontend/app/`. (1) The "暗助" header logo
  (`components/ChatApp.tsx`, and the equivalent in `components/SignIn.tsx`)
  had no `whitespace-nowrap` and too little size margin (`h-9 w-9`/`text-lg`
  for two CJK characters), so it wrapped onto two lines and overflowed its
  box on some mobile font-rendering paths — fixed with `whitespace-nowrap
  leading-none shrink-0` and a slightly smaller/safer font-size ratio on
  both. (2) The scroll-to-bottom effect in `ChatApp.tsx` always used
  `behavior: "smooth"`, including when a conversation's history first
  loads, producing a visible top-to-bottom animation on every open — fixed
  by having the history-load effect set a `historyJustLoadedRef` flag
  right before its `setTurns` call, which the scroll effect consumes (then
  resets) to jump instantly (`"auto"`) for a freshly-loaded conversation
  and only animate smoothly for genuinely new messages during an active
  session. (3) The composer and message-edit `<textarea>`s
  (`ChatApp.tsx`, `components/MessageBubble.tsx`) used `text-sm` (14px);
  any focused form field under 16px triggers iOS Safari's auto-zoom-on-tap,
  which doesn't reliably zoom back out — bumped to `text-base` (16px) on
  mobile, kept `md:text-sm` on desktop via this codebase's existing `md:`
  breakpoint convention so desktop sizing is unchanged. (4) `layout.tsx`'s
  `viewport` export was missing `interactiveWidget: "resizes-content"`,
  the modern standard for telling mobile browsers to resize (not overlay)
  the layout viewport when the on-screen keyboard opens — needed for the
  `h-dvh`-based fixed-composer layout to reliably end up above the
  keyboard. Verified all four end-to-end against the deployed app on a
  real mobile viewport (Playwright's iPhone 13 device profile, real
  session cookie minted via `create_session_cookie`): confirmed the logo's
  bounding box has zero overflow, confirmed `visualViewport.scale` stays
  at 1 before/after focusing the composer, and confirmed — via sampled
  `scrollTop` reads against a real long conversation's history load — that
  the scroll jumps straight to the bottom in one step rather than
  animating across multiple samples. No new tests (pure CSS/behavior
  fixes, already covered by the visual verification above and existing
  `npm run build`/`npm run lint` regression coverage). Verify: `cd frontend
  && npm run build && npm run lint` pass; deploy-and-verify.

### Card preview-before-creation + default AI model (tasks 51-59)

Two independent features, scoped via interview on 2026-07-14.

**Preview-before-creation (51-57):** today `create_anki_note` immediately
calls AnkiConnect — the `CardPayloadCard` payload is purely a post-hoc
"here's what I created" summary, there's no draft/approval state anywhere.
This batch adds a draft state (a rebuilt `PendingCard` table — the existing
one is dead scaffolding from task 2, hardcoded to Cloze-specific columns
`japanese_cloze`/`furigana`/`english` and never read or written by any real
code, confirmed via `grep -rn PendingCard backend/` finding only
`test_models.py`'s round-trip test), a real per-note-type template renderer
so Preview shows Dylan's actual card HTML/CSS rather than a generic field
list, and a per-conversation "instant creation" toggle (default off) that
restores today's immediate-creation behavior when Dylan wants it. Decisions
locked in during the interview (don't re-litigate these mid-implementation):
`create_anki_note` stays a single tool — `dispatch_tool` branches on a new
`instant_creation: bool` parameter rather than splitting into two tool
names; template rendering happens server-side in Python (testable with
pytest fixtures, unlike a client-side renderer that only `npm run
build`/lint would touch); the mobile/PC preview toggle changes only the
preview container's width, using the note type's own CSS to reflow, not
different CSS per device; Preview renders on-demand (a dedicated endpoint
called when Dylan clicks it) rather than eagerly on every proposal; a
superseded pending card (Dylan asked for a change, agent proposed a new one)
is deliberately left as-is rather than auto-disabled — Dylan's call, simpler
backend.

**Default AI model (58-59):** `POST /api/conversations` today always
defaults new chats to the hardcoded `model_registry.DEFAULT_MODEL_ID`. Add a
single-row `UserSettings` table Dylan can update via a "mark as default"
checkbox in the existing `AiSettingsButton` model panel, decoupled from
which model the *currently open* conversation uses.

- [x] **51. Backend: rebuild `PendingCard` as a generic draft-card table,
  and add `Conversation.instant_creation`.** Foundational — unblocks 52-56.
  `backend/app/models.py`: replace `PendingCard`'s current
  `japanese_cloze`/`furigana`/`english`/`note` columns with a generic shape
  matching what `create_anki_note`'s tool schema already accepts: `id`,
  `deck_name: str`, `model_name: str`, `fields: str` (JSON-serialized
  `dict[str, str]`, same shape as `CardPayloadCard.fields` today),
  `tags: str | None` (JSON-serialized `list[str]`), `status: str` (default
  `"pending"`; values `"pending"` / `"created"` / `"discarded"`),
  `note_id: int | None` (set once `"created"`), `created_at`. Since the old
  table has never been written to by app code (only by
  `test_models.py`'s round-trip test — safe to change freely, unlike every
  other `_add_*_column_if_missing` migration in this file which preserves
  real production data), add a new `_rebuild_pendingcard_table_if_stale`
  migration in `init_db()`: check `PRAGMA table_info(pendingcard)` for the
  new `deck_name` column: if a `pendingcard` table exists without it,
  `DROP TABLE pendingcard` before `create_all()` recreates it with the new
  schema (mirror the existing `_add_*_column_if_missing` functions'
  docstring-explains-why style for this one, since it's a deliberate
  deviation from the usual additive-only migration pattern). Also add
  `Conversation.instant_creation: bool = Field(default=False)`, plus its own
  `_add_conversation_instant_creation_column_if_missing` following the exact
  pattern of `_add_conversation_model_column_if_missing` (`ALTER TABLE
  conversation ADD COLUMN instant_creation BOOLEAN NOT NULL DEFAULT 0` —
  existing conversations backfill to off, i.e. today's actual behavior
  becomes the *non-default* opt-in going forward). Verify: `cd backend &&
  uv run pytest backend/tests/test_models.py` — round-trip a `PendingCard`
  through the new columns, and confirm both migrations are idempotent
  (calling `init_db()` twice doesn't error) and correctly backfill a
  pre-existing SQLite file lacking the new column/table shape.

- [x] **52. Backend: AnkiConnect `modelTemplates`/`modelStyling` wrappers.**
  Independent of 51, unblocks 53's manual testing and 54. `backend/app/
  clients/ankiconnect.py`: add `get_model_templates(name: str) -> dict[str,
  dict[str, str]]` (wraps AnkiConnect's `modelTemplates` action — returns
  `{card_name: {"Front": qfmt, "Back": afmt}}` per AnkiConnect's actual
  documented response shape, confirm the exact shape against AnkiConnect's
  real API docs rather than assuming, same caution tasks 19/35 already
  applied) and `get_model_styling(name: str) -> str` (wraps `modelStyling`,
  returns the model's CSS). Follow the existing `list_note_type_names`/
  `get_note_type_fields` wrapper style exactly (thin `invoke()` calls).
  Verify: `cd backend && uv run pytest backend/tests/test_ankiconnect.py` —
  new respx-mocked tests for both wrappers, covering success and
  AnkiConnect's error-surfacing case (same pattern as existing tests in this
  file).

- [x] **53. Backend: Anki template renderer.** Independent of 51-52 (pure
  function, no AnkiConnect/DB dependency — can be built and tested in
  isolation against hand-written fixture template strings). New
  `backend/app/agent/anki_template.py`: `render_card(qfmt: str, afmt: str,
  css: str, fields: dict[str, str]) -> dict` returning `{"front_html": str,
  "back_html": str, "css": css}`. Support the subset of Anki's template
  syntax actually needed: `{{FieldName}}` substitution, `{{FrontSide}}` (afmt
  only, substitutes the rendered front), `{{#FieldName}}...{{/FieldName}}` /
  `{{^FieldName}}...{{/FieldName}}` conditional sections (shown/hidden based
  on whether the field is non-empty), and `{{cloze:FieldName}}` — since
  Dylan's real cards are Cloze type, this must render correctly: find all
  `{{c<N>::text::hint}}`/`{{c<N>::text}}` deletions in the field, and always
  preview card ordinal 1 specifically (`c1`) as the representative card even
  if a note has multiple cloze numbers — front replaces the `c1` deletion(s)
  with Anki's actual `[...]`-or-hint masking behavior wrapped in a `<span
  class="cloze">` (matching Anki's real card CSS, since `.cloze` styling
  comes from the note type's own CSS returned by 52), back reveals the `c1`
  text unmasked in the same span; other cloze numbers in the same field
  render as plain revealed text in both front and back (matching Anki's
  actual behavior — only the "active" ordinal for that card gets masked on
  its front). Unsupported/malformed template syntax should render best-effort
  rather than raising (a broken preview beats a 500). Verify: `cd backend &&
  uv run pytest backend/tests/test_anki_template.py` — new test file
  covering plain-field substitution, a conditional section on empty vs.
  non-empty fields, `{{FrontSide}}`, and cloze front/back rendering
  (single-cloze and multi-cloze-in-one-field cases) against hand-written
  fixture templates.

- [x] **54. Backend: wire `instant_creation` through `dispatch_tool`/
  `run_turn`, and the pending-card REST endpoints.** Depends on 51 (schema)
  and 52+53 (preview endpoint needs both). `backend/app/agent/tools.py`:
  `dispatch_tool` gains an `instant_creation: bool = False` keyword param
  (same style as the existing `get_access_token` param). In the
  `create_anki_note` branch: if `instant_creation` is `True`, behave exactly
  as today (call AnkiConnect immediately, return `{"note_id": ...}`); if
  `False` (the new default), skip the AnkiConnect call entirely and instead
  save a `PendingCard(deck_name=..., model_name=..., fields=json.dumps(...),
  tags=json.dumps(...) if tags else None, status="pending")` row, returning
  `{"pending_card_id": <id>, "status": "pending"}`. Refactor the actual
  AnkiConnect-note-creation logic (the `audio`/`picture` resolution +
  `ankiconnect.create_note` call currently inline in this branch) into a
  standalone helper (e.g. `_create_note_in_anki(deck_name, model_name,
  fields, tags, audio_input, picture_input) -> int`) so both the
  `instant_creation=True` path here and task 54's new REST endpoint below
  call the same code, not two copies. `backend/app/agent/core.py`:
  `run_turn` gains `instant_creation: bool = False`, passed through to every
  `dispatch_tool` call. `backend/app/agent/prompts.py`: update the
  `create_anki_note` bullet in `SYSTEM_PROMPT` to explain that this tool may
  only *draft* the card depending on Dylan's instant-creation setting — the
  agent's reply text must say "I've drafted this card for you to preview"
  (not "I've created it in Anki") whenever the tool result's `status` is
  `"pending"`. `backend/app/api/chat.py`: read `conversation.instant_creation`
  and pass it into `run_turn`; extend `CreateConversationRequest` and
  `UpdateConversationRequest` with an optional `instant_creation: bool`
  field (same pattern as `model`), wire into `create_conversation`/
  `update_conversation`. Update `_payloads_for_message`'s `create_anki_note`
  branch: the `"card"` payload gains `"status"` (from the tool result) and
  `"pending_card_id"` (when present) alongside the existing `note_id`/
  `deck_name`/`model_name`/`fields`/`tags`. Add a new
  `pending_cards_router = APIRouter(prefix="/api/pending-cards", ...)` in
  `chat.py` (registered in `main.py`), all behind `require_auth`: `POST
  /api/pending-cards/{id}/create` (404 if missing, 409 if
  `status != "pending"`; otherwise loads the row, calls the new
  `_create_note_in_anki` helper, sets `status="created"` + `note_id`,
  returns `{"note_id": ...}`); `POST /api/pending-cards/{id}/discard` (404 if
  missing, 409 if not `"pending"`; sets `status="discarded"`); `GET
  /api/pending-cards/{id}/preview` (404 if missing; calls 52's
  `get_model_templates`/`get_model_styling` for the pending card's
  `model_name`, picks the first template Anki returns for a Cloze-style
  preview or the note type's actual front/back names otherwise, feeds them
  plus the pending card's `fields` into 53's `render_card`, returns
  `{"front_html": ..., "back_html": ..., "css": ...}`). Verify: `cd backend
  && uv run pytest backend/tests/test_chat.py backend/tests/test_agent.py`
  — cover: `dispatch_tool`'s `create_anki_note` with `instant_creation=False`
  creates a `PendingCard` and skips AnkiConnect (mock `ankiconnect.create_note`
  and assert it's never called); `instant_creation=True` behaves exactly as
  today's existing tests already assert; all three new endpoints' success,
  404, and 409 paths; the `"card"` payload shape including the pending case.

- [x] **55. Frontend: pending-card preview/create/discard UI.** Depends on
  54. `frontend/app/lib/types.ts`: extend `CardPayload` with `status:
  "pending" | "created" | "discarded"` and `pending_card_id: number | null`.
  `frontend/app/components/CardPayloadCard.tsx`: when `status === "pending"`,
  replace the current "Card added to Anki" header/Request-a-change-only
  layout with "Card draft" framing and three buttons — **Preview** (calls
  `GET /api/pending-cards/{id}/preview`, shows a loading state, then renders
  the returned `front_html`/`back_html`/`css` inside a sandboxed `<iframe
  sandbox="" srcDoc={...}>` — build `srcDoc` as `<style>${css}</style>
  <div class="card">${front_html}</div>` with a toggle to swap in
  `back_html`; add a second toggle switching the iframe's own width between
  a `~375px` (mobile) and `~700px` (PC) container, re-rendering the same
  `srcDoc` at each width, not re-fetching), **Create** (calls `POST
  /api/pending-cards/{id}/create`; on success, update this turn's payload
  in `turns` state to `status: "created"` with the returned `note_id`,
  switching the card to today's existing "Card added to Anki" rendering),
  and **Discard** (calls `POST /api/pending-cards/{id}/discard`; on success,
  update local state to `status: "discarded"` and render a small "Draft
  discarded" line instead of the buttons). When `status === "created"` or
  `"discarded"`, render as today (created) or the discarded line, with no
  Preview/Create/Discard buttons. Verify: `cd frontend && npm run build &&
  npm run lint` pass; note in PROGRESS.md that Dylan should confirm in a
  browser: proposing a card with instant-creation off shows a pending draft,
  Preview renders real card HTML/CSS with a working mobile/PC width toggle
  and a working front/back flip, Create turns it into a normal created-card
  display, and Discard on a separate draft correctly removes only that one.

- [ ] **56. Frontend: instant-creation checkbox.** Depends on 54 (the
  `Conversation.instant_creation` field and `PATCH`/`POST` support).
  `frontend/app/components/ChatApp.tsx`: add a labeled checkbox ("Create
  cards instantly") near the composer (e.g. in the same row as the
  attach-image button), reflecting `activeConversation.instant_creation`
  and defaulting to unchecked for a brand new conversation. Toggling it
  calls `PATCH /api/conversations/{id}` with `{instant_creation: <bool>}`
  (same pattern as `changeModel`), updating local state on success. Verify:
  `cd frontend && npm run build && npm run lint` pass; note in PROGRESS.md
  that Dylan should confirm in a browser: the checkbox starts unchecked on a
  new chat, persists across reload, and checking it makes the next card
  creation request skip the draft/preview step entirely (today's original
  immediate-creation behavior).

- [ ] **57. Docs: update the manual verification checklist for
  preview-before-creation.** Depends on 51-56. Update `docs/
  manual_verification.md` (task 13's checklist) with steps covering: leaving
  instant-creation off and confirming a proposed card shows as a draft with
  working Preview (both front/back and mobile/PC toggles) and Create/Discard;
  turning instant-creation on and confirming a card is created immediately
  as before; confirming a discarded draft never appears in Anki. Verify: the
  docs accurately reflect the built system (cross-check against tasks
  51-56); no code changes expected, so `cd backend && uv run pytest` and `cd
  frontend && npm run build && npm run lint` should still pass unchanged as
  a regression check.

- [ ] **58. Backend: `UserSettings` table + default-model endpoint.**
  Independent of 51-57. `backend/app/models.py`: add a `UserSettings` table
  (`id`, `default_model_id: str | None = Field(default=None)`,
  `updated_at`) — effectively a single row for this single-user app (no
  `email`/multi-row logic needed, matching this app's existing single-user
  conventions). Add a small helper module or inline functions in
  `backend/app/api/chat.py`: `_get_user_settings(session) -> UserSettings`
  (get-or-create the one row, id=1) and use it in two places: (a) a new
  `PUT /api/settings/default-model` route (`{"model_id": str}` body,
  `require_auth`, validates via `get_model()` raising 400 on an unknown id,
  otherwise upserts `UserSettings.default_model_id` and returns the updated
  settings) and (b) a new `GET /api/settings` route returning
  `{"default_model_id": ...}`; (c) `create_conversation`
  (`POST /api/conversations`): when the request doesn't specify a model
  explicitly... actually `CreateConversationRequest.model` already defaults
  to `DEFAULT_MODEL_ID` at the Pydantic level, which would shadow a
  DB-stored default — change `CreateConversationRequest.model` to `str |
  None = None`, and in `create_conversation`, resolve the actual model as
  `body.model or _get_user_settings(session).default_model_id or
  DEFAULT_MODEL_ID` before constructing the `Conversation` row. Verify: `cd
  backend && uv run pytest backend/tests/test_chat.py` — new tests covering
  `PUT /api/settings/default-model` (success + unknown-model-id 400), `GET
  /api/settings`, and `POST /api/conversations` resolving in the right
  precedence order (explicit body model wins over stored default wins over
  hardcoded `DEFAULT_MODEL_ID`).

- [ ] **59. Frontend: "mark as default" checkbox in the model panel.**
  Depends on 58. `frontend/app/lib/types.ts`: add a type for the `GET
  /api/settings` response. `frontend/app/components/ChatApp.tsx`: fetch
  `GET /api/settings` alongside the existing models/conversations bootstrap
  fetch, hold `defaultModelId` in state, pass it plus a new `onSetDefault`
  handler (calling `PUT /api/settings/default-model` and updating
  `defaultModelId` on success) down to `AiSettingsButton`.
  `frontend/app/components/AiSettingsButton.tsx`: add `defaultModelId:
  string | null` and `onSetDefault: (modelId: string) => void` props; render
  a small checkbox (or star icon) on each model row, checked when `model.id
  === defaultModelId`, calling `onSetDefault(model.id)` on click —
  `event.stopPropagation()` so it doesn't also trigger the row's existing
  onClick (which changes the *current conversation's* model, a separate
  action from marking a default). Verify: `cd frontend && npm run build &&
  npm run lint` pass; note in PROGRESS.md that Dylan should confirm in a
  browser: marking a model as default persists across reload, is visually
  distinct from (and independent of) the current conversation's selected
  model, and a brand new chat actually opens using the marked default.

- [ ] **60. Backend: persist a picked audio clip/image on a drafted
  `PendingCard`, so preview-before-creation doesn't silently drop them.**
  Found while implementing task 54: `PendingCard` (task 51's schema) has no
  audio/picture columns, and task 54's `dispatch_tool` `create_anki_note`
  branch (`instant_creation=False`) only stores `deck_name`/`model_name`/
  `fields`/`tags` — it never records `tool_input.get("audio")`/
  `tool_input.get("picture")` at all. So today, if Dylan picks audio or an
  image for a card and instant-creation is off (the new default), that pick
  is silently lost: the draft is created with no media, `POST
  /api/pending-cards/{id}/create` (task 54) always calls
  `_create_note_in_anki` with `audio_input=None, picture_input=None`, and
  neither the pending-card preview (task 54's `GET .../preview`, which only
  renders `fields` through the note type's template) nor the eventual
  AnkiConnect note reflects the picked media — with no error or warning
  anywhere, since nothing about this path currently fails, it just quietly
  drops the attachment. Fix: add `audio: str | None` /
  `picture: str | None` columns to `PendingCard` (JSON-serialized
  `{"clip_id"/"image_id": ..., "fields": [...]}`, same shape
  `create_anki_note`'s tool schema already uses for these arguments) via an
  additive `_add_pendingcard_audio_picture_columns_if_missing` migration
  (same pattern as every other additive migration in `app/models.py` — this
  one must NOT reuse task 51's drop-and-recreate approach, since by the time
  this task lands real Dylan-created `PendingCard` rows likely exist).
  `dispatch_tool`'s draft branch stores `tool_input.get("audio")`/
  `tool_input.get("picture")` (JSON-serialized) on the new `PendingCard` row.
  `POST /api/pending-cards/{id}/create` passes the stored audio/picture back
  into `_create_note_in_anki` instead of hardcoded `None, None`. Consider
  whether task 54's preview endpoint should also reflect attached media in
  some way (e.g. an audio player / image thumbnail alongside the rendered
  HTML) — not required to match real Anki's rendered `[sound:...]`/`<img>`
  markup exactly, since the template renderer (task 53) doesn't fetch actual
  media, but worth deciding rather than leaving picked-but-unpreviewed media
  as a silent gap in the preview too. Verify: `cd backend && uv run pytest`
  — cover: drafting a card with a picked audio clip and/or image persists
  them on the `PendingCard` row; `POST /api/pending-cards/{id}/create`
  attaches the stored audio/picture (mocked `respx`/`ankiconnect.create_note`,
  asserting the request body's `note.audio`/`note.picture` shape matches
  what task 35's existing instant-creation tests already assert); the
  migration is additive and idempotent, matching this file's other
  `_add_*_column_if_missing` migrations.

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
- Editing any user message other than the most recent one (tasks 33-34) —
  no history branching or multiple simultaneous edit points; older messages
  are read-only.
- Automatically deleting/undoing an Anki note when the message that created
  it is edited away (tasks 33-34) — Dylan handles that manually via chat,
  same as the existing "request a change" flow on `CardPayloadCard`.
- Vision/multimodal image input (tasks 35-39) — an uploaded image is stored
  and referenced by id only; the agent never "sees" its contents, mirroring
  how it never "hears" a generated audio clip. Considered during the
  interview and explicitly deferred as a real scope increase to the core
  chat loop, not a small addition.
- More than one image per Anki note, video attachments, or a standalone
  image gallery/library UI (tasks 35-39) — a single `picture` argument on
  `create_anki_note` is all that's built.
- Editing or replacing an image after it's been picked (tasks 35-39) — Dylan
  can create a new card or ask the agent to change it via chat, same
  "request a change" flow already used for card fields.
- Non-Japanese languages for Tatoeba/Forvo/dictionary lookups (tasks 43-47)
  — `search_word_pronunciations` hardcodes Forvo's language filter to
  Japanese; `search_example_sentences` and `search_dictionary` are scoped to
  this app's actual (Japanese-study) use case, not a general-purpose
  multi-language lookup surface.
- Caching Tatoeba/Forvo/dictionary responses (tasks 43-47) — every call hits
  the real API/local computation fresh; not expected to be a problem at
  Dylan's single-user usage volume.
- Persisting dictionary/frequency lookups to the DB (tasks 43-47) — only
  audio gets stored (as `AudioClip`), since only audio needs an id for
  `create_anki_note` to attach later; dictionary data is read and used by
  the agent in the moment, not referenced by id afterward.
- Any new frontend UI for these tools (tasks 43-47) — results surface via
  the agent's chat replies, same as `fetch_google_doc`; no dedicated
  sentence/pronunciation/dictionary picker component like
  `ImageOptionsCard`.
- A numeric frequency rank sourced from a bundled/licensed corpus list
  (tasks 43-47) — `wordfreq`'s built-in Japanese data is used instead
  specifically to avoid sourcing, licensing, and hosting a separate
  frequency dataset ourselves.
- A second `propose_anki_note`-style tool name, or any other split of
  `create_anki_note` into multiple tools (tasks 51-57) — deliberately kept
  as one tool with an `instant_creation` flag decided during the interview;
  don't refactor into two tools mid-implementation.
- A general-purpose Anki template/Mustache engine (task 53) — only the
  specific syntax subset Dylan's real note types use (`{{Field}}`,
  `{{FrontSide}}`, `{{#Field}}`/`{{^Field}}`, `{{cloze:Field}}`) is
  supported; exotic template features (nested conditionals, `{{type:Field}}`,
  `{{hint:Field}}`, TTS field references) are not required to render
  correctly.
- Previewing every cloze-number card a multi-cloze note would actually
  generate in real Anki (task 53) — only cloze ordinal `c1` is rendered as
  the representative preview; Dylan can trust AnkiConnect's real behavior
  for the rest once created.
- Auto-disabling or otherwise flagging a superseded pending card after a
  "Request a change" produces a newer one (tasks 51-57) — explicitly
  decided during the interview to leave old pending cards exactly as they
  are; Dylan is responsible for not clicking Create on a stale draft.
- Expiring, cleaning up, or capping the number of undecided `PendingCard`
  rows (tasks 51-57) — same "no cleanup needed, single-user low-volume
  SQLite" precedent as orphaned `AudioClip`/`ImageAsset` rows elsewhere in
  this file.
- A structured inline field-edit form on a pending card (tasks 51-57) —
  revising a draft goes through the same agent-driven "Request a change"
  conversation flow already used for created cards, consistent with this
  project's standing preference for agent reasoning over hardcoded
  structured editing UI (see the Workflows page's plain-text-only scoping
  above).
- Per-user (multi-user) default model settings (tasks 58-59) — `UserSettings`
  is a single effectively-global row, matching every other single-user
  assumption in this app (one allowlisted email, no per-user anything).
- Any effect on already-existing conversations from changing the default
  model (tasks 58-59) — it only changes what a *brand new* conversation
  starts with; conversations already in progress keep whatever model they're
  already set to.
