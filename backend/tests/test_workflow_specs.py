import pytest

from app.agent import workflow_specs
from app.models import init_db


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    return init_db()


def test_save_and_load_roundtrip(engine) -> None:
    saved = workflow_specs.save_workflow_spec("lesson-doc", '{"foo": "bar"}')
    assert saved.name == "lesson-doc"
    assert saved.spec == '{"foo": "bar"}'

    loaded = workflow_specs.load_workflow_spec("lesson-doc")
    assert loaded is not None
    assert loaded.name == "lesson-doc"
    assert loaded.spec == '{"foo": "bar"}'


def test_save_upserts_existing_name(engine) -> None:
    workflow_specs.save_workflow_spec("lesson-doc", "v1")
    workflow_specs.save_workflow_spec("lesson-doc", "v2")

    loaded = workflow_specs.load_workflow_spec("lesson-doc")
    assert loaded is not None
    assert loaded.spec == "v2"

    all_specs = workflow_specs.list_workflow_specs()
    assert len(all_specs) == 1


def test_load_missing_returns_none(engine) -> None:
    assert workflow_specs.load_workflow_spec("does-not-exist") is None


def test_list_workflow_specs(engine) -> None:
    assert workflow_specs.list_workflow_specs() == []

    workflow_specs.save_workflow_spec("lesson-doc", "spec-a")
    workflow_specs.save_workflow_spec("other-source", "spec-b")

    names = sorted(spec.name for spec in workflow_specs.list_workflow_specs())
    assert names == ["lesson-doc", "other-source"]


def test_save_bumps_updated_at_on_upsert(engine) -> None:
    original = workflow_specs.save_workflow_spec("lesson-doc", "v1")
    updated = workflow_specs.save_workflow_spec("lesson-doc", "v2")

    assert updated.updated_at >= original.updated_at
    assert updated.created_at == original.created_at


def test_delete_workflow_spec(engine) -> None:
    workflow_specs.save_workflow_spec("lesson-doc", "v1")

    assert workflow_specs.delete_workflow_spec("lesson-doc") is True
    assert workflow_specs.load_workflow_spec("lesson-doc") is None


def test_delete_missing_workflow_spec_returns_false(engine) -> None:
    assert workflow_specs.delete_workflow_spec("does-not-exist") is False
