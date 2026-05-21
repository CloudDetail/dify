import json
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
        rootCauseAnalysis = convert_to_json(
            tool_parameters.get("rootCauseAnalysis"), "rootCauseAnalysis", errormsgs
        )
        suggest = extract_collection(
            convert_to_json(tool_parameters.get("suggest"), "suggest", errormsgs), "suggest"
        )
        evidence = extract_collection(
            convert_to_json(tool_parameters.get("evidence"), "evidence", errormsgs), "evidence"
        )

        identity_tags = build_identity_tags(tool_parameters)
        merge_identity_tags(tags, identity_tags)
        if isinstance(overview, dict):
            overview_tags = overview.get("tags")
            if not isinstance(overview_tags, dict):
                overview_tags = {}
                overview["tags"] = overview_tags
            merge_identity_tags(overview_tags, identity_tags)
        enrich_evidence_identifiers(evidence, identity_tags, tool_parameters)

        alertDirection = tool_parameters.get("alertDirection")
        analyzeRunId = tool_parameters.get("analyzeRunId")
        impactScope = tool_parameters.get("impactScope")
        infraCheckResult = tool_parameters.get("infraCheckResult")
        networkCheckResult = tool_parameters.get("networkCheckResult")

        json_data = {
            'reportType': reportType,
            'overview': overview,
            'tags': tags,
            'topology': topology,
            'rootCauseAnalysis': rootCauseAnalysis,
            'suggest': suggest,
            'evidence': evidence,
            'alertDirection': alertDirection,
            'analyzeRunId': analyzeRunId,
            'impactScope': impactScope,
            'infraCheckResult': infraCheckResult,
            'networkCheckResult': networkCheckResult
        }
        resp = requests.post(dify_config.APO_BACKEND_URL + '/api/alerts/events/report/add', json=json_data)
        if resp.status_code != 200:
            errormsgs.append(f"Error while creating report, msg: {resp.text}")
        result = json.dumps({
            'type': 'report',
            'display': False,
            'msg': errormsgs
        })

        yield self.create_text_message(result)


def convert_to_json(data, name: str, errormsgs: list) -> Any:
    try:
        return json.loads(data)
    except:
        errormsgs.append(f'{name} Invalid JSON')
        return {}


def extract_collection(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        return data.get(key, {})
    if isinstance(data, list):
        return data
    return {}


def build_identity_tags(tool_parameters: dict[str, Any]) -> dict[str, Any]:
    tags = {}
    field_map = {
        "alertEventId": ["alertEventId"],
        "alertId": ["alertId"],
        "service": ["service"],
        "endpoint": ["endpoint"],
        "pod": ["pod"],
        "namespace": ["namespace"],
        "nodeName": ["nodeName", "node"],
        "pid": ["pid"],
        "containerId": ["containerId"],
    }
    for target, sources in field_map.items():
        value = first_value(tool_parameters, sources)
        if has_value(value):
            tags[target] = value
    return tags


def first_value(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if has_value(value):
            return value
    return None


def has_value(value: Any) -> bool:
    return value is not None and value != "" and value != {} and value != []


def merge_identity_tags(target: Any, identity_tags: dict[str, Any]) -> None:
    if not isinstance(target, dict):
        return
    for key, value in identity_tags.items():
        if not has_value(target.get(key)):
            target[key] = value


def enrich_evidence_identifiers(evidence: Any, identity_tags: dict[str, Any], tool_parameters: dict[str, Any]) -> None:
    if not isinstance(evidence, list) or not identity_tags:
        return

    identifiers = identity_tags.copy()
    start_time = tool_parameters.get("startTime")
    end_time = tool_parameters.get("endTime")
    if has_value(start_time) or has_value(end_time):
        identifiers["timeRange"] = {}
        if has_value(start_time):
            identifiers["timeRange"]["startTime"] = start_time
        if has_value(end_time):
            identifiers["timeRange"]["endTime"] = end_time

    for item in evidence:
        if not isinstance(item, dict):
            continue
        item_identifiers = item.get("identifiers")
        if not isinstance(item_identifiers, dict):
            item_identifiers = {}
            item["identifiers"] = item_identifiers
        merge_identity_tags(item_identifiers, identifiers)
