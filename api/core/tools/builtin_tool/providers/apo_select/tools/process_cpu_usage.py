from core.tools.builtin_tool.providers.apo_select.tools import process_resource_metric_base


class ProcessCPUUsageTool(process_resource_metric_base.ProcessResourceMetricTool):
    metric_name = "进程监控指标 - 进程 CPU 使用速率"
