import json
from collections.abc import Generator
from dataclasses import asdict
from typing import Any, Optional

from core.tools.builtin_tool.providers.data_source import query_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class PolarProcessAllRespThreeScenesTool(BuiltinTool):
    process_metric = "originx_thread_polaris_nanoseconds_sum"
    empty_metric = "^$"

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
        labels = self._build_scene_labels(tool_parameters)

        query_result = query_metric(
            metric_name="Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - 所有类型列表（三场景）",
            start_time=start_time,
            end_time=end_time,
            step=APOUtils.get_step(start_time, end_time),
            labels=labels,
        )
        resp = asdict(query_result)
        resp_str = json.dumps(resp)
        yield self.create_text_message(resp_str)

    def _build_scene_labels(self, tool_parameters: dict[str, Any]) -> dict[str, str]:
        if tool_parameters.get("pod"):
            return {
                "scene_pod_metric": self.process_metric,
                "scene_pod": tool_parameters["pod"],
                "scene_container_metric": self.empty_metric,
                "scene_vm_metric": self.empty_metric,
            }

        if tool_parameters.get("containerId"):
            return {
                "scene_pod_metric": self.empty_metric,
                "scene_container_metric": self.process_metric,
                "scene_container_id": tool_parameters["containerId"],
                "scene_vm_metric": self.empty_metric,
            }

        return {
            "scene_pod_metric": self.empty_metric,
            "scene_container_metric": self.empty_metric,
            "scene_vm_metric": self.process_metric,
            "scene_node_name": tool_parameters.get("nodeName", ""),
            "scene_pid": tool_parameters.get("pid", ""),
        }
