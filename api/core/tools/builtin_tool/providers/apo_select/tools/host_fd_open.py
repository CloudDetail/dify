import json
from collections.abc import Generator
from dataclasses import asdict
from typing import Any, Optional

from core.tools.builtin_tool.providers.data_source import query_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class HostCPUIoWaitRespTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        node = tool_parameters.get("node", ".*")
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        job = tool_parameters.get("job")
        labels = {
            "node": node,
            "job": job,
        }

        query_result = query_metric(
            metric_name="宿主机监控指标 - Storage Filesystem - File Descriptor - Open files",
            start_time=start_time,
            end_time=end_time,
            step=APOUtils.get_step(start_time, end_time),
            labels=labels,
        )
        resp = asdict(query_result)
        resp_str = json.dumps(resp)
        yield self.create_text_message(resp_str)
