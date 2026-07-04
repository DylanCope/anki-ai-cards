# anki-ai-cards

A personal chat app that turns Japanese lesson notes into Anki flashcards.
You chat with a Claude tool-use agent about a Google Doc lesson transcript;
it finds the teacher's red-marked corrections, proposes Cloze cards with
furigana and an English translation, generates three ElevenLabs audio takes
for you to pick from, discovers your real Anki note type's fields live over
AnkiConnect (no hardcoded field mapping), creates the note, and syncs it to
your real AnkiWeb account so it shows up on your phone/desktop with zero
client reconfiguration.

Full requirements and the reasoning behind each architectural choice live in
[`PRD.md`](PRD.md); a task-by-task log of what was actually built, and every
gotcha discovered along the way, is in [`PROGRESS.md`](PROGRESS.md). This
file is the practical "how do I run/deploy this" reference.

**Two distinct agents exist in this repo — don't confuse them:**
- The **Ralph loop** (`ralph/`) is the autonomous Claude harness that *wrote*
  this codebase, one PRD task per iteration.
- The **inner agent** (`backend/app/agent/`) is the Claude tool-use agent
  *this codebase implements* — the one you actually chat with at runtime.

## Architecture

```
                     ┌──────────────────────┐
   You (browser,  →  │  frontend/ (Next.js) │
   phone or desktop) │  chat UI, Google     │
                     │  sign-in             │
                     └─────────┬────────────┘
                               │ /api, /auth
                               │ (server-side proxy, same-origin cookie)
                     ┌─────────▼────────────┐        ┌───────────────┐
                     │  backend/ (FastAPI)  │──────→ │  Anthropic    │
                     │  Claude tool-use     │        │  (agent turns)│
                     │  agent + clients     │        └───────────────┘
                     └───┬─────────┬────────┘
                         │         │
              ┌──────────┘         └───────────┐
              ▼                                ▼
     ┌──────────────────┐            ┌───────────────────────────┐
     │ Google Docs API   │            │ deploy/anki-headless/     │
     │ (lesson doc)       │            │ headless Anki + AnkiConnect│
     └──────────────────┘            │ (own Fly app, VNC login   │
                                       │ once, logged into real    │
              ┌──────────────────┐    │ AnkiWeb account)           │
              │ ElevenLabs        │    └────────────┬──────────────┘
              │ (3 audio takes)   │                 │ AnkiConnect `sync`
              └──────────────────┘                  ▼
                                            ┌─────────────────┐
                                            │  AnkiWeb (real) │
                                            └────────┬────────┘
                                                     │ normal sync
                                                     ▼
                                     Your phone / desktop Anki apps
                                     (no reconfiguration needed)
```

Three separately-deployed Fly.io apps: `frontend/`, `backend/`, and
`deploy/anki-headless/` (an unmodified third-party Docker image, not built
from this repo). The backend reaches the headless Anki app only over Fly's
private network — AnkiConnect and VNC are never exposed publicly.

## Repo layout

```
backend/
  app/
    main.py            FastAPI app, mounts auth + chat routers, GET /health
    models.py           SQLModel tables: ConversationMessage, WorkflowSpec,
                         ProcessingCursor, PendingCard, OAuthToken
    auth.py              session cookie signing/verification, require_auth dep
    clients/
      google_docs.py     OAuth helpers, fetch_document, flatten_runs
                          (turns freeform doc layout into {text, color} spans)
      elevenlabs.py       generate_audio_options() — 3 varied TTS takes
      ankiconnect.py      invoke() + list_note_type_names/get_note_type_fields/
                          create_note/sync
    agent/
      prompts.py          SYSTEM_PROMPT describing the inner agent's job
      tools.py            tool schemas + dispatch_tool()
      core.py              run_turn() — the Claude tool-use loop
      workflow_specs.py   save/load/list learned per-source workflow specs
    api/
      auth.py              /auth/google/login, /auth/google/callback
      chat.py               /api/chat, /api/chat/history
    scripts/
      smoke_test_ankiconnect.py   CLI smoke test against a real AnkiConnect URL
  tests/                  pytest, everything mocked (respx / mocked Anthropic
                          client) — no test ever makes a real network call
  Dockerfile, fly.toml    backend deploy config

frontend/
  app/
    page.tsx               renders <ChatApp />
    components/
      ChatApp.tsx           state, message list, send form
      MessageBubble.tsx
      AudioOptionsCard.tsx  3 audio players + Pick buttons
      CardPayloadCard.tsx   generic field renderer for a created note
      SignIn.tsx
    lib/types.ts            TS mirrors of the backend's response shapes
    next.config.ts          rewrites /api and /auth to BACKEND_URL server-side
                            (keeps the session cookie same-origin)
  Dockerfile, fly.toml    frontend deploy config

deploy/anki-headless/
  fly.toml                config for the ankimcp/headless-anki image
                          (no source in this repo — see file header)

docs/manual_verification.md   end-to-end checklist Dylan runs by hand
ralph/                        the harness that built this (loop.sh, PROMPT.md, logs)
PRD.md, PROGRESS.md, AGENTS.md   spec, build log, and conventions
```

## Local development setup

### Prerequisites

- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/)
- Node 20+ (the build used Node 24) and npm
- A running AnkiConnect instance reachable at whatever `ANKICONNECT_URL`
  points to (your own desktop Anki + AnkiConnect addon works fine for local
  dev — you don't need the headless Fly deployment just to develop locally)
- Every secret in `.env.example` — see the next section for how to get each one.

### Getting the secrets

```bash
cp .env.example .env      # then fill in every value below
```

**`ANTHROPIC_API_KEY`** — the inner agent's Claude access.
1. Sign in (or sign up) at [console.anthropic.com](https://console.anthropic.com).
2. Add a payment method under **Billing** — the API is pay-as-you-go with no
   subscription, but a key won't successfully make requests until billing is set up.
3. Go to **Settings → API Keys**, click **Create Key**, name it (e.g.
   "anki-ai-cards"), optionally set a spending limit.
4. Copy it immediately — it's shown once, starts with `sk-ant-...`.

**`ELEVENLABS_API_KEY`** — TTS for the 3 audio options per card.
1. Sign in (or sign up) at [elevenlabs.io](https://elevenlabs.io).
2. Click your profile icon → **Profile + API key** (or, for a more
   production-appropriate key, **Workspace settings → Service Accounts →**
   create a service account and its own API key instead of your personal one).
3. Copy the key shown there.

**`GOOGLE_CLIENT_ID`** / **`GOOGLE_CLIENT_SECRET`** — Google sign-in +
read-only Docs access, in one OAuth client. This one has the most steps:
1. In [Google Cloud Console](https://console.cloud.google.com), create a new
   project (e.g. "anki-ai-cards") or pick an existing one.
2. **APIs & Services → Library**: search "Google Docs API", click **Enable**.
3. **APIs & Services → Google Auth Platform** (this is where OAuth consent
   configuration now lives — it used to be called just "OAuth consent screen"):
   - **Branding** tab: set an app name and support email.
   - **Audience** tab: choose **External** (this is a personal Gmail account,
     not a Workspace org), then under **Test users** add the one Google
     account you'll actually use — same address as `ALLOWED_EMAIL` below.
     This is required: an unverified app rejects anyone not on this list.
   - **Data Access** tab: add the scope
     `https://www.googleapis.com/auth/documents.readonly` (`openid`/`email`
     are included by default).
4. **APIs & Services → Credentials** (or the **Clients** tab of Google Auth
   Platform): **Create Credentials → OAuth client ID**, application type
   **Web application**. Add both redirect URIs you'll need under **Authorized
   redirect URIs** (one client can hold both):
   - `http://localhost:8000/auth/google/callback` (local dev)
   - `https://anki-ai-cards-backend.fly.dev/auth/google/callback` (production
     — adjust if you use a custom domain)
5. Copy the **Client ID** and **Client Secret** shown after creation.

   **Heads up:** keeping the app in "Testing" status (recommended here —
   going to "Production" requires Google's app verification process: a
   privacy policy URL, possibly a review) means test-user authorizations
   expire after **7 days**. In practice that just means you'll need to click
   "Sign in with Google" again about once a week — the frontend already
   handles this gracefully (any expired/401'd request drops you back to the
   sign-in screen, per `frontend/app/components/ChatApp.tsx`). Not worth
   verifying the app for a single personal user.

**`ALLOWED_EMAIL`** — the one Google account allowed to use the app. No
signup needed: just the Gmail address you added as a test user above. It
must match exactly what Google's userinfo endpoint returns for that account.

**`SESSION_SECRET_KEY`** — signs the session cookie, no external account
needed: `openssl rand -hex 32`.

### Run the backend

```bash
cd backend
uv sync
DATABASE_PATH=./data/anki-ai-cards.db uv run uvicorn app.main:app --reload --port 8000
```

(Load the rest of `.env` into the environment too — e.g. `export
$(grep -v '^#' ../.env | xargs)` or use `direnv`/your shell's preferred method.)

### Run the frontend

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:3000`, sign in with your allowlisted Google account,
and start chatting.

## Testing

```bash
cd backend && uv run pytest                     # all clients/agent/API mocked, no real network calls
cd frontend && npm run build && npm run lint     # frontend has no automated tests — appearance/UX is manual
```

## Deployment

Three Fly.io apps, deployed in this order (each is a **manual step** — the
Ralph loop never runs `fly deploy` itself):

### 1. Headless Anki + AnkiConnect

```bash
fly launch --config deploy/anki-headless/fly.toml --no-deploy   # first time only, creates the app
fly volumes create anki_data --region iad --size 10 -a anki-ai-cards-anki   # GB — must exist before first deploy
fly deploy --config deploy/anki-headless/fly.toml
```

Size the volume for your collection: 10GB is comfortable for up to ~10,000
notes with audio/images (roughly 1MB of media per note, well above what
short TTS clips and typical images use). Check an existing device's
`collection.media` folder size if you want to size more precisely. Fly
volumes can only be extended later, never shrunk, so it's fine to start
generous. If you run out of space after the fact:

```bash
fly volumes list -a anki-ai-cards-anki                          # get the volume ID + current size
fly volumes extend <volume-id> -a anki-ai-cards-anki --size 20   # bump it up
fly apps restart anki-ai-cards-anki                              # picks up the new size
```

Then, once deployed:

1. `fly proxy 5900 -a anki-ai-cards-anki`
2. Connect any VNC client to `localhost:5900` (no VNC auth — the private
   tunnel is the only access control). [TigerVNC](https://tigervnc.org/) is a
   good no-account option on Windows.
3. Inside the desktop, open Anki, sign into AnkiWeb with your real account,
   and wait for the initial sync to finish before doing anything else.
4. Install the AnkiConnect addon (code `2055492159`) via `Tools > Add-ons >
   Get Add-ons`. It requires an Anki restart to load — don't try to trigger
   this from inside the GUI (there's no window manager to relaunch Anki if
   you close it). Instead restart the whole machine, which safely re-runs the
   container's entrypoint (Anki, Xvfb, x11vnc, AnkiConnect all start fresh —
   your AnkiWeb login and collection are untouched, they live on the volume):
   `fly apps restart anki-ai-cards-anki`, then reconnect the VNC proxy.
5. This login persists on the `/data` volume — you shouldn't need to repeat
   it unless the volume is recreated.
6. Verify: `fly proxy 8765 -a anki-ai-cards-anki` in another terminal, then
   from `backend/`: `uv run python -m scripts.smoke_test_ankiconnect --url http://localhost:8765`

You can also trigger a manual AnkiWeb sync at any time without opening VNC,
since AnkiConnect's `sync` action does exactly what clicking the sync button
in the GUI does:
```bash
curl -s http://localhost:8765 -X POST -d '{"action": "sync", "version": 6}'
```
(with `fly proxy 8765 -a anki-ai-cards-anki` running). Once the backend is
deployed, the inner agent calls this automatically after creating a note, so
you shouldn't need to run this by hand in normal use.

### 2. Backend

**Run these from inside `backend/`, not the repo root** — `fly` uses your
current directory as the build context, and `backend/Dockerfile` won't be
found if you invoke `fly deploy --config backend/fly.toml` from elsewhere
(you'll get "app does not have a Dockerfile or buildpacks configured").

```bash
cd backend
fly launch --no-deploy   # first time only
fly secrets set -a anki-ai-cards-backend \
  ANTHROPIC_API_KEY=... ELEVENLABS_API_KEY=... \
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... \
  ALLOWED_EMAIL=... SESSION_SECRET_KEY=...
fly deploy
```

`backend/fly.toml` already points `ANKICONNECT_URL` at the headless Anki
app's private address and mounts a volume for the SQLite database — no
further config needed. Update your Google OAuth client's authorized redirect
URI to the real backend URL's `/auth/google/callback` once you know it.

### 3. Frontend

Same rule — run from inside `frontend/`:

```bash
cd frontend
fly launch --no-deploy   # first time only
fly deploy
```

`frontend/fly.toml` already points `BACKEND_URL` at the backend app's private
address, both as a runtime `[env]` var and — necessarily — as a
`[build.args]` value, since `next.config.ts` reads it at `next build` time to
bake the `/api`/`/auth` proxy destination into Next's routes manifest; the
runtime `[env]` value alone arrives too late for that. If the frontend loads
forever and its logs show `ECONNREFUSED 127.0.0.1:8000`, that means it was
built without the `BACKEND_URL` build arg (e.g. an image built before this
fix) — `fly deploy` again to rebuild with it.

### After deploying

Run through [`docs/manual_verification.md`](docs/manual_verification.md) —
sign-in, doc reading, live note-type discovery, card proposal, audio
selection, note creation, AnkiWeb sync, and workflow-spec reuse across
sessions. This is deliberately manual; it exercises real external services
the automated test suite never touches.

## Known limitations (see PROGRESS.md for full detail)

- Audio players and "card added" confirmations don't persist across a page
  reload — only the text transcript does (task 10's PROGRESS entry).
- There's no dedicated `propose_card`/approve-edit API — proposing, editing,
  and confirming a card all happen conversationally in chat text, then
  `create_anki_note` runs immediately once you confirm (task 9's PROGRESS
  entry).
- Single global conversation — no concept of separate/multiple chat threads.
