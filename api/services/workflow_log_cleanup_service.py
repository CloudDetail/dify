from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.workflow import (
    WorkflowAppLog,
    WorkflowNodeExecution,
    WorkflowNodeExecutionStatus,
    WorkflowNodeExecutionTriggeredFrom,
    WorkflowRun,
    WorkflowRunStatus,
)


class WorkflowLogCleanupService:
    @staticmethod
    def delete_runs_batch(session: Session, cutoff: datetime, batch_size: int) -> tuple[int, int, int]:
        """Delete one batch and its children atomically, without loading log payloads."""
        with session.begin():
            run_ids = list(
                session.scalars(
                    select(WorkflowRun.id)
                    .where(
                        WorkflowRun.finished_at < cutoff,
                        WorkflowRun.status.in_(
                            [
                                WorkflowRunStatus.SUCCEEDED,
                                WorkflowRunStatus.FAILED,
                                WorkflowRunStatus.STOPPED,
                                WorkflowRunStatus.PARTIAL_SUCCESSED,
                            ]
                        ),
                    )
                    .order_by(WorkflowRun.finished_at, WorkflowRun.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            if not run_ids:
                return 0, 0, 0

            nodes = session.execute(
                delete(WorkflowNodeExecution)
                .where(WorkflowNodeExecution.workflow_run_id.in_(run_ids))
                .execution_options(synchronize_session=False)
            ).rowcount
            logs = session.execute(
                delete(WorkflowAppLog)
                .where(WorkflowAppLog.workflow_run_id.in_(run_ids))
                .execution_options(synchronize_session=False)
            ).rowcount
            runs = session.execute(
                delete(WorkflowRun).where(WorkflowRun.id.in_(run_ids)).execution_options(synchronize_session=False)
            ).rowcount
        return runs, nodes, logs

    @staticmethod
    def delete_single_step_batch(session: Session, cutoff: datetime, batch_size: int) -> int:
        """Single-step debugging records have no parent workflow run."""
        with session.begin():
            node_ids = list(
                session.scalars(
                    select(WorkflowNodeExecution.id)
                    .where(
                        WorkflowNodeExecution.workflow_run_id.is_(None),
                        WorkflowNodeExecution.triggered_from == WorkflowNodeExecutionTriggeredFrom.SINGLE_STEP.value,
                        WorkflowNodeExecution.finished_at < cutoff,
                        WorkflowNodeExecution.status.in_(
                            [
                                WorkflowNodeExecutionStatus.SUCCEEDED.value,
                                WorkflowNodeExecutionStatus.FAILED.value,
                                WorkflowNodeExecutionStatus.EXCEPTION.value,
                            ]
                        ),
                    )
                    .order_by(WorkflowNodeExecution.finished_at, WorkflowNodeExecution.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            if not node_ids:
                return 0
            count = session.execute(
                delete(WorkflowNodeExecution)
                .where(WorkflowNodeExecution.id.in_(node_ids))
                .execution_options(synchronize_session=False)
            ).rowcount
        return count
