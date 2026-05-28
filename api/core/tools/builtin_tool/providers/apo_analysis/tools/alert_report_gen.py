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
        evidence, reportView = deduplicate_evidence_and_report_view(evidence, reportView)
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


def deduplicate_evidence_and_report_view(evidence: Any, reportView: Any) -> tuple[Any, Any]:
    if not isinstance(evidence, list):
        return evidence, reportView

    seen_indexes = {}
    index_mapping = {}
    deduplicated_evidence = []

    for index, item in enumerate(evidence):
        key = stable_json_fingerprint(item)
        if key in seen_indexes:
            index_mapping[index] = seen_indexes[key]
            continue

        new_index = len(deduplicated_evidence)
        seen_indexes[key] = new_index
        index_mapping[index] = new_index
        deduplicated_evidence.append(item)

    if len(deduplicated_evidence) == len(evidence):
        return evidence, reportView

    if isinstance(reportView, dict):
        reportView = remap_report_view_evidence_indexes(reportView, index_mapping)

    return deduplicated_evidence, reportView


def remap_report_view_evidence_indexes(reportView: dict, index_mapping: dict[int, int]) -> dict:
    normalized_report_view = dict(reportView)
    for field in ("rootCauseEvidenceRefs", "rootCauseMetricRefs", "evidenceHighlights"):
        refs = reportView.get(field)
        if isinstance(refs, list):
            normalized_report_view[field] = remap_report_view_ref_list(refs, index_mapping)
    return normalized_report_view


def remap_report_view_ref_list(refs: list, index_mapping: dict[int, int]) -> list:
    deduplicated_refs = []
    seen_refs = set()

    for ref in refs:
        normalized_ref = ref
        if isinstance(ref, dict):
            normalized_ref = dict(ref)
            evidence_index = normalized_ref.get("evidenceIndex")
            normalized_evidence_index = normalize_evidence_index(evidence_index)
            if normalized_evidence_index is not None and normalized_evidence_index in index_mapping:
                normalized_ref["evidenceIndex"] = index_mapping[normalized_evidence_index]

        key = stable_json_fingerprint(normalized_ref)
        if key in seen_refs:
            continue

        seen_refs.add(key)
        deduplicated_refs.append(normalized_ref)

    return deduplicated_refs


def normalize_evidence_index(value: Any) -> int | None:
    if type(value) is int:
        return value
    if type(value) is float and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value.strip())
    return None


def stable_json_fingerprint(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(data)


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
