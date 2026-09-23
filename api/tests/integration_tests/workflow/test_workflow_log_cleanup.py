"""Run against a disposable PostgreSQL database via WORKFLOW_CLEANUP_TEST_DATABASE_URL."""

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session

from models.workflow import WorkflowAppLog, WorkflowNodeExecution, WorkflowRun
from services.workflow_log_cleanup_service import WorkflowLogCleanupService

CUTOFF = datetime(2026, 8, 24)
OLD = CUTOFF - timedelta(days=1)
NEW = CUTOFF + timedelta(days=1)
MODELS = (WorkflowRun, WorkflowNodeExecution, WorkflowAppLog)
INDEX_NAMES = {
    "workflow_run_finished_at_idx",
    "workflow_node_execution_run_id_idx",
    "workflow_node_execution_single_step_finished_idx",
    "workflow_app_log_run_id_idx",
}


@pytest.fixture
def engine():
    url = os.environ.get("WORKFLOW_CLEANUP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set WORKFLOW_CLEANUP_TEST_DATABASE_URL to a disposable PostgreSQL database")
    admin = create_engine(url)
    schema = "cleanup_test_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Match the model's UUID default without installing database-wide extensions.
        conn.execute(
            text(
                f'CREATE FUNCTION "{schema}".uuid_generate_v4() RETURNS uuid '
                "LANGUAGE SQL AS 'SELECT gen_random_uuid()'"
            )
        )
    test_engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    try:
        with test_engine.begin() as conn:
            for model in MODELS:
                model.__table__.create(conn)
        yield test_engine
    finally:
        test_engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def add_run(engine, *, status="succeeded", finished_at=OLD, triggered_from="app-run"):
    run_id = str(uuid4())
    common = {"tenant_id": str(uuid4()), "app_id": str(uuid4()), "workflow_id": str(uuid4())}
    creator = {"created_by_role": "account", "created_by": str(uuid4())}
    with engine.begin() as conn:
        conn.execute(
            WorkflowRun.__table__.insert().values(
                id=run_id,
                **common,
                **creator,
                sequence_number=1,
                type="workflow",
                triggered_from=triggered_from,
                version="1",
                status=status,
                created_at=OLD - timedelta(days=1),
                finished_at=finished_at,
                graph='{"nodes": []}',
                outputs='{"result": "test"}',
            )
        )
        conn.execute(
            WorkflowNodeExecution.__table__.insert().values(
                id=str(uuid4()),
                **common,
                **creator,
                workflow_run_id=run_id,
                triggered_from="workflow-run",
                index=1,
                node_id="start",
                node_type="start",
                title="start",
                status="succeeded",
                created_at=OLD,
                finished_at=OLD,
                outputs='{"result": "node test"}',
            )
        )
        conn.execute(
            WorkflowAppLog.__table__.insert().values(
                id=str(uuid4()), **common, **creator, workflow_run_id=run_id, created_from="service-api"
            )
        )
    return run_id


def counts(engine):
    with engine.connect() as conn:
        return tuple(conn.scalar(select(func.count()).select_from(model)) for model in MODELS)


@pytest.mark.parametrize("status", ["succeeded", "failed", "stopped", "partial-succeeded"])
@pytest.mark.parametrize("triggered_from", ["app-run", "debugging"])
def test_expired_terminal_runs_and_children_are_deleted(engine, status, triggered_from):
    add_run(engine, status=status, triggered_from=triggered_from)
    with Session(engine) as session:
        assert WorkflowLogCleanupService.delete_runs_batch(session, CUTOFF, 100) == (1, 1, 1)
    assert counts(engine) == (0, 0, 0)


def test_running_recent_boundary_and_missing_finish_are_preserved(engine):
    add_run(engine, status="running")
    add_run(engine, finished_at=NEW)
    add_run(engine, finished_at=CUTOFF)
    add_run(engine, finished_at=None)
    with Session(engine) as session:
        assert WorkflowLogCleanupService.delete_runs_batch(session, CUTOFF, 100) == (0, 0, 0)
        assert WorkflowLogCleanupService.delete_single_step_batch(session, CUTOFF, 100) == 0
    assert counts(engine) == (4, 4, 4)


def test_batches_are_bounded_and_repeated_cleanup_is_idempotent(engine):
    for _ in range(5):
        add_run(engine)
    with Session(engine) as session:
        for size in (2, 2, 1, 0):
            assert WorkflowLogCleanupService.delete_runs_batch(session, CUTOFF, 2) == (size, size, size)
    assert counts(engine) == (0, 0, 0)


def test_failure_rolls_back_children_and_parent_together(engine):
    add_run(engine)

    def fail_parent_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM workflow_runs"):
            raise RuntimeError("simulated database failure")

    event.listen(engine, "before_cursor_execute", fail_parent_delete)
    try:
        with Session(engine) as session, pytest.raises(RuntimeError, match="simulated database failure"):
            WorkflowLogCleanupService.delete_runs_batch(session, CUTOFF, 100)
    finally:
        event.remove(engine, "before_cursor_execute", fail_parent_delete)
    assert counts(engine) == (1, 1, 1)


def test_locked_runs_are_skipped(engine):
    locked_id = add_run(engine)
    add_run(engine)
    with Session(engine) as owner, owner.begin():
        owner.execute(select(WorkflowRun.id).where(WorkflowRun.id == locked_id).with_for_update())
        with Session(engine) as cleaner:
            assert WorkflowLogCleanupService.delete_runs_batch(cleaner, CUTOFF, 100) == (1, 1, 1)
    assert counts(engine) == (1, 1, 1)


def test_single_step_cleanup_preserves_live_and_unrelated_nodes(engine):
    cases = [
        ("succeeded", OLD, "single-step"),
        ("failed", OLD, "single-step"),
        ("exception", OLD, "single-step"),
        ("running", OLD, "single-step"),
        ("retry", OLD, "single-step"),
        ("succeeded", NEW, "single-step"),
        ("succeeded", CUTOFF, "single-step"),
        ("succeeded", None, "single-step"),
        ("succeeded", OLD, "workflow-run"),
    ]
    with engine.begin() as conn:
        for status, finished_at, triggered_from in cases:
            conn.execute(
                WorkflowNodeExecution.__table__.insert().values(
                    id=str(uuid4()),
                    tenant_id=str(uuid4()),
                    app_id=str(uuid4()),
                    workflow_id=str(uuid4()),
                    created_by_role="account",
                    created_by=str(uuid4()),
                    triggered_from=triggered_from,
                    index=1,
                    node_id="start",
                    node_type="start",
                    title="start",
                    status=status,
                    created_at=OLD,
                    finished_at=finished_at,
                )
            )
    with Session(engine) as session:
        for size in (2, 1, 0):
            assert WorkflowLogCleanupService.delete_single_step_batch(session, CUTOFF, 2) == size
    assert counts(engine) == (0, 6, 0)


def test_cleanup_index_migration_upgrade_and_downgrade(engine):
    path = (
        Path(__file__).parents[3]
        / "migrations/versions/2026_09_23_0000-c9d8e7f6a5b4_add_workflow_log_cleanup_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("cleanup_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            with context.begin_transaction():
                migration.downgrade()
            with context.begin_transaction():
                migration.upgrade()
            names = {index["name"] for model in MODELS for index in inspect(conn).get_indexes(model.__tablename__)}
            assert names >= INDEX_NAMES
            conn.commit()
            with context.begin_transaction():
                migration.downgrade()
            names = {index["name"] for model in MODELS for index in inspect(conn).get_indexes(model.__tablename__)}
            assert not INDEX_NAMES & names
