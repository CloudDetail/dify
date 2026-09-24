import json
import logging
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import dataplane_scope, to_int
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage

logger = logging.getLogger(__name__)


def _first_non_empty_trace(items: list[Any]) -> dict[str, Any]:
    for item in items:
        if isinstance(item, dict) and item.get("data"):
            return item
    return {}


class DataplaneTracesTool(BuiltinTool):
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
        limit = to_int(limit or 10)
        filter = {
            "service": service,
            "operation": operation,
            "error": is_error,
            "minDuration": to_int(min_duration or 0),
            "maxDuration": to_int(max_duration or 0),
        }
        filter = {key: value for key, value in filter.items() if value is not None}
        if tool_parameters.get("traceId"):
            filter["traceId"] = tool_parameters["traceId"]
        params = {
            **dataplane_scope(tool_parameters.get("tenantId"), provider_id),
            "startTime": to_int(start_time),
            "endTime": to_int(end_time),
            "filter": filter,
            "limit": limit
        }
        try:
            empty_response = {
                "data": {},
                "type": "trace",
                "display": False,
            }
            resp = requests.post(dify_config.DATAPLANE_URL +
                                 '/datasource/queryTraces', json=params)
            if resp.status_code >= 400:
                logger.error(
                    f"HTTP {resp.status_code} error when querying traces: {resp.text}")
                yield self.create_text_message(json.dumps(empty_response))
                return
        except requests.exceptions.RequestException as e:
            logger.error(f"Request exception when querying traces: {str(e)}")
            yield self.create_text_message(json.dumps(empty_response))
            return

        list = resp.json().get('data', [])
        list = json.dumps({
            'type': 'trace',
            'display': False,
            'data': _first_non_empty_trace(list)
        })
        yield self.create_text_message(list)
