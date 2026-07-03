# Progress Log

Append-only log written by loop iterations. Newest entry at the top.
Each entry:

```
## <date> — <task name>
- Did: <what was implemented>
- Verified: <commands run and results>
- Learned: <gotchas, decisions, things a future iteration must know>
```

Blocked tasks go under a `Blocked:` line with what was tried.

---

## 2026-07-03 — Task 6: Google OAuth + session auth
- Did: Added `backend/app/auth.py` (`create_session_cookie`/`verify_session_cookie`
  using `itsdangerous.URLSafeTimedSerializer`, keyed by a new `SESSION_SECRET_KEY`
  env var, plus a `require_auth(request) -> str` FastAPI dependency that reads
  the `session` cookie, verifies it, and raises `HTTPException(401)` if
  missing/invalid/expired) and `backend/app/api/auth.py` (`APIRouter` at
  `/auth/google`, routes `/login` and `/callback`). `/login` generates a random
  `state` via `secrets.token_urlsafe`, redirects to
  `google_docs.build_authorize_url`, and stores `state` in a short-lived
  `oauth_state` cookie (10 min, httponly) rather than server-side storage —
  simplest CSRF protection for a single-user app with no pre-login session.
  `/callback` verifies `state` against that cookie, calls
  `exchange_code_for_tokens` + a new `google_docs.fetch_userinfo(access_token)`
  (hits `https://openidconnect.googleapis.com/v1/userinfo`, added to
  `app/clients/google_docs.py` since it's another plain Google HTTP call) to
  get the email, rejects with 403 if it isn't `ALLOWED_EMAIL`, otherwise
  upserts an `OAuthToken` row (by `email`, which is unique/indexed) and
  redirects to `/` with a signed `session` cookie (30-day max age). Wired
  `auth_router` into `app/main.py`. Added `itsdangerous` as a backend
  dependency (`uv add`, now in pyproject.toml) and `SESSION_SECRET_KEY` to
  `.env.example`. Added `backend/tests/test_auth.py`: login sets the state
  cookie and redirects to Google; callback with a mocked (respx) token
  exchange + userinfo response covers both the allowed-email-accepted path
  (session cookie set, `OAuthToken` row created) and the wrong-email-rejected
  path (403, no session cookie, no DB row); a mismatched/missing `state`
  returns 400; `require_auth` is tested directly against a small throwaway
  `FastAPI()` test app (not `app/main.py`) with a `Depends(require_auth)`
  route, covering missing cookie (401), valid cookie (200 + email), and a
  tampered/garbage cookie (401).
- Verified: `cd backend && uv run pytest` → 27 passed (20 pre-existing + 7 new
  auth tests). Also ran `uv run pytest tests/test_auth.py -v` in isolation, all
  green.
- Learned:
  - No `/api/*` protected routes exist yet (tasks 7–9 add them) — `require_auth`
    exists and is tested but isn't attached to any route in `main.py` yet aside
    from itself not being used anywhere. `/health` deliberately stays
    unauthenticated (infra health checks shouldn't need a session). **Future
    tasks adding real routes (chat API, task 9) must add
    `Depends(require_auth)` explicitly** — nothing enforces this automatically,
    there's no global middleware gating "all other routes."
  - Used Google's `openidconnect.googleapis.com/v1/userinfo` endpoint (Bearer
    access token) to get the email rather than decoding the `id_token` JWT
    locally — avoids needing a JWT/JWKS-verification dependency for a single
    call; token exchange already returns `id_token` in the response if a
    future task wants to switch to that instead.
  - State CSRF cookie is separate from the session cookie (`oauth_state` vs
    `session`) and is deleted on successful callback via
    `response.delete_cookie`. Both cookies are `httponly`+`samesite=lax`; not
    marked `secure` (Fly.io terminates TLS at the edge, and marking `secure`
    would break local `http://localhost` testing) — worth revisiting once
    task 12 sets up the real Fly deployment if cookies aren't arriving.
  - `request.url_for("google_callback")` (used to build the OAuth
    `redirect_uri` consistently between `/login` and `/callback`) requires the
    callback route to have an explicit `name="google_callback"` in its
    decorator — FastAPI's default name-from-function-name works fine too, but
    being explicit avoids breakage if the function is ever renamed.
  - `respx.mock` tests here are plain `def` (not `async def`) because they go
    through `TestClient` (sync interface) even though the routes themselves
    are `async def` — matches how `test_health.py`/other route-level tests
    are written; only the client-module-level tests in
    `test_google_docs.py`/`test_ankiconnect.py` that call client functions
    directly need `async def`.

## 2026-07-03 — Task 5: Google Docs client
- Did: Added `backend/app/clients/google_docs.py` with OAuth helpers
  (`build_authorize_url(redirect_uri, state)`, `exchange_code_for_tokens(code,
  redirect_uri)`, `refresh_access_token(refresh_token)`) hitting Google's
  standard `accounts.google.com`/`oauth2.googleapis.com` endpoints,
  `fetch_document(document_id, access_token) -> dict` (GET against the Docs
  API v1 `documents/{id}` endpoint with a Bearer token), and
  `flatten_runs(doc_json) -> list[dict]` which walks `body.content[].paragraph
  .elements[].textRun` in document order and emits one `{text, color}` span
  per run, where `color` is `"red"` (via `_classify_color` on
  `textStyle.foregroundColor.color.rgbColor`) or `None`. `GOOGLE_CLIENT_ID`/
  `GOOGLE_CLIENT_SECRET` read lazily from env, same pattern as other clients.
  `build_authorize_url` requests `access_type=offline`+`prompt=consent` so a
  refresh_token comes back on every login, not just the first consent.
  Added `backend/tests/test_google_docs.py` with a hand-written two-paragraph
  Docs-API-shaped fixture (plain English line + a Japanese attempt followed by
  a red-colored correction run) and tests for each function plus explicit
  assertions that only the red run is tagged `"red"` and other spans are
  `None`.
- Verified: `cd backend && uv run pytest` → 20 passed (14 pre-existing + 6 new
  Google Docs tests).
- Learned:
  - Red-detection heuristic is `red > 0.5 and red - green > 0.2 and red -
    blue > 0.2` on the Docs API's 0–1 float `rgbColor` — this is a guess at
    "looks red to a human," not calibrated against Dylan's actual doc. If task
    7/9 testing against the real lesson doc shows misses/false positives
    (e.g. teacher uses a orange-ish or maroon red), loosen/tighten these
    thresholds rather than assuming the logic is wrong.
  - Runs with no `textStyle` at all (plain black text) have no
    `foregroundColor` key — `_classify_color` treats missing/empty `rgbColor`
    as `color: None`, not black; there's no explicit "black" tag, only
    `"red"` vs `None`. Fine per PRD ("assert red-colored spans are correctly
    identified") but worth knowing if a later task wants to distinguish
    "explicitly black" from "default/unstyled."
  - Didn't build a `require_valid_token`/token-refresh-orchestration helper
    here — task 6 (OAuth + session auth) owns deciding when to call
    `refresh_access_token` vs. use a cached access token; this module only
    wraps the raw HTTP calls.

## 2026-07-03 — Task 4: ElevenLabs client
- Did: Added `backend/app/clients/elevenlabs.py` with
  `generate_audio_options(text, n=3, voice_id=DEFAULT_VOICE_ID) -> list[bytes]`.
  Issues `n` sequential POSTs to `{API_BASE_URL}/text-to-speech/{voice_id}`
  (ElevenLabs TTS REST endpoint), each with the same `text` but a different
  `voice_settings` (stability/similarity_boost) drawn from a small
  `_VOICE_SETTINGS_VARIANTS` list cycled by index, so the n outputs are
  audibly distinct takes rather than identical calls. `xi-api-key` header
  read lazily from `ELEVENLABS_API_KEY` env var (same lazy-env pattern as
  prior tasks). Returns raw response bytes (`response.content`) per option —
  no assumption about audio format, ElevenLabs defaults to MP3. Added
  `DEFAULT_VOICE_ID` module constant (ElevenLabs' public premade "Rachel"
  voice) since the PRD's env var list doesn't include a voice ID setting;
  callers (task 7's agent tool) can override `voice_id` per call instead.
  Added `backend/tests/test_elevenlabs.py` covering: 3 requests are made with
  3 distinct voice_settings payloads and the right byte payloads are
  returned in order (via respx `side_effect`), the `xi-api-key` header is
  sent, and `n` is respected for a non-default count.
- Verified: `cd backend && uv run pytest` → 14 passed (12 pre-existing + 2 new
  ElevenLabs test functions). Ran full suite, all green.
- Learned:
  - No `ELEVENLABS_VOICE_ID` env var exists in `.env.example`/PRD Requirements
    — don't add one without checking with Dylan first; `DEFAULT_VOICE_ID` is a
    reasonable stand-in but the agent (task 7) may want to expose voice choice
    as a tool parameter instead of a fixed default.
  - Used `respx`'s `side_effect=[...]` (list of Responses) rather than a
    single `return_value` to get distinct bytes back per call in order —
    `return_value` alone would make all 3 calls return identical content,
    which wouldn't actually test that 3 *options* were generated.

## 2026-07-03 — Task 3: AnkiConnect client
- Did: Added `backend/app/clients/ankiconnect.py` with a single `invoke(action,
  **params)` async wrapper over the AnkiConnect HTTP protocol (v6): POSTs
  `{"action", "version": 6, "params"}` (params key omitted when empty) to
  `ANKICONNECT_URL`, raises `AnkiConnectError` when the response's `error` key
  is non-null, otherwise returns `result`. Built `list_note_type_names()`
  (`modelNames`), `get_note_type_fields(name)` (`modelFieldNames`),
  `create_note(deck_name, model_name, fields, tags=None)` (`addNote`, wraps
  args into the `note` dict AnkiConnect expects), and `sync()` (`sync`) on top
  of it. `ANKICONNECT_URL` is read lazily from `os.environ` inside
  `_base_url()`, same lazy-env pattern as task 2's `get_engine()`. Added
  `backend/tests/test_ankiconnect.py` covering success, the error-surfacing
  case, and each of the four higher-level functions, all via `respx.mock`.
- Verified: `cd backend && uv run pytest` → 12 passed (6 pre-existing + 6 new
  AnkiConnect tests).
- Learned:
  - Don't assert on raw `request.content` bytes against a hand-written JSON
    literal — httpx's json encoder uses compact separators (`,`/`:` with no
    spaces), so a byte-for-byte comparison against `{"action": "version", ...}`
    (with spaces) fails even though the JSON is semantically identical.
    Instead `json.loads(request.content)` and compare the parsed dict.
  - AnkiConnect's real protocol omits the `params` key entirely for
    param-less actions like `version`/`sync` rather than sending
    `"params": {}` — `invoke()` only adds `params` to the payload when
    `params` is non-empty, matching that behavior.

## 2026-07-03 — Task 2: Persistence layer
- Did: Added `backend/app/models.py` with SQLModel tables `ConversationMessage`,
  `WorkflowSpec`, `ProcessingCursor`, `PendingCard`, `OAuthToken`, plus
  `get_engine()`/`init_db()`. `get_engine()` reads `DATABASE_PATH` from the
  environment lazily (at call time, not import time) via
  `create_engine(f"sqlite:///{DATABASE_PATH}")`, so tests can
  `monkeypatch.setenv("DATABASE_PATH", ...)` to a temp file before calling
  `init_db()`. Added `backend/tests/test_models.py` with a `tmp_path`-backed
  `engine` fixture and one round-trip test per table (insert in one session,
  re-query in a fresh session to prove persistence rather than just object
  identity).
- Verified: `cd backend && uv run pytest` → 6 passed (1 pre-existing health
  test + 5 new model tests). Ran both `uv run pytest tests/test_models.py` and
  the full suite; both green.
- Learned:
  - Kept the engine sync (`sqlmodel.create_engine`, not an async engine) even
    though the rest of the stack is async (FastAPI, httpx) — SQLModel/SQLAlchemy
    sync sessions over SQLite are the standard, low-friction choice here and
    the PRD doesn't require async DB access. Future tasks doing DB I/O from
    async route handlers should just call the sync session functions directly
    (FastAPI runs sync path functions in a threadpool) rather than introducing
    `aiosqlite`/async SQLAlchemy — not worth the complexity for a single-user
    SQLite app.
  - Field shapes for `PendingCard`/`WorkflowSpec`/`ProcessingCursor` aren't
    specified in detail by the PRD beyond table names — I picked reasonable
    minimal fields (e.g. `PendingCard.status` defaults to `"pending"`,
    `WorkflowSpec.spec` is a plain string so task 8 can decide whether it's
    raw text or JSON-encoded). If task 7/8/9 need different fields, adjust
    `app/models.py` then — don't treat this schema as frozen.
  - `uv run pytest` must be run with cwd inside `backend/` (pyproject.toml
    lives there and defines `[tool.pytest.ini_options]`); running it from the
    repo root with a `backend/tests/...` path arg fails to collect.

## 2026-07-03 — Task 1: Scaffold the repo
- Did: Created `backend/` as a `uv` project (Python 3.12) with FastAPI +
  uvicorn + sqlmodel + httpx + anthropic as deps, pytest/pytest-asyncio/respx
  as dev deps, `asyncio_mode = "auto"` in `[tool.pytest.ini_options]`. Package
  layout matches AGENTS.md: `app/{clients,agent,api}/__init__.py`,
  `app/main.py` with `GET /health`, `tests/test_health.py`. Created
  `frontend/` via `create-next-app` (TypeScript, Tailwind v4, App Router, ESLint,
  no src-dir, `@/*` import alias, npm). Added `.env.example` at repo root
  listing all six env vars from PRD Requirements.
- Verified: `cd backend && uv run pytest` → 1 passed. `cd frontend && npm run
  build && npm run lint` → build succeeds (static prerender of `/`), lint
  clean.
- Learned:
  - **Sandbox environment gotcha (not a project issue):** this WSL2 box's
    system DNS resolver hangs forever on `npm`/`npx`/`curl` for some domains,
    including `registry.npmjs.org` — glibc's getaddrinfo gets valid UDP
    answers for both A and AAAA queries, but for reasons specific to this
    VM's DNS proxy (10.255.255.254) then retries over TCP anyway and that
    TCP DNS query never gets a response. Fixed by running a small local
    CONNECT-proxy (`~/.local/share/anki-ai-cards/connect_proxy.py`, started
    via `~/.local/bin/ensure-npm-proxy.sh`) that does its own IPv4-only
    resolution, and pointing npm at it via `~/.npmrc` (`proxy`/`https-proxy`
    keys). Full detail is in AGENTS.md "Known constraints". If a future
    iteration sees `npm`/`npx` hang with no output, this is almost certainly
    it — run `~/.local/bin/ensure-npm-proxy.sh` (it's a no-op if already
    running) rather than debugging the project.
  - Neither `uv` nor a modern Node were preinstalled (system Node was v12,
    far too old for Next.js). Installed `uv` via astral's installer and Node
    24 LTS via `nvm`, then symlinked `node`/`npm`/`npx` into `~/.local/bin`
    (already on PATH) since `~/.bashrc`'s nvm sourcing only runs for
    interactive shells and this harness's Bash tool runs non-interactively.
  - AGENTS.md's verification commands section was already correct from a
    prior session (written before scaffolding existed) — no change needed
    there, only the new "Known constraints" bullet about the DNS proxy.
  - `create-next-app` generates its own `frontend/AGENTS.md` (points agents
    at bundled Next.js docs) and `frontend/CLAUDE.md` (`@AGENTS.md` import) —
    left both in place, they're scoped to the frontend subdir and don't
    conflict with the root AGENTS.md that the loop reads.
