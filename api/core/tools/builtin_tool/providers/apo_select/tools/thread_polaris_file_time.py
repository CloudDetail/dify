import json
from collections.abc import Generator
from typing import Any, Optional

from core.tools.builtin_tool.providers.data_source import query_legacy_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class ThreadPolarisFileTimeTool(BuiltinTool):
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
            "pod": "pod",
            "nodeName": "node_name",
            "pid": "pid",
            "containerId": "container_id"
        }
        metric_params = APOUtils.get_and_build_metric_params(tool_parameters, key_map)

        params = {
            'metricName': 'Thread Polaris Metrics - 北极星指标（线程） - 各类型耗时折线图 - File',
            'params': metric_params,
            'startTime': start_time,
            'endTime': end_time,
            'step': APOUtils.get_step(start_time, end_time),
        }
        list = query_legacy_metric(params, tenant_id=tool_parameters.get("tenantId"))
        list = json.dumps({
            'type': 'metric',
            'display': True,
            'unit': list['unit'],
            'data': {
                'timeseries': list['timeseries']
            }
        })
        yield self.create_text_message(list)