import json
import re
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class AlertReportGen(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        reportType = tool_parameters.get("reportType")
        errormsgs = []

        overview = convert_to_json(tool_parameters.get("overview"), "overview", errormsgs)
        tags = convert_to_json(tool_parameters.get("tags"), "tags", errormsgs)
        topology = convert_to_json(tool_parameters.get("topology"), "topology", errormsgs)
        rootCauseAnalysis = convert_to_json(tool_parameters.get("rootCauseAnalysis"), "rootCauseAnalysis", errormsgs)
        suggest = convert_to_json(tool_parameters.get("suggest"), "suggest", errormsgs).get("suggest", {})
        evidence = convert_to_json(tool_parameters.get("evidence"), "evidence", errormsgs).get("evidence", {})
        reportView = convert_to_json(tool_parameters.get("reportView"), "reportView", errormsgs, required=False)
        json_data = {
            'reportType': reportType,
            'overview': overview,
            'tags': tags,
            'topology': topology,
            'rootCauseAnalysis': rootCauseAnalysis,
            'suggest': suggest,
            'evidence': evidence
        }
        if reportView:
            json_data['reportView'] = reportView
        resp = requests.post(dify_config.APO_BACKEND_URL + '/api/alerts/events/report/add', json=json_data)
        if resp.status_code != 200:
            errormsgs.append(f"Error while creating report, msg: {resp.text}")
        list = json.dumps({
            'type': 'report',
            'display': False,
            'msg': errormsgs
        })

        yield self.create_text_message(list)


def convert_to_json(data, name: str, errormsgs: list, required: bool = True) -> dict:
    if data is None or data == "":
        if required:
            errormsgs.append(f'{name} Invalid JSON')
        return {}
    if isinstance(data, dict):
        return data
    data = data.strip()
    data = re.sub(r"<think>.*?</think>", "", data, flags=re.DOTALL | re.IGNORECASE).strip()
    data = re.sub(r"<think>.*", "", data, flags=re.DOTALL | re.IGNORECASE).strip()
    if data.startswith("```") and data.endswith("```"):
        data = data.split("\n", 1)[1].rsplit("\n", 1)[0]
        if data.startswith("json"):
            data = data[4:].strip()
    try:
        return json.loads(data)
    except:
        errormsgs.append(f'{name} Invalid JSON')
        return {}
