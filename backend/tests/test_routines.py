from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from app.agent.routines import (
    compute_next_run_at,
    create_routine,
    delete_routine,
    get_routine,
    list_routines,
    update_routine,
)
from app.models import Conversation, init_db


@pytest.fixture()
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "routines.db"))
    engine = init_db()
    with Session(engine) as session:
        conversation = Conversation(title="Routine home")
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        yield conversation.id


def test_compute_next_hourly_run() -> None:
    now = datetime(2026, 7, 27, 10, 15, tzinfo=timezone.utc)
    assert compute_next_run_at(
        {
            "schedule_unit": "hourly",
            "schedule_interval": 3,
            "schedule_time": None,
            "schedule_day_of_week": None,
        },
        now,
    ) == datetime(2026, 7, 27, 13, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 7, 27, 7, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 27, 8, 30, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 7, 27, 8, 30, tzinfo=timezone.utc),
            datetime(2026, 7, 29, 8, 30, tzinfo=timezone.utc),
        ),
    ],
)
def test_compute_next_daily_run(now, expected) -> None:
    assert compute_next_run_at(
        {
            "schedule_unit": "daily",
            "schedule_interval": 2,
            "schedule_time": "08:30",
            "schedule_day_of_week": None,
        },
        now,
    ) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 7, 27, 7, 0, tzinfo=timezone.utc),  # Monday
            datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc),  # Wednesday
        ),
        (
            datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_compute_next_weekly_run(now, expected) -> None:
    assert compute_next_run_at(
        {
            "schedule_unit": "weekly",
            "schedule_interval": 2,
            "schedule_time": "09:00",
            "schedule_day_of_week": 2,
        },
        now,
    ) == expected


def test_routine_crud(database) -> None:
    now = datetime(2026, 7, 27, 7, 0, tzinfo=timezone.utc)
    routine = create_routine(
        name="Daily review",
        prompt="Review yesterday's cards",
        schedule_unit="daily",
        schedule_interval=1,
        schedule_time="08:00",
        schedule_day_of_week=None,
        conversation_id=database,
        from_time=now,
    )
    assert routine.next_run_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 27, 8, 0, tzinfo=timezone.utc
    )
    assert get_routine(routine.id).prompt == "Review yesterday's cards"
    assert [item.name for item in list_routines()] == ["Daily review"]

    updated = update_routine(routine.id, prompt="Find leeches", enabled=False)
    assert updated.prompt == "Find leeches"
    assert updated.enabled is False
    assert delete_routine(routine.id) is True
    assert get_routine(routine.id) is None
    assert delete_routine(routine.id) is False


def test_schedule_validation_rejects_invalid_weekday() -> None:
    with pytest.raises(ValueError, match="day of week"):
        compute_next_run_at(
            {
                "schedule_unit": "weekly",
                "schedule_interval": 1,
                "schedule_time": "09:00",
                "schedule_day_of_week": 7,
            },
            datetime(2026, 7, 27, tzinfo=timezone.utc),
        )
