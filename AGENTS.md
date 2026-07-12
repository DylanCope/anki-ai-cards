# AGENTS.md — project conventions

Read by every loop iteration. Keep it short and current — this file and
PROGRESS.md are the only "memory" between iterations.

## Verification commands

- Backend tests: `cd backend && uv run pytest`
- Frontend build/lint: `cd frontend && npm run build && npm run lint`
- UI-overhaul tasks (PRD.md tasks 20-32): also `fly deploy` whichever app(s)
  the task touched, then `fly status -a <app>` (healthy/started) and skim
  `fly logs -a <app>` for startup/runtime errors — see PRD.md's
  "Deploy-and-verify convention" note above that task list for the full
  rationale. This doesn't replace Dylan's manual browser check for
  visual/UX correctness, it's in addition to it.

## Conventions

- Language/stack: Python (`uv`, FastAPI, SQLModel, httpx, `anthropic` SDK) in
  `backend/`; Next.js + TypeScript + Tailwind in `frontend/`.
- Commit style: one task per commit, imperative message, reference the PRD task number.
- Structure: `backend/app/{clients,agent,api,models.py}`, `backend/tests/`;
  `frontend/` standard Next.js App Router layout.
- All outbound HTTP (ElevenLabs, AnkiConnect, Google Docs, Anthropic) goes
  through `httpx`; tests mock it with `respx` (or mock the `anthropic` SDK
  client directly) — never hit real services from a test.
- Frontend deps as of the UI overhaul (PRD.md tasks 20-32): `react-markdown`
  + `remark-gfm` (message rendering), `lucide-react` (icons), Inter + Noto
  Sans JP fonts via `next/font/google` (replacing Geist), a persisted
  `localStorage`-backed light/dark toggle (not just
  `prefers-color-scheme`). Design tokens: purple-600 accent, gray-950/900
  dark surfaces, `rounded-xl` cards, `rounded-lg` buttons/inputs.
- Any keyboard handling on the chat composer must check
  `event.nativeEvent.isComposing` before treating Enter as submit — Dylan
  types Japanese directly into the chat sometimes, and Enter also confirms
  IME kana→kanji conversion.
- Secrets are env vars only, documented in `.env.example`, never committed.
  See PRD.md Requirements for the full list.
- The `search_images` tool (`app/clients/wikimedia_image_search.py`) calls
  Wikimedia Commons' public search API directly — no API key/env var, no
  manual setup step. It replaced the original Google Custom Search JSON API
  client (task 36), which turned out to be closed to new Google Cloud
  customers as of 2025 (confirmed against the real API, see PRD.md task 41)
  — don't reintroduce a Google Custom Search dependency here.

## Headless Anki deployment (manual steps for Dylan)

Config lives at `deploy/anki-headless/` — `fly.toml`, plus a `Dockerfile` +
`entrypoint.sh` that extend the prebuilt `ankimcp/headless-anki` image with a
socat relay in front of AnkiConnect (see that directory's header comments for
the full Flycast + relay story). Like `backend/`/`frontend/`, deploy from
*inside* this directory, not the repo root with `--config`.

**The loop may run `fly deploy`/`fly logs`/`fly status`/`fly apps restart`/
`fly ssh console` against all three apps** (`anki-ai-cards-anki`,
`anki-ai-cards-backend`, `anki-ai-cards-frontend`) to iterate and debug
autonomously — see "Autonomous deploy/debug access" below for what's still
off-limits (creating/extending volumes, allocating IPs, and anything
requiring interactive UI access, which remain Dylan's manual steps).

The `anki_data` volume must be created (`fly volumes create anki_data
--region iad --size 10 -a anki-ai-cards-anki`, size in GB — 10GB is
comfortable for up to ~10,000 notes with audio/images) before the first
`fly deploy --config deploy/anki-headless/fly.toml`. It doesn't get created
automatically from the fly.toml. Volumes can be extended later
(`fly volumes extend <id> -a anki-ai-cards-anki --size <n>`, then
`fly apps restart anki-ai-cards-anki` to pick it up) but never shrunk.

**AnkiConnect must be reached via Flycast (`anki-ai-cards-anki.flycast`, dialed
on port 80 — see point 4, NOT the app's `internal_port`) *and* through the
socat relay, never raw 6PN (`.internal`) or AnkiConnect's own port (8765)
directly.** Several independent problems, all confirmed empirically (see
PROGRESS.md/session history if it exists, or just trust this note —
re-deriving this cost a long debugging session):

1. AnkiConnect's web server is IPv4-only — `webBindAddress` in its addon
   config must stay `0.0.0.0`; setting it to `::` makes it fail to even start
   listening ("Failed to listen on port 8765"). Fly's private 6PN network is
   direct machine-to-machine and IPv6-only, so an IPv4-only listener is
   simply unreachable over it, no matter what it's bound to. Flycast routes
   through Fly's own proxy instead, which — like the public proxy reaching an
   app's health check — connects to the app over IPv4 internally regardless
   of the caller's protocol.
2. AnkiConnect (`/data/addons21/2055492159/web.py`) is a hand-rolled,
   single-threaded, `select()`-based HTTP server with a 5-second socket
   timeout and a manual byte-level request parser — not a standard library.
   `deploy/anki-headless/` builds a custom image (`Dockerfile` +
   `entrypoint.sh`) running a `socat` relay in front of it (Flycast talks to
   the relay on the app's `internal_port`, which forwards to AnkiConnect over
   genuine `127.0.0.1:8765` loopback) as a defensive measure against this
   server's fragility, rather than pointing Flycast at AnkiConnect's own port
   directly. **Caveat:** the original justification recorded here — that
   AnkiConnect itself was observed resetting connections arriving via the
   Flycast-proxied path specifically — turned out to be confounded with point
   4's port bug (dialing the app's `internal_port` directly instead of the
   Flycast proxy's port 80 also produces a connection reset, indistinguishable
   from this at the client). Whether AnkiConnect would in fact tolerate being
   dialed directly through a *correctly-addressed* Flycast connection was
   never re-tested after point 4 was found — the relay works and is low-risk,
   so it was left in place rather than re-opening that question.
3. **Anki itself segfaults intermittently and auto-restarts** (the base
   image's `/startup.sh` loops `anki -b /data`, `sleep 2` forever) — seen in
   `fly logs -a anki-ai-cards-anki` as `Segmentation fault` a few seconds
   after `Starting Anki...`, unprompted by any user interaction (happens
   during Anki's own startup, before anyone's even connected via VNC),
   preceded by `Failed to connect to the bus: ... /run/dbus/system_bus_socket:
   No such file or directory` (Anki's Qt/WebEngine UI expects a D-Bus system
   bus; none ran in this environment). This plausibly explains *why* point 2
   ever looked flaky/proxy-specific in the first place: any request has a
   chance of landing in the few-second dead window between a crash and the
   auto-restart, regardless of which network path it took. Two mitigations,
   both in place now: `entrypoint.sh` starts a real `dbus-daemon --system`
   before Anki launches (an attempt to remove the D-Bus absence as a
   variable — not confirmed to fully eliminate the segfault), and
   `backend/app/clients/ankiconnect.py`'s `invoke()` retries transient
   connection errors (`ConnectError`/`ReadError`/`RemoteProtocolError`/
   `ConnectTimeout`, never an AnkiConnect-reported `error` or HTTP status
   error) up to `MAX_ATTEMPTS` times with `RETRY_DELAY_SECONDS` between
   attempts — long enough to ride out the restart regardless of whether the
   dbus fix helps.
4. **The actual, previously-undiagnosed root cause of task 15's "list Anki
   note types" failure: `ANKICONNECT_URL` was dialing the anki app's
   `internal_port` (8766, the relay's port) directly instead of Flycast's
   proxy port (80).** Flycast is Fly's private-network equivalent of the
   public proxy — the address you dial (`<app>.flycast`) is a proxy sitting
   in front of the app, always listening on the service's *external* port
   (80/443, same as `force_https`/`[http_service]` govern for the public
   proxy) and forwarding from there to `internal_port` on an actual healthy
   machine. Dialing `internal_port` directly bypasses this proxy entirely and
   gets a bare TCP connection to... nothing — confirmed by replacing the
   socat relay with a bare Python listener logging every accepted connection,
   which never saw a single `accept()` while `anki-ai-cards-anki.flycast:8766`
   was being dialed from the backend, even for a self-connection from the
   anki app back to its own Flycast address. The client sees this as
   `ConnectionResetError`/`httpcore.ReadError` roughly 3.3s after connecting
   (Flycast's own give-up timeout) — indistinguishable from point 2's
   originally-suspected AnkiConnect-level reset, which is why this went
   undiagnosed for as long as it did. Fix: `backend/fly.toml`'s
   `ANKICONNECT_URL` is now `http://anki-ai-cards-anki.flycast` (implicit port
   80, force_https=false on that app means plain HTTP) — no port suffix.
   **Never point `ANKICONNECT_URL` (or any Flycast address) at a port other
   than 80/443** — that port always belongs to the target app's `fly.toml`,
   dialed over genuine loopback/6PN from *inside* that app's own container,
   never from a remote caller.

Setup needs: a private IPv6 allocated for the app (`fly ips allocate-v6
--private -a anki-ai-cards-anki`), an `[http_service]` block in
`deploy/anki-headless/fly.toml` pointed at the **relay's** port 8766 (not
AnkiConnect's own 8765) — required for Flycast to function at all, but does
not by itself expose anything publicly; confirm with `fly ips list
-a anki-ai-cards-anki` that no public IP exists — and `backend/fly.toml`'s
`ANKICONNECT_URL` pointed at `anki-ai-cards-anki.flycast` (port 80 — see point
4 above, never the relay's own port). `fly proxy`'s
tunnel likely goes over the same direct-6PN path as `.internal` (confirmed:
VNC over `fly proxy` worked while AnkiConnect over `fly proxy` didn't, before
the relay, since VNC's server binds more permissively than AnkiConnect's) —
so it's not a reliable way to test the Flycast+relay path specifically. The
real test is the chat agent successfully calling an AnkiConnect tool end to
end — run `backend/scripts/smoke_test_chat.py` (see "Autonomous deploy/debug
access" below) rather than `fly proxy` + the AnkiConnect-level smoke test for
this.

One-time AnkiWeb login via VNC, after that first deploy:

1. `fly proxy 5900 -a anki-ai-cards-anki` (tunnels the app's VNC port to
   `localhost:5900` over Fly's private network — no public VNC port is ever
   exposed). [TigerVNC](https://tigervnc.org/) is a good no-account VNC
   client on Windows.
2. Connect a VNC client to `localhost:5900` (no VNC auth is configured by the
   image, so the tunnel itself is the only access control).
3. Inside the desktop, open Anki, go to the AnkiWeb login screen, and sign in
   with Dylan's real AnkiWeb account credentials. Wait for the initial sync
   to finish before doing anything else.
4. Install the AnkiConnect addon (code `2055492159`) via `Tools > Add-ons >
   Get Add-ons`. It needs an Anki restart to load — since the VNC session has
   no window manager to relaunch a closed app, don't close Anki from inside
   the GUI to trigger this. Instead restart the whole machine
   (`fly apps restart anki-ai-cards-anki`), which safely re-runs the
   container's entrypoint (Anki/Xvfb/x11vnc/AnkiConnect all start fresh; the
   AnkiWeb login and collection persist on the volume, untouched), then
   reconnect the VNC proxy.
5. Leave AnkiConnect's `webBindAddress` config (`Tools > Add-ons >
   AnkiConnect > Config`) at `0.0.0.0` — see the Flycast note above for why.
6. Once logged in, Anki's sync state persists in the `/data` volume mount, so
   this step should not need repeating across deploys/restarts of the same
   app — only if the volume is ever recreated.
7. Verify AnkiConnect end to end via the chat agent (ask it to list Anki note
   types) — run `backend/scripts/smoke_test_chat.py` (see "Autonomous
   deploy/debug access" below) rather than `fly proxy` + the AnkiConnect-level
   smoke test from Dylan's own machine, which can't validate Flycast
   reachability (see above). `backend/scripts/smoke_test_ankiconnect.py` is
   still useful for narrower checks pointed at
   `anki-ai-cards-anki.flycast` (port 80 — see point 4 above, not the relay's
   own port) from *within* another Fly app in the same org (e.g.
   `fly ssh console -a anki-ai-cards-backend`).

## Backend/frontend deployment (manual steps for Dylan)

`backend/fly.toml` + `backend/Dockerfile` and `frontend/fly.toml` +
`frontend/Dockerfile` build/deploy the two main apps. Neither fly.toml
declares secrets (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAIL`,
`SESSION_SECRET_KEY`, `DEV_API_KEY`) — push those once via `fly secrets set -a
anki-ai-cards-backend KEY=value` before the first deploy. `backend/fly.toml`'s
`[env]` points `ANKICONNECT_URL` at the headless Anki app's private
`.internal` address, `PUBLIC_APP_URL` at the frontend's public URL, and
mounts a volume for `DATABASE_PATH`. `frontend/fly.toml`'s `[env]` points
`BACKEND_URL` at the backend app's private `.internal` address (same
reasoning as `next.config.ts`'s rewrite proxy — see that file's comment). The
loop may run `fly deploy` for either app now (see "Autonomous deploy/debug
access" below) — this was previously Dylan-only.

**Run `fly launch`/`fly deploy` from inside `backend/` or `frontend/`
respectively, not the repo root with `--config <dir>/fly.toml`.** Fly uses
the current working directory as the build context, and each Dockerfile's
`COPY` paths are relative to its own directory — invoking from the repo root
fails with "app does not have a Dockerfile or buildpacks configured" because
it looks for the Dockerfile in the wrong place. (This is also why
`backend/fly.toml` briefly lost its `[build]` stanza after a `fly launch` run
from the repo root — restored as an explicit empty `[build]` block, matching
`frontend/fly.toml`.)

**The backend's `[http_service]` must keep `min_machines_running = 1`, not
0.** The frontend reaches the backend over private 6PN networking
(`.internal`), which bypasses Fly's public proxy entirely — and only the
public proxy auto-wakes a stopped machine on an incoming request. If the
backend is allowed to scale to zero, `.internal` DNS resolution fails outright
(`getaddrinfo ENOTFOUND anki-ai-cards-backend.internal`) the moment it idles
out, breaking every chat request until its public URL is hit directly to wake
it. This isn't a crash or billing issue if `fly apps list` shows the backend
as "suspended" — that label just means its one machine is currently stopped;
check `fly status -a anki-ai-cards-backend` and `fly logs` to confirm. Costs
~$2-3/month to keep it always-on; worth it for a chat app that needs to be
reachable at unpredictable times.

**The backend must bind to `::`, not `0.0.0.0`.** Fly's private 6PN network
(what `anki-ai-cards-backend.internal` resolves over) is IPv6-only.
`backend/Dockerfile`'s `CMD` binds Uvicorn to `::` for exactly this reason —
`0.0.0.0` only listens on IPv4, so Fly's public proxy (which reaches the app
over IPv4 — health checks pass fine) works either way, but 6PN connections
from the frontend get `ECONNREFUSED` since nothing is listening on the IPv6
side. `::` is dual-stack by default on Linux, so it satisfies both without
needing two separate listeners. If this regresses (e.g. someone "simplifies"
it back to `0.0.0.0`), the symptom is: health checks green, but the frontend
logs `ECONNREFUSED` against the backend's `fdaa:...` 6PN address specifically
— DNS resolves fine, the app is definitely running, it's just not listening
on that address family.

The `backend_data` volume, like `anki_data`, isn't created automatically —
run `fly volumes create backend_data --region iad --size 1 -a
anki-ai-cards-backend` before the first deploy (1GB is ample for a SQLite
chat-history DB; no media lives here, unlike the Anki collection).

**The OAuth `redirect_uri` must be built from `PUBLIC_APP_URL`, never
inferred from the incoming request** (e.g. `request.url_for(...)`) — see
`backend/app/api/auth.py`'s `_redirect_uri`. Every request, including the
OAuth callback, arrives via the frontend's proxy, so the backend's own
"incoming request" view of its host is always that proxy's address (the
private `.internal` one in production) — inferring from it leaks that
unreachable address to Google as the `redirect_uri`, and Google rejects it
outright (`Error 400: invalid_request`) since it was never registered (and
couldn't be reached by the browser even if it were). `PUBLIC_APP_URL` must
match exactly what's registered as an authorized redirect URI on the Google
Cloud OAuth client, and must be the **frontend's** URL, not the backend's —
the whole point of routing `/auth/*` through the frontend's rewrite proxy is
so the session cookie set at the end of the flow lands on the origin the
browser's JS actually calls for `/api/*`.

## flyctl in this sandbox

`flyctl` is installed at `~/.fly/bin/flyctl` (not on PATH by default — add
`~/.fly/bin` to PATH or invoke it by full path). A real Fly account is logged
in here (`flyctl auth whoami` returns Dylan's account) — `fly deploy`,
`fly logs`, `fly status`, `fly apps restart`, and `fly ssh console` all hit
the real production apps, with real (if small) cost and availability impact.
`flyctl config validate --config <path>` remains useful for a quick local
schema check before deploying anything, and only needs *any* `FLY_API_TOKEN`
value (even a bogus one): `FLY_API_TOKEN=bogus ~/.fly/bin/flyctl config
validate --strict --config backend/fly.toml`.

## Autonomous deploy/debug access

The loop has standing authorization to run `fly deploy`/`fly logs`/
`fly status`/`fly apps restart`/`fly ssh console` against all three apps
(`anki-ai-cards-anki`, `anki-ai-cards-backend`, `anki-ai-cards-frontend`)
without asking Dylan first, so it can iterate on infra/connectivity bugs
(e.g. the AnkiConnect segfault/connectivity saga above) end to end in one
session. Still off-limits — these remain Dylan's manual steps: creating or
extending volumes, allocating IPs, and anything requiring interactive UI
access (Google OAuth consent, VNC login to the headless Anki instance).

To test end to end without a browser OAuth flow, the backend accepts
`Authorization: Bearer $DEV_API_KEY` as an alternate credential everywhere a
session cookie is normally required (see `backend/app/auth.py`'s
`require_auth`) — only active when the `DEV_API_KEY` env var is set. It's
pushed as a real secret on `anki-ai-cards-backend` (`fly secrets list -a
anki-ai-cards-backend` to confirm it's set; Dylan manages the actual value).
Use `backend/scripts/smoke_test_chat.py` to exercise the real, deployed chat
agent end to end (`DEV_API_KEY=... uv run python -m scripts.smoke_test_chat`
from `backend/`, or pass `--url` to target something other than the
production backend) — this is the authoritative way to verify an
AnkiConnect-connectivity fix, since it goes through the same path the real
chat UI does (agent → Docs/AnkiConnect tools → Flycast → relay → Anki).

## Known constraints

- Two distinct agents exist in this project: the Ralph loop (builds this
  code) and the inner agent (the runtime Claude tool-use agent this code
  implements, defined in `backend/app/agent/`). Don't conflate them.
- The loop must never attempt interactive OAuth consent or VNC logins to the
  headless Anki instance — one-time steps requiring a GUI, which Dylan runs
  manually. It *may* run `fly deploy`/`fly logs`/`fly status`/
  `fly apps restart`/`fly ssh console` (see "Autonomous deploy/debug access"
  above).
- No automated test may make a real network call to Google, Anthropic,
  ElevenLabs, or AnkiConnect — mock everything at the `httpx`/SDK-client
  boundary. `backend/scripts/smoke_test_chat.py` and
  `smoke_test_ankiconnect.py` are deliberate exceptions: manual/loop-invoked
  scripts for verifying real deployed infra, not part of `uv run pytest`
  (their own unit tests mock the HTTP calls, same as everything else).
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
