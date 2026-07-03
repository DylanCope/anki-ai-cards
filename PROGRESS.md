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

## 2026-07-03 — Task 12: Backend/frontend deployment config
- Did: Added `backend/Dockerfile` (python:3.12-slim, `uv sync --frozen
  --no-dev` for a runtime-only venv, copies `app/`+`scripts/`, runs
  `uvicorn app.main:app`) and `backend/fly.toml` (app
  `anki-ai-cards-backend`, `[http_service]` on internal port 8000 with a
  `/health` check, `[[mounts]]` for a `backend_data` volume at `/data`,
  `[env]` setting `DATABASE_PATH=/data/anki-ai-cards.db` and
  `ANKICONNECT_URL=http://anki-ai-cards-anki.internal:8765` — i.e. task 11's
  headless Anki app's private 6PN address, not a public URL). Added
  `frontend/Dockerfile` (multi-stage `node:24-slim`: `npm ci` + `npm run
  build` in a build stage, then copies only `.next/standalone` +
  `.next/static` + `public` into a slim runtime stage, `CMD ["node",
  "server.js"]`) and `frontend/fly.toml` (app `anki-ai-cards-frontend`,
  `[http_service]` on internal port 3000, `[env]` setting
  `BACKEND_URL=http://anki-ai-cards-backend.internal:8000` so the
  server-side rewrite proxy in `next.config.ts`, task 10, talks to the
  backend over the private network rather than a public URL). Added
  `output: "standalone"` to `frontend/next.config.ts` — required for the
  Dockerfile's `.next/standalone` copy step to exist at all; without it
  `next build` only produces the full `.next/` tree meant for `next start`,
  not a slim deployable bundle. Neither fly.toml declares any of the 6
  secret env vars (`ANTHROPIC_API_KEY` etc.) — documented in AGENTS.md
  (new "Backend/frontend deployment" section) that those go in via `fly
  secrets set`, per the PRD's "wired as Fly secrets placeholders" wording,
  which reads as "the config acknowledges secrets exist and are supplied
  out-of-band," not "fly.toml contains a `SECRET_NAME=` literal."
- Verified: Installed `flyctl` (not preinstalled in this sandbox — `curl -L
  https://fly.io/install.sh | bash` to `~/.fly/bin/flyctl`, unlike `npm`'s
  registry domain this install script's domain resolved fine, no DNS-proxy
  workaround needed). Discovered `flyctl config validate` needs *some*
  `FLY_API_TOKEN` to run at all, but doesn't need it to be a real/valid
  token — `FLY_API_TOKEN=bogus flyctl config validate --strict --config
  <path>` prints a harmless `Metrics send issue: ... 401` warning (that's
  just telemetry) but still runs the actual config schema check and reports
  "Configuration is valid" / exits 0. Ran this (with `--strict`, which also
  checks for unrecognized keys) against both new configs and, as a
  regression check, against task 11's existing
  `deploy/anki-headless/fly.toml` — all three pass. Documented this
  bogus-token trick in AGENTS.md's new "flyctl in this sandbox" section so
  future tasks touching any fly.toml don't have to rediscover it.
  Went further than config-syntax validation since a valid fly.toml
  pointing at a broken Dockerfile would still "pass" that check: copied
  `backend/` to a scratch dir and ran the Dockerfile's actual `uv sync
  --frozen --no-dev` there, then imported `app.main` under that stripped-down
  (no dev deps) venv to confirm it still works. For the frontend, ran the
  real `npm run build` (already required by AGENTS.md) with the new
  `output: "standalone"` config, confirmed `.next/standalone/server.js` +
  `.next/static` + `public` exist exactly where the Dockerfile's `COPY
  --from=build` lines expect them, then actually ran `node
  .next/standalone/server.js` on a scratch port and `curl`ed it — got a
  real 200 from the prerendered homepage through the standalone server, not
  just "the file exists." Also reran `cd backend && uv run pytest` (64
  passed) and `cd frontend && npm run build && npm run lint` (both clean)
  to confirm the `next.config.ts` change didn't break anything.
  **Not verified (real Docker build):** the Docker daemon isn't running in
  this sandbox and there's no passwordless sudo to start it
  (`Cannot connect to the Docker daemon at unix:///var/run/docker.sock`,
  `sudo service docker start` prompts for a password this session doesn't
  have) — couldn't run an actual `docker build`. The scratch-dir `uv
  sync`/`node .next/standalone/server.js` checks above are a substitute that
  exercises the same commands the Dockerfiles run, just outside a container;
  flagging a real `docker build -f backend/Dockerfile backend` / `docker
  build -f frontend/Dockerfile frontend` as a good manual sanity check for
  Dylan before the first real `fly deploy`, alongside the deploy itself
  (which the loop must never run).
- Learned:
  - **`flyctl config validate` only needs *a* `FLY_API_TOKEN` env var to be
    set, not a real/authenticated one** — it fails with "no access token
    available" if the var is completely unset, but any string works well
    enough to run the actual validation logic (only the separate metrics
    telemetry call gets a 401, which is just a printed warning, not a
    failure). This resolves task 11's PROGRESS note that a future task would
    "need `flyctl` installed to actually run that check" — it needed
    installing (not preinstalled) but not real credentials.
  - `next.config.ts`'s `output: "standalone"` didn't exist before this task
    — task 10 only added the `rewrites()` block. Adding `standalone` changes
    what `npm run build` produces (an extra `.next/standalone/` tree
    alongside the normal `.next/`) but doesn't change build/lint pass/fail,
    so it's safe for any deployment target, not just Docker/Fly.
  - Followed the existing `deploy/anki-headless/fly.toml` convention of
    putting the `[env]` var that crosses app boundaries
    (`ANKICONNECT_URL`/`BACKEND_URL`) directly in `fly.toml` rather than as a
    secret, since `.internal` addresses aren't sensitive (they're only
    reachable from inside the same Fly org's private network anyway) —
    consistent with why `deploy/anki-headless/fly.toml` has no secrets at
    all.
  - Chose `backend/fly.toml`/`backend/Dockerfile` and
    `frontend/fly.toml`/`frontend/Dockerfile` living inside their own app
    directories (not a new `deploy/backend/`, `deploy/frontend/` alongside
    task 11's `deploy/anki-headless/`) since, unlike the headless Anki app
    (an external prebuilt image with zero source in this repo), these two
    apps' Dockerfiles build *this repo's own code* — the standard Fly
    convention is `fly.toml` + `Dockerfile` next to the app they build, and
    `deploy/anki-headless/` was a deliberate exception for exactly the
    "no source, just a config for someone else's image" case.

---

## 2026-07-03 — Task 11: Headless Anki deployment config
- Did: Added `deploy/anki-headless/fly.toml` for the `ankimcp/headless-anki`
  image (`ghcr.io/ankimcp/headless-anki:x11-vnc-v1.0.0`, researched via
  WebSearch/WebFetch of the `ankimcp/headless-anki` GitHub repo since this
  image isn't part of this codebase) — deliberately declares **no**
  `[[services]]`/public ports: AnkiConnect (port 8765 inside the container)
  is reached only via Fly's private 6PN network at
  `anki-ai-cards-anki.internal:8765`, and VNC (port 5900, the image's
  documented VNC port alongside 8765/AnkiConnect and 3141/MCP server) is
  reached on-demand via `fly proxy 5900 -a anki-ai-cards-anki` rather than
  ever being exposed publicly — `fly proxy` tunnels straight to a Fly app's
  private-network port without needing a `[[services]]` block. `[[mounts]]`
  persists the Anki profile at `/data` (the path used by the image's own
  `x11-vnc/docker-compose.yaml` example, `./data:/data`).
  Documented the one-time manual VNC→AnkiWeb login step in AGENTS.md (new
  "Headless Anki deployment" section, before "Known constraints"): `fly
  proxy 5900 -a anki-ai-cards-anki`, connect a VNC client to `localhost:5900`
  (image has no VNC auth — the private tunnel is the only access control),
  sign into AnkiWeb inside Anki's GUI, and verify with the new smoke-test
  script over another `fly proxy 8765 -a anki-ai-cards-anki` tunnel. Made
  clear the loop must never run `fly deploy` or perform the login itself —
  only Dylan does, manually.
  Added the smoke-test script: `backend/scripts/smoke_test_ankiconnect.py`
  (new `backend/scripts/` package, `__init__.py` added) — `check_ankiconnect
  (url)` calls AnkiConnect's `version` action against a caller-supplied URL
  and returns the reported protocol version (or raises); `main(argv)` is a
  CLI wrapper (`--url`, falling back to `$ANKICONNECT_URL` if unset) that
  prints `ok: ...`/exits 0 on success or prints `error: ...` to stderr/exits
  1 on any failure (unreachable host, AnkiConnect's own `error` field, or no
  URL available at all). Run as `uv run python -m
  scripts.smoke_test_ankiconnect --url <url>` from `backend/` (needs `-m`,
  not a bare `python scripts/smoke_test_ankiconnect.py`, so `app` is
  importable — see Learned).
  To let the script pass a URL without touching `ANKICONNECT_URL` env state,
  gave `ankiconnect.invoke()` (task 3) a new keyword-only `base_url: str |
  None = None` param (`base_url or _base_url()`) — fully backward compatible,
  every existing caller (task 3's `list_note_type_names`/etc., task 7's
  agent tools) still omits it and falls through to the existing
  `ANKICONNECT_URL`-env-var lookup unchanged.
  Added `backend/tests/test_smoke_test_ankiconnect.py` (6 tests, all via
  `respx.mock` against a stub URL, no real network): `check_ankiconnect`
  returns the version on success; `main` prints `ok`/returns 0 on success;
  `main` prints `error`/returns 1 on a connection failure (`httpx.ConnectError`
  via respx `side_effect`) and on an AnkiConnect-reported `error` field;
  `main` returns 1 with no `--url` and no env var set; `main` falls back to
  `$ANKICONNECT_URL` when `--url` is omitted.
- Verified: `cd backend && uv run pytest` → 64 passed (58 pre-existing + 6
  new smoke-test-script tests). Ran full suite twice, both green. Also ran
  the script directly by hand against a deliberately-unreachable address
  (`uv run python -m scripts.smoke_test_ankiconnect --url http://127.0.0.1:1`)
  and confirmed it prints the expected `error: ... not reachable` message and
  exits 1 — this exercises the *real* httpx connection-failure path, not
  just the respx-mocked one in the test suite.
  **Not verified (per the task's own Verify clause — this is explicitly
  Dylan's manual step):** running the script against the real deployed
  headless Anki instance, `fly deploy`-ing `deploy/anki-headless/fly.toml`,
  or the VNC AnkiWeb login. `fly config validate` was also not run here —
  `flyctl` isn't installed in this sandbox and task 11's Verify clause
  doesn't require it (task 12's does, for the backend/frontend configs);
  flagging that whoever does task 12 will need `flyctl` installed to
  actually run that check, or an equivalent structural check that doesn't
  need the binary.
- Learned:
  - **`ankimcp/headless-anki` (the Docker image, not part of this repo) has
    no docker-compose/env-var docs in its rendered README/CLAUDE.md** —
    WebFetch on those pages came back mostly "not documented here." Had to
    fall back to fetching the actual `x11-vnc/docker-compose.yaml` file from
    the repo (via `raw.githubusercontent.com`) to get the real port list
    (5900 VNC, 8765 AnkiConnect, 3141 MCP server) and volume path (`/data`).
    **If a future task needs more detail about this image (e.g. task 12
    touching this same deploy, or if the login step in AGENTS.md doesn't
    work as described), go straight to that repo's actual Dockerfile/compose
    files under `x11-vnc/`, `qt-vnc/`, `base/`, not the README** — the README
    undersells what's actually configurable.
  - `fly proxy <port> -a <app>` (tunnels to a Fly app's private-network port
    without any `[[services]]` declaration) is why `deploy/anki-headless/fly.toml`
    has **zero** `[[services]]`/`[http_service]` blocks — this was a
    deliberate choice to keep AnkiConnect and VNC off the public internet
    entirely, matching the PRD's "backend reaches it over Fly's private
    networking" requirement literally (not just "AnkiConnect isn't
    public-by-default", but "there is no public port at all"). If task 12 or
    Dylan finds `fly proxy` insufficient in practice (e.g. wanting a
    always-on VNC without running `fly proxy` each time), that's a deliberate
    tradeoff to revisit, not an oversight.
  - **Running a script under `backend/scripts/` that imports `app.*` requires
    `uv run python -m scripts.<module>` (with `backend/scripts/__init__.py`
    present), not `uv run python scripts/<module>.py`** — the bare-script
    form puts `scripts/` (not `backend/`) at `sys.path[0]`, so `import app`
    fails with `ModuleNotFoundError`; `-m` runs with the invoking cwd
    (`backend/`) on the path instead, which is where `app/` actually lives.
    Verified this by hand before writing the test suite. Documented the
    correct invocation in the script's own module docstring and in AGENTS.md
    so this doesn't get rediscovered the hard way later.
  - Chose to extend `ankiconnect.invoke()` with `base_url` rather than
    writing a second, duplicate HTTP-calling function in the smoke-test
    script — keeps the AnkiConnect request/error-handling logic (task 3's
    `AnkiConnectError` on a non-null `error` field) in one place, and the
    smoke-test script's tests now also exercise that shared error path for
    free.

---

## 2026-07-03 — Task 10: Frontend chat UI
- Did: Replaced the `create-next-app` placeholder homepage with the chat UI.
  Added `frontend/app/lib/types.ts` (TS mirrors of task 9's `ChatResponseBody`/
  history-entry/payload shapes). Added client components:
  `app/components/ChatApp.tsx` (all state — auth check, message list, send
  form), `MessageBubble.tsx`, `AudioOptionsCard.tsx` (renders the 3
  `<audio>` players from an `audio_options` payload's base64 `options` list
  as `data:audio/mpeg;base64,...` src, each with a "Pick" button),
  `CardPayloadCard.tsx` (renders a `card` payload's `deck_name`/`model_name`/
  `fields`/`tags`/`note_id` generically via `Object.entries(fields)` — no
  hardcoded field names like "JP cloze"/"furigana", since the PRD Overview
  requires field mapping to be agent-discovered live via AnkiConnect, not
  fixed by the UI), `SignIn.tsx` (Google sign-in link). `app/page.tsx` now
  just renders `<ChatApp />`.
  `ChatApp` fetches `GET /api/chat/history` on mount; a 401 shows `SignIn`,
  success populates the thread with empty `payloads: []` per historical
  message (see Learned below — payloads can't be reconstructed for old
  turns). Sending a message optimistically appends the user bubble, POSTs
  `/api/chat`, and appends an assistant bubble with that turn's `reply` +
  `payloads` on success; a 401 mid-session flips back to `SignIn`; other
  failures show an inline error banner without losing the typed message from
  the thread.
  Added `frontend/next.config.ts` `rewrites()`: proxies `/api/:path*` and
  `/auth/:path*` server-side to a new `BACKEND_URL` env var (default
  `http://localhost:8000`, added to root `.env.example`). This was necessary,
  not just convenient — task 6's session cookie is `samesite=lax`, which
  Chrome/Firefox will NOT attach to a cross-origin `fetch()` (only to
  top-level navigations), so if the frontend called the backend's origin
  directly from client JS, every `/api/chat` call would arrive without the
  session cookie and 401 regardless of login state. Proxying through Next's
  own server keeps the browser on one origin the whole time; `Set-Cookie`
  from the backend passes through the proxy untouched.
  The audio "Pick" button and the card's "Request a change" button don't
  call a dedicated selection/edit API (none exists — see task 9's PROGRESS
  entry on why there's no `propose_card`/select tool). Instead "Pick" directly
  sends a chat message ("Use audio option 2.") and "Request a change" just
  prefills the input box with a templated message referencing the note_id,
  leaving Dylan to finish and send it — both route the choice back through
  the same conversational path the agent already understands, rather than
  inventing new API surface for this frontend-only task.
- Verified: `cd frontend && npm run build && npm run lint` — build succeeds
  (static prerender of `/`), lint clean. Ran twice. Also reran
  `cd backend && uv run pytest` (58 passed) to confirm the unrelated backend
  suite wasn't affected.
  **Not verified: appearance/UX.** Per AGENTS.md this needs Dylan's manual
  browser check — in particular: does the rewrite proxy actually preserve the
  session cookie end-to-end against a real running backend (only reasoned
  about, not run, since there's no backend server up in this environment);
  does the chat thread look right; do the audio players actually play the
  base64 MP3 data URIs in a real browser; is scrolling/layout reasonable on
  mobile widths (phone is the real target device per the PRD Overview).
- Learned:
  - **`GET /api/chat/history` (task 9) only returns `{role, text}` — it has
    no way to return the `audio_options`/`card` payloads that were part of
    past turns**, because `_extract_payloads` in `backend/app/api/chat.py`
    only ever looks at *new* messages from the current `run_turn` call, and
    that extraction never gets persisted anywhere. Practical effect: reload
    the page mid-conversation and you keep the full text transcript but lose
    the audio players / card confirmations from earlier turns — only the
    live turns in the current browser session show payloads. Didn't fix this
    here since it requires a backend schema/API change (e.g. persisting
    extracted payloads alongside messages, or recomputing them from stored
    tool_use/tool_result rows on history read) which is out of scope for a
    frontend-only task — flagging as a candidate follow-up task if Dylan
    finds this annoying in practice.
  - Next.js 16 + Turbopack here: JSX fragments used as `.map()` list items
    need an explicit `<Fragment key={...}>` import from `react`, not the
    `<>...</>` shorthand — the shorthand doesn't accept a `key` prop and
    silently doesn't error at the JSX level, but produces a
    React-console-only "missing key" warning at runtime and would fail a
    stricter lint rule. Used in `CardPayloadCard.tsx` for the fields `<dt>`/
    `<dd>` pairs.
  - Confirmed `npm run build`/`npm run lint` both still work fine standalone
    (no proxy/env needed at build time since `rewrites()` only reads
    `BACKEND_URL` at request time, and defaults if unset) — no new frontend
    build-time env requirement introduced.

## 2026-07-03 — Task 9: Chat API
- Did: Added `backend/app/api/chat.py`, a router at `/api/chat` with
  `POST /api/chat` (`{"message": str}` in, `{"reply": str, "payloads":
  [...]}` out) and `GET /api/chat/history` (`[{"role", "text"}, ...]`), both
  behind `Depends(require_auth)`. Wired into `app/main.py`.
  `POST /api/chat` loads every persisted `ConversationMessage` row, decodes
  each row's JSON `content` back into the shape `run_turn` expects, resolves
  a fresh Google access token (see below), calls `agent.core.run_turn`, then
  persists only the *new* tail of the returned history (`serialized[len(prior_rows):]`)
  as new rows — so each turn appends rather than rewriting the whole
  conversation. Content blocks in the returned history can be either real
  `anthropic` SDK objects (fresh from `run_turn`, e.g. `TextBlock`/
  `ToolUseBlock`) or plain dicts (reconstructed from a previous turn's stored
  JSON) — `_content_block_to_dict`/`_serialize_message` normalize both to
  plain JSON-able dicts before anything touches them, so persistence and
  payload-extraction only ever deal with one shape.
  Structured payloads for the frontend are extracted from this turn's new
  messages only (not the whole history) by matching `tool_use` blocks to
  their `tool_result` by `tool_use_id`: a `generate_audio` call becomes
  `{"type": "audio_options", "text", "options": [...]}` and a
  `create_anki_note` call becomes `{"type": "card", "deck_name",
  "model_name", "fields", "tags", "note_id"}`. `GET /api/chat/history`
  re-reads all rows and keeps only messages with actual text content
  (skipping pure tool_use/tool_result plumbing turns), producing a plain
  chat transcript.
  Also added `_get_access_token(email)`: reads the `OAuthToken` row, and if
  `expires_at` has passed, calls `google_docs.refresh_access_token` (task 5)
  and updates the row before returning — needed because a chat session can
  easily outlive a 1-hour Google access token, and `fetch_google_doc` would
  otherwise start failing mid-conversation.
  Added `backend/tests/test_chat.py` (8 tests): auth-required on both routes;
  a full turn's reply is returned and both new messages persisted correctly;
  a second call reuses the persisted history (asserted via a captured
  `history` arg) and only persists the incremental new rows (4 total after 2
  turns, not 8); `audio_options` and `card` payload extraction from
  synthetic tool_use/tool_result histories; expired-token refresh updates
  the DB and is actually invoked; the history endpoint returns only
  human-readable turns.
- Verified: `cd backend && uv run pytest` → 58 passed (50 pre-existing + 8
  new). Ran full suite twice, both green.
- Learned:
  - **SQLite round-trips `datetime` columns as naive, even when you store a
    tz-aware value.** `OAuthToken.expires_at` is written as
    `datetime.now(timezone.utc) + timedelta(...)` (tz-aware) in task 6's
    OAuth callback, but SQLModel/SQLAlchemy's default `DateTime` column type
    over SQLite silently drops the tzinfo — reading the row back gives a
    *naive* datetime. Comparing that naive value against a fresh
    `datetime.now(timezone.utc)` raises `TypeError: can't compare
    offset-naive and offset-aware datetimes`. Fixed by comparing against
    `datetime.now(timezone.utc).replace(tzinfo=None)` instead (a naive UTC
    value) in `_get_access_token`. **Any future code comparing against a
    datetime column read back from the DB (not one just constructed
    in-process) needs this same naive-vs-aware care** — this wasn't caught
    by task 6's tests because that code only ever *writes* `expires_at`,
    never reads it back for a comparison.
  - The PRD's task 9 wording ("structured payloads — proposed cards, audio
    options") reads as if there's a pre-creation "candidate card" the agent
    proposes and Dylan approves/edits before it's created — but the current
    tool set (tasks 7/8) has no `propose_card`-style tool, only
    `create_anki_note`, which actually inserts into Anki immediately. Rather
    than invent a new tool (out of scope for this task and not requested by
    the PRD's tool list), the `"card"` payload here reports a note *after*
    creation (fields, deck, model, note_id echoed back from the tool call
    that already ran). The "propose, then approve/edit, then create" flow
    Dylan wants is presumably meant to happen conversationally — the agent's
    text reply describes the candidate card and asks Dylan to confirm in a
    follow-up chat message before it calls `create_anki_note` — rather than
    via a dedicated UI approval widget wired to an uncommitted tool call.
    **If task 10's frontend work (or Dylan) wants true pre-creation
    approve/edit, that needs a new tool (e.g. `propose_card`) added to task
    7/8's tool schema first** — flagging here so that's a deliberate
    decision, not a gap discovered late.
  - `ConversationMessage.content` stores `json.dumps(content)` uniformly —
    even the very first user turn, whose `content` is a plain `str` per
    `run_turn`'s `{"role": "user", "content": message}` — so decoding is
    always a single `json.loads(row.content)` regardless of whether the
    original content was a string or a list of blocks, no type-sniffing
    needed at read time.
  - Kept persistence as "reload full history every request, append only the
    new tail" rather than trying to cache `run_turn`'s state in memory
    across requests — simplest correct thing for a single-user, non-streaming
    v1 API per the PRD, and DB round-trip cost is irrelevant at this scale
    (one conversation, one user).
  - Didn't add pagination/limits to `GET /api/chat/history` or a way to
    start a *new* conversation (the schema has no "conversation id" concept,
    `ConversationMessage` is one global append-only log) — the PRD doesn't
    mention multiple conversations and task 2's schema was already built
    without one; flagging as a possible future task if Dylan wants to reset
    or branch a conversation, not fixing now.

## 2026-07-03 — Task 8: Workflow spec persistence + tools
- Did: Added `backend/app/agent/workflow_specs.py` — plain sync SQLModel
  functions over the task 2 `WorkflowSpec` table: `save_workflow_spec(name,
  spec)` (upsert by `name` — updates `spec` in place if the name already
  exists, otherwise inserts), `load_workflow_spec(name) -> WorkflowSpec |
  None`, `list_workflow_specs() -> list[WorkflowSpec]`. Added 3 new tool
  schemas to `backend/app/agent/tools.py` (`save_workflow_spec`,
  `load_workflow_spec`, `list_workflow_specs`) and wired them into
  `dispatch_tool` — `load_workflow_spec` returns `None` (not an error) when
  the name doesn't exist, letting the agent recover gracefully rather than
  crashing the tool-use loop. Updated `run_turn` in `backend/app/agent/core.py`:
  new `_build_system_prompt(history)` helper appends a "Known workflow specs
  from past sessions: ..." line (with the saved names) to `SYSTEM_PROMPT`
  only when `history` is empty (i.e. start of a new conversation) and at
  least one spec exists — non-empty history or zero saved specs both fall
  through to the plain `SYSTEM_PROMPT` unchanged, so this doesn't add a
  DB round-trip to every turn, only the first one. Updated
  `backend/app/agent/prompts.py`'s `SYSTEM_PROMPT` with a new closing
  paragraph telling the agent to `save_workflow_spec` once it and Dylan
  settle on how to handle a source, and to consider `load_workflow_spec`
  when specs are listed at conversation start. Added
  `backend/tests/test_workflow_specs.py` (save/load round-trip, upsert
  overwrites rather than duplicating, load of a missing name returns `None`,
  listing) and extended `backend/tests/test_agent.py`: a `db` fixture
  (tmp-file SQLite via `DATABASE_PATH`, same pattern as
  `test_models.py::engine`) used by the 3 existing `run_turn` tests (which
  now touch the DB indirectly via `_build_system_prompt` on their empty-history
  calls) plus new `dispatch_tool` tests for the 3 new tools and 3 new
  `run_turn` tests asserting: known specs appear in the `system` kwarg on an
  empty-history call, the plain prompt is used when no specs are saved, and
  the plain prompt is used when history is non-empty even if specs exist.
- Verified: `cd backend && uv run pytest` → 50 passed (39 pre-existing + 11
  new: 4 in `test_workflow_specs.py`, 4 new `dispatch_tool` tests, 3 new
  `run_turn` spec-surfacing tests). Ran full suite twice, both green.
- Learned:
  - **Adding a DB-backed enrichment to `run_turn` broke all 3 pre-existing
    `run_turn` tests** until they were given a real `DATABASE_PATH` (via the
    new `db` fixture) — `_build_system_prompt` calls
    `workflow_specs.list_workflow_specs()` unconditionally whenever `history`
    is empty, and `get_engine()` reads `os.environ["DATABASE_PATH"]` with no
    fallback, so any test calling `run_turn([], ...)` without first setting
    that env var now raises `KeyError` before ever reaching the mocked
    Anthropic client. In production `DATABASE_PATH` is a required env var
    (already true per the PRD) so this isn't a real robustness gap — but it's
    a trap for future tests: **any test calling `run_turn` with empty history
    needs the `db` fixture (or equivalent `DATABASE_PATH` setup) even if the
    test has nothing to do with workflow specs.** Tests that pass non-empty
    `history` don't need it, since `_build_system_prompt` short-circuits
    before touching the DB.
  - Chose upsert-by-name for `save_workflow_spec` (not append-only /
    versioned) since the PRD frames this as "the agent and Dylan settle on
    how to handle a source" — a single evolving spec per named source, not a
    history of attempts. If task 9/10 usage shows Dylan wants to see prior
    versions or diff changes, that's a schema change to `WorkflowSpec`
    (task 2), not a change to these functions' upsert semantics.
  - `load_workflow_spec`'s tool wrapper returns `None` (JSON `null`) rather
    than raising when the name isn't found, unlike `dispatch_tool`'s handling
    of e.g. missing `access_token` (which does raise). Reasoning: a missing
    workflow spec is an expected, recoverable outcome the agent should reason
    about ("no spec saved yet, let's build one"), not a caller bug — keep
    this asymmetry in mind if a future task audits `dispatch_tool` for
    consistent error-vs-null conventions.
  - Didn't add a `delete_workflow_spec` tool — not in the PRD's task 8 tool
    list (`save`/`load`/`list` only) and no obvious use case yet (upsert
    already covers "this spec is wrong, fix it"). Add later only if Dylan
    asks for it.

## 2026-07-03 — Task 7: Claude agent core
- Did: Added `backend/app/agent/prompts.py` (`SYSTEM_PROMPT` describing the
  inner agent's job per the PRD Overview: read the lesson doc, find red-marked
  corrections, propose cards, generate audio options, discover the Anki note
  type/fields live, create the note, sync). Added `backend/app/agent/tools.py`:
  `TOOL_SCHEMAS` (Anthropic tool-definition list) for the 6 tools task 7 wires
  up — `fetch_google_doc`, `list_anki_note_types`, `get_anki_note_type_fields`,
  `generate_audio`, `create_anki_note`, `sync_anki` (the workflow-spec tools
  `save_workflow_spec`/`load_workflow_spec`/`list_workflow_specs` are task 8's
  job, not built here) — plus `dispatch_tool(name, tool_input, *,
  access_token=None)`, a single if/elif router that calls the matching
  task 3-5 client function and returns a JSON-serializable result
  (`fetch_google_doc` flattens the doc via `google_docs.flatten_runs`;
  `generate_audio` base64-encodes the raw MP3 bytes from
  `elevenlabs.generate_audio_options` since tool_result content must be
  JSON-able — actually playing audio in the UI is task 9/10's problem, not
  this task's). Added `backend/app/agent/core.py`: `MODEL_ID =
  "claude-opus-4-8"`, `run_turn(history, message, *, access_token=None) ->
  {"history": [...], "reply": str}` driving `anthropic.AsyncAnthropic`'s
  manual tool-use loop (append `response.content` verbatim as the assistant
  turn per the SDK's documented pattern, loop while `stop_reason ==
  "tool_use"` executing every `tool_use` block via `dispatch_tool` and
  sending back one `user` message with all `tool_result` blocks, stop and
  return the joined text blocks once `stop_reason != "tool_use"`) with a
  `MAX_ITERATIONS = 10` safety valve against a runaway loop. Added
  `backend/tests/test_agent.py`: one `dispatch_tool` test per tool asserting
  the right underlying client function is awaited with the right args (all
  client functions mocked via `monkeypatch.setattr` + `AsyncMock`, per
  AGENTS.md — no real network/SDK calls), plus 3 `run_turn` tests against a
  mocked `anthropic.AsyncAnthropic` (patched via
  `unittest.mock.patch("app.agent.core.anthropic.AsyncAnthropic", ...)`)
  covering a no-tool-use reply, a tool_use → end_turn sequence (asserts the
  `tool_result` block sent back carries the right `tool_use_id` and
  JSON-decodes to the tool's return value), and that `access_token` reaches
  `fetch_google_doc` without ever appearing in the model's tool input.
- Verified: `cd backend && uv run pytest` → 39 passed (27 pre-existing + 12
  new agent tests). Ran full suite twice, both green.
- Learned:
  - **Mocking a function whose caller mutates its own `messages` list
    in-place is a trap for `Mock.call_args`/`await_args_list` assertions.**
    `run_turn` builds one `messages` list and keeps appending to it across
    loop iterations (as the SDK's documented manual-loop pattern requires —
    each iteration appends the assistant turn, then a user turn with tool
    results). Since Python passes that list by reference, `Mock` records
    `call_args` as a reference to the *same* list object, not a snapshot —
    so by the time a test inspects `client.messages.create.call_args` after
    `run_turn` returns, `kwargs["messages"]` reflects the *final*,
    fully-mutated state (extra assistant/tool_result turns included), not
    the messages that were actually true at call time. Fixed by replacing
    the mock's `create` with a plain async function that
    `copy.deepcopy(kwargs)`s into a `call_snapshots` list *inside* the
    function body (i.e. before `run_turn` gets to mutate anything further) —
    see `_mock_create` in `test_agent.py`. Future tests of anything that
    mutates a shared list/dict across awaited calls should use this pattern,
    not `mock.call_args`/`assert_called_with`, if they need to inspect state
    as of a *specific* call rather than the final state.
  - `google_docs.flatten_runs` is a **sync** function (task 5), unlike every
    other client call `dispatch_tool` makes — monkeypatching it with
    `AsyncMock` instead of a plain `Mock`/lambda silently returns an
    un-awaited coroutine object instead of the list, and `dispatch_tool`
    (correctly, since the real function is sync) doesn't await it, so the
    bug only shows up as a wrong-type assertion failure, not a "coroutine
    was never awaited" warning at the call site. Worth double-checking
    per-tool whether the underlying task 3-5 function is async before
    choosing `AsyncMock` vs `Mock` in future tests.
  - Response content blocks from the `anthropic` SDK are plain attribute-bearing
    objects (`block.type`, `block.text` / `block.id`/`.name`/`.input`) — tests
    use `types.SimpleNamespace` stand-ins instead of constructing real
    `anthropic.types.TextBlock`/`ToolUseBlock` instances, since `core.py` only
    ever does attribute access and duck-typing is enough; no need to depend on
    exact SDK response-object construction in tests.
  - `access_token` is deliberately a keyword-only parameter on `run_turn`/
    `dispatch_tool`, not something read out of the model's tool input — the
    Google OAuth access token is caller-supplied context (task 9's chat API
    will source it from the `OAuthToken` table via task 6's auth), never a
    string the agent itself constructs or sees. Only `fetch_google_doc`
    currently needs it; `dispatch_tool` raises `ValueError` if it's missing
    when that tool is called.
  - Model pinned to `claude-opus-4-8` (no thinking/effort config) — this is a
    tool-calling/data-entry agent, not a hard-reasoning task, so the default
    request shape (no `thinking`, default effort) is enough; revisit if task
    9/10 testing against the real lesson doc shows it needs more reasoning
    depth on ambiguous docs.
  - `run_turn`'s tests set `ANTHROPIC_API_KEY` via `monkeypatch.setenv` even
    though the client itself is mocked — `_get_client()` in `core.py` still
    reads `os.environ["ANTHROPIC_API_KEY"]` *before* constructing (the mocked)
    `anthropic.AsyncAnthropic`, so the env var must exist or the test fails on
    a `KeyError` before ever reaching the mock.

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
