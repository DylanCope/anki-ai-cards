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
but must never run `fly deploy`, create/extend volumes, restart the app, or
perform the login below — all real infrastructure/side effects Dylan runs
manually.

The `anki_data` volume must be created (`fly volumes create anki_data
--region iad --size 10 -a anki-ai-cards-anki`, size in GB — 10GB is
comfortable for up to ~10,000 notes with audio/images) before the first
`fly deploy --config deploy/anki-headless/fly.toml`. It doesn't get created
automatically from the fly.toml. Volumes can be extended later
(`fly volumes extend <id> -a anki-ai-cards-anki --size <n>`, then
`fly apps restart anki-ai-cards-anki` to pick it up) but never shrunk.

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
5. Once logged in, Anki's sync state persists in the `/data` volume mount, so
   this step should not need repeating across deploys/restarts of the same
   app — only if the volume is ever recreated.
6. Verify AnkiConnect is up: run
   `uv run python -m scripts.smoke_test_ankiconnect --url http://localhost:8765`
   from `backend/` after also running `fly proxy 8765 -a anki-ai-cards-anki`
   in another terminal (or from another Fly app on the same private network,
   pointed at `anki-ai-cards-anki.internal:8765` directly, no proxy needed).
   A manual AnkiWeb sync can also be triggered any time without VNC via
   AnkiConnect's `sync` action directly: `curl -s http://localhost:8765 -X
   POST -d '{"action": "sync", "version": 6}'` (with the 8765 proxy running).

## Backend/frontend deployment (manual steps for Dylan)

`backend/fly.toml` + `backend/Dockerfile` and `frontend/fly.toml` +
`frontend/Dockerfile` build/deploy the two main apps. Neither fly.toml
declares secrets (`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAIL`,
`SESSION_SECRET_KEY`) — push those once via `fly secrets set -a
anki-ai-cards-backend KEY=value` before the first deploy. `backend/fly.toml`'s
`[env]` points `ANKICONNECT_URL` at the headless Anki app's private
`.internal` address, `PUBLIC_APP_URL` at the frontend's public URL, and
mounts a volume for `DATABASE_PATH`. `frontend/fly.toml`'s `[env]` points
`BACKEND_URL` at the backend app's private `.internal` address (same
reasoning as `next.config.ts`'s rewrite proxy — see that file's comment). The
loop must never run `fly deploy` for either app — only Dylan does, manually.

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
`~/.fly/bin` to PATH or invoke it by full path). There's no real Fly account
logged in here, but `flyctl config validate --config <path>` only needs *any*
`FLY_API_TOKEN` value (even a bogus one) to run its local schema check — it
prints a `Metrics send issue: ... 401` warning (harmless, ignore it) but
still validates the config and prints "Configuration is valid" / exits 0.
Use this to verify any new/changed `fly.toml`, e.g.:
`FLY_API_TOKEN=bogus ~/.fly/bin/flyctl config validate --strict --config backend/fly.toml`.

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
