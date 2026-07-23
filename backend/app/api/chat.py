"""Chat API: the frontend's only entry point into the inner agent.

Conversations are first-class (`Conversation` rows) so Dylan can start a new
chat and switch back to older ones — every `ConversationMessage` belongs to
exactly one. `POST /api/chat` loads the persisted conversation for the given
`conversation_id`, runs one turn of `app.agent.core.run_turn`, persists
whatever new messages that turn produced, and returns the agent's text reply
plus any structured payloads (audio options, created cards) extracted from
the tool calls made during the turn. `GET /api/chat/history` returns a
plain-text transcript of one conversation for rendering a chat thread.

If a turn fails outright (the `except Exception` branch below), the user's
message and a short explanatory assistant reply are still persisted —
earlier versions only ever persisted a successful turn's messages, so a
failed turn would vanish entirely on reload with no trace of what was asked
or what went wrong.

Content blocks coming back from `run_turn`'s history may be either
`anthropic` SDK objects (fresh from the model) or plain dicts (reconstructed
from a prior turn's persisted JSON) — `_content_block_to_dict` normalizes
both to dicts before anything here inspects or persists them.
"""

import base64
import functools
import json
import re
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.agent import anki_template
from app.agent import core as agent_core
from app.agent import tools as agent_tools
from app.agent.model_registry import AVAILABLE_MODELS, DEFAULT_MODEL_ID, get_model
from app.auth import require_auth
from app.clients import ankiconnect, google_docs
from app.models import (
    AudioClip,
    BugReport,
    Conversation,
    ConversationMessage,
    ImageAsset,
    OAuthToken,
    PendingCard,
    UserSettings,
    get_engine,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
conversations_router = APIRouter(prefix="/api/conversations", tags=["conversations"])
models_router = APIRouter(prefix="/api/models", tags=["models"])
settings_router = APIRouter(prefix="/api/settings", tags=["settings"])

TITLE_MAX_LENGTH = 60


class ChatRequest(BaseModel):
    conversation_id: int
    message: str
    edit: bool = False
    image_id: int | None = None


class ChatResponse(BaseModel):
    reply: str
    payloads: list[dict]
    # The image (if any) `body.image_id` attached to this turn's own user
    # message — a dedicated field rather than folded into `payloads` since
    # it belongs to the user's turn, not the assistant's reply `payloads`
    # already denotes; see `post_chat`'s `image_id` handling.
    attached_image: dict | None = None


class CreateConversationRequest(BaseModel):
    # None means "use the resolved default" (Dylan's stored default_model_id
    # if set, else DEFAULT_MODEL_ID) — see create_conversation. Defaulting
    # this field to DEFAULT_MODEL_ID directly would shadow a DB-stored
    # default at the Pydantic level, since an explicit body model always
    # wins over the stored one.
    model: str | None = None
    instant_creation: bool = False


class UpdateDefaultModelRequest(BaseModel):
    model_id: str


class UpdateConversationRequest(BaseModel):
    model: str | None = None
    title: str | None = None
    instant_creation: bool | None = None


def _conversation_to_dict(conversation: Conversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "model": conversation.model,
        "instant_creation": conversation.instant_creation,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _title_from_message(message: str) -> str:
    stripped = message.strip().replace("\n", " ")
    if len(stripped) <= TITLE_MAX_LENGTH:
        return stripped
    return stripped[:TITLE_MAX_LENGTH].rstrip() + "…"


def _get_conversation_or_404(session: Session, conversation_id: int) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _get_user_settings(session: Session) -> UserSettings:
    """Get-or-create the single settings row (id=1) — this app is
    single-user, so there's only ever one."""
    settings = session.get(UserSettings, 1)
    if settings is None:
        settings = UserSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def _content_block_to_dict(block) -> dict:
    if isinstance(block, dict):
        return block
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        result = {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
        # Gemini-only: an opaque signature that must be replayed on later
        # requests referencing this tool call — absent (None) on
        # Anthropic-originated blocks. See gemini_provider's module
        # docstring for why this can't just live provider-side.
        thought_signature = getattr(block, "gemini_thought_signature", None)
        if thought_signature is not None:
            result["gemini_thought_signature"] = thought_signature
        return result
    raise ValueError(f"Unsupported content block type: {block.type!r}")


def _serialize_message(message: dict) -> dict:
    content = message["content"]
    if isinstance(content, str):
        return {"role": message["role"], "content": content}
    return {
        "role": message["role"],
        "content": [_content_block_to_dict(block) for block in content],
    }


#  The exact suffix `post_chat` appends to a message when `body.image_id` is
# set (see its `effective_message` handling) — a machine-readable note for
# the agent's benefit, not something Dylan should see on reload now that
# the attached image itself renders as an inline `image_attachment` payload
# (see `_payloads_for_message`). Only strips it for *display*; the
# persisted/model-facing content keeps the note so later turns still have it.
_IMAGE_ATTACHMENT_NOTE_RE = re.compile(r"\n\n\(Attached image_id: \d+ for use on a card\.\)$")


def _display_text(content) -> str | None:
    if isinstance(content, str):
        return _IMAGE_ATTACHMENT_NOTE_RE.sub("", content)
    texts = [block["text"] for block in content if block.get("type") == "text"]
    return _IMAGE_ATTACHMENT_NOTE_RE.sub("", "\n".join(texts)) if texts else None


def _build_tool_results(messages: list[dict]) -> dict[str, object]:
    """Map each `tool_use_id` to its parsed `tool_result` content, scanning
    every message given (not just one turn's) so a tool_use/tool_result pair
    can be matched regardless of which rows they landed in."""

    tool_results: dict[str, object] = {}
    for message in messages:
        if message["role"] != "user" or isinstance(message["content"], str):
            continue
        for block in message["content"]:
            if block.get("type") == "tool_result":
                try:
                    tool_results[block["tool_use_id"]] = json.loads(block["content"])
                except (TypeError, json.JSONDecodeError):
                    tool_results[block["tool_use_id"]] = block["content"]
    return tool_results


def _collect_assets(engine, tool_results: dict[str, object], model_cls, id_key: str) -> dict:
    """Load every `model_cls` row referenced by `id_key` (e.g. `clip_ids`,
    `image_ids`) across all tool_results, keyed by id."""

    ids: set[int] = set()
    for result in tool_results.values():
        if isinstance(result, dict):
            ids.update(result.get(id_key, []) or [])
    if not ids:
        return {}
    with Session(engine) as session:
        return {
            row.id: row
            for row in session.exec(select(model_cls).where(model_cls.id.in_(ids))).all()
        }


def _collect_audio_clips(engine, tool_results: dict[str, object]) -> dict[int, AudioClip]:
    return _collect_assets(engine, tool_results, AudioClip, "clip_ids")


def _collect_image_assets(
    engine, tool_results: dict[str, object], messages: list[dict]
) -> dict[int, ImageAsset]:
    """Same as `_collect_assets(..., ImageAsset, "image_ids")`, plus any
    id(s) attached directly to a message via its `image_id` key (an upload
    attached to that specific user message — see `_apply_edit`'s sibling,
    `post_chat`'s `image_id` handling — as opposed to `image_ids` produced by
    a `search_images`/`generate_image` tool call)."""

    ids: set[int] = {
        message["image_id"] for message in messages if message.get("image_id") is not None
    }
    for result in tool_results.values():
        if isinstance(result, dict):
            ids.update(result.get("image_ids", []) or [])
    if not ids:
        return {}
    with Session(engine) as session:
        return {
            row.id: row
            for row in session.exec(select(ImageAsset).where(ImageAsset.id.in_(ids))).all()
        }


def _payloads_for_message(
    message: dict,
    tool_results: dict[str, object],
    clips_by_id: dict[int, AudioClip],
    images_by_id: dict[int, ImageAsset],
) -> list[dict]:
    """Extract the structured payloads (audio options, image options, created
    cards, an uploaded image attachment) produced by a single message — the
    tool_use blocks of an assistant message, or the `image_id` a user
    message carried (see `post_chat`'s `image_id` handling)."""

    payloads: list[dict] = []
    image_id = message.get("image_id")
    if image_id is not None and image_id in images_by_id:
        image = images_by_id[image_id]
        payloads.append(
            {
                "type": "image_attachment",
                "image_id": image_id,
                "data": base64.b64encode(image.data).decode("ascii"),
                "content_type": image.content_type,
            }
        )

    if message["role"] != "assistant" or isinstance(message["content"], str):
        return payloads

    for block in message["content"]:
        if block.get("type") != "tool_use":
            continue
        result = tool_results.get(block["id"])
        tool_input = block["input"]
        if block["name"] in ("generate_audio", "search_word_pronunciations"):
            clip_ids = result.get("clip_ids", []) if isinstance(result, dict) else []
            options = [
                base64.b64encode(clips_by_id[cid].audio).decode("ascii")
                for cid in clip_ids
                if cid in clips_by_id
            ]
            payloads.append(
                {
                    "type": "audio_options",
                    "text": tool_input.get("text")
                    if block["name"] == "generate_audio"
                    else tool_input.get("word"),
                    "clip_ids": clip_ids,
                    "options": options,
                }
            )
        elif block["name"] in ("search_images", "generate_image"):
            image_ids = result.get("image_ids", []) if isinstance(result, dict) else []
            found = [images_by_id[iid] for iid in image_ids if iid in images_by_id]
            payloads.append(
                {
                    "type": "image_options",
                    "query_or_prompt": tool_input.get("query")
                    if block["name"] == "search_images"
                    else tool_input.get("prompt"),
                    "image_ids": image_ids,
                    "options": [
                        base64.b64encode(image.data).decode("ascii") for image in found
                    ],
                    "content_types": [image.content_type for image in found],
                }
            )
        elif block["name"] == "load_workflow_spec":
            # No payload when the loaded name wasn't found (result is None) —
            # nothing to surface to Dylan; the agent's own text reply already
            # has to explain a miss.
            if isinstance(result, dict):
                payloads.append(
                    {
                        "type": "workflow_loaded",
                        "name": result.get("name"),
                        "spec": result.get("spec"),
                    }
                )
        elif block["name"] == "create_anki_note":
            result_dict = result if isinstance(result, dict) else {}
            note_id = result_dict.get("note_id")
            # instant_creation=True's tool result is just {"note_id": ...} —
            # no explicit "status" key (see dispatch_tool) — so a note_id
            # with no status means "created" here.
            status = result_dict.get("status") or ("created" if note_id is not None else None)
            payloads.append(
                {
                    "type": "card",
                    "deck_name": tool_input.get("deck_name"),
                    "model_name": tool_input.get("model_name"),
                    "fields": tool_input.get("fields"),
                    "tags": tool_input.get("tags"),
                    "note_id": note_id,
                    "status": status,
                    "pending_card_id": result_dict.get("pending_card_id"),
                }
            )
    return payloads


def _extract_payloads(messages: list[dict], engine) -> list[dict]:
    """Pull frontend-renderable structured payloads (audio options, created
    cards) out of a batch of messages' tool calls, keyed by matching each
    tool_use block to its tool_result by `tool_use_id`."""

    tool_results = _build_tool_results(messages)
    clips_by_id = _collect_audio_clips(engine, tool_results)
    images_by_id = _collect_image_assets(engine, tool_results, messages)
    payloads: list[dict] = []
    for message in messages:
        payloads.extend(_payloads_for_message(message, tool_results, clips_by_id, images_by_id))
    return payloads


def _build_history_entries(rows: list[ConversationMessage], engine) -> list[dict]:
    """Reconstruct a conversation's full transcript, with each text-bearing
    message's payloads attached to it. A tool-use-only message has no display
    text of its own (its payloads carry forward and attach to the next
    text-bearing message, normally that turn's final assistant reply) — this
    mirrors how `POST /api/chat` already bundles a turn's reply text together
    with that turn's payloads in one response."""

    messages = [
        {"role": row.role, "content": json.loads(row.content), "image_id": row.image_id}
        for row in rows
    ]
    tool_results = _build_tool_results(messages)
    clips_by_id = _collect_audio_clips(engine, tool_results)
    images_by_id = _collect_image_assets(engine, tool_results, messages)

    entries: list[dict] = []
    pending_payloads: list[dict] = []
    for message in messages:
        pending_payloads.extend(
            _payloads_for_message(message, tool_results, clips_by_id, images_by_id)
        )
        text = _display_text(message["content"])
        if text is not None:
            entries.append({"role": message["role"], "text": text, "payloads": pending_payloads})
            pending_payloads = []
    return entries


def _has_create_anki_note_call(content) -> bool:
    if isinstance(content, str):
        return False
    return any(
        block.get("type") == "tool_use" and block.get("name") == "create_anki_note"
        for block in content
    )


def _is_user_authored_message(row) -> bool:
    """True for a real chat message Dylan typed, as opposed to a `role:
    "user"` row that's actually just the tool-result carrier the
    Anthropic/Gemini message format uses to return a tool's output — those
    share the "user" role but aren't something to treat as "the last thing
    Dylan said"."""

    if row.role != "user":
        return False
    content = json.loads(row.content)
    if isinstance(content, str):
        return True
    return not any(block.get("type") == "tool_result" for block in content)


def _apply_edit(session: Session, conversation_id: int, prior_rows: list) -> list:
    """Discard the last user message and everything after it, so the caller
    can resubmit replacement text as if that turn never happened. Raises a
    409 if a `create_anki_note` call already happened after that message —
    rewriting history that already caused a real Anki side effect is not
    allowed (the frontend is expected to prevent this via a disabled edit
    affordance; this is the backend's own guard against it)."""

    last_user_index = None
    for index in range(len(prior_rows) - 1, -1, -1):
        if _is_user_authored_message(prior_rows[index]):
            last_user_index = index
            break
    if last_user_index is None:
        raise HTTPException(status_code=400, detail="No prior message to edit")

    for row in prior_rows[last_user_index + 1 :]:
        if row.role == "assistant" and _has_create_anki_note_call(json.loads(row.content)):
            raise HTTPException(
                status_code=409,
                detail="Can't edit — a card was already created from this message",
            )

    remaining_rows = prior_rows[:last_user_index]
    for row in prior_rows[last_user_index:]:
        session.delete(row)
    session.commit()
    # `commit()` expires every object still attached to this session (the
    # default `expire_on_commit` behavior), so the rows we're keeping need a
    # refresh now — otherwise reading their attributes after this session
    # closes raises `DetachedInstanceError` instead of returning stale data.
    for row in remaining_rows:
        session.refresh(row)
    return remaining_rows


async def _get_access_token(email: str) -> str:
    """Return a fresh Google access token for `email`, refreshing it via
    `google_docs.refresh_access_token` first if it has expired.

    Passed into `agent_core.run_turn` as a lazy `get_access_token` callable
    rather than called eagerly here — only `fetch_google_doc` needs a Google
    token, so a turn that never touches it shouldn't have to pay for (or can
    fail on) a token refresh, and every other tool (including `search_images`)
    would otherwise be blocked by an unrelated Google auth problem."""

    engine = get_engine()
    with Session(engine) as session:
        token = session.exec(select(OAuthToken).where(OAuthToken.email == email)).first()
        if token is None:
            raise HTTPException(status_code=401, detail="No stored Google credentials")

        # SQLite drops tzinfo on round-trip (SQLModel/SQLAlchemy stores a
        # naive UTC value), so compare against a naive UTC value rather than
        # an aware `datetime.now(timezone.utc)` to avoid a naive/aware TypeError.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if token.expires_at <= now:
            refreshed = await google_docs.refresh_access_token(token.refresh_token)
            token.access_token = refreshed["access_token"]
            token.expires_at = now + timedelta(seconds=refreshed.get("expires_in", 3600))
            session.add(token)
            session.commit()
            session.refresh(token)

        return token.access_token


@router.post("", response_model=ChatResponse)
async def post_chat(body: ChatRequest, email: str = Depends(require_auth)) -> ChatResponse:
    engine = get_engine()
    with Session(engine) as session:
        conversation = _get_conversation_or_404(session, body.conversation_id)
        prior_rows = session.exec(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == body.conversation_id)
            .order_by(ConversationMessage.id)
        ).all()
        if body.edit:
            prior_rows = _apply_edit(session, body.conversation_id, prior_rows)
            session.refresh(conversation)
        first_message = not prior_rows
    history = [{"role": row.role, "content": json.loads(row.content)} for row in prior_rows]

    effective_message = body.message
    if body.image_id is not None:
        effective_message = (
            f"{body.message}\n\n(Attached image_id: {body.image_id} for use on a card.)"
        )

    try:
        result = await agent_core.run_turn(
            history,
            effective_message,
            get_access_token=functools.partial(_get_access_token, email),
            model_id=conversation.model,
            instant_creation=conversation.instant_creation,
        )
    except Exception as exc:
        detail = f"{traceback.format_exc()}\n\nUser message: {body.message}"
        with Session(engine) as session:
            bug_report = BugReport(message=str(exc), detail=detail)
            session.add(bug_report)
            session.commit()
            session.refresh(bug_report)

        # Persist the failed turn instead of silently dropping it — without
        # this, a failure meant the user's own message (and any trace that
        # something went wrong) vanished on the next page reload, since
        # nothing about a failed turn was ever saved.
        error_text = f"Something went wrong — bug report #{bug_report.id} filed."
        with Session(engine) as session:
            session.add(
                ConversationMessage(
                    conversation_id=body.conversation_id,
                    role="user",
                    content=json.dumps(body.message),
                )
            )
            session.add(
                ConversationMessage(
                    conversation_id=body.conversation_id,
                    role="assistant",
                    content=json.dumps([{"type": "text", "text": error_text}]),
                )
            )
            conversation = session.get(Conversation, body.conversation_id)
            conversation.updated_at = datetime.now(timezone.utc)
            if first_message and conversation.title is None:
                conversation.title = _title_from_message(body.message)
            session.add(conversation)
            session.commit()

        raise HTTPException(
            status_code=500,
            detail={"error": "Something went wrong.", "bug_report_id": bug_report.id},
        ) from exc

    serialized_history = [_serialize_message(message) for message in result["history"]]
    new_messages = serialized_history[len(prior_rows) :]

    attached_image = None
    with Session(engine) as session:
        for index, message in enumerate(new_messages):
            # Only the turn's own first message (Dylan's actual new user
            # message, not a later tool-result carrier) can own the upload
            # named by `body.image_id` — see `_collect_image_assets`'s
            # message-level `image_id` handling.
            session.add(
                ConversationMessage(
                    conversation_id=body.conversation_id,
                    role=message["role"],
                    content=json.dumps(message["content"]),
                    image_id=body.image_id if index == 0 else None,
                )
            )
        conversation = session.get(Conversation, body.conversation_id)
        conversation.updated_at = datetime.now(timezone.utc)
        if first_message and conversation.title is None:
            conversation.title = _title_from_message(body.message)
        session.add(conversation)
        session.commit()

        if body.image_id is not None:
            image = session.get(ImageAsset, body.image_id)
            if image is not None:
                attached_image = {
                    "type": "image_attachment",
                    "image_id": image.id,
                    "data": base64.b64encode(image.data).decode("ascii"),
                    "content_type": image.content_type,
                }

    return ChatResponse(
        reply=result["reply"],
        payloads=_extract_payloads(new_messages, engine),
        attached_image=attached_image,
    )


@router.get("/history")
async def get_chat_history(
    conversation_id: int, email: str = Depends(require_auth)
) -> list[dict]:
    engine = get_engine()
    with Session(engine) as session:
        _get_conversation_or_404(session, conversation_id)
        rows = session.exec(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id)
        ).all()

    return _build_history_entries(rows, engine)


@conversations_router.post("")
async def create_conversation(
    body: CreateConversationRequest = CreateConversationRequest(),
    email: str = Depends(require_auth),
) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        resolved_model = (
            body.model or _get_user_settings(session).default_model_id or DEFAULT_MODEL_ID
        )
        try:
            get_model(resolved_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        conversation = Conversation(model=resolved_model, instant_creation=body.instant_creation)
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
    return _conversation_to_dict(conversation)


@conversations_router.get("")
async def list_conversations(email: str = Depends(require_auth)) -> list[dict]:
    engine = get_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(Conversation).order_by(Conversation.updated_at.desc())
        ).all()
    return [_conversation_to_dict(row) for row in rows]


@conversations_router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    body: UpdateConversationRequest,
    email: str = Depends(require_auth),
) -> dict:
    if body.model is not None:
        try:
            get_model(body.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = get_engine()
    with Session(engine) as session:
        conversation = _get_conversation_or_404(session, conversation_id)
        if body.model is not None:
            conversation.model = body.model
        if body.title is not None:
            conversation.title = body.title
        if body.instant_creation is not None:
            conversation.instant_creation = body.instant_creation
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
    return _conversation_to_dict(conversation)


@conversations_router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    email: str = Depends(require_auth),
) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        conversation = _get_conversation_or_404(session, conversation_id)
        messages = session.exec(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id
            )
        ).all()
        for message in messages:
            session.delete(message)
        session.delete(conversation)
        session.commit()
    return {"deleted": True}


@models_router.get("")
async def list_models(email: str = Depends(require_auth)) -> list[dict]:
    return [
        {
            "id": model.id,
            "provider": model.provider,
            "display_name": model.display_name,
            "input_price_per_mtok": model.input_price_per_mtok,
            "output_price_per_mtok": model.output_price_per_mtok,
            "description": model.description,
        }
        for model in AVAILABLE_MODELS
    ]


@settings_router.get("")
async def get_settings(email: str = Depends(require_auth)) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        settings = _get_user_settings(session)
    return {"default_model_id": settings.default_model_id}


@settings_router.put("/default-model")
async def set_default_model(
    body: UpdateDefaultModelRequest, email: str = Depends(require_auth)
) -> dict:
    try:
        get_model(body.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = get_engine()
    with Session(engine) as session:
        settings = _get_user_settings(session)
        settings.default_model_id = body.model_id
        settings.updated_at = datetime.now(timezone.utc)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return {"default_model_id": settings.default_model_id}


bug_reports_router = APIRouter(prefix="/api/bug-reports", tags=["bug-reports"])


@bug_reports_router.get("")
async def list_bug_reports(email: str = Depends(require_auth)) -> list[dict]:
    engine = get_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(BugReport).order_by(BugReport.created_at.desc()).limit(20)
        ).all()
    return [
        {"id": row.id, "created_at": row.created_at, "message": row.message} for row in rows
    ]


@bug_reports_router.get("/{bug_report_id}")
async def get_bug_report(bug_report_id: int, email: str = Depends(require_auth)) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        bug_report = session.get(BugReport, bug_report_id)
    if bug_report is None:
        raise HTTPException(status_code=404, detail="Bug report not found")
    return {
        "id": bug_report.id,
        "created_at": bug_report.created_at,
        "message": bug_report.message,
        "detail": bug_report.detail,
    }


pending_cards_router = APIRouter(prefix="/api/pending-cards", tags=["pending-cards"])


def _get_pending_card_or_404(session: Session, pending_card_id: int) -> PendingCard:
    pending_card = session.get(PendingCard, pending_card_id)
    if pending_card is None:
        raise HTTPException(status_code=404, detail="Pending card not found")
    return pending_card


@pending_cards_router.post("/{pending_card_id}/create")
async def create_pending_card(
    pending_card_id: int, email: str = Depends(require_auth)
) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        pending_card = _get_pending_card_or_404(session, pending_card_id)
        if pending_card.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Pending card is already {pending_card.status}",
            )
        try:
            note_id = await agent_tools._create_note_in_anki(
                pending_card.deck_name,
                pending_card.model_name,
                json.loads(pending_card.fields),
                json.loads(pending_card.tags) if pending_card.tags else None,
                json.loads(pending_card.audio) if pending_card.audio else None,
                json.loads(pending_card.picture) if pending_card.picture else None,
            )
        except Exception as exc:
            # Same diagnosability pattern as POST /api/chat: an AnkiConnect
            # failure here (duplicate note, unknown deck/model/field, the
            # headless container mid-crash-restart, ...) used to propagate as
            # a bare unhandled 500 — no BugReport filed, no detail reaching
            # the frontend beyond "Could not create the card in Anki.",
            # leaving Dylan unable to tell a duplicate-note rejection from
            # AnkiConnect being unreachable. The PendingCard row itself is
            # untouched here (still "pending"), so retrying after fixing the
            # underlying cause just works.
            detail = f"{traceback.format_exc()}\n\nPending card id: {pending_card_id}"
            with Session(engine) as bug_session:
                bug_report = BugReport(message=str(exc), detail=detail)
                bug_session.add(bug_report)
                bug_session.commit()
                bug_session.refresh(bug_report)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Could not create the card in Anki.",
                    "bug_report_id": bug_report.id,
                },
            ) from exc
        pending_card.status = "created"
        pending_card.note_id = note_id
        session.add(pending_card)
        session.commit()
    return {"note_id": note_id}


@pending_cards_router.post("/{pending_card_id}/discard")
async def discard_pending_card(
    pending_card_id: int, email: str = Depends(require_auth)
) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        pending_card = _get_pending_card_or_404(session, pending_card_id)
        if pending_card.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Pending card is already {pending_card.status}",
            )
        pending_card.status = "discarded"
        session.add(pending_card)
        session.commit()
    return {"status": "discarded"}


@pending_cards_router.get("/{pending_card_id}/preview")
async def preview_pending_card(
    pending_card_id: int, email: str = Depends(require_auth)
) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        pending_card = _get_pending_card_or_404(session, pending_card_id)
        model_name = pending_card.model_name
        fields = json.loads(pending_card.fields)
        # The template renderer (app.agent.anki_template) only substitutes
        # field text — it has no notion of media — so a picked audio
        # clip/image doesn't show up in front_html/back_html at all. Rather
        # than leave that a silent gap, surface the raw picked media
        # alongside the rendered HTML so a frontend can show a player/
        # thumbnail next to the preview if it chooses to.
        audio_input = json.loads(pending_card.audio) if pending_card.audio else None
        picture_input = json.loads(pending_card.picture) if pending_card.picture else None
        audio_clip = (
            session.get(AudioClip, audio_input["clip_id"]) if audio_input else None
        )
        image_asset = (
            session.get(ImageAsset, picture_input["image_id"]) if picture_input else None
        )

    templates = await ankiconnect.get_model_templates(model_name)
    css = await ankiconnect.get_model_styling(model_name)
    # Cloze note types have exactly one card template; other note types may
    # define more than one (e.g. Basic (and reversed)) — the first is enough
    # for a representative preview, same "preview one representative card"
    # scoping the template renderer itself uses for cloze ordinals.
    card_name = next(iter(templates))
    template = templates[card_name]
    result = anki_template.render_card(template["Front"], template["Back"], css, fields)
    if audio_clip is not None:
        result["audio_base64"] = base64.b64encode(audio_clip.audio).decode("ascii")
    if image_asset is not None:
        result["picture_base64"] = base64.b64encode(image_asset.data).decode("ascii")
        result["picture_content_type"] = image_asset.content_type
    return result
