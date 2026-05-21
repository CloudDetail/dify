import json
from collections.abc import Generator
from dataclasses import asdict
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import query_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils

PROCESS_RESOURCE_KEY_MAP = {
    "nodeName": "instance_name",
    "pid": "pid",
}


class ProcessResourceMetricTool(BuiltinTool):
    metric_name = ""
    use_backend_api = False
    key_map = PROCESS_RESOURCE_KEY_MAP

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
        step = APOUtils.get_step(start_time, end_time)
        labels = APOUtils.get_and_build_metric_params(tool_parameters, self.key_map)

        if self.use_backend_api:
            params = {
                "metricName": self.metric_name,
                "params": labels,
                "startTime": start_time,
                "endTime": end_time,
                "step": step,
            }
            resp = requests.post(f"{dify_config.APO_BACKEND_URL}/api/metric/query", json=params)
            result = resp.json()["result"]
            resp_str = json.dumps(
                {
                    "type": "metric",
                    "display": True,
                    "unit": result["unit"],
                    "data": {
                        "timeseries": result["timeseries"],
                    },
                }
            )
        else:
            query_result = query_metric(
                metric_name=self.metric_name,
                start_time=start_time,
                end_time=end_time,
                step=step,
                labels=labels,
            )
            resp_str = json.dumps(asdict(query_result))

        yield self.create_text_message(resp_str)
