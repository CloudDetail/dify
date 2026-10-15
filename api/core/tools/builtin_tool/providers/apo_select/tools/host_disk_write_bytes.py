from core.tools.builtin_tool.providers.data_source import metric_error
import json
from collections.abc import Generator
from typing import Any, Optional

from core.tools.builtin_tool.providers.data_source import query_legacy_metric
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class HostDiskWriteBytesTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        node = tool_parameters.get("node", '.*')
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        params = {
          'metricName': '宿主机监控指标 - Storage Disk - Disk R/W Data - Written bytes',
          'params': {
            "node": node
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
