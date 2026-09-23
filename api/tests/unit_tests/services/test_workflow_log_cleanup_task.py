from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from configs.feature import CeleryBeatConfig
from dify_app import DifyApp
from extensions import ext_celery
from schedule import clean_workflow_logs as cleanup


@pytest.fixture
def task_dependencies(monkeypatch):
    monkeypatch.setattr(cleanup.dify_config, "WORKFLOW_LOG_CLEANUP_ENABLED", True)
    monkeypatch.setattr(cleanup.dify_config, "WORKFLOW_LOG_RETENTION_DAYS", 30)
    redis = MagicMock()
    monkeypatch.setattr(cleanup, "redis_client", redis)
    monkeypatch.setattr(cleanup, "db", SimpleNamespace(engine=object()))
    monkeypatch.setattr(cleanup, "Session", MagicMock())
    service = MagicMock()
    monkeypatch.setattr(cleanup, "WorkflowLogCleanupService", service)
    service.delete_runs_batch.side_effect = [(2, 4, 2), (0, 0, 0)]
    service.delete_single_step_batch.side_effect = [1, 0]
    return redis.lock.return_value, service


def test_disabled_task_never_accesses_redis_or_database(monkeypatch):
    monkeypatch.setattr(cleanup.dify_config, "WORKFLOW_LOG_CLEANUP_ENABLED", False)
    redis = MagicMock()
    monkeypatch.setattr(cleanup, "redis_client", redis)
    cleanup.clean_workflow_logs.run()
    redis.lock.assert_not_called()


def test_duplicate_task_does_not_delete(task_dependencies):
    lock, service = task_dependencies
    lock.acquire.return_value = False
    cleanup.clean_workflow_logs.run()
    service.delete_runs_batch.assert_not_called()
    service.delete_single_step_batch.assert_not_called()
    lock.release.assert_not_called()


def test_task_drains_batches_and_renews_lock(task_dependencies):
    lock, service = task_dependencies
    cleanup.clean_workflow_logs.run()
    assert service.delete_runs_batch.call_count == 2
    assert service.delete_single_step_batch.call_count == 2
    assert lock.reacquire.call_count == 4
    lock.release.assert_called_once()
    assert cleanup.clean_workflow_logs.queue == "dataset"


def test_database_error_releases_lock_and_fails_task(task_dependencies):
    lock, service = task_dependencies
    service.delete_runs_batch.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        cleanup.clean_workflow_logs.run()
    lock.release.assert_called_once()
    service.delete_single_step_batch.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_beat_registers_daily_cleanup_only_when_enabled(monkeypatch, enabled):
    monkeypatch.setattr(ext_celery.dify_config, "WORKFLOW_LOG_CLEANUP_ENABLED", enabled)
    celery = ext_celery.init_app(DifyApp(__name__))
    try:
        assert "schedule.clean_workflow_logs" in celery.conf.imports
        assert ("clean_workflow_logs" in celery.conf.beat_schedule) is enabled
        if enabled:
            schedule = celery.conf.beat_schedule["clean_workflow_logs"]
            assert schedule["task"] == "schedule.clean_workflow_logs.clean_workflow_logs"
            assert schedule["schedule"].hour == {3}
            assert schedule["schedule"].minute == {0}
    finally:
        celery.close()


@pytest.mark.parametrize("field", ["WORKFLOW_LOG_RETENTION_DAYS", "WORKFLOW_LOG_CLEANUP_BATCH_SIZE"])
@pytest.mark.parametrize("value", [0, -1])
def test_cleanup_rejects_non_positive_limits(field, value):
    with pytest.raises(ValidationError):
        CeleryBeatConfig(**{field: value})
