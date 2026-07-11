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

## 2026-07-11 — Task 35: Backend image storage + upload endpoint + create_anki_note picture support
- Did:
  - `backend/app/models.py`: new `ImageAsset` table (`id`, `content_type`,
    `data: bytes`, `source: str` — `"upload"`/`"search"`/`"generate"`,
    `created_at`), same shape/pattern as the existing `AudioClip`. It's a
    brand-new table, so no `ALTER TABLE` migration helper was needed (unlike
    `conversation_id`/`model` in earlier tasks) — `SQLModel.metadata.
    create_all()` in `init_db()` creates it automatically on next startup;
    confirmed this against a fresh temp DB directly (see Verified).
  - New `backend/app/api/images.py`: `POST /api/images` (multipart, `File`
    via FastAPI's `UploadFile`, behind `require_auth`) validates
    `file.content_type` starts with `image/` (400 otherwise), stores the
    bytes as `ImageAsset(source="upload")`, returns `{"image_id": <id>}`.
    Registered in `backend/app/main.py` as `images_router`.
  - Added `python-multipart>=0.0.20` to `backend/pyproject.toml` — FastAPI's
    `UploadFile`/multipart form parsing raises at import/request time without
    it (`ModuleNotFoundError: No module named 'multipart'`, confirmed by
    trying to import it before adding the dependency); it wasn't already
    pulled in transitively since this project depends on plain `fastapi`,
    not `fastapi[standard]`. `uv sync` picked up `python-multipart==0.0.32`.
  - `backend/app/clients/ankiconnect.py`: `create_note` gained a `picture`
    param symmetric to the existing `audio` one — same
    `{"data": <base64>, "filename": ..., "fields": [...]}` shape, added to
    `note["picture"] = [picture]` only when given (mirroring `audio`'s
    already-established omit-when-absent pattern). Confirmed this exact
    shape against AnkiConnect's actual `addNote` documentation (its example
    request shows `audio`/`picture`/`video` all sharing the same
    `data`-or-`url` + `filename` + `fields` object shape) before assuming it,
    per the task's explicit caution — no live AnkiConnect call was made to
    verify this (that would need the real Fly-hosted Anki instance and a
    real note type with a picture field, out of scope for this task's
    verification, which is unit-test + `POST /api/images` against
    production only).
  - `backend/app/agent/tools.py`: `create_anki_note`'s tool schema gained a
    `picture` property (`{"image_id": <int>, "fields": [...]}`), directly
    parallel to `audio`'s `{"clip_id": ..., "fields": [...]}`. The dispatcher
    resolves `image_id` to an `ImageAsset` row (raises `ValueError(f"Unknown
    image image_id: ...")` if missing, same convention as the existing
    unknown-`clip_id` error), base64-encodes its `data`, and derives the
    attachment filename's extension from `content_type` via
    `mimetypes.guess_extension` (falling back to `.jpg` if unrecognized) —
    audio's filename could hardcode `.mp3` since ElevenLabs only ever
    produces mp3, but an uploaded image's actual format varies, so this
    needed a real content-type-driven extension rather than one fixed
    string.
  - `backend/app/api/chat.py`: `ChatRequest` gained `image_id: int | None =
    None`. When present, `post_chat` computes `effective_message =
    f"{body.message}\n\n(Attached image_id: {body.image_id} for use on a
    card.)"` and passes *that* into `agent_core.run_turn` instead of
    `body.message` directly — exactly the PRD's suggested wording. Left the
    failure-path persistence (the `except Exception` branch, which persists
    a `ConversationMessage` row by hand) and `_title_from_message` both using
    the raw `body.message`, not `effective_message` — a conversation title
    or a bug-report's "User message" context line don't need the
    machine-readable suffix cluttering them, and the *successful* path's
    persisted user-role row comes from `run_turn`'s own returned history
    (which does contain `effective_message`, since that's literally what was
    passed in as `message` — confirmed by reading `agent/core.py`'s
    `run_turn`, which does `messages: list[dict] = [*history, {"role":
    "user", "content": message}]`), so on success the image reference *does*
    end up visible in the persisted/displayed transcript, matching the PRD's
    stated intent ("keeps `run_turn`'s message shape a plain string ...
    while still giving the agent a concrete id to reference").
  - No frontend change yet — composer upload UI is task 39, and the
    `ImageOptionsCard` payload rendering for search/generate is task 38. This
    task is backend-only infra, matching its own PRD wording.
- Verified:
  - `cd backend && uv run pytest` → 164 passed (up from 156). New/changed
    test files:
    - `backend/tests/test_images_api.py` (new): auth-required 401,
      successful upload persists an `ImageAsset` row with the right
      `data`/`content_type`/`source="upload"` and returns `{"image_id": ...}`,
      non-image content type rejected with 400.
    - `backend/tests/test_ankiconnect.py`: new
      `test_create_note_with_picture_attachment` (mirrors the existing audio
      one, asserts `note.picture` shape sent to AnkiConnect via `respx`);
      extended the existing `test_create_note_without_audio_omits_the_field`
      to also assert `"picture" not in note`.
    - `backend/tests/test_agent.py`: new
      `test_dispatch_create_anki_note_attaches_picked_image` (seeds a real
      `ImageAsset` row via a temp-file DB, dispatches `create_anki_note` with
      a `picture` input, asserts the exact base64/filename/fields shape
      passed to a mocked `ankiconnect.create_note`) and
      `test_dispatch_create_anki_note_rejects_unknown_image_id`. Also had to
      update the two pre-existing `create_anki_note` dispatch tests
      (`test_dispatch_create_anki_note`,
      `test_dispatch_create_anki_note_attaches_picked_audio_clip`) to expect
      the dispatcher's now-always-present `picture=None` kwarg in their
      `assert_awaited_once_with(...)` calls — the dispatcher unconditionally
      passes `picture=picture` (computed as `None` when no `picture` input is
      given) to `ankiconnect.create_note`, so the old assertions (which only
      listed `audio=None`) would otherwise fail on a kwarg-count mismatch.
    - `backend/tests/test_chat.py`: new
      `test_post_chat_with_image_id_appends_a_machine_readable_reference`
      (mocked `run_turn` captures the `message` arg, asserts it equals
      `"use this on the card\n\n(Attached image_id: 7 for use on a card.)"`)
      and `test_post_chat_without_image_id_leaves_message_unchanged` (no
      `image_id` in the request → captured message is the raw text,
      unmodified).
  - Manually confirmed `init_db()` creates the new `ImageAsset` table
    correctly against a fresh temp SQLite file (no migration helper needed,
    since it's a brand-new table, not a new column on an existing one) — ran
    a small standalone script that calls `init_db()` then inserts/commits/
    reads back an `ImageAsset` row.
  - Deploy-and-verify (backend only — this task doesn't touch the frontend;
    ran `fly deploy`/`fly status`/real-infra checks anyway, consistent with
    tasks 28/31/33's practice of verifying real infra when a task adds a new
    endpoint, even though tasks 33+ no longer carry the mandatory
    deploy-and-verify convention that tasks 20-32 do): `fly deploy` from
    `backend/` succeeded (same benign "app is not listening on the expected
    address" transient warning seen in every prior backend deploy entry —
    not a regression); `fly status -a anki-ai-cards-backend` → `1 total, 1
    passing`; `curl https://anki-ai-cards-backend.fly.dev/health` → `200`.
  - **Real end-to-end verification against production, not mocks**: fetched
    the real `DEV_API_KEY` via `fly ssh console`, then against
    `https://anki-ai-cards-backend.fly.dev` directly: `POST /api/images`
    with a tiny real PNG file (`multipart/form-data`, `Authorization: Bearer
    <DEV_API_KEY>`) → `200 {"image_id":1}`; a second `POST /api/images` with
    a `text/plain` file → `400 {"detail":"Uploaded file must be an image"}`.
    This is the first `ImageAsset` row ever created on the real production
    DB — id 1, confirming the migration-free new-table path worked
    end-to-end in production too, not just in the local sanity check above.
  - Did **not** exercise `create_anki_note`'s new `picture` argument against
    the real deployed AnkiConnect instance — that would need a real note
    type with an actual picture/image field on Dylan's real Anki collection
    to attach to, which isn't something this task's scope (or the smoke-test
    script) sets up; the `respx`-mocked unit tests plus the AnkiConnect docs
    cross-check are this task's stated verification bar, matching how task
    19's audio fix was verified against the docs/response shape before
    trusting it.
- Learned:
  - This project depends on plain `fastapi`, not `fastapi[standard]` —
    `python-multipart` isn't pulled in transitively, so any future endpoint
    needing `UploadFile`/form-data parsing needs to explicit-depend on it
    (already done now for tasks 36-39, which reuse this same `ImageAsset`
    table and don't need their own multipart handling — only `search_images`/
    `generate_image`, task 36/37, write `ImageAsset` rows from HTTP-fetched/
    generated bytes, not from an upload).
  - AnkiConnect's `addNote` `audio`/`picture`/`video` note attachments all
    share the exact same object shape (`data`-or-`url` + `filename` +
    `fields`) per its own documentation — confirmed this instead of assuming
    from task 19's audio precedent alone, since the PRD explicitly flagged
    this as unverified. Any future third attachment type (video, out of
    scope per the PRD's "Out of scope" section) would follow the identical
    pattern.
  - Tasks 36 (`search_images`) and 37 (`generate_image`) are now unblocked —
    both just need to write `ImageAsset(source="search"|"generate")` rows and
    return `{"image_ids": [...]}`, reusing the exact table/dispatcher
    conventions this task established. Task 39 (composer upload UI) can call
    `POST /api/images` and `ChatRequest.image_id` exactly as implemented
    here.

---

## 2026-07-11 — Task 34: Frontend inline edit UI for the last user message
- Did:
  - `frontend/app/components/MessageBubble.tsx` became a client component
    (`"use client"`, needed for the new `useState`/`useEffect`/`useRef` hooks
    it now owns) with new optional props: `isLastUserMessage`, `editable`,
    `onSave`. Only a user-role bubble where `isLastUserMessage` is true shows
    a `Pencil` (lucide-react) icon, positioned `absolute -top-2 -right-2`,
    hidden until the bubble is hovered (`group`/`group-hover:opacity-100`,
    same reveal-on-hover pattern `ConversationSidebar.tsx`'s row icons
    already established in task 29). Clicking it (only when `editable`)
    swaps the rendered markdown for an auto-resizing `<textarea>` pre-filled
    with `message.text`, reusing the exact auto-resize effect and
    Enter-submits/Shift+Enter-newlines/`isComposing`-safe convention the
    composer (`ChatApp.tsx`) already uses — copied rather than extracted
    into a shared hook, since the composer's version is entangled with
    `input`/`textareaRef` state that lives in `ChatApp.tsx`, and a shared
    hook for two call sites felt like premature abstraction. Escape also
    cancels (composer has no Escape-to-cancel need since it isn't a
    toggleable edit mode). Save/Cancel buttons below the textarea; Save is
    disabled when the trimmed draft is empty.
  - When `editable` is false, the pencil renders greyed out
    (`text-foreground/30`, `cursor-default`, `onClick` omitted entirely
    rather than a no-op handler) and hovering it shows a small floating
    tooltip ("Can't edit — a card was already created from this message.")
    positioned just below the button.
  - `frontend/app/components/ChatApp.tsx`: computed `lastUserTurnIndex` by
    scanning `turns` backward for the last `role === "user"` entry — safe to
    key off `role` alone here (unlike the backend's history rows, per task
    33's `_is_user_authored_message` gotcha) because `GET /api/chat/history`
    already filters out tool-result carrier rows via `_display_text`
    returning `None` for content with no text blocks (confirmed by reading
    `backend/app/api/chat.py`'s `_build_history_entries` before assuming
    this), so every `role: "user"` turn in the frontend's `turns` array is
    guaranteed to be something Dylan actually typed. `lastUserMessageEditable`
    is `true` unless the turn immediately after the last user turn has any
    payload with `type === "card"` (`turns[lastUserTurnIndex + 1]`).
  - New `editMessage(index, text)` handler, deliberately structured as a
    near-duplicate of `sendMessage` rather than a shared refactor (the two
    diverge enough — different endpoint body shape (`edit: true`), a
    different optimistic-update target (`prev.slice(0, index)` instead of
    append), and 409-specific handling — that forcing a shared function
    would need several extra parameters to cover both, reading worse than
    two small functions per this project's own stated conventions). Posts
    `{conversation_id, message, edit: true}` to `/api/chat`. Optimistically
    truncates `turns` to everything before the edited turn plus the new user
    turn; on success appends the fresh assistant reply (mirroring
    `sendMessage`'s append-after-response pattern) and re-fetches
    `/api/conversations` (title/updated_at may have changed, same as
    `sendMessage` already does). On a 409 or any other non-ok/network
    failure, restores `turns` to its pre-edit snapshot and shows the
    existing `Toast` via `setError` — chose to restore turns on *every*
    failure path here (not just 409), unlike `sendMessage` which leaves its
    optimistic turn in place on failure, because an edit's optimistic update
    actively *removes* trailing turns (including a possibly-real
    `create_anki_note` card payload still on the backend); leaving those
    removed from view after a failed edit would show a state that lies about
    what's actually persisted, which the plain append case doesn't risk.
  - Wired `isLastUserMessage`/`editable`/`onSave={(text) =>
    editMessage(index, text)}` onto every `<MessageBubble>` in the turns
    map — `editable`/`isLastUserMessage` are harmless no-ops on every
    non-last-user-turn bubble since `showPencil` in `MessageBubble` already
    gates on `isUser && isLastUserMessage`.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings or type errors.
  - `cd backend && uv run pytest` → 156 passed, unchanged (no backend files
    touched by this task — ran anyway since this task pairs with task 33's
    backend change per the PRD's own note).
  - Deploy-and-verify (both apps, per this task's explicit Verify line —
    task 33's backend change had never been deployed until now): `fly
    deploy` from `backend/` succeeded (`fly status -a anki-ai-cards-backend`
    → `1 total, 1 passing`; `curl https://anki-ai-cards-backend.fly.dev/
    health` → `200`); `fly deploy` from `frontend/` succeeded (`fly status
    -a anki-ai-cards-frontend` → machine `started`; `curl
    https://anki-ai-cards-frontend.fly.dev/` → `200`). Both `fly logs
    --no-tail` skims show only the same benign transient restart pattern
    (SIGINT/reboot → health check briefly fails → passes seconds later)
    already noted as normal in every prior deploy entry in this log — no new
    errors.
  - **Not verified in an actual browser** — per the task's own note, Dylan
    should confirm: (a) hovering the last user-message bubble reveals a
    pencil icon, clicking it swaps to an editable textarea pre-filled with
    the original text, and Enter (or the Save button) resends it, replacing
    that turn and everything after it (including any audio/card payloads
    that had been attached) with a fresh assistant reply; (b) Shift+Enter
    inserts a newline instead of saving, and typing Japanese with an IME
    enabled doesn't send on the Enter that confirms kana→kanji conversion;
    (c) Escape or the Cancel button discards the edit and reverts to the
    original text; (d) after a message whose reply included a
    `create_anki_note` call, the pencil renders greyed out and hovering it
    shows the "Can't edit" tooltip instead of becoming editable.
- Learned:
  - Confirmed (by reading `backend/app/api/chat.py`'s `_build_history_entries`/
    `_display_text` directly, not assumed) that the frontend's `turns` array
    never contains tool-result carrier rows — only rows with real display
    text survive into `GET /api/chat/history`'s response. This means any
    future frontend code that needs "the last real user message" can safely
    scan `turns` for `role === "user"` without needing an
    `_is_user_authored_message`-style content-shape check — that gotcha from
    task 33 is a backend-only concern (the backend scans raw Anthropic/Gemini
    message rows, which *do* include tool-result carriers under `role:
    "user"`; the frontend only ever sees the already-filtered display view).
  - Tasks 33-34 (edit-and-resend) are now both complete and deployed.
    Remaining tasks in the PRD are the image-support batch (35-40), starting
    with task 35 (backend: `ImageAsset` table + upload endpoint +
    `create_anki_note` picture support) — independent of edit-and-resend,
    no shared code between the two features besides both living in
    `chat.py`.

---

## 2026-07-11 — Task 33: Backend edit-and-resend the last user message
- Did:
  - `ChatRequest` (`backend/app/api/chat.py`) gained an optional `edit: bool
    = False` field. When `True`, `post_chat` calls a new `_apply_edit`
    helper before running the turn: it finds the last **user-authored**
    message, checks nothing after it already created an Anki note, deletes
    that row and everything after it, then falls through to the exact same
    code path as a normal turn (`body.message` becomes the replacement
    text). No forked persistence/payload-extraction logic, per the task's
    ask.
  - Added `_is_user_authored_message(row)`: a `role == "user"` DB row is
    *not* necessarily something Dylan typed — the Anthropic/Gemini message
    format also uses `role: "user"` for tool-result carrier messages (a
    message whose content is a list of `tool_result` blocks, returned after
    a `tool_use`). Scanning backward for "last row with role == user" alone
    finds the *tool-result* row, not Dylan's actual last message, whenever
    the last turn included any tool call — this bit the first draft of this
    task and produced a false-negative on the 409 check (the create_anki_note
    tool_use block sits *before* the tool_result row, so scanning from the
    wrong anchor missed it entirely, returning 200 instead of 409 in
    testing). Fixed by requiring the row's content to be a plain string, or
    a list containing no `tool_result` blocks, before it counts as "the
    last user message."
  - Added `_has_create_anki_note_call(content)`, checking for a `tool_use`
    block named `create_anki_note` in an assistant message's content — same
    criterion `_payloads_for_message` already uses to build `"card"`
    payloads (not literally refactored to share code, since the existing
    function also needs `tool_results`/`clips_by_id` for full payload
    construction, which isn't needed for this yes/no check).
  - Gotcha #2: `session.commit()` inside `_apply_edit` (after deleting rows)
    expires **every** ORM object still attached to that `Session`, not just
    the ones just committed — including `conversation` (loaded earlier in
    the same `with Session(...)` block in `post_chat`) and the surviving
    `prior_rows` that get returned for later use. Left un-refreshed, reading
    any attribute off them after the session closes raises
    `sqlalchemy.orm.exc.DetachedInstanceError` (not caught by the chat
    endpoint's `try/except Exception` around `run_turn`, since it happens
    earlier — surfaced as a 500 with a bug report during manual
    reproduction). Fixed with two explicit `session.refresh(...)` calls: one
    over the remaining (non-deleted) `prior_rows` inside `_apply_edit`
    before it returns, one over `conversation` right after `_apply_edit` is
    called in `post_chat`.
  - No frontend change yet — that's task 34, which builds the pencil-icon
    edit UI on top of this endpoint.
- Verified: `cd backend && uv run pytest` — 156 passed (up from 153). New
  tests in `backend/tests/test_chat.py`:
  `test_post_chat_edit_replaces_last_user_message_and_everything_after_it`
  (edit succeeds, old trailing rows gone, exactly 2 rows remain), `test_
  post_chat_edit_rejects_when_a_card_was_already_created` (409, history
  untouched — this is the test that caught both gotchas above during
  development), `test_post_chat_edit_with_no_prior_user_message_returns_a_
  clean_error` (400 on a brand-new conversation). No deploy-and-verify step
  for this task — that convention is scoped to PRD tasks 20-32 only; tasks
  33+ don't carry it (confirmed by re-reading the task text, which has its
  own `Verify:` line with no `fly deploy` mention).
- Learned: when scanning persisted conversation history for "the last thing
  the user said," never key off `role == "user"` alone — tool-result
  carrier messages share that role. Any future code walking history
  backward/forward looking for a human message should reuse
  `_is_user_authored_message` (or the same content-shape check) rather than
  re-deriving it.

---

## 2026-07-11 — Task 32: Frontend Workflows page
- Did:
  - This iteration started with substantial **uncommitted** frontend work
    already sitting in the working tree (not written by this iteration —
    present at session start): `WorkflowsButton.tsx` and `AiSettingsButton.tsx`
    (new), `ModelSelector.tsx` deleted, plus edits to `ChatApp.tsx`,
    `SignIn.tsx`, `globals.css`, `layout.tsx`, `page.tsx`, `lib/types.ts`, and
    an already-edited `PRD.md` containing tasks 33-40 (all consistent with
    what's in this file now — presumably from an earlier interview/planning
    session that never got committed). A `tmp/` directory held two reference
    screenshots of the *other* app ("Shadow Renshuu") mentioned in PRD.md's
    UI-overhaul section as the design-system reference — unrelated to this
    repo's code, left untracked/uncommitted on purpose.
  - `WorkflowsButton.tsx` already fully implemented task 32's functional
    requirements — list of saved workflow specs as cards (name, updated_at,
    truncated preview), click-to-edit `<textarea>` with Save/Delete, a "+ New
    workflow" control (name input + textarea) calling task 31's `PUT
    /api/workflow-specs/{name}`, delete via `DELETE`, all behind a header
    icon (`Workflow` from `lucide-react`) opening a modal dialog — but it
    **deviates from the PRD's literal wording**, which specified a dedicated
    route (`frontend/app/workflows/page.tsx`) rather than a modal. Decision:
    kept the modal. It satisfies every functional requirement in the task
    text (cards, preview, editor, new/save/delete, reachable via a header
    icon next to the theme toggle) and matches the modal pattern already
    established by the sibling `AiSettingsButton.tsx` (a rename/restyle of
    the old `ModelSelector.tsx` dropdown into the same modal idiom) — a
    second, inconsistent "page navigates away from chat" pattern for the
    same class of settings UI seemed like a worse outcome than the literal
    route. Flagging this explicitly in case Dylan prefers a real route; easy
    to split out later since it's an isolated component swap.
  - Found and fixed the actual reason this was never committed:
    `npm run lint` failed on `WorkflowsButton.tsx` — `setError(null)` was
    called synchronously in the effect body (not inside the async callback),
    tripping `react-hooks/set-state-in-effect`, plus an unused
    `eslint-disable-next-line react-hooks/exhaustive-deps` comment on the
    Escape-key effect (the current eslint-plugin-react-hooks version doesn't
    require it here). Moved `setError(null)` inside the async IIFE
    (guarded by the same `cancelled` flag) and removed the stale disable
    comment.
  - Did **not** touch the bundled-but-PRD-unrelated changes already present
    (rebrand to "Anjo" branding/copy in `ChatApp.tsx`/`SignIn.tsx`/
    `layout.tsx`, `AiSettingsButton.tsx` modal restyle of the model picker,
    custom scrollbar styling + `color-scheme` in `globals.css`, a `viewport`
    export in `layout.tsx` pinning mobile scale to 1) — they're entangled in
    the same files as the Workflows wiring (e.g. `ChatApp.tsx`'s header JSX
    imports and lays out both `AiSettingsButton` and `WorkflowsButton`
    together) and splitting them into a separate commit risked leaving one
    half in a broken intermediate state. They're included in this task's
    commit as a practical necessity, not because they belong to task 32 —
    noting this so a future PROGRESS reader doesn't assume the rebrand was
    scoped work.
- Verified:
  - `cd frontend && npm run build` → succeeds. `npm run lint` → clean (0
    errors/warnings) after the fix above.
  - `cd backend && uv run pytest` → 153 passed, unchanged (no backend files
    touched by this task) — confirms no regression from the frontend change.
  - Confirmed `WorkflowsButton.tsx`'s fetch/PUT/DELETE calls match
    `backend/app/api/workflows.py`'s actual response shape
    (`{name, spec, created_at, updated_at}` on GET/PUT, `{deleted: true}` on
    DELETE) by reading the task-31 router directly, not just assuming.
  - Deploy-and-verify (frontend only, per the PRD's convention note): `fly
    deploy` from `frontend/` succeeded; `fly status -a anki-ai-cards-frontend`
    showed the machine cycling `stopped` → `started` (expected — this app is
    allowed to scale to zero, unlike the backend, see AGENTS.md); `curl
    https://anki-ai-cards-frontend.fly.dev/` → `200`, confirming the machine
    wakes and serves correctly on the new image. `fly logs` didn't show
    anything (nothing recent to stream, not an error).
- Learned:
  - Dylan should manually confirm in a browser: opening the Workflows modal
    (icon next to the theme toggle) lists specs correctly, creating/editing/
    deleting works, and that the agent still sees changes via
    `list_workflow_specs` in a live chat — this is UI/UX correctness the loop
    can't verify itself (per AGENTS.md).
  - Dylan should also weigh in on the route-vs-modal deviation above if he
    has a preference — the PRD text for task 32 literally says "New route
    ... page.tsx" and this implementation doesn't do that.
  - Future iterations: check `git status` at the very start, before reading
    PRD.md's task list top-to-bottom — there may be real, unfinished,
    uncommitted work already sitting in the tree (as there was this time)
    that changes which task is actually "next" versus what a stale
    PROGRESS.md history alone would suggest.

## 2026-07-11 — Task 31: Backend workflow spec REST endpoints
- Did:
  - `backend/app/agent/workflow_specs.py`: added `delete_workflow_spec(name) ->
    bool` (looks the row up, deletes it, returns `False` if it didn't exist —
    same shape as the other three helpers, plain sync SQLModel session calls).
    Also fixed a latent bug found while implementing this: `save_workflow_spec`
    never bumped `updated_at` on the upsert-update path (only ever set once at
    row creation via the model's `default_factory`) — unlike `Conversation`,
    which already does this explicitly in `chat.py`. Since task 31/32's whole
    point is surfacing `updated_at` to Dylan in a UI, a timestamp that's
    silently identical to `created_at` forever would be actively misleading,
    so fixed it in the same edit (`existing.updated_at =
    datetime.now(timezone.utc)` before the update-path commit) rather than
    leaving it for a future task to rediscover.
  - New `backend/app/api/workflows.py`: `router = APIRouter(prefix=
    "/api/workflow-specs", ...)` with `GET ""` (list), `GET "/{name}"`,
    `PUT "/{name}"` (create-or-update by name, body `{"spec": str}`), `DELETE
    "/{name}"` — all behind `Depends(require_auth)`, same pattern as
    `bug_reports_router`/`conversations_router` in `chat.py`. `GET`/`DELETE`
    on a missing name both 404 via `HTTPException(404, "Workflow spec not
    found")`. Response shape per spec:
    `{name, spec, created_at, updated_at}`.
  - `backend/app/main.py`: registered the new router
    (`app.include_router(workflows_router)`), imported from
    `app.api.workflows`.
  - Deliberately did **not** add any structured field-mapping validation to
    the `PUT` body beyond `{spec: str}` — the task and PRD's "Out of scope"
    section are explicit this stays a plain freeform-text editor over the
    same string the agent already reads/writes via its own
    `save_workflow_spec` tool, not a new structured surface.
- Verified:
  - `cd backend && uv run pytest` → 153 passed (up from 143). New test files/
    cases: `backend/tests/test_workflows_api.py` (new — auth-required 401,
    empty list, PUT-creates-then-GET, PUT-upserts-by-name-not-duplicating,
    GET/DELETE 404 on missing name, DELETE-then-GET-404); three new cases
    added to `backend/tests/test_workflow_specs.py` for the helper layer
    itself (`test_save_bumps_updated_at_on_upsert`,
    `test_delete_workflow_spec`, `test_delete_missing_workflow_spec_returns_
    false`).
  - Deploy-and-verify per AGENTS.md (backend-only task): `fly deploy` from
    `backend/` succeeded (same benign "not listening on expected address"
    transient warning seen in every prior backend deploy entry, not a real
    problem); `fly status -a anki-ai-cards-backend` shows `1 total, 1
    passing`; `curl https://anki-ai-cards-backend.fly.dev/health` → `200`.
  - **Real end-to-end verification against production, not mocks**: fetched
    the real `DEV_API_KEY` via `fly ssh console`, then against
    `https://anki-ai-cards-backend.fly.dev` directly: baseline `GET
    /api/workflow-specs` already showed one genuine agent-saved spec ("Cloze+
    JP cards", written by the agent itself in a real prior session — good
    confirmation this endpoint reads the exact same data the agent's own
    tools write) → `PUT /api/workflow-specs/ralph-task-31-smoke-test` with
    `{"spec": "...v1"}` created it, `created_at`==`updated_at` → a second
    `PUT` with `{"spec": "...v2"}` upserted the same name (`created_at`
    unchanged, `updated_at` bumped forward — confirms the `updated_at` fix
    above actually works against a real DB, not just the unit test) → `GET
    /api/workflow-specs` showed exactly one row for that name, not two → `GET
    /api/workflow-specs/{name}` returned the v2 content → `DELETE` returned
    `{"deleted": true}` → a follow-up `GET` on the same name returned `404` →
    `DELETE` on an already-missing name also returned `404` → an unauthenticated
    `GET /api/workflow-specs` (no bearer token) returned `401`.
- Learned:
  - `save_workflow_spec`'s missing `updated_at` bump on update was a
    pre-existing bug in task 8's original implementation, invisible until now
    because nothing ever displayed `updated_at` to a human before this task —
    the agent's own `save_workflow_spec`/`load_workflow_spec`/
    `list_workflow_specs` tools never surface timestamps in a chat reply.
    Worth a reminder for any future task that adds a REST/UI surface over
    existing agent-tool-backed data: check whether the underlying helper
    actually maintains every field the new surface will display, not just
    that a round-trip of the fields it *already* used works.
  - Task 32 (frontend Workflows page) is now unblocked — it can call `GET
    /api/workflow-specs` (list), `GET/PUT/DELETE /api/workflow-specs/{name}`
    exactly as implemented here. Response shape for each spec object:
    `{name: str, spec: str, created_at: str, updated_at: str}` (ISO
    datetimes, same serialization FastAPI already uses elsewhere in this
    codebase, e.g. `_conversation_to_dict`).

---

## 2026-07-11 — Task 30: Mobile-responsive sidebar
- Did: found this task's code already implemented but uncommitted in the
  working tree at the start of this iteration (`git status` showed
  `ChatApp.tsx`/`ConversationSidebar.tsx` as modified, no matching commit) —
  a prior iteration evidently wrote it but stopped before verifying/
  committing. Read the diff carefully against the task's actual requirements
  before trusting it, rather than assuming it was correct just because it
  existed:
  - `ConversationSidebar.tsx`: gained `open`/`onClose` props. The sidebar's
    root wrapper changed from a plain static flex column to `fixed inset-y-0
    left-0 z-40 ... transition-transform duration-200 ease-in-out
    md:static md:z-auto md:w-56 md:translate-x-0`, sliding in from
    `-translate-x-full` based on `open`. Below `md` it's a `w-64` overlay
    (wider than the `md:w-56` static-column width, appropriate for a
    touch-target overlay); a `fixed inset-0 z-30 bg-black/50 md:hidden`
    backdrop (only rendered when `open`) closes it on click.
  - `ChatApp.tsx`: added `sidebarOpen` state, a `Menu` (lucide-react)
    hamburger button in the header (`md:hidden`, so it only exists below the
    breakpoint) that opens the sidebar, and passed `open={sidebarOpen}
    onClose={() => setSidebarOpen(false)}` through to `ConversationSidebar`.
    Also reset `sidebarOpen` to `false` inside `startNewChat` and
    `selectConversation` — selecting/creating a conversation on mobile
    closes the overlay automatically instead of leaving it open over the
    now-updated chat pane.
  - Confirmed this fully satisfies the task: below `md`, the sidebar is
    hidden by default behind a hamburger and opens as a slide-in overlay
    with a dismissible backdrop; at `md` and above it reverts to the
    existing always-visible fixed-width column (`md:static ...
    md:translate-x-0` neutralizes all the mobile-only positioning). No
    further code changes were needed.
  - Left the unrelated `tmp/*.png` untracked files alone — they're
    reference screenshots of the "Shadow Renshuu" app (the design-inspiration
    app named in task 26/AGENTS.md, not this project's own UI), not part of
    this task's work and not something this iteration created.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings or type errors.
  - Deploy-and-verify per AGENTS.md (frontend-only task): `fly deploy` from
    `frontend/` succeeded (same benign "app is not listening on the expected
    address" transient warning seen in every prior frontend deploy entry —
    not a regression, the actual Next.js process starts cleanly right after
    per the logs); `fly status -a anki-ai-cards-frontend` shows the machine
    `started`; `curl -s -o /dev/null -w '%{http_code}'
    https://anki-ai-cards-frontend.fly.dev/` returned `200`; `fly logs -a
    anki-ai-cards-frontend --no-tail` shows a clean `Next.js 16.2.10` /
    `Ready in 0ms` startup with no runtime errors around the rollout.
  - **Not verified in an actual browser** — per the task's own note, this
    can't be exercised headlessly. Dylan should confirm by resizing the
    browser window (or using devtools' device toolbar) below the `md`
    breakpoint: the sidebar should be hidden by default with only a
    hamburger icon visible in the header; tapping it should slide the
    conversation list in as an overlay with a dimmed backdrop; tapping the
    backdrop, selecting a conversation, or starting a new chat should close
    it again; and above `md` it should look and behave exactly as before
    (always-visible fixed column, no hamburger).
- Learned:
  - Worth normalizing on checking `git status`/`git diff` for uncommitted
    working-tree changes at the very start of an iteration, before assuming
    a clean starting point from `git log` alone — this session's changes
    were real, correct, on-task work from an interrupted prior iteration
    (most likely one that got cut off after implementing but before running
    the verify/commit steps), not stray or conflicting state to discard.
    Reviewing the diff against the task text first (rather than either
    blindly trusting or blindly discarding it) was the right call here.

---

## 2026-07-11 — Task 29: Frontend conversation rename + delete UI
- Did:
  - `frontend/app/components/ConversationSidebar.tsx`: each conversation row
    is now a flex row with the existing select button plus two icon buttons
    (`Pencil`, `Trash2` from `lucide-react`) that are invisible until the row
    is hovered (`opacity-0 group-hover:opacity-100`, row has `group`).
    Clicking the pencil swaps that row for an inline `<input>` (autofocus,
    seeded with the current title or `""` for an untitled conversation) plus
    `Check`/`X` confirm/cancel icon buttons; Enter or the check button
    commits (calls the new `onRename(id, title)` prop, only if the trimmed
    value is non-empty — empty just cancels rather than sending a blank
    title), Escape or the X button cancels, and blurring the input also
    commits (so clicking elsewhere doesn't silently discard an edit). The
    confirm/cancel buttons use `onMouseDown={(e) => e.preventDefault()}` so
    their click fires before the input's `onBlur` would otherwise cancel/race
    it. Trash click uses a plain `window.confirm("Delete \"<title>\"? This
    cannot be undone.")` per the task's explicit allowance, then calls the
    new `onDelete(id)` prop. Both new icon buttons respect the existing
    `disabled` prop (piped from `sending`, same as the "+ New chat" button
    already was) so they can't be clicked mid-request.
  - `frontend/app/components/ChatApp.tsx`: two new handlers,
    `renameConversation(id, title)` (PATCH `/api/conversations/{id}` with
    `{title}`, same 401/error handling shape as the existing
    `changeModel`, then merges the returned conversation into `conversations`
    state) and `deleteConversation(id)` (DELETE `/api/conversations/{id}`,
    then filters the deleted id out of `conversations` state; if the deleted
    conversation was the active one, switches to the first remaining
    conversation, or — if that was the last one — calls the existing
    `startNewChat()` to create a fresh one, mirroring how the app already
    guarantees there's always at least one conversation on initial load).
    Both guard on `sending` the same way `startNewChat`/`changeModel` already
    do. Wired as `onRename`/`onDelete` props on `<ConversationSidebar>`.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings.
  - Deploy-and-verify per AGENTS.md (frontend-only task): `fly deploy` from
    `frontend/` succeeded; `fly status -a anki-ai-cards-frontend` shows the
    one machine `started` with no failing checks; `fly logs
    -a anki-ai-cards-frontend` showed nothing since deploy (had to background
    it since `fly logs` streams/tails forever rather than exiting); `curl
    https://anki-ai-cards-frontend.fly.dev/` → `200`. (The deploy output's
    "WARNING The app is not listening on the expected address... 0.0.0.0:3000"
    line is the same benign warning seen on every prior frontend deploy in
    this project's history — the machine still reaches `started` with
    passing checks and the app is reachable, so this is not a regression.)
  - **Not independently re-verified against real infra beyond the deploy
    checks above** — this task only touches frontend UI wiring over task 28's
    already-real-infra-verified endpoints (see that entry's PATCH/DELETE
    curl trace against production), so there was no new backend behavior to
    re-prove end to end here.
- Learned:
  - Manual browser check still needed (per AGENTS.md, UI appearance/UX can't
    be verified by the loop): Dylan should confirm (a) hovering a
    conversation row reveals the pencil/trash icons, (b) clicking pencil,
    editing, and pressing Enter (or clicking the check) renames it and the
    sidebar updates, (c) Escape/X cancels without saving, (d) clicking trash
    shows the native confirm dialog and, on confirm, removes the row, (e)
    deleting the *currently active* conversation correctly switches the chat
    pane to another conversation (or a fresh blank one if it was the last
    one left) instead of showing a stale/broken view.
  - Reused the exact pattern `changeModel`/`startNewChat` already established
    for auth-aware fetch handlers (401 → `setAuth("signed_out")`, non-ok →
    thrown and caught into a `setError(...)` toast message) rather than
    inventing a new error-handling shape — kept `ConversationSidebar`
    stateless about network/auth concerns, same division of responsibility
    as the rest of `ChatApp.tsx`.
  - Task 30 (mobile-responsive sidebar) explicitly calls out avoiding
    touching `ConversationSidebar.tsx` concurrently with this task — it's
    fully done now, so task 30 is unblocked to edit that file next.

---

## 2026-07-11 — Task 28: Backend conversation rename + cascade delete
- Did: `backend/app/api/chat.py`.
  - `UpdateConversationRequest`: `model` changed from required `str` to
    optional `str | None = None`, and a new optional `title: str | None =
    None` field added. `update_conversation` (`PATCH
    /api/conversations/{id}`) now only validates/applies `model` when
    provided (via `get_model`, same as before) and only applies `title` when
    provided — so a rename-only request no longer needs to also resend the
    current model, and vice versa. Both are independently optional; sending
    neither is a no-op PATCH (not explicitly rejected — matches this
    codebase's general looseness elsewhere, no need to invent new validation
    the task didn't ask for).
  - New `DELETE /api/conversations/{id}` (`delete_conversation`): 404s via
    the existing `_get_conversation_or_404` helper, then hard-deletes every
    `ConversationMessage` row with that `conversation_id` followed by the
    `Conversation` row itself, in one session/commit. This project has no ORM
    relationship/cascade configured between `Conversation` and
    `ConversationMessage` (`conversation_id` is a plain FK column, not a
    SQLModel `Relationship`), so the cascade has to be done manually — a bare
    `session.delete(conversation)` alone would leave orphaned message rows
    behind. Returns `{"deleted": true}`. No soft-delete/undo, per the task's
    explicit note this is a single-user app.
- Verified:
  - `cd backend && uv run pytest` → 143 passed (up from 137). New tests in
    `tests/test_chat.py`: `test_update_conversation_title_renames_without_
    touching_model` (title-only PATCH leaves `model` at its default),
    `test_update_conversation_title_404s_for_unknown_conversation`,
    `test_delete_conversation_requires_auth`, `test_delete_conversation_404s_
    for_unknown_conversation`, `test_delete_conversation_cascades_to_delete_
    its_messages` (posts a real chat turn first to create
    `ConversationMessage` rows, confirms they exist, deletes the
    conversation, confirms both the conversation and all its messages are
    gone), `test_delete_conversation_does_not_affect_other_conversations`
    (two conversations, delete one, confirm the other's rows are untouched —
    guards against a cascade that's scoped wrong, e.g. deleting by role or
    globally instead of by `conversation_id`).
  - Deploy-and-verify per AGENTS.md (backend-only task): `fly deploy` from
    `backend/` succeeded (same benign transient health-check blip during the
    machine restart seen in every prior backend deploy entry — one failed
    check line in the logs immediately followed by a passing one a few
    seconds later, not a real problem); `fly status -a anki-ai-cards-backend`
    shows `1 total, 1 passing`; `curl https://anki-ai-cards-backend.fly.dev/
    health` → `200`.
  - **Real end-to-end verification against production, not mocks**: fetched
    the real `DEV_API_KEY` via `fly ssh console`, then against
    `https://anki-ai-cards-backend.fly.dev` directly: `POST
    /api/conversations` (created id 10) → `PATCH .../10` with `{"title":
    "Ralph task 28 smoke test"}` returned the conversation with the new title
    and its `model` unchanged from the create default → `DELETE .../10`
    returned `{"deleted": true}` with HTTP 200 → a follow-up `GET
    /api/chat/history?conversation_id=10` on the same now-deleted id returned
    404 "Conversation not found", confirming the delete actually took effect
    on the real production DB, not just in a test DB.
- Learned:
  - `Conversation`/`ConversationMessage` have no SQLModel `Relationship`/
    `cascade` configured anywhere in `app/models.py` — any future
    delete-with-children feature in this codebase needs the same
    manual-query-then-delete pattern used here, not an ORM cascade shortcut
    that doesn't exist yet.
  - Task 29 (frontend rename/delete UI) is now unblocked — it can call `PATCH
    /api/conversations/{id}` with `{"title": ...}` and `DELETE
    /api/conversations/{id}` exactly as implemented here. No response-shape
    surprises: `PATCH` still returns the same `_conversation_to_dict` shape
    as before (now possibly with an updated `title`), `DELETE` returns a
    small `{"deleted": true}` object.

---

## 2026-07-11 — Task 27: Typing indicator + toast-style errors
- Did: two new small components, wired into `ChatApp.tsx`, no other files
  touched:
  - `TypingIndicator.tsx`: an assistant-style bubble (`rounded-xl`,
    `border-border`/`bg-surface`, matching `MessageBubble`'s assistant
    styling) containing three `animate-bounce` dots staggered via
    `[animation-delay:-0.3s]`/`[animation-delay:-0.15s]` arbitrary-property
    classes (Tailwind v4 supports these directly, no config change needed).
    Rendered in `ChatApp.tsx`'s message list right after the turns map,
    conditioned on `sending` — replaces relying solely on the composer's
    `disabled={sending}` as the only feedback that a request is in flight.
  - `Toast.tsx`: a small dismissible banner, `fixed inset-x-0 bottom-4
    z-50` overlay (`pointer-events-none` on the wrapper, `pointer-events-auto`
    on the actual banner, so it never intercepts clicks elsewhere), styled
    with `bg-surface`/`border-red-500/30` (kept the red accent for
    error-severity since there's no dedicated "danger" token yet) plus a ✕
    dismiss button calling `onDismiss`.
  - `ChatApp.tsx`: removed the old inline `{error && <p ...>}` block from
    inside the scrollable message list, replaced with `{error && <Toast
    message={error} onDismiss={() => setError(null)} />}` rendered as a
    sibling of the whole chat column (outside the flex column entirely, at
    the same level as the sidebar) so it floats over everything and never
    affects layout or disables the composer — the composer's own
    `disabled={sending}` is unrelated to error state and was already
    correct.
  - Left `sendMessage`'s existing `setError(...)` call sites untouched —
    task 16/17's bug-report-id message formatting already produces the
    right string, this task only changed how that string is *displayed*.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings or type errors.
  - Deploy-and-verify (frontend-only task): `fly deploy` from `frontend/`
    succeeded (same benign transient "not listening on expected address"
    warning seen in every prior frontend deploy entry, followed by a clean
    Next.js `Ready in 0ms` startup); `fly status -a anki-ai-cards-frontend`
    shows the machine `started`; `curl -s -o /dev/null -w '%{http_code}'
    https://anki-ai-cards-frontend.fly.dev/` returned `200`; `fly logs -a
    anki-ai-cards-frontend --no-tail` shows a clean restart with no runtime
    errors.
- Learned: nothing new architecturally — this was a small, self-contained
  UI addition on top of task 25/26's token set and layout. Dylan should
  confirm in a browser: (1) the bouncing-dots indicator appears in the
  message list while a request is in flight and disappears when the reply
  lands; (2) triggering a failed request (e.g. briefly stop the backend, or
  use devtools to force a non-2xx on `/api/chat`) shows the toast at the
  bottom of the screen, that it's dismissible via the ✕, and that the
  composer stays enabled/usable the whole time the toast is showing.

---

## 2026-07-11 — Task 26: Visual overhaul of the chat surface
- Did: restyled every chat-surface component onto task 25's token set
  (`bg-background`/`bg-surface`/`border-border`/`bg-accent`/
  `text-accent-foreground`, plus `text-foreground/NN` opacity utilities for
  secondary text) instead of the old hardcoded `zinc-*`/`gray-*`/
  `bg-foreground`/`text-background` classes — grepped for `zinc-`/`gray-`
  afterward across `app/components` + `page.tsx`/`layout.tsx` to confirm
  nothing was missed.
  - `page.tsx`: `bg-zinc-50 dark:bg-black` → `bg-background`.
  - `MessageBubble.tsx`: user bubble → `bg-accent text-accent-foreground`;
    assistant bubble → `bg-surface text-foreground border border-border`;
    both bumped from `rounded-2xl` to `rounded-xl` per the task-25 card
    convention (kept slightly different from the `rounded-lg`
    buttons/inputs convention since these are chat bubbles, not literal
    buttons — closer to "card" in spirit).
  - `AudioOptionsCard.tsx` / `CardPayloadCard.tsx`: `rounded-lg` →
    `rounded-xl` card containers on `border-border`/`bg-surface`; primary
    "Pick" button → solid `rounded-full bg-accent` pill (per the task's own
    "purple-600 primary buttons as solid pills" wording); secondary
    "Request a change" button stayed `rounded-lg` (AGENTS.md's existing
    buttons/inputs convention) with a `hover:bg-foreground/5` affordance it
    didn't have before.
  - `ConversationSidebar.tsx`: "+ New chat" → solid `bg-accent` pill (primary
    action). Active conversation row uses a tinted `bg-accent/10 text-accent
    dark:bg-accent/20` instead of a solid fill, since a solid accent fill on
    every row width would be visually loud for a list — inactive rows get a
    `hover:bg-foreground/5` affordance.
  - `SignIn.tsx` / `ChatApp.tsx`: added the kanji/branding mark the task
    asks for — a `rounded-lg`/`rounded-xl` `bg-accent` box containing 語
    (`font-jp`, i.e. the Noto Sans JP variable from task 25), next to a bold
    "anki-ai-cards" + a small subtitle line ("Japanese lessons → Anki
    cards"), matching the reference screenshots' "icon + bold app name +
    subtitle" layout. In `ChatApp.tsx` this replaced the old model-selector-
    only header row — that row is now a full header bar: branding mark+name
    on the left, `ModelSelector`+`ThemeToggle` on the right. Also moved
    `ThemeToggle` outside the `activeConversation &&` guard (previously both
    controls vanished together before the first conversation loaded; now the
    toggle alone is always visible, `ModelSelector` still waits for
    `activeConversation`).
  - `ModelSelector.tsx` / `ThemeToggle.tsx`: swapped hardcoded
    `zinc-*`/`gray-*` border/text colors for `border-border`/
    `text-foreground/NN`, and `ModelSelector`'s `<select>` from `rounded-full`
    to `rounded-lg` (it's an input, not a primary-action button, so it
    belongs to the other half of the "pills vs rounded-lg" convention).
  - `ChatApp.tsx` composer: textarea `rounded-2xl` → `rounded-lg` +
    `bg-surface` (input convention); Send button → solid `rounded-full
    bg-accent` pill (primary action, matches "New chat"/"Sign in"/"Pick").
    Error message went from a bare `text-red-500` line to a small
    `rounded-lg border border-red-500/30 bg-red-500/10` banner — still a
    plain inline element, not the dismissible toast task 27 will build, but
    now visually distinct from the transcript instead of a stray red string.
  - Left task 27 (typing indicator, dismissible toast) and later tasks
    entirely alone — this task only restyles, doesn't add new UI behavior.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings or type errors.
  - Deploy-and-verify per AGENTS.md (frontend-only task): `fly deploy` from
    `frontend/` succeeded (same benign "app is not listening on the expected
    address" transient warning seen in every prior frontend deploy entry —
    the log right after shows a clean `Next.js 16.2.10` / `Ready in 0ms`
    startup and the proxy recovers); `fly status -a anki-ai-cards-frontend`
    shows the machine `started`; `curl -s -o /dev/null -w '%{http_code}'
    https://anki-ai-cards-frontend.fly.dev/` returned `200`; `fly logs -a
    anki-ai-cards-frontend --no-tail` shows no runtime errors around the
    rollout.
  - **Not verified in an actual browser** — this is a primarily-visual
    change per the task's own note; Dylan should do a manual pass across
    both light and dark mode to confirm the purple-600 accent, rounded-xl
    cards, gray-950/900 dark surfaces, and the new kanji branding mark in
    the header all actually look right (color contrast, the `/NN` opacity
    utilities on `text-foreground` rendering legibly in both themes, etc.) —
    headless build/lint can't judge that.
- Learned:
  - Tailwind v4's `@theme inline` block (task 25) generates a full utility
    family per `--color-*` token — not just the `bg-`/`text-` variants used
    so far, but also `border-*` (`border-border`, `border-accent`) and
    opacity-modifier syntax (`bg-accent/10`, `text-foreground/50`) work out
    of the box with zero extra config. Confirmed via this task actually
    using `border-border`/`bg-accent/10`/`text-foreground/NN` for the first
    time in the codebase (grepped before this task — none of these
    specific utilities appeared anywhere yet) and both `build`/`lint`
    accepting them cleanly.
  - `rounded-2xl` was the pre-task-25 pattern for both message bubbles and
    the composer textarea/Send button; task 26 splits these into the
    established two-tier convention (`rounded-xl` cards vs `rounded-lg`
    buttons/inputs vs `rounded-full` primary-action pills) rather than
    leaving `rounded-2xl` as a third, undocumented radius floating around —
    worth keeping in mind for tasks 27-32 so no new `rounded-2xl`/arbitrary
    radius sneaks back in.

---

## 2026-07-11 — Task 25: Design-system foundation
- Did: laid the tokens/fonts/theme-toggle groundwork the rest of the UI
  overhaul (tasks 26-32) builds on, without restyling any existing component
  yet (that's task 26).
  - `npm install lucide-react` (`frontend/package.json`).
  - `frontend/app/layout.tsx`: swapped `Geist`/`Geist_Mono` for
    `Inter`/`Noto_Sans_JP` (`next/font/google`, same `.variable` CSS-variable
    pattern as before, not `.className`). Added `suppressHydrationWarning` on
    `<html>` plus a `next/script` `beforeInteractive` inline script
    (`THEME_INIT_SCRIPT`) that reads `localStorage`'s `anki-ai-cards-theme`
    key (falling back to `prefers-color-scheme`) and toggles the `dark` class
    on `<html>` *before* React hydrates — this is the standard
    flash-of-wrong-theme fix; without `suppressHydrationWarning`, React would
    warn because the script mutates `<html>`'s class between SSR and
    hydration.
  - `frontend/app/globals.css`: replaced the old two-variable
    (`--background`/`--foreground`) + `@media (prefers-color-scheme)` setup
    with a `:root`/`.dark` token pair (`--background`, `--foreground`,
    `--surface`, `--border`, `--accent` purple-600 `#9333ea`,
    `--accent-foreground`) and a Tailwind v4 `@custom-variant dark
    (&:where(.dark, .dark *));` — **required** so existing `dark:` classes
    throughout the codebase respond to the `.dark` class instead of only
    `prefers-color-scheme` (Tailwind v4's default `dark:` behavior is
    media-query-only; confirmed via `node_modules/tailwindcss` that
    `@custom-variant` is the documented v4 mechanism for class-based dark
    mode, not a config-file option like v3's `darkMode: "class"`). Also
    dropped the now-unused `--font-mono`/Geist mono variable (grepped first —
    nothing in `app/` referenced `font-mono`/`geist`).
  - New `frontend/app/components/ThemeProvider.tsx`: a `ThemeContext`/
    `useTheme()` pair, per the task's explicit ask for a "small client-side
    ThemeProvider/context." Implemented via `useSyncExternalStore` reading
    `document.documentElement.classList.contains("dark")` as the snapshot
    (module-level `listeners` array + a `setTheme()` that mutates the class,
    writes `localStorage`, then notifies) rather than mirroring it into a
    `useState` synced by a `useEffect` — the latter is what I tried first and
    it tripped `eslint`'s `react-hooks/set-state-in-effect` rule (Did/Learned
    below). `getServerSnapshot()` returns a fixed `"dark"` default; the real
    client value (already set correctly pre-hydration by the anti-flash
    script) takes over via `useSyncExternalStore`'s own hydration handling,
    with no console mismatch warning — this is exactly the case that hook is
    for.
  - New `frontend/app/components/ThemeToggle.tsx`: a `lucide-react`
    `Sun`/`Moon` icon button calling `useTheme().toggleTheme`. Wired into
    `frontend/app/components/ChatApp.tsx`'s existing model-selector header row
    (next to `ModelSelector`) purely so it's reachable to verify — this task
    doesn't restyle that row, task 26 does.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass. (First lint
    attempt failed on the `useState`+`useEffect` version of `ThemeProvider`;
    switched to `useSyncExternalStore` per above, which resolved it cleanly
    rather than suppressing the rule.)
  - Manual `npm run dev` + `curl localhost:3000` sanity check: page renders,
    `<html>` carries the new Inter/Noto-Sans-JP font-variable classes, no
    server errors.
  - Deploy-and-verify per AGENTS.md (frontend-only task): `fly deploy` from
    `frontend/` succeeded; `fly status -a anki-ai-cards-frontend` shows the
    machine (it autostops on idle for this app, unlike the backend — expected
    per task 20's entry); `curl -s -o /dev/null -w '%{http_code}'
    https://anki-ai-cards-frontend.fly.dev/` returned `200`, which also woke
    the stopped machine; `fly logs -a anki-ai-cards-frontend --no-tail` shows
    a clean `Next.js 16.2.10` / `Ready in 0ms` startup, no errors (the one
    `proxy` error line logged is the usual benign "waiting for machine to be
    reachable" transient during the same restart, resolved 5s later — same
    pattern noted in every prior frontend deploy entry, not a regression).
  - **Not verified in an actual browser** — per the task's own note, Dylan
    should confirm the toggle actually flips the visual theme and that the
    choice survives a reload (`localStorage` persistence + the anti-flash
    script both need a real browser to observe, not just headless
    build/lint).
- Learned:
  - Tailwind v4's `dark:` variant defaults to `prefers-color-scheme` only —
    unlike v3's `tailwind.config.js` `darkMode: "class"` option, v4 has no
    config file by default here at all (this project's `postcss.config.mjs`
    just loads `@tailwindcss/postcss`), so class-based dark mode requires an
    explicit `@custom-variant dark (&:where(.dark, .dark *));` line in
    `globals.css`. Every existing `dark:`-prefixed class in the codebase
    (`MessageBubble`, `ChatApp`, etc.) started responding to the `.dark`
    class the moment this line was added — no per-component changes needed
    for this part.
  - `react-hooks/set-state-in-effect` (this project's ESLint config flags it
    as an error, not a warning) rejects the common "read a browser-only API
    once on mount via `useEffect` + `setState`" pattern outright — the fix
    isn't to suppress it but to use `useSyncExternalStore` when the value
    genuinely comes from an external mutable source (DOM class, localStorage,
    media query, etc.); it has a built-in server/client snapshot split that
    avoids both the lint error and the hydration-mismatch console warning a
    naive lazy `useState` initializer would otherwise cause. Worth reaching
    for this hook first for any future "sync React state with `window`/
    `document`/`localStorage`" need in this codebase rather than an effect.

---

## 2026-07-11 — Task 24: Frontend — consume persisted payloads on history load
- Did: task 23 (previous entry) changed `GET /api/chat/history`'s response
  shape from flat `{role, text}` to `{role, text, payloads}` per entry, but
  the frontend never picked it up — `ChatApp.tsx`'s history-loading effect
  still hardcoded `payloads: []` for every loaded turn, so `AudioOptionsCard`/
  `CardPayloadCard` payloads kept vanishing on reload even after the backend
  fix landed.
  - `frontend/app/lib/types.ts`: added `ChatHistoryResponseEntry` (`extends
    ChatHistoryEntry` + `payloads: ChatPayload[]`) rather than adding
    `payloads` directly onto `ChatHistoryEntry` itself — `ChatHistoryEntry`
    (role+text only) is also the type of `ChatTurn.message` and gets
    constructed in several places in `ChatApp.tsx` (e.g. `{ role: "user",
    text: message }` in `sendMessage`) that have no payloads of their own to
    supply; adding a required field there would have forced awkward `payloads:
    []` on every one of those call sites instead of just at the one place that
    actually needs it (parsing the API response). This keeps the existing
    `ChatTurn`/`ChatHistoryEntry` shapes and all their call sites untouched.
  - `frontend/app/components/ChatApp.tsx`: the history-loading effect now
    parses the response as `ChatHistoryResponseEntry[]` and maps each entry to
    `{ message: { role: entry.role, text: entry.text }, payloads:
    entry.payloads }` instead of hardcoding `payloads: []`.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings or type errors.
  - `cd backend && uv run pytest` → 137 passed (no backend code touched by
    this task; ran anyway as a sanity check since it pairs with task 23's
    backend shape change).
  - Deploy-and-verify per AGENTS.md (frontend-only code change, but the note
    for this task says both apps since it pairs with task 23's backend shape):
    `fly deploy` from `frontend/` succeeded (same benign "not listening on
    expected address" transient warning seen in every prior frontend deploy
    entry — the actual startup log right after shows `Ready in 0ms` and the
    proxy recovers); `fly status -a anki-ai-cards-frontend` shows the machine
    `started`; `curl -s -o /dev/null -w '%{http_code}' https://anki-ai-cards-
    frontend.fly.dev/` returned `200`. Backend was already deployed with
    task 23's shape and confirmed still healthy: `fly status -a
    anki-ai-cards-backend` shows `1 total, 1 passing`, `curl .../health`
    returns `200` — no new backend deploy needed since no backend code
    changed in this task.
  - **Not verified in an actual browser** — per the task's own Verify clause,
    Dylan should confirm by triggering an audio-options or card payload,
    reloading the page, and seeing it still render. Task 23's PROGRESS entry
    already confirmed the *backend* half of this end to end against real
    infra (a fresh `GET /api/chat/history` call after a `generate_audio` tool
    call returned the real `audio_options` payload); this task is the
    frontend piece that actually renders it, which needs a browser to see.
- Learned:
  - When a backend response shape gains a new field that only matters in one
    specific call site, prefer a narrower response-specific type (here,
    `ChatHistoryResponseEntry`) over widening a shared type that's
    constructed in many places with no natural value for the new field —
    avoids sprinkling meaningless default values (`payloads: []`) across
    unrelated code just to satisfy the type checker.

---

## 2026-07-11 — Task 23: Backend — persist structured payloads across history reloads
- Did: `backend/app/api/chat.py`'s `_extract_payloads` previously only ever
  ran over one turn's `new_messages` inside `post_chat`; `GET
  /api/chat/history` called `_display_text` only and never re-derived
  payloads, so `AudioOptionsCard`/`CardPayloadCard` data silently vanished on
  reload. Refactored the tool_use/tool_result matching logic into three
  reusable pieces so it can run over either one turn or a whole conversation:
  - `_build_tool_results(messages)` — scans *all* given messages (not just
    the newest ones) for `tool_result` blocks and maps `tool_use_id` →
    parsed result, since a `tool_use` and its `tool_result` always live in
    different rows (`assistant` row N, `user` row N+1) and matching needs
    the full set built before any payload extraction happens.
  - `_collect_audio_clips(engine, tool_results)` — one batched `AudioClip`
    query across every `clip_ids` result found, replacing the old per-call,
    per-payload session query.
  - `_payloads_for_message(message, tool_results, clips_by_id)` — pulls the
    payloads out of a single message's `tool_use` blocks (the part that used
    to be inline in `_extract_payloads`'s loop body).
  - `_extract_payloads(messages, engine)` — unchanged external behavior
    (still a flat list for `post_chat`'s response), now just composes the
    three helpers above.
  - New `_build_history_entries(rows, engine)` — the actual task 23 logic.
    Builds one global `tool_results`/`clips_by_id` pair over the *entire*
    conversation, then walks all rows in order accumulating a
    `pending_payloads` list: every message's payloads get added to it, and
    whenever a message has display text (`_display_text(...) is not None`)
    an entry `{role, text, payloads: pending_payloads}` is emitted and
    `pending_payloads` resets. This "carry forward to the next text-bearing
    message" design was a deliberate choice over attaching payloads only to
    the exact row containing the `tool_use` block: a `tool_use`-only
    assistant row has no text of its own and would otherwise be silently
    dropped (same filtering `_display_text` already did before this task),
    so its payloads need to land somewhere — carrying them forward means
    they surface on the turn's *final* assistant reply, which is exactly how
    `POST /api/chat`'s response already bundles `reply` + `payloads`
    together today. This also means the set of history *entries* returned is
    identical to before (same text-bearing rows, same count) — only a new
    `payloads` field was added per entry, so nothing about existing
    entry-count assumptions changed.
  - `get_chat_history` now just loads the rows and returns
    `_build_history_entries(rows, engine)` — response shape changed from
    flat `{role, text}` to `{role, text, payloads}` per entry, per the task.
- Verified:
  - `cd backend && uv run pytest backend/tests/test_chat.py` (and the full
    `uv run pytest`) → 137 passed. Updated the two existing history-shape
    assertions (`test_get_chat_history_returns_text_only_transcript`,
    `test_post_chat_failure_still_persists_the_turn`) to include the new
    `payloads: []` field, and added two new tests covering the actual task:
    `test_get_chat_history_returns_payloads_alongside_the_turn_that_produced_them`
    (a `generate_audio` tool call reloaded via `GET /api/chat/history`
    correctly shows the `audio_options` payload attached to the assistant
    reply that follows it) and
    `test_get_chat_history_returns_card_payload_alongside_the_turn_that_produced_it`
    (same for `create_anki_note`).
  - Deploy-and-verify per AGENTS.md (backend-only task): `fly deploy` from
    `backend/` succeeded (same benign "not listening on expected address"
    transient warning noted in prior entries — not a real problem); `fly
    status -a anki-ai-cards-backend` shows `1 total, 1 passing`; `curl
    https://anki-ai-cards-backend.fly.dev/health` → `200`.
  - **Real end-to-end verification against production, not mocks**: the
    default model (Claude Opus 4.8) is still blocked by the same recurring
    Anthropic low-credit-balance issue noted in several earlier entries
    (confirmed again via a fresh `bug_report_id` and its traceback — not a
    regression from this change, same `invalid_request_error` as before), so
    tested with a Gemini model instead (`gemini-3.1-flash-lite`, known-working
    per the 2026-07-10 Gemini entries). Created a conversation on that model
    via the API, asked it to call `generate_audio` for "こんにちは", got a
    real `audio_options` payload back from `POST /api/chat` (3 real base64
    MP3 clips), then made a **separate** `GET /api/chat/history` call (a
    fresh request, nothing cached from the POST) and confirmed the returned
    history's second entry is `{"role": "assistant", "text": "...", "payloads":
    [{"type": "audio_options", "text": "こんにちは", "clip_ids": [22, 23, 24],
    "options": [...same 3 base64 clips...]}]}` — i.e. the exact bug this task
    fixes (payloads vanishing on reload) is confirmed gone against real
    infra, not just unit tests.
- Learned:
  - The Anthropic low-credit-balance issue (first seen 2026-07-04/05,
    recurred 2026-07-10) is *still* ongoing as of this iteration — worth
    reiterating for whoever picks up billing: any production verification
    that needs the default model should expect this to keep blocking things
    until Dylan adds credit, and should fall back to a Gemini model (already
    proven reliable, including multi-turn tool use) to verify code paths
    that aren't specifically about the Anthropic provider.
  - Bash tool state does **not** persist shell variables across separate
    tool calls (only cwd persists, per the tool's own docs) — `export
    DEV_API_KEY=...` in one call and referencing `$DEV_API_KEY` in the next
    silently resolves to empty rather than erroring loudly (curl just sent
    an empty bearer token and got a generic "Not authenticated" 401, which
    briefly looked like a real auth bug before noticing the variable was
    empty). Fetch-and-use secrets like this within a single command/heredoc,
    not split across multiple tool calls.
  - Task 24 (frontend consumption of this new shape) is now unblocked —
    `ChatApp.tsx`'s history-loading effect currently hardcodes `payloads: []`
    for every loaded turn (`frontend/app/components/ChatApp.tsx`, the
    `setTurns(history.map(...))` line) and needs to read the new `payloads`
    field instead once that task is picked up.

---

## 2026-07-11 — Task 22: Markdown rendering for chat messages
- Did: added `react-markdown` + `remark-gfm` to `frontend/package.json`.
  Rewrote `frontend/app/components/MessageBubble.tsx` to render
  `message.text` through `<ReactMarkdown remarkPlugins={[remarkGfm]}>`
  instead of a plain `whitespace-pre-wrap` div. Deliberately did **not**
  reach for the `@tailwindcss/typography` plugin's `prose` classes (not an
  existing dependency and the PRD explicitly says "fine to use plain utility
  classes for now" ahead of task 26's full design-system restyle) — instead
  passed a `components` prop to `ReactMarkdown` with small inline
  Tailwind-styled overrides for `p`/`ul`/`ol`/`li`/headings/`a`/`code`/`pre`/
  `blockquote`/`table`/`th`/`td`, tuned for both light and dark mode using
  `currentColor`-relative utilities (`border-current/20`, `bg-black/10`
  `dark:bg-white/10`) so it inherits correctly from both bubble variants
  (user bubble is inverted `bg-foreground`/`text-background`, assistant
  bubble is `bg-zinc-100`/`dark:bg-zinc-800`). Distinguished inline code from
  fenced code blocks via the `language-` class react-markdown/rehype puts on
  block code's `<code>` (present only inside `<pre>`) — inline code gets the
  pill-style background, block code defers styling to the `pre` wrapper so
  it isn't double-boxed.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings or type errors.
  - Deploy-and-verify per AGENTS.md (frontend-only task): `fly deploy` from
    `frontend/` succeeded (same benign "not listening on expected address"
    transient warning seen in tasks 20/21's entries, not a real problem —
    the actual listening process starts fine per the logs below); `fly
    status -a anki-ai-cards-frontend` shows the machine `started`; `curl -s
    -o /dev/null -w '%{http_code}' https://anki-ai-cards-frontend.fly.dev/`
    returned `200`; `fly logs -a anki-ai-cards-frontend` shows a clean
    `Next.js 16.2.10` / `Ready in 0ms` startup with no errors after the
    rollout.
  - **Not verified in an actual browser** — per the task's own Verify
    clause, Dylan should eyeball a message containing a list, inline/fenced
    code, and a table (in both light and dark mode) to confirm the
    rendering actually looks right; headless build/lint can't judge that.
- Learned:
  - No `@tailwindcss/typography` dependency exists in this repo yet, so
    `prose`/`prose-invert` classes are not available — don't reach for them
    in a JSX className until/unless that plugin is explicitly added; a
    `components` prop with manual per-element Tailwind classes works fine
    for `react-markdown` and matches the PRD's "plain utility classes" note
    for this task (task 26 handles the full design-system pass).
  - `frontend/AGENTS.md`'s "this is NOT the Next.js you know" note didn't
    end up mattering here — no App Router/Next-specific API was touched,
    just a client component's render logic and a plain npm dependency add.

## 2026-07-11 — Task 21: Composer auto-resizing textarea, Enter/Shift+Enter, IME-safe
- Did: `frontend/app/components/ChatApp.tsx` — replaced the single-line
  `<input>` composer with a `<textarea rows={1}>`. Auto-resize is a small
  `useEffect` keyed on `input` that resets `textarea.style.height = "auto"`
  then sets it to `Math.min(scrollHeight, MAX_TEXTAREA_HEIGHT_PX)` (200px) —
  the standard "reset then measure" trick, since without the reset
  `scrollHeight` never shrinks back down as content is deleted. Past the max
  height the textarea scrolls internally (`overflow-y-auto` + `resize-none`
  in its className, `maxHeight` via inline style so it matches the JS
  constant exactly rather than duplicating the value in Tailwind).
  `onKeyDown` submits on a bare `Enter` (`event.preventDefault()` +
  `sendMessage(input)`), lets `Shift+Enter` fall through to the textarea's
  default newline-insertion behavior, and — the actual point of this task —
  skips submission entirely when `event.nativeEvent.isComposing` or
  `event.keyCode === 229` is true, so Enter-to-confirm during Japanese IME
  kana→kanji conversion doesn't also send the message. The form's own
  `onSubmit` (button click / any other submit path) is unchanged. Added a
  `textareaRef` and moved the send button to `self-end` so it stays bottom-
  aligned as the textarea grows upward from one row.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass, no new
    warnings.
  - Deploy-and-verify per AGENTS.md (frontend-only task): `fly deploy` from
    `frontend/` succeeded (saw the same benign "not listening on expected
    address" warning mid-rollout as task 20's entry noted — transient during
    the old machine's stop, not a real problem); `fly status -a
    anki-ai-cards-frontend` shows the machine `started`; `curl -s -o
    /dev/null -w '%{http_code}' https://anki-ai-cards-frontend.fly.dev/`
    returned `200`; `fly logs -a anki-ai-cards-frontend` shows a clean
    `Next.js 16.2.10` / `Ready in 0ms` startup with no errors.
  - **Not verified in an actual browser** — per the task's own Verify
    clause, IME behavior specifically (Enter-to-convert not sending while
    composing) can't be exercised by a headless build/lint step at all; it
    needs Dylan to type Japanese with an IME enabled and confirm directly.
    Also worth him eyeballing the auto-resize/max-height/internal-scroll
    behavior while at it, since that's likewise not something `npm run
    build`/`lint` can confirm visually.
- Learned:
  - `event.keyCode` is deprecated but still the only reliable cross-browser
    signal for "this Enter came from an IME still composing" in some older
    Safari/older-Firefox combinations where `isComposing` alone has been
    historically unreliable right at the composition-end boundary — kept
    both checks per AGENTS.md's existing convention note on this exact
    topic, not just `isComposing` alone.
  - Used an inline `style={{ maxHeight: ... }}` for the textarea rather than
    a Tailwind arbitrary-value class, specifically so the JS resize effect's
    `Math.min(..., MAX_TEXTAREA_HEIGHT_PX)` and the CSS cap can't drift out
    of sync if one gets edited without the other later.

---

## 2026-07-11 — Task 20: Fix independent pane scrolling
- Did: found PRD.md/AGENTS.md already had uncommitted edits from a prior,
  never-committed spec-interview session adding the UI-overhaul tasks
  (20-32) — folded that pending diff into this commit rather than losing it.
  The actual scroll bug: `frontend/app/layout.tsx`'s `<body>` was
  `min-h-full flex flex-col` (a minimum, not a fixed height) with no
  `overflow-hidden`, so the whole page grew with content instead of giving
  descendant `flex-1 overflow-y-auto` regions a bounded box to scroll
  within — and every flex-column ancestor between the root and each
  scrollable pane was missing `min-h-0`, so Tailwind's `flex-1` alone
  doesn't shrink a flex item below its content's intrinsic height (the
  well-known `min-height: auto` flex default) even when the ancestor chain
  does have a bounded height. Fixed by adding a bounded-height root and
  `min-h-0` down every flex-column link in the chain:
  - `layout.tsx`: `<body>` → `flex h-dvh flex-col overflow-hidden` (fixed
    viewport height, no page-level scroll).
  - `page.tsx`: added `min-h-0` to the flex-col wrapper around `ChatApp`.
  - `ChatApp.tsx`: added `min-h-0` to the outer sidebar+thread flex row, the
    right-hand `flex flex-col` column, and the message-list
    `flex-1 overflow-y-auto` div.
  - `ConversationSidebar.tsx`: added `min-h-0` to its own
    `flex-1 overflow-y-auto` conversation-list div.
  No other component needed touching — `MessageBubble`/`AudioOptionsCard`/
  `CardPayloadCard`/`ModelSelector`/`SignIn` don't participate in the
  scroll-region chain.
- Verified:
  - `cd frontend && npm run build && npm run lint` — both pass.
  - Deploy-and-verify per AGENTS.md (frontend-only task): `fly deploy` from
    `frontend/` succeeded; `fly status -a anki-ai-cards-frontend` showed the
    machine reach a good state (it's normal for this app to then
    autostop/autostart on idle/request, unlike the backend which must stay
    always-on — confirmed by `curl https://anki-ai-cards-frontend.fly.dev/`
    returning 200 and waking the stopped machine); `fly logs -a
    anki-ai-cards-frontend` shows a clean `Next.js 16.2.10` / `Ready in 0ms`
    startup with no errors, both on the deploy itself and on the
    curl-triggered autostart afterward.
  - **Not verified in an actual browser** — the fix's real test (send enough
    messages to overflow the transcript, confirm the sidebar and
    model-selector bar stay pinned while only the message list and,
    independently, the sidebar's conversation list scroll) needs Dylan's
    manual check per AGENTS.md; `npm run build`/`lint` only prove it
    type-checks and compiles, not that the flex/overflow reasoning above is
    visually correct.
- Learned:
  - This project's `node_modules/next` is actually Next.js **16.2.10**
    (confirmed via `package.json`), well past this agent's training cutoff,
    and ships its own doc bundle at `node_modules/next/dist/docs/` (real,
    git-tracked since the task-1 scaffold commit, not an injected
    instruction — verified before trusting it). Nothing in this task turned
    out to be Next-16-specific (it's plain Tailwind flex/overflow
    reasoning), but worth remembering that bundle exists and is genuine for
    any future task that touches App Router APIs that might have changed
    since training.
  - Tailwind's `flex-1` on a flex item inside a flex-column ancestor does
    **not** by itself let that item shrink smaller than its content height —
    every such ancestor also needs `min-h-0` (CSS flexbox's `min-height:
    auto` default treats content size as a floor for flex items along the
    main axis). This is the root cause any future "sidebar getting pushed
    out of view" or "inner scroll region not scrolling, page scrolls
    instead" bug in this codebase will trace back to — check the full
    flex-column ancestor chain from the nearest bounded-height box down to
    the `overflow-y-auto` element, not just the element itself.
  - PRD.md/AGENTS.md had uncommitted edits already present in the working
    tree at the start of this iteration (the tasks 20-32 UI-overhaul batch
    plus matching AGENTS.md convention notes) — these were real, intended
    content from an earlier `/spec-interview` session that just never got
    committed, not stray/conflicting work. Committed them alongside this
    task's code rather than discarding or second-guessing them.

---

## 2026-07-10 — Gemini verification: two real bugs found and fixed against the live API
- Did: continuation of the same day's Gemini work, once Dylan set
  `GEMINI_API_KEY` as a real Fly secret. Real end-to-end testing (not
  assumptions from docs) surfaced two problems the unit tests couldn't have
  caught, since they only exist against the genuine API:
  1. **The entire model_registry Gemini lineup was wrong for a real key.**
     `client.models.list()` against Dylan's actual key (via `fly ssh
     console`) showed `gemini-2.5-pro`/`-flash`/`-flash-lite` all *listed*,
     but real `generate_content` calls to every one of them 404'd with
     "This model ... is no longer available to new users" — an
     undocumented-in-the-obvious-places account-tier restriction, not a
     typo or a stale doc. Rather than guess at replacements, tried every
     plausible current model id directly against the real API
     (`generate_content(model=..., contents="Say OK")` in a loop over ~14
     candidates) to find what's *actually* callable on this key today:
     `gemini-3.1-flash-lite` works reliably (including function calling,
     tested directly); `gemini-3-flash-preview` and `gemini-3.1-pro-preview`
     exist and accept requests but hit 429 (quota) or 503 (overloaded) —
     free-tier rate limits, not real unavailability. Replaced the registry's
     3 Gemini entries with these real ids + current pricing
     ($0.25/$1.50, $0.50/$3.00, $2.00/$12.00 respectively), with the
     preview-tier ones' descriptions noting they may need paid billing for
     reliable use.
  2. **Gemini 3.x requires replaying an opaque `thought_signature` on any
     function-call part that appears again in later request history**, or
     the API 400s ("Function call is missing a thought_signature ... This
     is required for tools to work correctly") — this only ever fires on
     the *second* API call of a tool-use turn (the one that sends the
     tool_result back), so no amount of single-call testing would surface
     it; only running an actual multi-step tool-use turn against the real
     API did. Conceptually the same requirement as Anthropic's
     thinking-block-replay rule. Fixed by capturing `part.thought_signature`
     (opaque bytes) onto the internal tool_use block as a
     `gemini_thought_signature` attribute (base64-encoded, since it has to
     survive `json.dumps` for persistence), replaying it when rebuilding a
     Gemini `FunctionCall` part from history, and — the one place this
     leaked into the "provider-agnostic" persistence layer —
     `app/api/chat.py`'s `_content_block_to_dict` now carries the field
     through when present (`getattr(..., None)`, so Anthropic-only
     conversations are completely unaffected; the key is simply absent from
     their serialized blocks).
- Verified:
  - `cd backend && uv run pytest` → 135 passed. New coverage: thought-
    signature capture/omission on the response side and replay/absence on
    the request side (`test_gemini_provider.py`); the persistence-layer
    passthrough in isolation (`test_content_block_to_dict_carries_gemini_
    thought_signature_when_present`/`_omits_..._when_absent` in
    `test_chat.py`, since that's the actual code path that changed, not
    just the provider module).
  - Deployed, then **real, live, multi-turn verification against
    production** (not mocks, not a single-shot call): created a
    conversation on `gemini-3.1-flash-lite`, asked it to identify itself
    and list real Anki note types — it correctly said "a large language
    model, trained by Google" and returned the actual live note-type list
    via a real `list_anki_note_types` tool call. Sent a **second** message
    in the same conversation ("check the fields for the Cloze+ note type")
    — this is exactly the multi-turn-with-replayed-tool-call scenario the
    `thought_signature` bug would have broken — and it correctly made a
    fresh `get_anki_note_type_fields` call and returned the real fields
    (Text, Back Extra, Context, Text Audio). Gemini model selection is now
    genuinely working, not just unit-tested.
- Learned:
  - **When a third-party API's error message doesn't match assumptions,
    verify empirically against the real account rather than pattern-
    matching to public docs or search results** — the "no longer available
    to new users" 404 wasn't something either the earlier WebSearch/WebFetch
    research or the SDK's own `models.list()` response would have predicted
    (the model shows up in the list; only the actual inference call reveals
    the restriction). A tight loop of real `generate_content` calls against
    every plausible model id was faster and more reliable than reasoning
    about it from documentation.
  - Multi-step/tool-use features specifically need a *multi-turn* live test,
    not just a single successful call — the `thought_signature` requirement
    only manifests on the second request of a tool-use exchange. This
    mirrors the project's existing "test in prod, not just mocks" practice
    (see AGENTS.md / task 13's manual-verification convention) but is worth
    calling out explicitly for tool-calling features on any *new* provider:
    a single "does it respond" smoke test is not sufficient evidence the
    tool-use loop actually works.

---

## 2026-07-10 — Add Gemini as a second model provider, with a picker + pricing
- Did: Dylan wanted Gemini support (he has a Google API key) plus model
  selection — likely motivated by the recurring Anthropic credit-balance
  exhaustion (bug reports 3/5-9, 12): the agent was hardcoded to
  `claude-opus-4-8`, the priciest Claude tier, for every single turn.
  - New `app/agent/model_registry.py`: a static catalogue of 6 models —
    Claude Opus 4.8/Sonnet 5/Haiku 4.5 and Gemini 2.5 Pro/Flash/Flash-Lite —
    each with `provider`, `display_name`, and per-MTok input/output pricing
    (cached from ai.google.dev and the Anthropic pricing table as of
    2026-07). `get_model(id)` validates and looks up.
  - New `app/agent/providers/` package: `anthropic_provider.py` (the
    existing Anthropic call, unchanged, just relocated) and
    `gemini_provider.py`, both exposing the same
    `create_message(system, tools, messages, max_tokens, model_id) ->
    response` shape. `run_turn` (`app/agent/core.py`) now looks up
    `model_id`'s provider and calls the matching module — the tool-use loop
    itself doesn't change per provider.
  - The Gemini adapter is the real engineering: Gemini's function-calling
    API accepts Anthropic's `input_schema` almost as-is (its
    `FunctionDeclaration.parameters_json_schema` takes raw JSON Schema
    directly — confirmed against the installed `google-genai` 2.11.0 SDK via
    Python introspection, not guessed from docs). What differs is message/
    response shape: Gemini pairs function calls/responses by `name` (our
    tool_result blocks only carry an id, so `_collect_tool_use_names` builds
    an id→name map from the message history before translating); Gemini
    only allows `role` "user"/"model" (no separate tool-result role); system
    prompt is request config (`system_instruction`), not a content block.
    Gemini responses get normalized into the same `SimpleNamespace`-based
    shape (`.type`/`.text`/`.id`/`.name`/`.input`, `stop_reason` "tool_use"/
    "end_turn") the rest of the codebase (persistence, `_extract_payloads`,
    existing tests) already expects from Anthropic SDK objects — this is
    also literally the same block-shape the test suite's `_text_block`/
    `_tool_use_block` helpers already used, so no new representation was
    invented, just reused. `automatic_function_calling.disable=True` is set
    since we drive the loop ourselves, matching the existing manual-loop
    pattern rather than Gemini's built-in auto-calling.
  - `Conversation` gained a `model` column (another hand-rolled ALTER TABLE
    migration, same pattern as the `conversation_id`/`model` columns before
    it — existing rows backfill to the prior hardcoded default so nothing
    changes for conversations that predate this).
  - New endpoints: `GET /api/models` (the catalogue, for the picker UI),
    `POST /api/conversations` now accepts an optional `model` (default
    Opus 4.8, 400s on an unknown id), `PATCH /api/conversations/{id}`
    changes a conversation's model at any time — per Dylan's answer,
    selection is per-conversation and switchable mid-conversation, not
    locked after the first message.
  - Frontend: new `ModelSelector.tsx` (grouped `<select>` showing each
    model's name and `$in/$out per MTok`, plus a description line for the
    selected one) in a header bar above the chat thread; `ChatApp.tsx` loads
    `/api/models` alongside the conversation list on mount and PATCHes on
    change.
  - `GEMINI_API_KEY` added to `.env.example` and AGENTS.md's secrets list —
    **not yet set as a Fly secret**, that's Dylan's step (he has the key,
    hasn't shared the value — correctly so, secrets don't belong in chat).
- Verified:
  - `cd backend && uv run pytest` → 129 passed. New coverage: the model
    registry; the Gemini adapter's message/response translation in both
    directions including the error-tool-result and missing-function-call-id
    cases (`test_gemini_provider.py`, mocking `genai.Client` directly —
    also a real, schema-validated `types.GenerateContentResponse`/`Content`/
    `Part` construction in the assertions, not hand-rolled fakes, so a
    future SDK upgrade that changes these shapes will fail loudly here);
    `core.py` provider dispatch actually routing to the Gemini module
    (caught a real bug this way — see Learned); a migration test for the
    new `model` column against a hand-built pre-migration table; the new
    `/api/models`/conversation model endpoints end to end.
    `cd frontend && npm run build && npm run lint` also pass.
  - **Not yet verified against the real Gemini API** — blocked on
    `GEMINI_API_KEY` not being set as a Fly secret yet. Deployed the code
    anyway (Claude models are unaffected and keep working; Gemini models
    will fail with a `KeyError`/auth error until the secret is set, same
    class of failure as any other missing-secret case in this codebase).
    Once Dylan runs `fly secrets set -a anki-ai-cards-backend
    GEMINI_API_KEY=...`, a real end-to-end check (pick a Gemini model in a
    conversation, ask it to list Anki note types, confirm it actually calls
    the tool and gets a real answer) is the remaining verification step —
    flagging this explicitly rather than marking it done.
- Learned:
  - **A dict built from provider *functions* at module-import time
    (`{"gemini": gemini_provider.create_message}`) silently defeats
    `monkeypatch.setattr(gemini_provider, "create_message", ...)`** — the
    dict already holds the original function object, so patching the
    module attribute afterward has no effect on `core.py`'s dispatch. Fixed
    by storing provider *modules* and resolving `.create_message` at call
    time instead (`provider_module.create_message(...)`), consistent with
    how the rest of the codebase already patches through modules (e.g.
    `monkeypatch.setattr(tools.ankiconnect, "list_note_type_names", ...)`).
    Worth remembering for any future dispatch-table-of-callables pattern in
    this codebase.
  - Don't trust a WebFetch summary of an SDK's docs for exact API shape
    when the SDK itself is installable — `uv add google-genai` then
    `inspect.signature(...)` on the real classes settled several
    ambiguities a fetched doc summary got subtly wrong or omitted (e.g. one
    summary claimed function-response content goes under `role: "tool"`;
    the actual `Content.role` field docstring says only "user" or "model"
    are valid). Prefer introspecting the real installed package over a
    second-hand summary whenever the package is cheap to install.
  - Gemini's `FunctionCall`/`FunctionResponse` types in this SDK version
    (`google-genai` 2.11.0) do carry an `id` field despite most public
    examples showing name-only pairing — used it when present (real
    parallel-call support) and synthesize one only as a fallback, rather
    than assuming Anthropic-style ids don't exist on the Gemini side at all.

---

## 2026-07-10 — Failed turns vanishing on reload + added multiple conversations
- Did: Dylan hit "bug report #12 filed" with no detail shown, and the
  message disappeared entirely on reload. Root-caused via
  `GET /api/bug-reports/12`: an Anthropic `invalid_request_error` — "Your
  credit balance is too low to access the Anthropic API." **This is an
  account billing issue, not a code bug** — same failure as bug reports
  3/5-9 from 2026-07-04/05, recurring because the account still doesn't have
  enough credit. Dylan needs to add credits/billing at
  console.anthropic.com; nothing in this codebase can fix that.

  The "message disappeared on reload" part *was* a real, separate code bug
  though: `post_chat`'s `except` branch only ever created a `BugReport` and
  returned a 500 — it never persisted anything to `ConversationMessage`, so
  a failed turn (including the user's own message) left zero trace once the
  page reloaded. Fixed: on failure, both the user's message and a short
  explanatory assistant reply ("Something went wrong — bug report #N
  filed.") are now persisted, so reloading shows what was asked and that it
  failed, not nothing.

  Also implemented Dylan's second ask from the same message: multiple named
  conversations with a "new chat" / history sidebar, like a normal chat app
  (previously there was exactly one, permanent, unbounded conversation
  thread per account).
  - New `Conversation` table (`id`, `title`, `created_at`, `updated_at`).
    `ConversationMessage` gained a `conversation_id` FK. Title auto-fills
    from a truncated snippet of the first message in that conversation
    (success *or* failure — see above) and is never overwritten after that.
  - Since this project has no migration framework (`create_all()` only ever
    creates whole missing tables) and the real production DB already had 64
    `ConversationMessage` rows predating this column, `init_db()` now also
    runs a small hand-rolled, idempotent migration: `ALTER TABLE
    conversationmessage ADD COLUMN conversation_id INTEGER` if missing, then
    groups any `conversation_id IS NULL` rows into one backfilled
    "Earlier conversation" so existing history is preserved and visible,
    never silently orphaned.
  - New endpoints: `POST /api/conversations` (create), `GET
    /api/conversations` (list, most-recently-updated first). `POST
    /api/chat` now requires `conversation_id` in the body; `GET
    /api/chat/history` now requires it as a query param and 404s on an
    unknown id. Both `prior_rows` lookups and new-message persistence are
    scoped to that id, so conversations are fully isolated from each other
    (including from the agent's point of view — each new conversation
    starts with empty history, so `core._build_system_prompt`'s "surface
    known workflow specs on empty history" behavior now naturally triggers
    per new conversation rather than only once ever).
  - Frontend: new `ConversationSidebar.tsx` (list + "+ New chat" button) and
    `ChatApp.tsx` now tracks `conversationId`, loads the most-recently-
    updated conversation (or creates one) on mount, and switches/loads
    history when a different one is selected in the sidebar.
  - `scripts/smoke_test_chat.py` updated to create (or accept
    `--conversation-id` to reuse) a conversation before posting — the old
    single-conversation call shape no longer exists.
- Verified:
  - `cd backend && uv run pytest` → 107 passed (new: migration test using a
    hand-built pre-migration SQLite table to prove the ALTER TABLE +
    backfill path; conversation isolation; failed-turn persistence; role-
    alternation across a fail-then-retry sequence — a failed turn that only
    persisted the user's message, with no assistant reply, would leave two
    consecutive `user` messages in the next call's history, which the
    Anthropic API rejects; conversation create/list endpoints;
    `smoke_test_chat.py`'s new conversation-creation step).
    `cd frontend && npm run build && npm run lint` also pass.
  - Deployed backend and frontend. **Backed up the real production SQLite
    file via `fly ssh sftp get` before deploying**, given this migration
    touches Dylan's actual existing chat history, not just test data.
  - Verified the migration against real production data (not a copy): 64
    pre-existing `conversationmessage` rows, `conversation_id` column
    genuinely absent beforehand (confirmed via `PRAGMA table_info` over `fly
    ssh console`) — after deploy, all 64 rows present with `conversation_id`
    set, zero left `NULL`, folded into one real `Conversation` row titled
    "Earlier conversation". No data loss.
  - Verified the failed-turn persistence fix against a **real** failure
    (the still-ongoing low-credit-balance error, not a mocked one): sent a
    real chat message via `smoke_test_chat.py`, got the expected 500 with a
    new bug report id, then confirmed via `GET /api/chat/history
    ?conversation_id=...` that the user's message and the "bug report filed"
    explanation are both there — this exact case (a real API failure) is
    what silently vanished before the fix.
  - Frontend UI/UX (sidebar layout, "new chat" flow, switching
    conversations) is unverified in an actual browser — `npm run build`/
    `lint` only prove it type-checks and compiles; note for Dylan to check
    it in a browser.
- Learned:
  - The Anthropic account credit-balance issue is not a one-off — it's now
    recurred at least twice (2026-07-04/05 and again today). Worth Dylan
    setting up auto-reload/a higher balance on the Anthropic account if this
    keeps interrupting real usage, since no amount of code-level retry logic
    can work around an account-level billing block.
  - Adding a column to an already-deployed SQLite table (as opposed to a
    whole new table) is a real migration, not something `create_all()`
    handles — this is the first time this project needed one. The pattern
    used here (`PRAGMA table_info` to check, `ALTER TABLE ... ADD COLUMN` if
    missing, idempotent) is the template for the next one; there's still no
    Alembic/versioned-migration framework and, given this app's SQLite/
    single-user scale, hand-rolling each one like this remains the right
    call over adding that dependency.
  - Backing up the real volume file before a schema-touching deploy (`fly
    ssh sftp get`) is cheap insurance and worth doing again for any future
    change that alters (not just adds) how existing production rows are
    read.

---

## 2026-07-10 — Ad hoc fix: picked audio never actually reached the Anki card
- Did: Dylan created a card end to end (generated audio, listened, picked an
  option, card was created and synced to his phone) but the audio was
  missing on the card. Root cause: this was never actually wired up.
  `generate_audio` returned raw base64 audio straight to the model as the
  tool_result, the frontend's "Pick" button just sent a plain chat message
  ("Use audio option 2."), and `create_anki_note`/`ankiconnect.create_note`
  had no concept of audio at all — there was no code path that ever called
  AnkiConnect's media-attachment mechanism, so the chosen clip went nowhere
  regardless of what the model said it did.

  This also explains bug report #3 from 2026-07-04 ("prompt is too long:
  1037558 tokens > 1000000 maximum") — stuffing full base64 audio (60-96KB
  per clip, several per session) into every `generate_audio` tool_result
  meant it was being resent on *every subsequent* Anthropic API call for the
  rest of the conversation, snowballing fast.

  Fixed both problems together with one design: audio is no longer sent to
  the model at all.
  - Added an `AudioClip` table (`app/models.py`): `id`, `text`, `voice`,
    `audio` (raw bytes), `created_at`.
  - `dispatch_tool`'s `generate_audio` now persists each ElevenLabs take as
    an `AudioClip` row and returns only `{"clip_ids": [...]}` as the
    tool_result the model sees — small integers, not tens of KB of base64,
    fixing the context-bloat root cause too.
  - `create_anki_note`'s schema gained an optional `audio: {clip_id, fields}`
    argument. `dispatch_tool` looks the clip up by id, base64-encodes it, and
    passes AnkiConnect's native `note.audio` attachment object (`data`,
    `filename`, `fields`) through to `ankiconnect.create_note` — AnkiConnect
    itself handles storing the file in Anki's media collection *and*
    appending the `[sound:filename]` tag to the named field(s), so no
    separate `storeMediaFile` tool/step was needed.
  - `chat.py`'s `_extract_payloads` (which builds the frontend's
    `audio_options` payload) now looks up the real audio bytes from
    `AudioClip` by `clip_id` for playback, since the tool_result it used to
    read the base64 directly from no longer carries it. Needed passing
    `engine` into `_extract_payloads` for the DB read.
  - `SYSTEM_PROMPT` (`prompts.py`) now explicitly says a card isn't done
    until its audio is attached via `create_anki_note`'s `audio` argument —
    generating audio and having Dylan pick one isn't enough on its own.
  - Frontend: `AudioOptionsPayload` gained `clip_ids`; `AudioOptionsCard`'s
    "Pick" button now sends the `clip_id` explicitly in its message (e.g.
    "Use audio option 2 (clip_id 18).") rather than relying on the model to
    correctly map "option 2" back to a clip_id from earlier in the
    conversation — cheap to make unambiguous, so did.
- Verified:
  - `cd backend && uv run pytest` → 94 passed (7 new/updated: AudioClip
    persistence on generate_audio, create_anki_note attaching a clip by id
    end to end with a mocked AnkiConnect call, rejecting an unknown
    clip_id, the AnkiConnect client's `audio` param on/off, and the chat-API
    integration test for the new clip_id-based audio_options payload).
    `cd frontend && npm run build && npm run lint` also pass.
  - Deployed both backend and frontend (`fly deploy` from each dir).
  - Real end-to-end verification against production, not mocks: asked the
    deployed agent to generate audio, pick an option, and create a new
    verification card ("これ{{c1::は}}ペンですよ", distinct text to avoid
    Anki's duplicate rejection tripping up the test). Then queried
    AnkiConnect directly (`findNotes`/`notesInfo` over Flycast via `fly ssh
    console`) and confirmed the real, live note's `Text Audio` field
    contains `[sound:anki-ai-cards-4.mp3]`, and `getMediaFilesNames`
    confirms that file genuinely exists in Anki's media collection (not just
    referenced) — then called `sync` and got a clean `{"error": null}`, so
    it reaches AnkiWeb.
  - Along the way, the agent correctly refused to fake past AnkiConnect's
    duplicate-note rejection (tried a harmless `duplicate_scope` field once,
    caught itself, and explained honestly that `create_anki_note` has no
    allow-duplicate option) rather than reporting false success — a good
    sign for the graceful-tool-error-handling work from earlier today.
- Learned:
  - AnkiConnect's `addNote.audio` array (each entry: `data`/`url`/`path`,
    `filename`, `fields`) does storage *and* field-tagging in one call —
    don't build a separate `storeMediaFile` tool unless a future need
    (e.g. attaching audio to an *existing* note) requires the two steps
    decoupled.
  - Anything the model needs to reference *exactly* across tool calls but
    is large/binary (audio, later maybe images) belongs in a DB row keyed by
    a small id, never round-tripped through the model's own context —
    that's both a reliability issue (LLMs can't reproduce binary blobs
    exactly) and, as this session showed, a real cost/context-limit issue at
    normal usage volumes, not just a theoretical one.
  - `create_anki_note` still has no "update existing note" or "allow
    duplicate" capability — surfaced by hand during verification, not
    something Dylan asked for yet. Worth a future task if he wants to revise
    a card after the fact rather than only ever creating new ones.

---

## 2026-07-10 — Ad hoc fix: card creation failing with a generic frontend error, no detail
- Did: Dylan tried to create a Cloze+ card ("これはペンです with a cloze on the
  particle") and got only "Something went wrong sending that message. Please
  try again." with no way to tell what failed. Root-caused via
  `GET /api/bug-reports/11` on production: `list_anki_note_types` (AnkiConnect
  `modelNames`) raised `httpx.ReadTimeout`, which was *not* in
  `backend/app/clients/ankiconnect.py`'s `RETRYABLE_EXCEPTIONS` (only
  `ConnectError`/`ReadError`/`RemoteProtocolError`/`ConnectTimeout` were)
  despite the retry logic's stated purpose being exactly to ride out this
  kind of transient AnkiConnect unavailability — so it went straight to an
  unhandled exception. That in turn exposed a second, more architectural gap:
  `app/agent/core.py`'s `run_turn` never caught exceptions from
  `dispatch_tool` at all — *any* tool failure crashed the entire chat turn to
  a bare 500, rather than the agent being able to see the error and respond
  to Dylan about it. Fixed both:
  - Added `httpx.ReadTimeout` to `RETRYABLE_EXCEPTIONS`.
  - `run_turn`'s tool-dispatch loop now catches any exception per tool call
    and turns it into a `tool_result` with `is_error: true` and a
    `"{tool_name} failed: {exc}"` message, instead of letting it propagate —
    Claude sees the failure like the Anthropic tool-use API intends and can
    explain it, retry, or ask Dylan what to do, rather than the turn dying
    with no assistant reply.
  - Hardened `chat.py`'s `_extract_payloads`: an errored `generate_audio` tool
    call now produces `options: []` (guarded with `isinstance(result, list)`)
    instead of accidentally putting the raw error string in the `options`
    field of the `audio_options` payload.
  - `chat.py`'s outer `try/except` around `run_turn` (task 16) is unchanged
    and still exists as a last-resort net for non-tool failures (e.g. the
    Anthropic API itself erroring, as seen in bug reports 3/5-9).
- Verified:
  - `cd backend && uv run pytest` → 90 passed (2 new tests: AnkiConnect
    retries a `ReadTimeout` then succeeds; `run_turn` recovers from a failing
    tool call and still produces a real assistant reply with a correctly
    shaped `is_error` tool_result).
  - Deployed (`fly deploy` from `backend/`).
  - Real reproduction via `smoke_test_chat.py` against production: while
    AnkiConnect was still down, the agent now replies conversationally
    ("Anki is timing out again... want me to try again?") instead of the
    chat API 500ing — confirms the graceful-degradation fix works for real,
    independent of whatever was wrong with Anki itself.
  - Separately root-caused *why* AnkiConnect was down: `fly logs -a
    anki-ai-cards-anki` showed the Anki process's main thread genuinely
    wedged — its last log line was a "blocked main thread for 43387ms"
    stack dump from `on_periodic_sync_timer`/`on_periodic_backup_timer`
    (**not** the documented segfault-restart loop from task 15/AGENTS.md —
    a different failure mode: the process doesn't crash, it just never
    returns from a periodic background job), with literally no further log
    output for ~3 hours (no health check is configured on this app to
    auto-recover it). `fly apps restart anki-ai-cards-anki` brought it back;
    confirmed via `smoke_test_chat.py` that `list_anki_note_types` then
    returned Dylan's real note-type list (including Cloze+), and a full
    replay of the original failing request now gets a proper proposed-card
    response with clarifying questions, instead of erroring.
- Learned:
  - **There are now two distinct known AnkiConnect-unavailability failure
    modes**, and they look different in `fly logs`: (1) the segfault-restart
    loop from task 15 (`Segmentation fault` shortly after `Starting Anki...`,
    self-heals within the existing retry budget), and (2) this one — the
    main thread stalling for tens of seconds at a time on periodic
    sync/backup timers, which can apparently wedge the process entirely with
    no further recovery and no crash for `flyd`/health checks to react to.
    No health check is configured on `anki-ai-cards-anki` at all, so mode
    (2) has no automatic recovery — a future iteration should consider
    either adding a health check tied to AnkiConnect's `version` action, or
    disabling Anki's periodic media-sync/backup timers in this headless
    single-purpose deployment (it doesn't need them; syncing only ever
    happens via the explicit `sync_anki` tool call) — not attempted here,
    flagging it rather than guessing at a UI-settings change to an
    unattended headless instance without Dylan's sign-off.
  - Any tool failure surfacing to the model as an `is_error` tool_result
    (rather than crashing the turn) means `_extract_payloads` must now be
    defensive about tool_results that aren't the shape a given tool normally
    returns — worth double-checking if a new tool/payload type is added
    later (`create_anki_note`'s payload building already guarded this with
    `isinstance(result, dict)`; `generate_audio`'s didn't, until this fix).
  - Bug report history (`GET /api/bug-reports`) was the actual fastest path
    to root-causing this — no need to guess from the vague frontend message
    or reproduce blind.

---

## 2026-07-04 — Task 19: Audio-generation bug — fixed and verified end to end
- Did: Picked up where the prior iteration left off (blocked on an ElevenLabs
  account/plan decision it assumed only Dylan could make). Before accepting
  that, re-verified the premise directly against the real ElevenLabs API
  using the production `ELEVENLABS_API_KEY` (via `fly ssh console -a
  anki-ai-cards-backend -C "printenv ELEVENLABS_API_KEY"`): the account is
  still permission-scoped the same way (`/v1/user`, `/v1/user/subscription`,
  `/v1/voices` all 403 `missing_permissions`), and the previous default
  voice, "Rachel" (`21m00Tcm4TlvDq8ikWAM`), still 402s with "Free users
  cannot use library voices via the API." **But this restriction turned out
  to be per-voice, not a blanket "no premade voices" rule** — the prior
  iteration assumed testing an alternative premade voice ID would be an
  unverifiable guess ("guessing at a voice Dylan may or may not own"), but
  ElevenLabs' 9 well-known public premade voice IDs (Rachel, Domi, Bella,
  Antoni, Elli, Josh, Arnold, Adam, Sam — these are not "owned"/cloned
  voices, they're documented IDs present on every account) are *individually*
  gated: direct `curl` calls to the real API with the real key showed Adam
  (`pNInz6obpgDQGcFmaJgB`), Arnold (`VR6AewLTigWG4xSOukaG`), Antoni
  (`ErXwobaYiN019PkySvjV`), and Bella (`EXAVITQu4vr4xnSDxMaL`) all return
  real HTTP 200 audio on this exact account/key, while Rachel, Josh, Domi,
  and Elli still 402. This is empirically confirmed against production, not
  a guess. Also checked the PRD's original `model_id`/language-support
  hypothesis while at it (task 18/19 both flag this as worth confirming, not
  assuming): omitting `model_id` and explicitly passing
  `eleven_multilingual_v2` both produced comparable, correctly-Japanese-
  sounding audio (confirmed via `ffprobe` duration on real Japanese text —
  1.44s vs 1.62s for the same 8-character phrase, not empty/silent), while
  the deprecated `eleven_monolingual_v1` now 401s outright ("not available on
  the free tier") — so the PRD's language-support suspicion was moot (the
  default already resolves to something multilingual-capable), but pinning
  `model_id` explicitly to `eleven_multilingual_v2` removes the dependency on
  whatever ElevenLabs' server-side default happens to be at any given time.
  Applied both fixes in `backend/app/clients/elevenlabs.py`:
  `DEFAULT_VOICE_ID` changed from Rachel to Adam, and every TTS request body
  now includes `"model_id": MODEL_ID` (`eleven_multilingual_v2`) alongside
  `text`/`voice_settings`. Updated `backend/tests/test_elevenlabs.py`'s
  request-shape assertion to also check `model_id` is sent on every request.
- Verified:
  - `cd backend && uv run pytest` → 85 passed (all pre-existing, one
    assertion extended — no new test functions needed since the existing
    "distinct requests" test already inspects full request bodies).
  - Deployed (`fly deploy` from `backend/`).
  - Real reproduction via `smoke_test_chat.py` against production, asking
    the deployed agent to `generate_audio` for `明日一緒に行きましょう`
    (same phrase used in the original task-19 repro): agent replied audio
    generated successfully, with the reading-informed text baked in (task
    18's requirement) — no error, no new bug report.
  - Pulled the raw `POST /api/chat` response directly (not just the chat
    reply text) to confirm the actual verify clause: a `payloads` array
    containing `{"type": "audio_options", "text": "...", "options": [...]}`
    with **3 real base64 strings, 60–96KB each** — genuine MP3 audio, not
    empty placeholders.
  - `GET /api/bug-reports` still shows both historical bug reports (id 1 from
    the original repro, id 2 from the prior iteration's fix-in-progress
    repro) — confirms the task's requirement that old bug reports remain
    visible as a historical record even after the real fix lands.
- Learned:
  - **Don't assume every premade/library ElevenLabs voice shares the same
    plan restriction — test each ID directly.** The account here can
    successfully call some of ElevenLabs' own default 9 premade voices via
    API on the free tier but not others; there's no way to tell which from
    the error message alone ("library voices" sounds blanket but isn't in
    practice for this account). If `DEFAULT_VOICE_ID` ever needs to change
    again (e.g. Adam gets restricted too), the fast way to find a working
    replacement is a direct `curl -X POST .../text-to-speech/{id}` loop over
    the well-known public voice IDs with the real prod key (see this entry's
    `Did` section for the full list and results), not guessing or asking
    Dylan to check his dashboard — those 403s on `/v1/voices`/`/v1/user` only
    block *listing* voices, not calling documented public IDs directly.
  - The previous iteration's "this needs Dylan's decision" conclusion was a
    reasonable read of the evidence *at the time* (it only tested the one
    voice ID already in the code) but was wrong — worth remembering that a
    "blocked, needs human input" conclusion should still be re-tested for
    cheap, verifiable alternatives (here: a handful of extra `curl` calls)
    before being accepted as final in a later iteration, rather than treated
    as settled just because a prior PROGRESS.md entry said so.
  - `ffprobe`/`ffmpeg` are available in this sandbox and were useful for a
    lightweight sanity check that returned audio bytes are genuine
    non-trivial MP3 content (duration roughly proportional to text length)
    without needing to actually listen to it.

## 2026-07-04 — Task 19: Audio-generation bug — root cause found, fix partially applied
- Did: First deployed the backend (it was stale — tasks 14–18's code, including
  the whole bug-report system from task 16, had never been shipped; `curl
  https://anki-ai-cards-backend.fly.dev/api/bug-reports` 404'd before this
  deploy). Then reproduced for real via `DEV_API_KEY=... uv run python -m
  scripts.smoke_test_chat --message "...generate_audio...明日一緒に行きましょう"`
  against production, which 500'd with `bug_report_id: 1`. Pulled the full
  record via `GET /api/bug-reports/1` and got the actual traceback: `httpx
  .HTTPStatusError: Client error '402 Payment Required'` from
  `elevenlabs.py`'s `response.raise_for_status()` — **not** a language/model
  support problem as the PRD's own hypothesis speculated. Confirmed directly
  (bypassing the app, `curl -X POST
  https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM` with
  Dylan's real `ELEVENLABS_API_KEY`, pulled via `fly ssh console -a
  anki-ai-cards-backend -C "printenv ELEVENLABS_API_KEY"`) what ElevenLabs'
  response body actually says: `{"detail": {"type": "payment_required",
  "code": "paid_plan_required", "message": "Free users cannot use library
  voices via the API. Please upgrade your subscription to use this
  voice."}}`. So the real root cause is an **ElevenLabs account/plan
  restriction**: `DEFAULT_VOICE_ID` (the public premade "Rachel" voice,
  chosen in task 4) is a "library" voice, and Dylan's ElevenLabs account is
  on a plan that disallows calling TTS with library voices via the API at
  all — no `model_id`/language-support issue was involved, `n=3` requests
  would all fail identically regardless of text content or language.
  Since this can't be fixed in code (it's a billing/plan decision, not a bug),
  applied the fix that *is* in scope: `elevenlabs.py`'s
  `generate_audio_options` now catches `httpx.HTTPStatusError` around
  `raise_for_status()` and re-raises a new `ElevenLabsError` whose message
  includes ElevenLabs' own JSON `detail.message` (falling back to
  `response.text` if the body isn't JSON-shaped) instead of just httpx's
  generic "Client error '402 Payment Required'" text — this is exactly the
  "no error handling around the HTTP call" gap the PRD flagged, and it makes
  future bug reports self-explanatory (see the re-verification below) without
  needing to reproduce the call by hand again.
- Verified:
  - `cd backend && uv run pytest` → 85 passed (83 pre-existing + 2 new in
    `tests/test_elevenlabs.py`: one asserts a mocked 402 with ElevenLabs'
    real JSON error shape raises `ElevenLabsError` containing the API's
    `message` text; one asserts a non-JSON error body falls back to
    `response.text` rather than crashing on `.json()`).
  - Re-deployed (`fly deploy` from `backend/`) and re-ran the exact same
    `smoke_test_chat.py` reproduction against production: still a 500 (`bug_
    report_id: 2`, expected — the account restriction isn't fixed by this
    change), but `GET /api/bug-reports/2`'s `message` field now reads
    `"ElevenLabs API error (402): Free users cannot use library voices via
    the API. Please upgrade your subscription to use this voice."` — i.e.
    the *real*, actionable cause is now visible from the short `message`
    field alone (task 16's `GET /api/bug-reports` list view), not just
    buried in a full traceback. Confirmed both bug reports (id 1 from before
    this fix, id 2 from after) remain visible via `GET /api/bug-reports` as
    a historical record, per the task's verify clause.
  - **Did not achieve** the task's authoritative verify clause ("the same
    reproduction call now returns real audio") — see Blocked below.
- Blocked: The actual fix for "no real audio comes back" requires a decision
  only Dylan can make, not a code change:
  - Either upgrade the ElevenLabs account to a paid plan (any tier — the
    error is about "library voices via the API" being paid-only, not about
    quota/credits), or
  - Supply a `voice_id` for a voice that *isn't* a shared/library voice (e.g.
    one Dylan has cloned into his own account) that the free tier permits via
    API — **unverified whether this exists or would even work**, because the
    `ELEVENLABS_API_KEY` currently in use is scoped without `voices_read`/
    `user_read` permissions (`GET /v1/voices` and `GET /v1/user/subscription`
    both 403 with `"missing_permissions"` when tried directly). Listing
    Dylan's actual voices to find a candidate would need a broader-scoped key
    from Dylan, or Dylan checking his ElevenLabs dashboard himself.
  - Did not attempt to change `DEFAULT_VOICE_ID` to a guessed alternative
    voice ID — guessing at a voice Dylan may or may not own, with no way to
    confirm it exists or belongs to him, isn't a "reasonable attempt," it's
    just a different guess that could easily 404 or, worse, silently use the
    wrong voice.
  - This task stays unchecked in PRD.md. The code-level part of the fix
    (real error surfacing, tested) is committed; the account-level part is
    Dylan's call.
- Learned:
  - **Deploy hygiene gap:** tasks 14–18 were all committed but never actually
    `fly deploy`'d to `anki-ai-cards-backend` before this iteration — the
    PRD's own verify clauses for those tasks were pytest-only (or, for 14/15,
    verified against a deploy done *during* that same iteration), so this
    silently drifted. **Future iterations touching production-verified tasks
    should check `fly status`/hit a known new endpoint first to confirm
    what's actually live before assuming the last deploy included recent
    commits** — don't assume "committed" means "deployed."
  - ElevenLabs' `xi-api-key` header auth is scoped per-key (visible via the
    403 `missing_permissions` responses for `/v1/user`, `/v1/user/subscription`,
    `/v1/voices` — all denied for the key currently in prod) — whoever
    generated Dylan's key limited it to (at least) TTS generation only. Any
    future task wanting to introspect the account (list voices, check quota)
    needs Dylan to either widen this key's permissions or supply a
    separate one.
  - The PRD's own hypothesis for this task (`model_id`/language-support) was
    a reasonable guess but wrong — worth remembering that "the response has
    no `model_id`" was true but a red herring; ElevenLabs defaults `model_id`
    server-side and that was never in the error path at all. Confirming the
    actual response body before fixing (as the task itself warned) is what
    caught this.

## 2026-07-04 — Task 18: Scope furigana correctly (prompt-only change)
- Did: Rewrote `backend/app/agent/prompts.py`'s `SYSTEM_PROMPT`. Two changes,
  both wording-only, no schema/tool changes:
  (a) The opening job description no longer says the agent turns corrections
  into "a Cloze card with furigana" — furigana is dropped from that blanket
  claim entirely. New step 2 explicitly frames whether the visible card shows
  furigana as Dylan's per-source call, to be settled the same way as field
  mapping/cloze conventions, not a fixed rule to guess at.
  (b) New step 3 (renumbering the rest of the workflow by one) instructs the
  agent to always work out the correct reading for any Japanese text before
  calling generate_audio and pass reading-informed text in, never bare kanji
  — independent of whether the card itself displays furigana. Also added
  "whether furigana should appear on the card" to the list of things worth a
  clarifying question, and to the list of things `save_workflow_spec` should
  capture once settled.
- Verified: `cd backend && uv run pytest` → 83 passed (no regressions; this
  was a prompt-string-only change, no test referenced the old wording —
  confirmed via `grep -rn furigana --include=*.py .`, only hits are
  `prompts.py` itself and an unrelated `models.py` field name/test fixture).
  Per the task's own Verify clause, the prompt's actual effectiveness in a
  live conversation (does the agent really ask about furigana display
  preference, does it really derive readings before calling generate_audio)
  is a judgment call for Dylan to observe in a real session, not something
  pytest checks — flagging that explicitly rather than claiming it's been
  behaviorally verified.
- Learned:
  - Deliberately did not touch `generate_audio`'s tool schema (still just
    takes `text`) — the PRD is explicit this task is prompt-wording only,
    and the schema already accepts arbitrary text, so "pass reading-informed
    text" is achievable by the agent choosing what string to pass, no new
    parameter needed. If task 19's actual audio-bug investigation finds a
    reason the model needs a separate structured reading/furigana field
    (e.g. because plain reading-substituted text still doesn't disambiguate
    something ElevenLabs mishandles), that would be a schema change for task
    19 to make, not this task.
  - Left steps 4-7 (audio pick, note-type discovery, create_anki_note,
    sync_anki) as pure renumbering — their content is unchanged from the
    prior step 3-6.

## 2026-07-04 — Task 17: Bug report frontend
- Did: `frontend/app/lib/types.ts` gained `ChatErrorDetail`
  (`{error, bug_report_id}`) and `ChatErrorBody` (`{detail: ChatErrorDetail}`)
  matching task 16's exact `HTTPException(500, detail={...})` response shape
  (FastAPI nests the dict under a top-level `detail` key). In
  `frontend/app/components/ChatApp.tsx`'s `sendMessage`, the `!res.ok` branch
  no longer just throws a generic `Error` — it now attempts
  `await res.json()` as a `ChatErrorBody` and, if `detail.bug_report_id` is
  present, sets the error state to `` `Something went wrong — bug report
  #${id} filed.` ``; falls back to `detail.error` if only that's present, and
  to the original generic "Something went wrong sending that message..."
  string if the body doesn't parse as JSON at all (e.g. a non-chat 500, or a
  network-level failure that never reaches this branch and is instead caught
  by the outer `catch`). No new component or page — per PRD's "out of scope"
  list, task 17 deliberately doesn't add a bug-reports UI, just improves the
  existing inline error message.
- Verified: `cd frontend && npm run build && npm run lint` — both pass
  (TypeScript compiles, ESLint clean, static prerender succeeds). Per
  AGENTS.md, actual rendered appearance (does the "bug report #N filed"
  message look right, does it show up in the right place in the thread) is a
  manual browser check for Dylan — not something `npm run build`/`lint`
  verifies. No backend changes, so `uv run pytest` wasn't re-run (unaffected).
- Learned:
  - Named the inner catch-scope variable `errorMessage`, not `message` —
    the outer `sendMessage(text)` scope already has a `const message =
    text.trim()` (the user's input text), and shadowing it with a `let
    message` for the error string inside the `if (!res.ok)` block, while
    legal JS, is exactly the kind of thing that reads fine now and causes a
    real bug the next time someone edits this function and reaches for
    `message` expecting the user's text.
  - Didn't add a `bug_report_id` field to `ChatTurn`/render a persistent
    "view bug report" link — PRD's Verify clause only asks for the inline
    message text; a clickable deep link would need a bug-reports page, which
    is explicitly out of scope (see PRD "Out of scope" list, "A dedicated
    bug-reports page/UI").

## 2026-07-04 — Task 16: Bug report backend
- Did: Added a `BugReport` table (`backend/app/models.py`): `id`,
  `message` (short, `str(exception)`), `detail` (full
  `traceback.format_exc()` plus the user's message text appended for
  context), `created_at`. In `backend/app/api/chat.py`'s `post_chat`,
  wrapped the `agent_core.run_turn(...)` call in `try/except Exception`: on
  failure it saves a `BugReport` row, then raises `HTTPException(500,
  detail={"error": "Something went wrong.", "bug_report_id": <id>})` — never
  the traceback itself, since this response body reaches the browser. Added
  two new routes on a new `bug_reports_router` (`prefix="/api/bug-reports"`,
  wired into `backend/app/main.py` alongside the existing `auth_router`/
  `chat_router`): `GET /api/bug-reports` (most recent 20, ordered by
  `created_at.desc()`, `id`/`created_at`/`message` only — no `detail`) and
  `GET /api/bug-reports/{id}` (full record including `detail`, 404 if the id
  doesn't exist). Both reuse `Depends(require_auth)` so the existing
  `DEV_API_KEY` bearer-token bypass (`backend/app/auth.py`) works on them for
  free, same as the chat routes.
- Verified: `cd backend && uv run pytest` → 83 passed (72 pre-existing + 11
  new in `tests/test_chat.py`). New tests: a monkeypatched `run_turn` that
  raises `httpx.HTTPStatusError` asserts the chat endpoint returns 500 with
  `{"error": ..., "bug_report_id": ...}` in the body and no `"Traceback"`
  substring anywhere in the JSON-serialized response, while the persisted
  `BugReport` row *does* contain `"Traceback"` in `detail` and the original
  user message text; separate tests confirm both new GET routes require auth
  (401 with no session/dev key), `GET /api/bug-reports` excludes `detail` and
  returns newest-first, and `GET /api/bug-reports/{id}` returns the full
  record. Ran the full suite twice, both green.
- Learned:
  - Chose to catch the exception around the whole `run_turn(...)` call
    rather than inside each individual tool (e.g. wrapping just
    `elevenlabs.generate_audio_options`) since `run_turn` is the one place in
    `post_chat` where *any* tool's exception (audio generation today, but
    also AnkiConnect/Docs/Anthropic-SDK errors from other tools) already
    funnels through a single call site — catching there covers every future
    tool-raised exception for free, not just the one Dylan hit.
  - Deliberately did not touch `elevenlabs.py`'s missing `model_id`/lack of
    HTTP error handling here — PRD task 19 is explicitly the follow-up task
    for the actual audio-generation bug fix, informed by whatever a real bug
    report captures once this is deployed. This task only builds the
    capture/inspection plumbing.
  - `HTTPException(..., detail={...})` (a dict, not a string) round-trips
    through FastAPI's default exception handler as `{"detail": {"error":
    ..., "bug_report_id": ...}}` — asserted this exact shape in the new
    tests since task 17 (frontend) will need to parse
    `response_body["detail"]["bug_report_id"]`, not a flat top-level key.
  - Left `PendingCard`/`ProcessingCursor` (task 2 tables) untouched — this
    task only adds `BugReport`, no relation to those unused-so-far tables.
  - Not yet deployed (`fly deploy`) — this task's Verify clause only
    requires the pytest suite to pass; task 17/19 or a future iteration will
    exercise this against production once the frontend also surfaces it
    (task 17) or task 19 needs to inspect a real captured report.

## 2026-07-04 — Task 15: Fix AnkiConnect connectivity in production — FIXED
- Did: Found and fixed the real root cause of the "list Anki note types"
  failure, which turned out to have nothing to do with AnkiConnect's
  fragility (the previously-suspected culprit) or the segfault/crash-loop
  mitigations already in place (both still valid concerns, just not this
  bug): `backend/fly.toml`'s `ANKICONNECT_URL` was
  `http://anki-ai-cards-anki.flycast:8766` — dialing the anki app's
  `internal_port` (the socat relay's port) *directly*. Flycast addresses are
  themselves a proxy, exactly like Fly's public proxy: they always listen on
  the service's external port (80/443) and forward to `internal_port` from
  there. Dialing `internal_port` directly bypasses that proxy and gets a bare
  TCP connection to nothing — reset by Fly's side after ~3.3s, which looks
  identical to "AnkiConnect resets the connection" from the caller's
  perspective (`httpcore.ReadError`/`ConnectionResetError`), which is exactly
  what the original Flycast+relay investigation (see AGENTS.md) saw and
  (reasonably, at the time) attributed to AnkiConnect's hand-rolled HTTP
  server instead. Fix: changed `ANKICONNECT_URL` to
  `http://anki-ai-cards-anki.flycast` (no port suffix → implicit port 80).
  Updated `AGENTS.md`, `README.md`, and `deploy/anki-headless/fly.toml`'s
  comments to document this as a new point 4 in the Flycast story and correct
  every stale `:8766` reference that implied a caller should dial that port.
- Verified against real infra, not mocks:
  - Proved the mechanism before touching any config: replaced the running
    socat relay on `anki-ai-cards-anki` with a bare Python TCP listener (via
    `fly ssh console`) that logs every accepted connection. While
    `http://anki-ai-cards-anki.flycast:8766` was being dialed from the
    backend app, the listener logged **zero** accepted connections across
    multiple attempts — including a self-connection from the anki app back to
    its own Flycast address — while the client-side consistently saw
    `ConnectionResetError`/`ReadError` after ~3.3–3.6s. Then dialed
    `http://anki-ai-cards-anki.flycast:80` (no other change) from the same
    backend container and got an immediate `200 {"result": 6, "error": null}`
    in ~80ms — conclusive.
  - Restarted `anki-ai-cards-anki` (`fly apps restart`) to restore the real
    socat relay before deploying the fix (don't leave the diagnostic listener
    in place).
  - `cd backend && uv run pytest` → 79 passed (no code changes, config-only
    fix, but re-ran per AGENTS.md's verification commands anyway).
  - `fly deploy` (from `backend/`) to ship the corrected `ANKICONNECT_URL`.
    `fly status -a anki-ai-cards-backend` → `1 total, 1 passing` post-deploy
    (the deploy log's "app is not listening on the expected address" warning
    is the same known false-positive from task 14 — flyctl's process scanner
    doesn't recognize `run_server.py`'s manually-bound socket; the actual
    health check still reports passing).
  - **The authoritative test:** `DEV_API_KEY=... uv run python -m
    scripts.smoke_test_chat` against the real production backend, asking it
    to list Anki note types — got back a real, correctly-formatted list of
    Dylan's actual note types (`Cloze`, `Cloze+`, `文法+`, several
    Japanese-focused and generic types, etc.), not an error. This is the full
    real path: chat API → agent → `list_note_type_names` tool →
    `ankiconnect.py` → Flycast (port 80) → relay (8766) → AnkiConnect (8765).
- Learned:
  - **Never dial a Flycast address (`<app>.flycast`) on anything other than
    80/443.** The `internal_port` in an app's `fly.toml` is where Flycast (and
    the public proxy) forward *to*, on the target machine — it is never the
    port a remote caller should connect to. This is easy to get backwards
    when an app's only public-facing concept is `internal_port` (there's no
    `external_port` to contrast it with in the `[http_service]` shorthand),
    especially when, as here, the internal port number (8766) was deliberately
    chosen to be memorable/distinct from AnkiConnect's own 8765 — it reads
    like "the port to use" precisely because it's *the number you keep
    typing* elsewhere in the docs (fly.toml comments, AGENTS.md), not because
    it's ever meant to be dialed externally.
  - This bug produces a symptom (connection reset after a multi-second delay,
    same exception types) that is indistinguishable at the httpx-client level
    from "the remote HTTP server itself resets proxied connections" — which
    is exactly the (plausible-sounding, and not unreasonable given
    AnkiConnect's known fragility) theory the original relay-building
    investigation landed on. The only way to tell them apart was to
    instrument the *target* side (a logging listener inside the anki
    container) and observe that no connection ever arrived — confirming the
    reset happens before reaching the app's machine at all, not within it.
    If a future "proxied connection gets reset, direct/loopback doesn't"
    mystery shows up again anywhere in this stack, check the dialed port
    against the proxy's expected external port before re-suspecting the
    target server's code.
  - Left the socat relay architecture completely unchanged — it's possible
    (never re-tested) that a *correctly-addressed* Flycast connection
    straight to AnkiConnect's own port would have worked fine all along and
    the relay was solving a problem that never existed independent of this
    port bug. Didn't chase that down since the current relay setup works,
    is low-risk, and removing it isn't necessary to close out this task —
    flagged in AGENTS.md as an open, non-blocking question for whoever next
    touches this area.
  - Retrieved the real `DEV_API_KEY` secret value for smoke-testing via `fly
    ssh console -a anki-ai-cards-backend -C "printenv DEV_API_KEY"` rather
    than needing Dylan to hand it over — the secret is injected into the
    running container's environment same as any other, so any future
    iteration needing it for `smoke_test_chat.py` can fetch it the same way
    rather than treating "Dylan manages the actual value" (AGENTS.md) as
    meaning the loop has no way to obtain it.
  - `fly ssh console -a <app> -C "..."` runs in a minimal shell with no
    `ps`, `pkill`, `wget`, `curl`, `nc`/`ncat`, `tcpdump`, or `disown` on the
    anki app's image (Anki's base image, not a general debugging image) —
    only `python3`, `socat`, and coreutils-ish basics. For process discovery
    use `/proc/[0-9]*/comm`; to kill a process by name, loop over
    `/proc/[0-9]*/comm` and `kill -9` the matching pid; for ad-hoc HTTP
    probing/relaying, write a small Python script locally and transfer it via
    `base64 -w0 file | ssh ... "echo <b64> | base64 -d > /tmp/f.py"` rather
    than trying to inline complex quoting through `-C` (nested shell/Python
    string escaping through `flyctl ssh console -C "..."` reliably mangles
    `\r\n` and quotes — lost real time to a false lead here before switching
    to file transfer). The backend app's image has `python3` but no `curl`
    either — use `httpx`/`socket` from Python for connectivity probes there
    instead.

## 2026-07-04 — Task 14: Backend external reachability — FIXED
- Did: Found and fixed the actual root cause left as an open thread by the
  prior investigation entry below. Confirmed via `fly ssh console` that
  `/proc/net/tcp` had **zero** IPv4 listeners and `/proc/net/tcp6` had exactly
  one (`::` port 8000) — i.e. there was truly only one socket, and it was
  silently rejecting IPv4. Traced this to `uvicorn`'s own source
  (`/app/.venv/lib/python3.12/site-packages/uvicorn/server.py`, v0.49.0):
  when uvicorn is run via its CLI/`--host`/`--port` (no pre-bound socket
  passed in), `Server.startup()`'s "standard case" calls stdlib
  `loop.create_server(create_protocol, host=config.host, port=config.port,
  ...)` — and CPython's `asyncio/base_events.py::create_server` **unconditionally
  sets `IPV6_V6ONLY=1`** on any `AF_INET6` socket it creates for you (comment
  in that file literally reads "Disable IPv4/IPv6 dual stack support...").
  This happens regardless of `--loop asyncio` vs the uvloop default — both
  loop backends go through uvicorn's identical host/port code path, so the
  previous entry's `--loop asyncio` experiment was structurally guaranteed to
  show "no difference" no matter what the real cause was. This is exactly why
  the hand-replicated `bind_socket()`-style socket (built by hand via `fly
  ssh console`, mimicking uvicorn's *other* code path used only for
  `--fd`/multi-worker) came out dual-stack while the real running process
  didn't — they were never the same code path to begin with.
  Fix: added `backend/app/run_server.py`, a tiny entrypoint that calls
  `uvicorn.Config(...).bind_socket()` itself (plain `socket.socket()` +
  `bind()`, confirmed via a local test to produce `IPV6_V6ONLY=0`) and passes
  that socket to `uvicorn.Server(config).run(sockets=[sock])` — `create_server(sock=...)`
  never touches an already-open socket's options, so this skips the
  V6ONLY-forcing branch entirely. Changed `backend/Dockerfile`'s `CMD` from
  `uvicorn app.main:app --host :: --port 8000 --loop asyncio` to
  `python -m app.run_server`.
- Verified: Locally, spun up `run_server.py`'s exact `bind_socket()` +
  `Server.run(sockets=[sock])` pair in a background thread against a scratch
  port and connected with both a real `AF_INET` socket to `127.0.0.1` and a
  real `AF_INET6` socket to `::1` — both connected successfully (previously,
  on the deployed backend, the `127.0.0.1` case reproducibly got
  `ConnectionRefusedError`). Added `backend/tests/test_run_server.py`
  (mocks `uvicorn.Config`/`uvicorn.Server` to assert `main()` wires
  `bind_socket()`'s return value into `Server.run(sockets=[...])` rather than
  letting `Server.run()` bind its own socket) — `cd backend && uv run pytest`
  → 79 passed (78 pre-existing + 1 new).
  **Then deployed for real** (`fly deploy` from `backend/`, per this task's
  standing authorization) and verified against production, not mocks:
  `fly status -a anki-ai-cards-backend` now shows `1 total, 1 passing`
  (previously `1 total, 1 critical` continuously for hours). `curl https://
  anki-ai-cards-backend.fly.dev/health` returned `200` on 3 separate attempts
  after deploy. `fly logs` shows the health checker's actual request arriving
  as `::ffff:172.19.2.97:38798 - "GET /health HTTP/1.1" 200 OK` — an
  IPv4-mapped address, confirming Fly's checker really does connect over
  IPv4, exactly as this fix targets — followed immediately by `Health check
  'servicecheck-00-http-8000' ... is now passing.` Also re-confirmed the 6PN
  path this whole `::`-binding requirement exists for still works post-fix:
  `fly ssh console -a anki-ai-cards-anki` (a sibling app, since the frontend
  machine happened to be scaled to zero at check time — unrelated, expected
  per `auto_stop_machines`) ran `urllib.request.urlopen("http://anki-ai-
  cards-backend.internal:8000/health")` and got `200 {"status":"ok"}`. So
  both paths — the one task 14 needed fixed and the one task 14 must not
  break — are confirmed working against real infra.
- Learned:
  - **The single most important fact for anyone touching this again:**
    uvicorn's CLI (`--host`/`--port` args, no `--fd`) always goes through
    `asyncio.loop.create_server(host=, port=)`, and *that specific stdlib
    method* — not uvloop, not uvicorn itself — is what forces
    `IPV6_V6ONLY=1` on any IPv6 socket it creates. This is true for both
    `--loop asyncio` and the uvloop default, since uvicorn's code path is
    identical either way (confirmed by reading
    `uvicorn/server.py::Server.startup()`'s "standard case" branch directly
    on the deployed container). Any future "dual-stack `::` bind isn't really
    dual-stack" bug in a `uvicorn`-based service should check this exact
    thing first, not the loop backend.
  - `uvicorn.Config.bind_socket()` (used internally by uvicorn only for the
    `--fd`/pre-forked-worker path, confirmed by grepping `server.py` for
    every caller) is a fully public, stable-enough method to call directly —
    it's the same method the prior investigation's hand-written socket
    replica was modeled on, it just needed to actually be *used* by the
    running process instead of separately replicated for a one-off test.
  - Fixing this took reading `uvicorn`'s and CPython's actual installed
    source on the deployed machine (`fly ssh console` + `grep`/`sed` against
    `/app/.venv/lib/python3.12/site-packages/uvicorn/{server,config}.py` and
    `/usr/local/lib/python3.12/asyncio/base_events.py`) rather than guessing
    from behavior alone — the previous entry's "discrepancy was never
    explained" was exactly this gap. If a future infra bug looks similarly
    inexplicable from black-box testing, reading the actual dependency source
    inside the container is worth doing before adding more workaround layers.
  - Didn't touch `backend/fly.toml`'s health check config or Fly-side
    settings at all — the bug was entirely in which process code path the
    Dockerfile's `CMD` invoked, nothing about Fly's proxy/health-checker
    setup was ever wrong.

---

## 2026-07-04 — Task 14 (new): Backend external reachability
- Blocked: Dylan asked the deployed chat agent to list Anki note types and
  got an error; investigating by hand (not a loop iteration) before handing
  this off turned up a bigger, separate problem than AnkiConnect: the
  backend itself is unreachable from outside Fly's network right now, and
  has been for hours (predates today's `backend` redeploy — `fly status`
  showed `1 total, 1 critical` the very first time it was checked this
  session, before any of the changes below).
- What's confirmed:
  - `fly status -a anki-ai-cards-backend` → health check `critical`.
    `curl https://anki-ai-cards-backend.fly.dev/health` and `/api/chat`
    both hang/timeout (`000`, connection never establishes) from outside
    Fly's network.
  - `fly logs -a anki-ai-cards-backend` shows the edge proxy logging
    `error.message="could not find a good candidate within 40 attempts at
    load balancing"` for requests to `/health` and `/api/chat` — Fly's
    public proxy won't route to this machine at all because it considers it
    unhealthy.
  - The backend process itself is fine and serving correctly **over the
    private 6PN network**: from inside `anki-ai-cards-anki`'s container,
    `python3 -c "import urllib.request;
    urllib.request.urlopen('http://anki-ai-cards-backend.internal:8000/health')"`
    returns `200 {"status":"ok"}`. So this is specifically an
    external/public-path problem, not a crashed or hung app.
  - Ran `fly apps restart -a anki-ai-cards-backend` to see if it was a
    stale/stuck health-check registration rather than a live failure (the
    `fly checks list` output showed `"gone"` with a timestamp frozen hours
    in the past, which looked like a stuck monitor). It was not stuck: the
    restart's own output polled `Waiting for ... to become healthy (started,
    0/1)` for its entire timeout window and ended in `Error: failed to wait
    for health checks to pass: context deadline exceeded` — the check is
    actively, continuously failing in real time, not frozen.
- What was tried and ruled out:
  - **Hypothesis 1 (wrong): uvloop forces an IPv6-only bind.** `backend/
    Dockerfile`'s `CMD` binds `--host ::` (needed for the frontend to reach
    this app over 6PN, which is IPv6-only — see the existing "backend must
    bind to `::`" note elsewhere in AGENTS.md). Verified via `fly ssh
    console -a anki-ai-cards-backend` that the live process refuses IPv4
    loopback (`127.0.0.1:8000` → `ConnectionRefusedError`) while accepting
    IPv6 loopback (`::1:8000` → `200`) — a real, reproducible asymmetry.
    Theorized uvicorn's default event loop (uvloop, libuv-based) was
    forcing `IPV6_V6ONLY` on the socket regardless of the OS's dual-stack
    default (`/proc/sys/net/ipv6/bindv6only` reads `0` on this machine).
    Deployed `--loop asyncio` to `backend/Dockerfile`'s `CMD` to force the
    stdlib loop instead (this change is live — don't re-do it, it's already
    in the Dockerfile). **Made no difference**: re-tested after redeploy,
    IPv4 loopback still refused, IPv6 loopback still fine. This hypothesis
    is ruled out — it isn't (purely) about which event loop uvicorn uses.
  - **Hypothesis 2 (unresolved): something specific to uvicorn's actual
    running socket, not its bind code.** Replicated uvicorn's exact
    `Config.bind_socket()` logic by hand (`socket.socket(family=AF_INET6)`,
    `SO_REUSEADDR`, `bind(('::', <port>))`, `listen()`) via a `python3 -c`
    one-liner run through `fly ssh console` on the *same* machine/container
    — this produced a socket with `IPV6_V6ONLY=0` that happily accepted a
    `127.0.0.1` connection in the same script. So a byte-for-byte replica of
    uvicorn's own bind code works fine, but the real uvicorn process
    (verified via `/proc/<pid>/cmdline`, confirmed running with `--loop
    asyncio --host :: --port 8000`) still refuses IPv4 on the same port.
    **This discrepancy was never explained** — whatever's different between
    the replica and the real process is the actual root cause and is the
    open thread for whoever picks this up next.
  - Also checked `flyctl config show -a anki-ai-cards-backend` — the
    registered `http_service`/`checks` config matches `fly.toml` exactly,
    nothing corrupted there.
- Learned / suggestions for next attempt:
  - Don't trust `fly checks list`'s displayed timestamp/`"gone"` output as
    evidence of a stale/frozen monitor — `fly apps restart`'s live polling
    output is the more reliable signal of whether checks are actually
    passing right now.
  - The next concrete experiment worth running: temporarily set `--host
    0.0.0.0` (dropping IPv6 support entirely) and redeploy, to conclusively
    prove/disprove that the bind address is really the deciding factor for
    the *public* path — if the health check immediately goes green, the fix
    needs to serve both address families at once (since `0.0.0.0` alone
    breaks the frontend→backend 6PN path, which is IPv6-only and is why
    `::` was chosen in the first place by commit `607bf74`), e.g. by running
    two separate listening sockets/processes, or finding whatever's
    different about uvicorn's actual socket vs. the working hand-replica
    above and fixing that specifically. Don't leave the app on `0.0.0.0`
    permanently without also solving 6PN — that's the exact regression
    `607bf74` was fixing.
  - `backend/Dockerfile` currently has `--loop asyncio` in its `CMD` from
    this investigation. It didn't fix the bug but also didn't break
    anything — leave it unless a future finding says otherwise.

---

## 2026-07-03 — Task 13: Manual end-to-end verification checklist
- Did: Added `docs/manual_verification.md`, an 8-section manual checklist
  (sign-in/allowlist rejection, starting a chat and pointing at the real
  lesson doc, live note-type/field discovery, proposing a card, generating
  and picking audio, creating the note + verifying in Anki via VNC, syncing
  and checking the phone/desktop app, and reusing a saved workflow spec in a
  second session) plus a closing "If something doesn't match" note
  distinguishing "doc is stale, update it" from "real bug, file a new PRD
  task." This is the last PRD task, so every checklist step was written by
  actually reading the real task 1-12 code (not just re-paraphrasing the
  PRD) to make sure it matches current behavior exactly: `backend/app/api/
  auth.py` for the login/callback/`ALLOWED_EMAIL` flow, `backend/app/agent/
  {prompts,tools,core}.py` for the actual tool names
  (`fetch_google_doc`/`list_anki_note_types`/`get_anki_note_type_fields`/
  `generate_audio`/`create_anki_note`/`sync_anki`/`save_workflow_spec`/
  `load_workflow_spec`/`list_workflow_specs`) and the fact there's no
  `propose_card` tool (task 9's PROGRESS entry — proposal/confirmation is
  conversational, not a dedicated API), `backend/app/api/chat.py` for what
  does/doesn't persist across a reload (payloads don't, per task 10's
  PROGRESS entry — called this out explicitly in step 2 so Dylan doesn't
  think it's a new bug), and the actual frontend components
  (`SignIn.tsx`/`AudioOptionsCard.tsx`/`CardPayloadCard.tsx`) for exact
  button labels ("Sign in with Google", "Pick", "Request a change") and
  card copy ("Card added to Anki") so the checklist's UI descriptions won't
  drift from what's actually rendered.
- Verified: Per the task's own Verify clause, "the document exists and
  accurately reflects the built system's actual flow" is a cross-check
  against tasks 1-12's code, which is what the writing process above did
  (reading `main.py`, `api/auth.py`, `api/chat.py`, `agent/{prompts,tools,
  core}.py`, and every referenced frontend component directly rather than
  trusting PROGRESS.md summaries alone). Also reran both objective
  verification commands to confirm this docs-only change didn't regress
  anything: `cd backend && uv run pytest` → 64 passed; `cd frontend && npm
  run build && npm run lint` → build succeeds, lint clean.
  **Not verified (explicitly Dylan's manual job per the task):** actually
  running the checklist itself against a real deployed instance, a real
  Google account, a real lesson doc, and a real Anki collection — the loop
  has never had access to any of those (per AGENTS.md, no real network
  calls to Google/Anthropic/ElevenLabs/AnkiConnect from the loop, and no
  `fly deploy`/VNC login), so there was no way to execute the checklist,
  only to verify it's an accurate description of what running it *should*
  do.
- Learned:
  - This was the final unchecked PRD task — every task in PRD.md's Tasks
    section is now `[x]`. Per the loop's own completion rule, this
    iteration ends with the `RALPH_DONE` sentinel below rather than picking
    a new task.
  - Deliberately did **not** invent a mock/stub end-to-end test harness to
    "verify" this checklist automatically — the task's Verify clause is
    explicit that running it is manual, and the PRD's Out of scope section
    already rules out the loop performing OAuth consent/VNC logins/
    `fly deploy`, which is most of what the checklist exercises. Faking a
    stand-in verification here would misrepresent what was actually
    checked.
  - If a future change adds real pre-creation card approval (the
    `propose_card`-style tool flagged as a possible gap in task 9's
    PROGRESS entry) or persists payloads across reload (flagged in task
    10's), this checklist's steps 2, 4, and 6 will need a small rewrite —
    they currently describe the current, conversational-only behavior as
    correct, not as a placeholder.

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
