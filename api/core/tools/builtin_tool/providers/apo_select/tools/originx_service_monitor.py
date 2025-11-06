import json
from collections.abc import Generator
from dataclasses import asdict
from typing import Any, Optional

from core.tools.builtin_tool.providers.data_source import query_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class OriginxServiceMonitorTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        node_name = tool_parameters.get("node_name")
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        pid = tool_parameters.get("pid")

        labels = {"node_name": node_name, **({"pid": pid} if pid else {})}
        query_result = query_metric(
            metric_name="Thread Polaris Metrics - 北极星指标（进程） - 节点上被监控的服务列表",
            start_time=start_time,
            end_time=end_time,
            step=APOUtils.get_step(start_time, end_time),
            labels=labels,
        )
        resp = asdict(query_result)
        resp_str = json.dumps(resp)
        yield self.create_text_message(resp_str)
