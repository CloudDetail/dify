import logging
from datetime import UTC, datetime, timedelta

from celery import shared_task
from redis.exceptions import LockNotOwnedError
from sqlalchemy.orm import Session

from configs import dify_config
from extensions.ext_database import db
from extensions.ext_redis import redis_client
from services.workflow_log_cleanup_service import WorkflowLogCleanupService

logger = logging.getLogger(__name__)


@shared_task(queue="dataset")
def clean_workflow_logs():
    if not dify_config.WORKFLOW_LOG_CLEANUP_ENABLED:
        return

    lock = redis_client.lock("workflow_log_cleanup", timeout=3600, blocking=False)
    if not lock.acquire():
        logger.info("Workflow log cleanup is already running; skipping")
        return

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=dify_config.WORKFLOW_LOG_RETENTION_DAYS)
    batch_size = dify_config.WORKFLOW_LOG_CLEANUP_BATCH_SIZE
    totals = [0, 0, 0]
    try:
        logger.info("Cleaning workflow logs finished before %s UTC", cutoff)
        with Session(db.engine) as session:
            while True:
                lock.reacquire()
                counts = WorkflowLogCleanupService.delete_runs_batch(session, cutoff, batch_size)
                if not counts[0]:
                    break
                totals = [total + count for total, count in zip(totals, counts)]
                logger.info("Deleted workflow log batch: runs=%s nodes=%s app_logs=%s", *counts)

            while True:
                lock.reacquire()
                count = WorkflowLogCleanupService.delete_single_step_batch(session, cutoff, batch_size)
                if not count:
                    break
                totals[1] += count
        logger.info("Workflow log cleanup completed: runs=%s nodes=%s app_logs=%s", *totals)
    except Exception:
        logger.exception("Workflow log cleanup failed; previously committed batches remain deleted")
        raise
    finally:
        try:
            lock.release()
        except LockNotOwnedError:
            logger.warning("Workflow log cleanup lock expired before release")
