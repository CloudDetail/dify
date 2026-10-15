import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import dataplane_scope, to_int
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class DataplaneTopologyTool(BuiltinTool):
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

        params = {
            **dataplane_scope(tool_parameters.get("tenantId"), tool_parameters.get("providerId")),
            "startTime": to_int(start_time),
            "endTime": to_int(end_time),
        }
        try:
            resp = requests.post(
                dify_config.DATAPLANE_URL + '/datasource/queryTopology',
                json=params,
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("success") is not True or not isinstance(payload.get("data"), list):
                raise ValueError(payload.get("error") or "dataplane topology query failed")
            data = payload["data"]
        except (requests.RequestException, ValueError, TypeError) as exc:
            yield self.create_text_message(json.dumps({
                "type": "json", "display": False, "data": [], "status": "error", "error": str(exc)[:500],
            }))
            return

        result = json.dumps({
            # TODO 拓扑结构为parent current children能否展示全量拓扑
            # "type": "topology"
            "type": "json",
            "display": False,
            "data": data,
        })

        yield self.create_text_message(result)
