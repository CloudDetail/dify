import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class DataplaneSpansTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        provider_id = tool_parameters.get("providerId")
        limit = tool_parameters.get("limit")
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        service = tool_parameters.get("service")
        operation = tool_parameters.get("operation")
        is_error = tool_parameters.get("isError")
        min_duration = tool_parameters.get("minDuration")
        max_duration = tool_parameters.get("maxDuration")
        if limit == 0:
            limit = 10
        filter = {
            "service": service,
            "operation": operation,
            "error": is_error,
            "minDuration": min_duration,
            "maxDuration": max_duration,
        }
        params = {
            "providerId": provider_id,
            "startTime": start_time,
            "endTime": end_time,
            "filter": filter,
            "limit": limit
        }
        resp = requests.post(dify_config.DATAPLANE_URL + '/datasource/querySpans', json=params)
        list = resp.json()['data']
        list = json.dumps({
            'type': 'trace',
            'display': False,
            'data': list[0] if len(list) > 0 else []
        })
        yield self.create_text_message(list)