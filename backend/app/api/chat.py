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
import json
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.agent import core as agent_core
from app.agent.model_registry import AVAILABLE_MODELS, DEFAULT_MODEL_ID, get_model
from app.auth import require_auth
from app.clients import google_docs
from app.models import (
    AudioClip,
    BugReport,
    Conversation,
    ConversationMessage,
    OAuthToken,
    get_engine,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
conversations_router = APIRouter(prefix="/api/conversations", tags=["conversations"])
models_router = APIRouter(prefix="/api/models", tags=["models"])

TITLE_MAX_LENGTH = 60


class ChatRequest(BaseModel):
    conversation_id: int
    message: str


class ChatResponse(BaseModel):
    reply: str
    payloads: list[dict]


class CreateConversationRequest(BaseModel):
    model: str = DEFAULT_MODEL_ID


class UpdateConversationRequest(BaseModel):
    model: str


def _conversation_to_dict(conversation: Conversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "model": conversation.model,
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


def _display_text(content) -> str | None:
    if isinstance(content, str):
        return content
    texts = [block["text"] for block in content if block.get("type") == "text"]
    return "\n".join(texts) if texts else None


def _extract_payloads(new_messages: list[dict], engine) -> list[dict]:
    """Pull frontend-renderable structured payloads (audio options, created
    cards) out of this turn's tool calls, keyed by matching each tool_use
    block to its tool_result by `tool_use_id`."""

    tool_results: dict[str, object] = {}
    for message in new_messages:
        if message["role"] != "user" or isinstance(message["content"], str):
            continue
        for block in message["content"]:
            if block.get("type") == "tool_result":
                try:
                    tool_results[block["tool_use_id"]] = json.loads(block["content"])
                except (TypeError, json.JSONDecodeError):
                    tool_results[block["tool_use_id"]] = block["content"]

    payloads: list[dict] = []
    for message in new_messages:
        if message["role"] != "assistant" or isinstance(message["content"], str):
            continue
        for block in message["content"]:
            if block.get("type") != "tool_use":
                continue
            result = tool_results.get(block["id"])
            tool_input = block["input"]
            if block["name"] == "generate_audio":
                clip_ids = (
                    result.get("clip_ids", []) if isinstance(result, dict) else []
                )
                options = []
                if clip_ids:
                    with Session(engine) as session:
                        clips_by_id = {
                            clip.id: clip
                            for clip in session.exec(
                                select(AudioClip).where(AudioClip.id.in_(clip_ids))
                            ).all()
                        }
                    options = [
                        base64.b64encode(clips_by_id[cid].audio).decode("ascii")
                        for cid in clip_ids
                        if cid in clips_by_id
                    ]
                payloads.append(
                    {
                        "type": "audio_options",
                        "text": tool_input.get("text"),
                        "clip_ids": clip_ids,
                        "options": options,
                    }
                )
            elif block["name"] == "create_anki_note":
                payloads.append(
                    {
                        "type": "card",
                        "deck_name": tool_input.get("deck_name"),
                        "model_name": tool_input.get("model_name"),
                        "fields": tool_input.get("fields"),
                        "tags": tool_input.get("tags"),
                        "note_id": (result or {}).get("note_id")
                        if isinstance(result, dict)
                        else None,
                    }
                )
    return payloads


async def _get_access_token(email: str) -> str:
    """Return a fresh Google access token for `email`, refreshing it via
    `google_docs.refresh_access_token` first if it has expired."""

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
        first_message = not prior_rows
    history = [{"role": row.role, "content": json.loads(row.content)} for row in prior_rows]

    access_token = await _get_access_token(email)
    try:
        result = await agent_core.run_turn(
            history, body.message, access_token=access_token, model_id=conversation.model
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

    with Session(engine) as session:
        for message in new_messages:
            session.add(
                ConversationMessage(
                    conversation_id=body.conversation_id,
                    role=message["role"],
                    content=json.dumps(message["content"]),
                )
            )
        conversation = session.get(Conversation, body.conversation_id)
        conversation.updated_at = datetime.now(timezone.utc)
        if first_message and conversation.title is None:
            conversation.title = _title_from_message(body.message)
        session.add(conversation)
        session.commit()

    return ChatResponse(
        reply=result["reply"], payloads=_extract_payloads(new_messages, engine)
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

    transcript = []
    for row in rows:
        text = _display_text(json.loads(row.content))
        if text is not None:
            transcript.append({"role": row.role, "text": text})
    return transcript


@conversations_router.post("")
async def create_conversation(
    body: CreateConversationRequest = CreateConversationRequest(),
    email: str = Depends(require_auth),
) -> dict:
    try:
        get_model(body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = get_engine()
    with Session(engine) as session:
        conversation = Conversation(model=body.model)
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
    try:
        get_model(body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = get_engine()
    with Session(engine) as session:
        conversation = _get_conversation_or_404(session, conversation_id)
        conversation.model = body.model
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
    return _conversation_to_dict(conversation)


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
