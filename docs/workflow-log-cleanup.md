# 工作流执行记录定期清理

用于控制自动执行工作流产生的数据库历史记录增长。启用后每天 03:00（`LOG_TZ`，默认 UTC）清理一次，默认保留最近 30 天已完成的记录。

在 API、worker、Celery Beat 使用的环境变量中配置：

```dotenv
WORKFLOW_LOG_CLEANUP_ENABLED=true
WORKFLOW_LOG_RETENTION_DAYS=30
WORKFLOW_LOG_CLEANUP_BATCH_SIZE=100
```

`WORKFLOW_LOG_RETENTION_DAYS` 和 `WORKFLOW_LOG_CLEANUP_BATCH_SIZE` 必须大于 0。修改配置后重启 worker 和 Beat。

清理范围是整个实例中已结束且 `finished_at` 早于保留期限的 `workflow_runs`，以及通过运行 ID 关联的 `workflow_node_executions`、`workflow_app_logs`。每批在同一事务中先删除关联记录，再删除运行记录。单节点调试记录单独按完成时间清理。运行中、重试中的单节点记录和缺少完成时间的记录不会被清理。任务通过 Redis 锁避免重复执行，日志输出各表删除数量。

## 部署

先构建并使用包含本次代码的 API 镜像，执行数据库迁移（`flask upgrade-db`，或由 API 的 `MIGRATION_ENABLED=true` 启动流程执行）。迁移为清理查询增加索引。仓库中的 `langgenius/dify-api:1.0.0` 是原有镜像引用，不包含本次改动；API、worker、worker_beat 均需换为新镜像。

Docker Compose 部署在 `docker/.env` 中设置上述变量，并在迁移完成后启动：

```bash
docker compose --profile workflow-cleanup up -d worker worker_beat
```

如果已经有 Celery Beat，复用现有实例即可，不要再启动第二个。非 Compose 部署保持一个 `MODE=beat` 进程（或 `celery -A app.celery beat`），并确保 worker 订阅 `dataset` 队列；默认 worker 已订阅该队列。

本功能删除数据库记录，PostgreSQL 通过 autovacuum 回收供后续写入复用的空间，数据文件不会因此保证立即缩小。

## 验证

数据库集成测试只在显式指定的测试 PostgreSQL 上运行，各用例创建独立临时 schema：

```bash
cd api
WORKFLOW_CLEANUP_TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/TEST_DB \
  poetry run pytest tests/integration_tests/workflow/test_workflow_log_cleanup.py \
  tests/unit_tests/services/test_workflow_log_cleanup_task.py
```
