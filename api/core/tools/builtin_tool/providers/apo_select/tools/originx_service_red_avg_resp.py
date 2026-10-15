from core.tools.builtin_tool.providers.data_source import metric_error
import json
from collections.abc import Generator
from typing import Any, Optional

from core.tools.builtin_tool.providers.data_source import query_legacy_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class OriginxServiceRedAvgRespTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        service_name = tool_parameters.get("service_name")
        content_key = tool_parameters.get("content_key")
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        params = {
          'metricName': 'Originx 北极星指标 (服务层级) - RED指标 - 平均响应时间',
          'params': {
            "service_name": service_name,
            "content_key": content_key
          },
          'startTime': start_time,
          'endTime': end_time,
          'step': APOUtils.get_step(start_time, end_time),
          }
        list = query_legacy_metric(params, tenant_id=tool_parameters.get("tenantId"))
        list = json.dumps({**metric_error(list),
            'type': 'metric',
            'display': True,
            'unit': list['unit'],
            'data': {
                "timeseries": list['timeseries']
            }
        })
        yield self.create_text_message(list)
