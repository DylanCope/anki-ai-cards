"""SQLModel table definitions and database setup.

Engine/session creation reads `DATABASE_PATH` lazily (at call time, not import
time) so tests can point it at a temp file via `monkeypatch.setenv` before
calling `init_db()`.
"""

import os
from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, create_engine, select


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#  Keep in sync with app.agent.model_registry.DEFAULT_MODEL_ID — duplicated
# as a plain string here (rather than imported) so this persistence module
# doesn't depend on the agent layer.
_DEFAULT_MODEL_ID = "gemini-3.1-flash-lite"


class Conversation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # None until the first user message arrives, then set once from a
    # truncated snippet of it — see app.api.chat's post_chat.
    title: str | None = Field(default=None)
    model: str = Field(default=_DEFAULT_MODEL_ID)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ConversationMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # Nullable for backward compatibility with rows written before multiple
    # conversations existed — init_db() backfills any such rows into a
    # single legacy Conversation on first startup after upgrade, so this is
    # only ever NULL on a database that hasn't been migrated yet.
    conversation_id: int | None = Field(
        default=None, foreign_key="conversation.id", index=True
    )
    role: str
    content: str
    # Set only on the one user message a given `POST /api/chat` call attached
    # an upload to (via `ChatRequest.image_id`) — lets the chat transcript
    # render that image inline with the message it was sent with, even after
    # a page reload. See app.api.chat's image_id handling.
    image_id: int | None = Field(default=None, foreign_key="imageasset.id")
    created_at: datetime = Field(default_factory=_utcnow)


class WorkflowSpec(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    spec: str
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ProcessingCursor(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_id: str = Field(unique=True, index=True)
    position: str
    updated_at: datetime = Field(default_factory=_utcnow)


class PendingCard(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    japanese_cloze: str
    furigana: str
    english: str
    note: str | None = Field(default=None)
    status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=_utcnow)


class OAuthToken(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    access_token: str
    refresh_token: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=_utcnow)


class BugReport(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    message: str
    detail: str
    created_at: datetime = Field(default_factory=_utcnow)


class AudioClip(SQLModel, table=True):
    """A single ElevenLabs-generated audio take, persisted server-side so a
    later create_anki_note call can attach it by id (`clip_id`) instead of
    the model having to reproduce the raw audio bytes itself — see
    app.agent.tools.dispatch_tool's generate_audio/create_anki_note handling."""

    id: int | None = Field(default=None, primary_key=True)
    text: str
    # For "tatoeba"/"forvo" clips, holds the sentence's/pronunciation's
    # contributor or speaker attribution (a Tatoeba username, a Forvo
    # username) when available, or a fixed placeholder like "native" when
    # not — kept as a required str rather than making it nullable, so no
    # SQLite column-nullability migration is needed for the "generate" case,
    # which already always has a real ElevenLabs voice name.
    voice: str
    audio: bytes
    source: str = Field(default="generate")  # "generate" / "tatoeba" / "forvo"
    created_at: datetime = Field(default_factory=_utcnow)


class ImageAsset(SQLModel, table=True):
    """An image (uploaded, searched, or generated), persisted server-side so
    a later create_anki_note call can attach it by id (`image_id`) — same
    pattern as AudioClip. The agent never sees the raw bytes, only this id;
    it's referenced via a plain text mention in the user's message (see
    app.api.chat.post_chat's image_id handling), never sent to Claude as
    multimodal input."""

    id: int | None = Field(default=None, primary_key=True)
    content_type: str
    data: bytes
    source: str  # "upload" / "search" / "generate"
    created_at: datetime = Field(default_factory=_utcnow)


def get_engine():
    database_path = os.environ["DATABASE_PATH"]
    return create_engine(f"sqlite:///{database_path}")


def _add_conversation_id_column_if_missing(engine) -> None:
    """`create_all()` only creates whole missing tables, never alters an
    existing one — this project has no migration framework, so a column
    added to an already-deployed table (like `conversation_id` here) needs
    its own explicit, idempotent ALTER TABLE, or the real production
    database (which predates the `Conversation` table) would keep 404ing on
    `conversation_id` forever."""

    with engine.connect() as conn:
        columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversationmessage)")
        }
        if "conversation_id" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE conversationmessage ADD COLUMN conversation_id INTEGER"
            )
            conn.commit()


def _add_conversation_model_column_if_missing(engine) -> None:
    """Same rationale as `_add_conversation_id_column_if_missing` — adding
    model selection to an already-deployed `Conversation` table needs its
    own ALTER TABLE. Existing rows backfill to the prior hardcoded default
    (Opus 4.8), preserving today's behavior for conversations that predate
    model selection."""

    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation)")}
        if "model" not in columns:
            conn.exec_driver_sql(
                f"ALTER TABLE conversation ADD COLUMN model TEXT NOT NULL DEFAULT '{_DEFAULT_MODEL_ID}'"
            )
            conn.commit()


def _add_conversation_message_image_id_column_if_missing(engine) -> None:
    """Same rationale as `_add_conversation_id_column_if_missing` — the
    `image_id` column (added so an uploaded image renders inline with the
    message it was sent with, see app.api.chat) needs its own ALTER TABLE on
    an already-deployed `conversationmessage` table. Existing rows backfill
    to NULL, which just means older messages render exactly as they do
    today (no attachment)."""

    with engine.connect() as conn:
        columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversationmessage)")
        }
        if "image_id" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE conversationmessage ADD COLUMN image_id INTEGER"
            )
            conn.commit()


def _add_audioclip_source_column_if_missing(engine) -> None:
    """Same rationale as `_add_conversation_id_column_if_missing` — the
    `source` column (added so an AudioClip can record whether it came from
    ElevenLabs generation, Tatoeba, or Forvo — see app.agent.tools) needs its
    own ALTER TABLE on an already-deployed `audioclip` table. Existing rows
    (all pre-dating this column, so all ElevenLabs-generated) backfill to
    'generate', preserving their actual origin."""

    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(audioclip)")}
        if "source" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE audioclip ADD COLUMN source TEXT NOT NULL DEFAULT 'generate'"
            )
            conn.commit()


def _backfill_legacy_conversation(engine) -> None:
    """Any ConversationMessage row with no conversation_id predates the
    multi-conversation feature — group them all into one real Conversation
    so existing history is preserved (visible in the conversation list)
    rather than silently orphaned/hidden."""

    with Session(engine) as session:
        orphaned = session.exec(
            select(ConversationMessage).where(ConversationMessage.conversation_id == None)  # noqa: E711
        ).all()
        if not orphaned:
            return
        legacy = Conversation(title="Earlier conversation")
        session.add(legacy)
        session.commit()
        session.refresh(legacy)
        for row in orphaned:
            row.conversation_id = legacy.id
            session.add(row)
        session.commit()


def init_db():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _add_conversation_id_column_if_missing(engine)
    _add_conversation_model_column_if_missing(engine)
    _add_conversation_message_image_id_column_if_missing(engine)
    _add_audioclip_source_column_if_missing(engine)
    _backfill_legacy_conversation(engine)
    return engine
