import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import dataplane_scope, to_int
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


def _first_non_empty_span(items: list[Any]) -> Any:
    for item in items:
        if isinstance(item, dict) and item.get("data"):
            return item
    return {}


class DataplaneSpansTool(BuiltinTool):
    def _invoke(self, user_id, tool_parameters, conversation_id=None, app_id=None, message_id=None):
        try:
            yield from self._query(user_id, tool_parameters, conversation_id, app_id, message_id)
        except Exception as e:
            yield self.create_text_message(json.dumps({"type": "span", "display": False,
                "data": {}, "status": "error", "error": str(e)}))

    def _query(
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
        result = {"type": "span", "display": False, "data": {}, "status": "no_data"}
        try:
            resp = requests.post(dify_config.DATAPLANE_URL + '/datasource/querySpans', json=params, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get('success') is False:
                raise ValueError(payload.get('error') or 'dataplane query failed')
            providers = payload.get('data') or []
            errors = [str(p['error']) for p in providers if isinstance(p, dict) and p.get('error')]
            result['data'] = _first_non_empty_span(providers)
            result['status'] = 'ok' if result['data'] else 'no_data'
            if errors:
                result.update(status='partial' if result['data'] else 'error', error='; '.join(errors))
        except (requests.RequestException, ValueError, TypeError) as exc:
            result.update(status='error', error=str(exc)[:500])
        yield self.create_text_message(json.dumps(result))
