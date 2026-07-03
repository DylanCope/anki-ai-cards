from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.models import (
    ConversationMessage,
    OAuthToken,
    PendingCard,
    ProcessingCursor,
    WorkflowSpec,
    init_db,
)


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    return init_db()


def test_conversation_message_roundtrip(engine) -> None:
    with Session(engine) as session:
        session.add(ConversationMessage(role="user", content="hello"))
        session.commit()

    with Session(engine) as session:
        message = session.exec(select(ConversationMessage)).one()
        assert message.role == "user"
        assert message.content == "hello"


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
