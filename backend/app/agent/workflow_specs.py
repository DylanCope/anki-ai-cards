"""CRUD helpers over the `WorkflowSpec` table (task 2's persistence layer).

Backs the `save_workflow_spec`/`load_workflow_spec`/`list_workflow_specs`
agent tools. Plain synchronous SQLModel session calls, same as every other
DB access in this project (see `app/models.py`'s "Learned" note in
PROGRESS.md on why the engine is sync even though the rest of the stack is
async) — `dispatch_tool` is async but calls these directly rather than
through a threadpool, which is fine for single-user SQLite.
"""

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models import WorkflowSpec, get_engine


def save_workflow_spec(name: str, spec: str) -> WorkflowSpec:
    """Create or update the named workflow spec (upsert by `name`)."""

    engine = get_engine()
    with Session(engine) as session:
        existing = session.exec(
            select(WorkflowSpec).where(WorkflowSpec.name == name)
        ).one_or_none()
        if existing is not None:
            existing.spec = spec
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

        workflow_spec = WorkflowSpec(name=name, spec=spec)
        session.add(workflow_spec)
        session.commit()
        session.refresh(workflow_spec)
        return workflow_spec


def load_workflow_spec(name: str) -> WorkflowSpec | None:
    engine = get_engine()
    with Session(engine) as session:
        return session.exec(
            select(WorkflowSpec).where(WorkflowSpec.name == name)
        ).one_or_none()


def list_workflow_specs() -> list[WorkflowSpec]:
    engine = get_engine()
    with Session(engine) as session:
        return list(session.exec(select(WorkflowSpec)).all())


def rename_workflow_spec(name: str, new_name: str) -> WorkflowSpec | None:
    """Rename the named workflow spec in place. Returns None if it doesn't exist.

    Raises ValueError if `new_name` is already taken by a different spec.
    """

    engine = get_engine()
    with Session(engine) as session:
        existing = session.exec(
            select(WorkflowSpec).where(WorkflowSpec.name == name)
        ).one_or_none()
        if existing is None:
            return None
        if new_name != name:
            conflict = session.exec(
                select(WorkflowSpec).where(WorkflowSpec.name == new_name)
            ).one_or_none()
            if conflict is not None:
                raise ValueError(f"A workflow named {new_name!r} already exists")
        existing.name = new_name
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing


def delete_workflow_spec(name: str) -> bool:
    """Delete the named workflow spec. Returns False if it didn't exist."""

    engine = get_engine()
    with Session(engine) as session:
        existing = session.exec(
            select(WorkflowSpec).where(WorkflowSpec.name == name)
        ).one_or_none()
        if existing is None:
            return False
        session.delete(existing)
        session.commit()
        return True
