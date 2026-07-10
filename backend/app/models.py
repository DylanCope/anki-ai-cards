"""SQLModel table definitions and database setup.

Engine/session creation reads `DATABASE_PATH` lazily (at call time, not import
time) so tests can point it at a temp file via `monkeypatch.setenv` before
calling `init_db()`.
"""

import os
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel, create_engine


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    role: str
    content: str
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
    voice: str
    audio: bytes
    created_at: datetime = Field(default_factory=_utcnow)


def get_engine():
    database_path = os.environ["DATABASE_PATH"]
    return create_engine(f"sqlite:///{database_path}")


def init_db():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    return engine
