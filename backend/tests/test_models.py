from datetime import datetime, timezone

import pytest
from sqlmodel import Session, create_engine, select

from app.models import (
    Conversation,
    ConversationMessage,
    OAuthToken,
    PendingCard,
    ProcessingCursor,
    WorkflowSpec,
    _DEFAULT_MODEL_ID,
    init_db,
)


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    return init_db()


def test_conversation_roundtrip(engine) -> None:
    with Session(engine) as session:
        session.add(Conversation(title="Lesson doc cards"))
        session.commit()

    with Session(engine) as session:
        conversation = session.exec(select(Conversation)).one()
        assert conversation.title == "Lesson doc cards"
        assert conversation.model == _DEFAULT_MODEL_ID


def test_conversation_model_can_be_set_explicitly(engine) -> None:
    with Session(engine) as session:
        session.add(Conversation(model="gemini-2.5-flash"))
        session.commit()

    with Session(engine) as session:
        conversation = session.exec(select(Conversation)).one()
        assert conversation.model == "gemini-2.5-flash"


def test_conversation_message_roundtrip(engine) -> None:
    with Session(engine) as session:
        session.add(Conversation())
        session.commit()
        conversation_id = session.exec(select(Conversation)).one().id
        session.add(
            ConversationMessage(
                conversation_id=conversation_id, role="user", content="hello"
            )
        )
        session.commit()

    with Session(engine) as session:
        message = session.exec(select(ConversationMessage)).one()
        assert message.conversation_id == conversation_id
        assert message.role == "user"
        assert message.content == "hello"


def test_init_db_migrates_a_pre_conversation_database(tmp_path, monkeypatch) -> None:
    # Simulate a database from before the Conversation table/column existed:
    # a conversationmessage table with no conversation_id column at all, one
    # real row in it. init_db() must add the column and fold that row into a
    # backfilled "legacy" conversation rather than losing it or erroring.
    db_path = tmp_path / "pre_migration.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    legacy_engine = create_engine(f"sqlite:///{db_path}")
    with legacy_engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE conversationmessage ("
            "id INTEGER PRIMARY KEY, role TEXT, content TEXT, created_at TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO conversationmessage (role, content, created_at) "
            "VALUES ('user', '\"hi from before\"', '2026-07-01T00:00:00')"
        )
        conn.commit()

    engine = init_db()

    with Session(engine) as session:
        conversations = session.exec(select(Conversation)).all()
        assert len(conversations) == 1
        assert conversations[0].title == "Earlier conversation"

        message = session.exec(select(ConversationMessage)).one()
        assert message.conversation_id == conversations[0].id
        assert message.content == '"hi from before"'

    # Idempotent: running it again on an already-migrated database is a no-op,
    # not a second legacy conversation.
    init_db()
    with Session(engine) as session:
        assert len(session.exec(select(Conversation)).all()) == 1


def test_init_db_migrates_a_pre_model_selection_database(tmp_path, monkeypatch) -> None:
    # Simulate a database from before model selection existed: a real
    # conversation table with no `model` column. init_db() must add the
    # column and backfill existing rows to the prior hardcoded default
    # (Opus 4.8) rather than erroring or leaving them without a model.
    db_path = tmp_path / "pre_model_selection.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    legacy_engine = create_engine(f"sqlite:///{db_path}")
    with legacy_engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE conversation ("
            "id INTEGER PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO conversation (title, created_at, updated_at) "
            "VALUES ('Old conversation', '2026-07-01T00:00:00', '2026-07-01T00:00:00')"
        )
        conn.commit()

    engine = init_db()

    with Session(engine) as session:
        conversation = session.exec(select(Conversation)).one()
        assert conversation.title == "Old conversation"
        assert conversation.model == _DEFAULT_MODEL_ID

    # Idempotent, and doesn't clobber a model already set on a real row.
    with Session(engine) as session:
        conversation.model = "gemini-2.5-flash"
        session.add(conversation)
        session.commit()
    init_db()
    with Session(engine) as session:
        assert session.exec(select(Conversation)).one().model == "gemini-2.5-flash"


def test_workflow_spec_roundtrip(engine) -> None:
    with Session(engine) as session:
        session.add(WorkflowSpec(name="lesson-doc", spec='{"foo": "bar"}'))
        session.commit()

    with Session(engine) as session:
        spec = session.exec(select(WorkflowSpec)).one()
        assert spec.name == "lesson-doc"
        assert spec.spec == '{"foo": "bar"}'


def test_processing_cursor_roundtrip(engine) -> None:
    with Session(engine) as session:
        session.add(ProcessingCursor(source_id="doc-123", position="para-4"))
        session.commit()

    with Session(engine) as session:
        cursor = session.exec(select(ProcessingCursor)).one()
        assert cursor.source_id == "doc-123"
        assert cursor.position == "para-4"


def test_pending_card_roundtrip(engine) -> None:
    with Session(engine) as session:
        session.add(
            PendingCard(
                japanese_cloze="{{c1::食べます}}",
                furigana="たべます",
                english="to eat",
            )
        )
        session.commit()

    with Session(engine) as session:
        card = session.exec(select(PendingCard)).one()
        assert card.japanese_cloze == "{{c1::食べます}}"
        assert card.status == "pending"


def test_oauth_token_roundtrip(engine) -> None:
    expires_at = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            OAuthToken(
                email="dylanr.cope@gmail.com",
                access_token="access",
                refresh_token="refresh",
                expires_at=expires_at,
            )
        )
        session.commit()

    with Session(engine) as session:
        token = session.exec(select(OAuthToken)).one()
        assert token.email == "dylanr.cope@gmail.com"
        assert token.access_token == "access"
