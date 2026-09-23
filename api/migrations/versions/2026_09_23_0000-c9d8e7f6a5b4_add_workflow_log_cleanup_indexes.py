"""Add indexes for batched workflow log cleanup.

Revision ID: c9d8e7f6a5b4
Revises: 08ec4f75af5e
"""

import sqlalchemy as sa
from alembic import op

revision = "c9d8e7f6a5b4"
down_revision = "08ec4f75af5e"
branch_labels = None
depends_on = None


def upgrade():
    # Build indexes without blocking workflow execution writes on large tables.
    with op.get_context().autocommit_block():
        op.create_index(
            "workflow_run_finished_at_idx", "workflow_runs", ["finished_at", "id"], postgresql_concurrently=True
        )
        op.create_index(
            "workflow_node_execution_run_id_idx",
            "workflow_node_executions",
            ["workflow_run_id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "workflow_node_execution_single_step_finished_idx",
            "workflow_node_executions",
            ["finished_at", "id"],
            postgresql_where=sa.text("workflow_run_id IS NULL AND triggered_from = 'single-step'"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "workflow_app_log_run_id_idx", "workflow_app_logs", ["workflow_run_id"], postgresql_concurrently=True
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index("workflow_app_log_run_id_idx", table_name="workflow_app_logs", postgresql_concurrently=True)
        op.drop_index(
            "workflow_node_execution_single_step_finished_idx",
            table_name="workflow_node_executions",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "workflow_node_execution_run_id_idx", table_name="workflow_node_executions", postgresql_concurrently=True
        )
        op.drop_index("workflow_run_finished_at_idx", table_name="workflow_runs", postgresql_concurrently=True)
