import json
from collections.abc import Generator
from tarfile import data_filter
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


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
            "startTime": start_time,
            "endTime": end_time,
        }
        resp = requests.post(
            dify_config.DATAPLANE_URL + '/datasource/queryTopology',
            json=params
        )

        data = resp.json().get("data", [])

        result = json.dumps({
            # TODO 拓扑结构为parent current children能否展示全量拓扑
            # "type": "topology"
            "type": "json",
            "display": False,
            "data": data,
        })

        yield self.create_text_message(result)
