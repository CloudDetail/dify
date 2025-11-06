import json
from collections.abc import Generator
from dataclasses import asdict
from typing import Any, Optional

from core.tools.builtin_tool.providers.data_source import query_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class ContainerCpuUsageContainerdTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")

        key_map = {
            "cadvisor_job_name": "cadvisor_job_name",
            "namespace": "namespace",
            "pod": "pod"
        }

        labels = APOUtils.get_and_build_metric_params(tool_parameters, key_map)
        query_result = query_metric(
            metric_name='基础设施情况 - 容器CPU - 容器CPU使用率 - Containerd',
            start_time=start_time,
            end_time=end_time,
            step=APOUtils.get_step(start_time, end_time),
            labels=labels,
        )
        resp = asdict(query_result)
        resp_str = json.dumps(resp)
        yield self.create_text_message(resp_str)