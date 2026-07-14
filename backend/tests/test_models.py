import json
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, create_engine, select

from app.models import (
    AudioClip,
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


def test_conversation_instant_creation_defaults_to_false(engine) -> None:
    with Session(engine) as session:
        session.add(Conversation(title="Lesson doc cards"))
        session.commit()

    with Session(engine) as session:
        conversation = session.exec(select(Conversation)).one()
        assert conversation.instant_creation is False


def test_conversation_instant_creation_can_be_set_explicitly(engine) -> None:
    with Session(engine) as session:
        session.add(Conversation(instant_creation=True))
        session.commit()

    with Session(engine) as session:
        conversation = session.exec(select(Conversation)).one()
        assert conversation.instant_creation is True


def test_init_db_migrates_a_pre_instant_creation_database(tmp_path, monkeypatch) -> None:
    # Simulate a database from before instant_creation existed: a real
    # conversation table (with the model column already present) but no
    # instant_creation column. init_db() must add it and backfill existing
    # rows to 0 (off) rather than erroring.
    db_path = tmp_path / "pre_instant_creation.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    legacy_engine = create_engine(f"sqlite:///{db_path}")
    with legacy_engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE conversation ("
            "id INTEGER PRIMARY KEY, title TEXT, model TEXT, "
            "created_at TEXT, updated_at TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO conversation (title, model, created_at, updated_at) "
            "VALUES ('Old conversation', 'gemini-3.1-flash-lite', "
            "'2026-07-01T00:00:00', '2026-07-01T00:00:00')"
        )
        conn.commit()

    engine = init_db()

    with Session(engine) as session:
        conversation = session.exec(select(Conversation)).one()
        assert conversation.instant_creation is False

    # Idempotent, and doesn't clobber a value already set on a real row.
    with Session(engine) as session:
        conversation.instant_creation = True
        session.add(conversation)
        session.commit()
    init_db()
    with Session(engine) as session:
        assert session.exec(select(Conversation)).one().instant_creation is True


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
                deck_name="Japanese",
                model_name="Cloze",
                fields=json.dumps({"Text": "{{c1::食べます}}", "Extra": "to eat"}),
                tags=json.dumps(["lesson-doc"]),
            )
        )
        session.commit()

    with Session(engine) as session:
        card = session.exec(select(PendingCard)).one()
        assert json.loads(card.fields) == {"Text": "{{c1::食べます}}", "Extra": "to eat"}
        assert json.loads(card.tags) == ["lesson-doc"]
        assert card.status == "pending"
        assert card.note_id is None


def test_pending_card_tags_default_to_none(engine) -> None:
    with Session(engine) as session:
        session.add(
            PendingCard(
                deck_name="Japanese",
                model_name="Cloze",
                fields=json.dumps({"Text": "{{c1::食べます}}"}),
            )
        )
        session.commit()

    with Session(engine) as session:
        card = session.exec(select(PendingCard)).one()
        assert card.tags is None


def test_pending_card_status_can_be_set_to_created(engine) -> None:
    with Session(engine) as session:
        session.add(
            PendingCard(
                deck_name="Japanese",
                model_name="Cloze",
                fields=json.dumps({"Text": "{{c1::食べます}}"}),
                status="created",
                note_id=12345,
            )
        )
        session.commit()

    with Session(engine) as session:
        card = session.exec(select(PendingCard)).one()
        assert card.status == "created"
        assert card.note_id == 12345


def test_init_db_rebuilds_a_stale_pendingcard_table(tmp_path, monkeypatch) -> None:
    # Simulate a database with the old task-2 PendingCard schema
    # (japanese_cloze/furigana/english/note, no deck_name column at all).
    # Since no real app code ever wrote to that shape, init_db() must drop
    # and recreate the table with the new schema rather than erroring.
    db_path = tmp_path / "pre_rebuild_pendingcard.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    legacy_engine = create_engine(f"sqlite:///{db_path}")
    with legacy_engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE pendingcard ("
            "id INTEGER PRIMARY KEY, japanese_cloze TEXT, furigana TEXT, "
            "english TEXT, note TEXT, status TEXT, created_at TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO pendingcard (japanese_cloze, furigana, english, status, created_at) "
            "VALUES ('{{c1::食べます}}', 'たべます', 'to eat', 'pending', '2026-07-01T00:00:00')"
        )
        conn.commit()

    engine = init_db()

    with Session(engine) as session:
        assert session.exec(select(PendingCard)).all() == []
        session.add(
            PendingCard(
                deck_name="Japanese",
                model_name="Cloze",
                fields=json.dumps({"Text": "{{c1::食べます}}"}),
            )
        )
        session.commit()

    with Session(engine) as session:
        card = session.exec(select(PendingCard)).one()
        assert card.deck_name == "Japanese"

    # Idempotent: running it again on an already-rebuilt database is a no-op.
    init_db()
    with Session(engine) as session:
        assert len(session.exec(select(PendingCard)).all()) == 1


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


def test_audio_clip_source_defaults_to_generate(engine) -> None:
    with Session(engine) as session:
        session.add(AudioClip(text="こんにちは", voice="male", audio=b"aaa"))
        session.commit()

    with Session(engine) as session:
        clip = session.exec(select(AudioClip)).one()
        assert clip.source == "generate"


def test_audio_clip_source_can_be_set_explicitly(engine) -> None:
    with Session(engine) as session:
        session.add(
            AudioClip(text="こんにちは", voice="native", audio=b"aaa", source="tatoeba")
        )
        session.commit()

    with Session(engine) as session:
        clip = session.exec(select(AudioClip)).one()
        assert clip.source == "tatoeba"


def test_init_db_migrates_a_pre_source_audioclip_database(tmp_path, monkeypatch) -> None:
    # Simulate a database from before AudioClip.source existed: a real
    # audioclip table with no `source` column. init_db() must add the
    # column and backfill existing rows to 'generate' (the only origin that
    # existed before this column was added) rather than erroring or leaving
    # them without a source.
    db_path = tmp_path / "pre_source_audioclip.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    legacy_engine = create_engine(f"sqlite:///{db_path}")
    with legacy_engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE audioclip ("
            "id INTEGER PRIMARY KEY, text TEXT, voice TEXT, audio BLOB, created_at TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO audioclip (text, voice, audio, created_at) "
            "VALUES ('こんにちは', 'male', X'6161', '2026-07-01T00:00:00')"
        )
        conn.commit()

    engine = init_db()

    with Session(engine) as session:
        clip = session.exec(select(AudioClip)).one()
        assert clip.source == "generate"

    # Idempotent: running it again on an already-migrated database is a
    # no-op, not an error.
    init_db()
