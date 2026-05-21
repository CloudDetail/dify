import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class AlertEventTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        service = tool_parameters.get("service")
        pod = tool_parameters.get("pod")
        node = tool_parameters.get("node")
        pid = tool_parameters.get("pid")
        containerId = tool_parameters.get("containerId")
        namespace = tool_parameters.get("namespace")
        page = tool_parameters.get("page")
        size = tool_parameters.get("pageSize")
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        
        params_to_check = [
            ("tags.serviceName", service),
            ("tags.pod", pod),
            ("tags.node", node),
            ("tags.pid", pid),
            ("labels.container_id", containerId),
            ("tags.namespace", namespace)
        ]

        filters = [
            {"key": key, "selected": [value]}
            for key, value in params_to_check if value
        ]

        request_body = {
            "startTime": start_time,
            "endTime": end_time,
            "pagination": {
                "currentPage": page,
                "pageSize": size
            },
            "filters": filters,
            "groupId": 0
        }
        print(request_body)
        resp = requests.post(dify_config.APO_BACKEND_URL + '/api/alerts/event/list', json=request_body)
        result = json.dumps({
            'type': 'alerts',
            'display': False,
            'data': resp.json().get("events", []),
        })
        yield self.create_text_message(result)