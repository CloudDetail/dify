import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import query_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


# TODO need more test
class ServiceLastSeen(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        start_time = tool_parameters.get("startTime", 0)
        end_time = tool_parameters.get("endTime", 0)
        workload_name = tool_parameters.get("workloadName")
        comm = tool_parameters.get("comm")
        node_name = tool_parameters.get("nodeName")
        pid = tool_parameters.get("pid")

        by_labels = ["node_name"]
        label_filters = []
        if node_name:
            label_filters = [f'node_name="{node_name}"']
        if workload_name:
            label_filters.append(f'workload_name="{workload_name}"')
            by_labels.append("workload_name")
        if comm:
            label_filters.append(f'comm="{comm}"')
            by_labels.append("comm")
        if pid:
            label_filters.append(f'pid="{pid}"')

        try:
            if dify_config.DATA_SOURCE == "apo":
                label_str = "{" + ",".join(label_filters) + "}"
                by_str = ",".join(by_labels)
                interval = APOUtils.get_step_with_unit(start_time, end_time)
                query = f"max(originx_process_last_seen{label_str}) by({by_str})"
                params = {
                    "query": query,
                    "time": end_time / 1000,
                }

                resp = requests.get(dify_config.APO_VM_URL + "/prometheus/api/v1/query", params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()

                last_seen = ""
                for res in data.get("data", {}).get("result", []):
                    value_pair = res.get("value", [])
                    if len(value_pair) == 2:
                        try:
                            last_seen = value_pair[1]
                        except Exception:
                            pass

                resp_json = json.dumps({
                    "type": "metric",
                    "display": False,
                    "unit": "s",
                    "data": last_seen
                })

                yield self.create_text_message(resp_json)
            else:
                params = {
                    "node_name": node_name or ".*",
                    "workload_name": workload_name or ".*",
                    "comm": comm or ".*",
                    "pid": pid or ".*"
                }

                query_result = query_metric(
                    metric_name="Originx 北极星指标 (服务层级) - service.process_last_seen",
                    start_time=end_time,  # Set startTime = endTime to query a single point
                    end_time=end_time,
                    step=APOUtils.get_step(start_time, end_time),
                    labels=params,
                )

                last_seen = 0
                for ts in query_result.data.get("timeseries", []):
                    chart_data = ts.get("chart", {}).get("chartData", {})
                    if isinstance(chart_data, dict):
                        max_val = max(chart_data.values(), default=0)
                        last_seen = max(last_seen, max_val)

                if last_seen == 0:
                    last_seen = ""

                resp_json = json.dumps({
                    "type": "metric",
                    "display": False,
                    "unit": "s",
                    "data": last_seen
                })

                yield self.create_text_message(resp_json)
        except Exception as e:
            yield self.create_text_message(json.dumps({
                "type": "error",
                "display": False,
                "data": str(e)
            }))
            return



