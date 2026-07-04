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
   redirect URIs** (one client can hold both). **These must be the
   frontend's URLs, not the backend's** — every request (including the OAuth
   callback) arrives at the backend via the frontend's proxy, and the
   redirect must land on an origin your browser can actually reach and that
   the session cookie can be scoped to (see `backend/app/api/auth.py`'s
   `_redirect_uri` comment):
   - `http://localhost:3000/auth/google/callback` (local dev — the
     frontend's dev server port, not the backend's 8000)
   - `https://anki-ai-cards-frontend.fly.dev/auth/google/callback`
     (production — adjust if you use a custom domain)
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

**`PUBLIC_APP_URL`** — the frontend's own public URL (no external account
needed). Used to build the OAuth `redirect_uri` explicitly, since the backend
can't safely infer it from the incoming request (every request arrives via
the frontend's proxy, so the backend would otherwise see — and leak to
Google — its own private address instead). Must match whatever you registered
above: `http://localhost:3000` for local dev, the frontend's real
`https://...fly.dev` URL in production.

### Run the backend

```bash
cd backend
uv sync
DATABASE_PATH=./data/anki-ai-cards.db PUBLIC_APP_URL=http://localhost:3000 \
  uv run uvicorn app.main:app --reload --port 8000
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

Same rule as backend/frontend — run from inside `deploy/anki-headless/`, not
the repo root, since this now builds from a real Dockerfile in that directory:

```bash
cd deploy/anki-headless
fly launch --no-deploy   # first time only, creates the app
fly volumes create anki_data --region iad --size 10 -a anki-ai-cards-anki   # GB — must exist before first deploy
fly ips allocate-v6 --private -a anki-ai-cards-anki   # Flycast address — see below for why this is needed
fly deploy
fly ips list -a anki-ai-cards-anki   # confirm: only the private Flycast address, no public IPs
```

**Why Flycast, and why a relay on top of it:** AnkiConnect's web server is
IPv4-only — its `webBindAddress` config must stay `0.0.0.0`; it fails to even
start listening if changed to an IPv6 address like `::`. But Fly's private
6PN network (`anki-ai-cards-anki.internal`) is direct machine-to-machine and
IPv6-only, so the backend can never reach an IPv4-only listener over it.
Flycast (`anki-ai-cards-anki.flycast`) routes through Fly's own proxy
instead — same as the public proxy already does for health checks — which
reaches the app over IPv4 internally regardless of the caller's protocol.
That alone wasn't quite enough, though: AnkiConnect turned out to be a
hand-rolled, single-threaded HTTP server (not a standard library), which
resets connections arriving via the Flycast-proxied path even though it
handles genuine loopback connections perfectly — so `deploy/anki-headless/`
now builds a small custom image (see its `Dockerfile`/`entrypoint.sh`) that
runs a `socat` relay in front of AnkiConnect: Flycast talks to the relay
(port 8766), and the relay forwards to AnkiConnect over real
`127.0.0.1:8765` loopback, which is the one thing proven to work reliably.
`fly ips allocate-v6 --private` is what makes the Flycast address exist;
`deploy/anki-headless/fly.toml`'s `[http_service]` block (pointed at the
relay's port 8766, not AnkiConnect's own 8765) is required for Flycast to
work at all, but does **not** by itself make anything publicly reachable —
only a public IP would do that, hence checking `fly ips list` shows none.

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
5. **Leave AnkiConnect's `webBindAddress` config at `0.0.0.0`** (`Tools >
   Add-ons > AnkiConnect > Config`) — its web server is IPv4-only and fails
   to even start listening if set to `::` or another IPv6 form. Reachability
   from the backend comes from Flycast (see above), not from changing this.
6. This login persists on the `/data` volume — you shouldn't need to repeat
   it unless the volume is recreated.
7. **The real verification is the chat UI itself**, not a CLI smoke test —
   `fly proxy`'s tunnel goes over the same direct 6PN path as raw `.internal`
   addressing (confirmed: VNC over `fly proxy` worked while AnkiConnect over
   `fly proxy` didn't, before the relay), so it can't validate the Flycast +
   relay path the backend actually uses. Once the backend is deployed with
   the updated `ANKICONNECT_URL` (port 8766, the relay — not AnkiConnect's
   own 8765), ask the chat agent to list your Anki note types — if it
   succeeds, the whole path is working end to end.

You can also trigger a manual AnkiWeb sync at any time without opening VNC,
since AnkiConnect's `sync` action does exactly what clicking the sync button
in the GUI does:
```bash
curl -s http://localhost:8765 -X POST -d '{"action": "sync", "version": 6}'
```
(with `fly proxy 8765 -a anki-ai-cards-anki` running) — **if this stops
working now that AnkiConnect only binds `0.0.0.0`**, it's the same
IPv4-vs-IPv6 story as above: `fly proxy` may route the same direct-6PN way
raw `.internal` calls do, which an IPv4-only listener can't answer over. If
so, just ask the chat agent to sync instead (it calls the same action via
Flycast, which does work), or open VNC and trigger the sync button in Anki's
own UI directly. Once the backend is
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
fly volumes create backend_data --region iad --size 1 -a anki-ai-cards-backend   # 1GB is ample, no media here
fly secrets set -a anki-ai-cards-backend \
  ANTHROPIC_API_KEY=... ELEVENLABS_API_KEY=... \
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... \
  ALLOWED_EMAIL=... SESSION_SECRET_KEY=...
fly deploy
```

`backend/fly.toml` already points `ANKICONNECT_URL` at the headless Anki
app's private address, `PUBLIC_APP_URL` at the frontend's public URL (used to
build the OAuth `redirect_uri` — see "Getting the secrets" above), and mounts
a volume for the SQLite database — no further config needed, as long as the
frontend app name matches what's already in `backend/fly.toml`'s
`PUBLIC_APP_URL` and what you registered with Google.

If signing in shows Google's **"Error 400: invalid_request"** page with a
`redirect_uri` in the details that isn't the frontend's public URL (e.g. it
shows the backend's private `.internal` address, or `localhost:8000` instead
of `:3000`), that means `PUBLIC_APP_URL` and the Google Cloud OAuth client's
authorized redirect URI have gotten out of sync — fix whichever one is wrong
so both agree on the frontend's URL + `/auth/google/callback`.

**The backend must bind to `::` (IPv6), not `0.0.0.0`.** `backend/Dockerfile`
already does this — Fly's private 6PN network (what the frontend uses to
reach `anki-ai-cards-backend.internal`) is IPv6-only, so `0.0.0.0` (IPv4 only)
leaves the backend unreachable from the frontend even though the public proxy
(which reaches it over IPv4) and its health checks work fine. The tell-tale
symptom is health checks green but the frontend logging `ECONNREFUSED`
against the backend's `fdaa:...` address specifically.

The backend is deliberately kept always-on (`min_machines_running = 1`,
~$2-3/month) rather than scaling to zero. The frontend reaches it over
private 6PN networking (`.internal`), which bypasses Fly's public proxy — and
only the public proxy auto-wakes a stopped machine on request. With
`min_machines_running = 0`, the backend idling out breaks every chat request
with `getaddrinfo ENOTFOUND anki-ai-cards-backend.internal` until something
happens to hit its public URL directly. If the frontend ever shows
"Loading..." forever with that error in its logs, check
`fly status -a anki-ai-cards-backend` — a stopped machine here is the cause.

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
