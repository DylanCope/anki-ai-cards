# Manual end-to-end verification checklist

This is a **manual** checklist for Dylan — it exercises the real, deployed
system against real Google/Anthropic/ElevenLabs/AnkiConnect services. None of
this is (or can be) run by the Ralph loop: the loop's automated tests mock
every external service (per AGENTS.md) and never perform interactive OAuth
consent, VNC logins, or `fly deploy`. Run this after the one-time headless
Anki VNC login (AGENTS.md "Headless Anki deployment") and after both apps
have been deployed (`fly deploy --config backend/fly.toml` /
`--config frontend/fly.toml`, with secrets already pushed via `fly secrets
set`, per AGENTS.md "Backend/frontend deployment").

Check off each step as you go. If a step doesn't match what's described here,
that's either a bug or this doc is stale — see the "If something doesn't
match" note at the bottom.

## 1. Sign in with Google

- [ ] Open the frontend's URL. You should see the chat page load, briefly
  show "Loading...", then show a "Sign in with the Google account that has
  access to your lesson doc and Anki collection" screen with a **Sign in with
  Google** button (`frontend/app/components/SignIn.tsx`).
- [ ] Click it. You're redirected to `/auth/google/login` on the backend,
  then to Google's consent screen requesting `openid`, `email`, and
  `https://www.googleapis.com/auth/documents.readonly` scopes.
- [ ] Sign in with your allowlisted Google account (the one in the
  `ALLOWED_EMAIL` Fly secret). You're redirected back and land on the chat
  UI, now showing an empty message thread with an input box.
- [ ] **Negative check:** if you have a second Google account handy, try
  signing in with it once. It should be rejected (403) at
  `/auth/google/callback` rather than reaching the chat UI — confirms
  `ALLOWED_EMAIL` gating is live in production, not just in tests.

## 2. Start a chat and point the agent at the real lesson doc

- [ ] Type a message giving the agent your lesson doc's ID or URL, e.g.
  "Here's today's lesson doc: `https://docs.google.com/document/d/<id>/edit`
  — find the teacher's corrections and propose some cards." Send it.
- [ ] The agent's reply should indicate it read the doc (it calls
  `fetch_google_doc` internally, which flattens the doc into `{text, color}`
  spans and identifies red-marked corrections — `backend/app/clients/
  google_docs.py`). You won't see the tool call itself in the UI, only the
  agent's resulting text — confirm the reply references content that's
  actually in your doc (specific phrases/corrections), not generic filler.
- [ ] Reload the page. The conversation transcript should still be there
  (persisted via `ConversationMessage` rows, replayed by `GET /api/chat/
  history`). Note: only text turns persist across reload — audio players and
  the "card added" confirmation from earlier turns won't reappear after a
  reload, only in the live session that produced them (see PROGRESS.md,
  task 10 entry — a known, deliberate gap, not a bug).

## 3. Confirm live note-type/field discovery

- [ ] Ask the agent something like "What Anki note type and fields will you
  use?" before it creates anything. Its answer should name your **actual**
  existing note type and field names from your real Anki collection (it
  calls `list_anki_note_types` / `get_anki_note_type_fields` against
  AnkiConnect live) — not a hardcoded guess like "Front/Back" unless that
  really is your note type's field names.
- [ ] If your collection has more than one note type, ask the agent to
  confirm which one it picked and why — it should be able to explain its
  reasoning (e.g. "Cloze" because the card needs a cloze deletion), not just
  assert a choice silently.

## 4. Propose a card

- [ ] Ask the agent to propose a card for one specific correction from the
  doc. Its reply (plain chat text, not a dedicated UI widget — there is no
  `propose_card` tool, see PROGRESS.md task 9 entry) should show a Japanese
  cloze deletion, furigana, an English translation, and ask you to confirm
  or request edits before creating anything.
- [ ] Ask for at least one edit (e.g. "actually cloze the whole verb, not
  just the ending") and confirm the agent incorporates it before proceeding.
  This exercises the "propose → confirm/edit → create" conversational flow
  the PRD describes, which lives entirely in the chat text, not a special
  approve/edit button.

## 5. Generate audio and pick one

- [ ] Once you confirm a card, the agent should call `generate_audio` and
  the response should render an **Audio options** card in the chat with 3
  players labeled "Option 1/2/3", each with a **Pick** button
  (`frontend/app/components/AudioOptionsCard.tsx`).
- [ ] Play each option — confirm they're audibly distinct takes of the same
  Japanese text (ElevenLabs `voice_settings` are varied per option, not
  identical calls — `backend/app/clients/elevenlabs.py`), and that the
  Japanese pronunciation sounds correct.
- [ ] Click **Pick** on one. This sends a chat message ("Use audio option
  N.") rather than calling a dedicated selection API — confirm the agent
  acknowledges the pick and proceeds using that audio.

## 6. Create the note

- [ ] After you've picked audio, ask the agent to create the note (or
  confirm it does so automatically once card + audio are settled — either
  is consistent with the system prompt). The chat should show a **Card
  added to Anki** card (`frontend/app/components/CardPayloadCard.tsx`)
  listing the deck, note type, every field (generically rendered — no
  hardcoded field names in the UI), any tags, and a `note #<id>`.
- [ ] Open Anki directly via the VNC session (`fly proxy 5900 -a
  anki-ai-cards-anki`, per AGENTS.md) and confirm the note actually exists
  in the collection with the fields you expect, including the audio
  attachment.
- [ ] Try the **Request a change** button on the card — confirm it prefills
  the chat input referencing the note's ID and lets you send a follow-up
  edit request, rather than silently failing.

## 7. Sync and confirm on your phone/desktop

- [ ] Ask the agent to sync (or confirm it calls `sync_anki` automatically
  after creating the note — the system prompt tells it to). There's no
  dedicated "sync" UI button; this is conversational, same as the rest of
  the flow.
- [ ] On your phone or desktop Anki app (already logged into your real
  AnkiWeb account — no reconfiguration needed per the PRD), trigger a normal
  sync.
- [ ] Confirm the new card appears, with the correct fields, furigana,
  translation, and that the audio plays.

## 8. Reuse a workflow spec (second session)

- [ ] Start a **new** browser session (or just refresh after some time) and
  send an opening message. If you and the agent settled on a workflow
  earlier in step 2-6, the agent should proactively mention it knows a saved
  workflow spec and offer to reuse it (`save_workflow_spec`/
  `load_workflow_spec`/`list_workflow_specs`, surfaced via the system prompt
  only on a fresh/empty conversation — see `backend/app/agent/core.py`).
- [ ] Confirm reusing it actually skips re-deriving the doc layout/field
  mapping from scratch (e.g. it doesn't re-ask "what note type should I
  use?" if the spec already answers that).

## If something doesn't match

This doc was written by cross-checking PRD.md tasks 1-12 and the actual code
in `backend/app/` and `frontend/app/` as of the task-13 commit. If a step
above doesn't match what the running system actually does:

- If the **code** has moved on (e.g. a later change added a real
  `propose_card` tool or persisted payloads across reloads), this doc is
  stale — update it to match the new behavior.
- If the **system** doesn't do what both this doc and the code say it
  should, that's a real bug — file it as a new task in PRD.md rather than
  fixing it inside this doc.
