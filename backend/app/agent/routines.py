"""CRUD and schedule helpers for recurring agent routines."""

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.models import Routine, get_engine

SCHEDULE_UNITS = {"hourly", "daily", "weekly"}


def _validate_schedule(
    schedule_unit: str,
    schedule_interval: int,
    schedule_time: str | None,
    schedule_day_of_week: int | None,
) -> None:
    if schedule_unit not in SCHEDULE_UNITS:
        raise ValueError("schedule_unit must be hourly, daily, or weekly")
    if schedule_interval < 1:
        raise ValueError("schedule_interval must be at least 1")
    if schedule_unit == "hourly":
        if schedule_time is not None or schedule_day_of_week is not None:
            raise ValueError("hourly schedules cannot set a time or day of week")
        return
    if schedule_time is None:
        raise ValueError(f"{schedule_unit} schedules require schedule_time")
    try:
        hour_text, minute_text = schedule_time.split(":")
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("schedule_time must use HH:MM") from exc
    if (
        len(schedule_time) != 5
        or schedule_time[2] != ":"
        or not 0 <= hour <= 23
        or not 0 <= minute <= 59
    ):
        raise ValueError("schedule_time must use HH:MM")
    if schedule_unit == "daily" and schedule_day_of_week is not None:
        raise ValueError("daily schedules cannot set a day of week")
    if schedule_unit == "weekly" and (
        schedule_day_of_week is None or not 0 <= schedule_day_of_week <= 6
    ):
        raise ValueError("weekly schedules require a day of week from 0 to 6")


def compute_next_run_at(schedule: Routine | dict, from_time: datetime) -> datetime:
    """Return the first scheduled instant strictly after ``from_time``.

    Weekdays follow Python's convention (Monday=0). Naive datetimes are
    treated as UTC; aware datetimes retain their timezone.
    """

    get = (
        (lambda key: getattr(schedule, key))
        if isinstance(schedule, Routine)
        else schedule.__getitem__
    )
    unit = get("schedule_unit")
    interval = get("schedule_interval")
    schedule_time = get("schedule_time")
    day_of_week = get("schedule_day_of_week")
    _validate_schedule(unit, interval, schedule_time, day_of_week)

    if from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=timezone.utc)
    if unit == "hourly":
        return from_time + timedelta(hours=interval)

    hour, minute = map(int, schedule_time.split(":"))
    candidate = from_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if unit == "daily":
        if candidate <= from_time:
            candidate += timedelta(days=interval)
        return candidate

    days_ahead = (day_of_week - from_time.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= from_time:
        candidate += timedelta(weeks=interval)
    return candidate


def create_routine(
    *,
    name: str,
    prompt: str,
    schedule_unit: str,
    schedule_interval: int,
    schedule_time: str | None,
    schedule_day_of_week: int | None,
    conversation_id: int,
    enabled: bool = True,
    from_time: datetime | None = None,
) -> Routine:
    now = from_time or datetime.now(timezone.utc)
    schedule = {
        "schedule_unit": schedule_unit,
        "schedule_interval": schedule_interval,
        "schedule_time": schedule_time,
        "schedule_day_of_week": schedule_day_of_week,
    }
    routine = Routine(
        name=name,
        prompt=prompt,
        conversation_id=conversation_id,
        enabled=enabled,
        next_run_at=compute_next_run_at(schedule, now),
        **schedule,
    )
    with Session(get_engine()) as session:
        session.add(routine)
        session.commit()
        session.refresh(routine)
        return routine


def update_routine(routine_id: int, **changes) -> Routine | None:
    allowed = {
        "name",
        "prompt",
        "schedule_unit",
        "schedule_interval",
        "schedule_time",
        "schedule_day_of_week",
        "enabled",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Unknown routine fields: {', '.join(sorted(unknown))}")
    with Session(get_engine()) as session:
        routine = session.get(Routine, routine_id)
        if routine is None:
            return None
        for field, value in changes.items():
            setattr(routine, field, value)
        _validate_schedule(
            routine.schedule_unit,
            routine.schedule_interval,
            routine.schedule_time,
            routine.schedule_day_of_week,
        )
        if set(changes) & {
            "schedule_unit",
            "schedule_interval",
            "schedule_time",
            "schedule_day_of_week",
        }:
            routine.next_run_at = compute_next_run_at(
                routine, datetime.now(timezone.utc)
            )
        routine.updated_at = datetime.now(timezone.utc)
        session.add(routine)
        session.commit()
        session.refresh(routine)
        return routine


def list_routines() -> list[Routine]:
    with Session(get_engine()) as session:
        return list(session.exec(select(Routine).order_by(Routine.name)).all())


def get_routine(routine_id: int) -> Routine | None:
    with Session(get_engine()) as session:
        return session.get(Routine, routine_id)


def delete_routine(routine_id: int) -> bool:
    with Session(get_engine()) as session:
        routine = session.get(Routine, routine_id)
        if routine is None:
            return False
        session.delete(routine)
        session.commit()
        return True
