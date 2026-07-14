from pathlib import Path
from typing import Any
import copy

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
TARGET = WORKFLOW_DIR / "告警简单根因分析V2.yml"
ENVIRONMENT_NODE_ID = "v2_runtime_environment_context"

ENVIRONMENT_CODE = '''def main(pod: str, container_id: str, node: str, pid: str) -> dict:
    pod = str(pod or "").strip()
    container_id = str(container_id or "").strip()
    node = str(node or "").strip()
    pid = str(pid or "").strip()

    if not pod and not container_id and node and pid:
        return {
            "scene": "vm",
            "instance_term": "进程实例",
            "location_text": f"主机 {node} 上的进程 PID {pid}",
            "allowed_command_context": "top, pidstat, ss, nstat, iotop, strace, perf, systemctl, journalctl",
            "forbidden_terms": "Pod, 容器, Namespace, Deployment, K8s, Kubernetes, OOMKill, kubectl, docker",
            "prompt_context": "当前为纯虚拟机环境。使用主机、进程、PID、系统服务等术语；禁止输出任何容器或 Kubernetes 专属术语与命令。",
        }
    if pod or container_id:
        return {
            "scene": "container",
            "instance_term": "应用实例",
            "location_text": pod or container_id,
            "allowed_command_context": "仅使用与现有证据匹配的容器或 Kubernetes 命令",
            "forbidden_terms": "",
            "prompt_context": "当前为容器环境，可使用 Pod、容器和 Kubernetes 术语，但命令必须与证据匹配。",
        }
    return {
        "scene": "unknown",
        "instance_term": "实例",
        "location_text": node,
        "allowed_command_context": "使用跨环境通用诊断命令",
        "forbidden_terms": "不得猜测 Pod、容器或虚拟机",
        "prompt_context": "当前运行环境不明确，必须使用实例、运行节点、进程或服务等中性术语。",
    }
'''

ENV_AWARE_TITLES = {
    "llm analysis root cause",
    "网络方向分析",
    "总结下游影响",
    "可行动方向建议",
    "可行动建议JSON",
    "根因方向JSON",
    "生成报告展示结构",
}

RTT_DETECTION_CODE = '''import json
import math
import statistics


ABSOLUTE_THRESHOLD = 0.05
SPARSE_MIN_SPIKE = 0.02
SPARSE_ZERO_RATIO = 0.5
SPARSE_POSITIVE_RATIO = 0.2
ROBUST_SIGMA_FACTOR = 3.0
MIN_RELATIVE_INCREASE = 1.5


def _valid_values(chart):
    values = []
    for raw in chart.values():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        value = float(raw)
        if math.isfinite(value) and value >= 0:
            values.append(value)
    return values


def _robust_baseline(positive):
    if len(positive) < 3:
        return None
    median = statistics.median(positive)
    deviations = [abs(value - median) for value in positive]
    mad = statistics.median(deviations)
    robust_sigma = 1.4826 * mad
    if robust_sigma == 0:
        robust_sigma = statistics.pstdev(positive)
    upper = median + ROBUST_SIGMA_FACTOR * robust_sigma
    return {"median": median, "robust_sigma": robust_sigma, "upper": upper}


def analyze_data(result_str: str):
    try:
        data = json.loads(result_str)
    except (TypeError, json.JSONDecodeError):
        return json.dumps([])

    timeseries = data.get("data", {}).get("timeseries", []) or []
    unit = data.get("unit", "")
    filtered = []

    for entry in timeseries:
        labels = entry.get("labels", {}) or {}
        legend = str(entry.get("legend", "") or "")
        chart = entry.get("chart", {}).get("chartData", {}) or {}
        values = _valid_values(chart)
        if not values:
            continue

        positive = [value for value in values if value > 0]
        if not positive:
            continue

        total_count = len(values)
        positive_count = len(positive)
        zero_count = total_count - positive_count
        zero_ratio = zero_count / total_count
        positive_ratio = positive_count / total_count
        spike = max(positive)
        avg = sum(positive) / positive_count
        reasons = []
        abnormal_values = set()

        for index, value in enumerate(values):
            if value > ABSOLUTE_THRESHOLD:
                abnormal_values.add(index)
        if abnormal_values:
            reasons.append("absolute")

        baseline = _robust_baseline(positive)
        if baseline and baseline["median"] > 0:
            robust_hits = {
                index
                for index, value in enumerate(values)
                if value > baseline["upper"] and value / baseline["median"] >= MIN_RELATIVE_INCREASE
            }
            if robust_hits:
                abnormal_values.update(robust_hits)
                reasons.append("robust_baseline")

        if (
            zero_ratio >= SPARSE_ZERO_RATIO
            and positive_ratio <= SPARSE_POSITIVE_RATIO
            and spike >= SPARSE_MIN_SPIKE
        ):
            reasons.append("sparse_spike")
            abnormal_values.update(index for index, value in enumerate(values) if value == spike)

        if not reasons:
            continue

        filtered.append({
            "chart": chart,
            "abnormalCount": len(abnormal_values),
            "labels": labels,
            "legend": legend,
            "avg": avg,
            "unit": unit,
            "spike": spike,
            "zeroRatio": zero_ratio,
            "positiveCount": positive_count,
            "detectionReasons": reasons,
            "baseline": baseline or {},
        })

    return json.dumps(filtered)


def main(arg1: str) -> dict:
    return {"result": analyze_data(arg1)}
'''

RTT_ATTRIBUTION_CODE = '''import json
from collections import defaultdict


def _load(data_json):
    try:
        data = json.loads(data_json)
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _target_identity(item, unknown_index):
    labels = item.get("labels", {}) or {}
    for key in ("dst_pod", "dst_ip"):
        value = str(labels.get(key, "") or "").strip()
        if value:
            return value, True
    legend = str(item.get("legend", "") or "").strip()
    if legend:
        return legend, True
    return f"unknown_dst_instance_{unknown_index}", False


def main(data_json):
    data = _load(data_json)
    if not data:
        return {
            "result": "未检测到可用于归因的 RTT 异常数据，需要通过调用链补充分析。",
            "direction_summary": "未明确归因",
            "abnormal_downstream_instances": "[]",
            "evidence_quality": "insufficient",
            "requires_span_fallback": True,
        }

    first_labels = data[0].get("labels", {}) or {}
    src_pod = first_labels.get("src_pod") or first_labels.get("pod") or "当前实例"
    src_node = first_labels.get("src_node") or first_labels.get("node") or ""
    src_ip = first_labels.get("src_ip") or ""
    instances = []
    details_by_node = defaultdict(list)
    valid_count = 0
    complete_count = 0
    seen = set()

    for index, item in enumerate(data, start=1):
        labels = item.get("labels", {}) or {}
        identity, is_valid = _target_identity(item, index)
        if not is_valid or identity in seen:
            continue
        seen.add(identity)
        valid_count += 1
        dst_node = str(labels.get("dst_node", "") or "").strip()
        dst_ip = str(labels.get("dst_ip", "") or "").strip()
        if dst_node and dst_ip:
            complete_count += 1
        avg = item.get("avg")
        unit = item.get("unit", "")
        spike = item.get("spike")
        instance = {
            "instance_name": identity,
            "rtt_avg": f"{avg}{unit}",
            "rtt_spike": f"{spike}{unit}",
            "node": dst_node,
            "ip": dst_ip,
            "evidence_quality": "complete" if dst_node and dst_ip else "partial",
        }
        instances.append(instance)
        if dst_node:
            details_by_node[dst_node].append(instance)

    if valid_count == 0:
        return {
            "result": "检测到 RTT 波动，但缺少可识别的下游目标，需要通过高耗时 Span 补充归因。",
            "direction_summary": "未明确归因",
            "abnormal_downstream_instances": "[]",
            "evidence_quality": "insufficient",
            "requires_span_fallback": True,
        }

    evidence_quality = "complete" if complete_count == valid_count else "partial"
    distinct_nodes = len(details_by_node)
    dominant_node = None
    for node, node_instances in details_by_node.items():
        if len(node_instances) > 1 and len(node_instances) / valid_count >= 0.7:
            dominant_node = node
            break

    if dominant_node:
        direction = "下游节点问题"
        result = f"{src_pod} 的 RTT 异常主要集中在下游节点 {dominant_node}，将结合高耗时 Span 补充具体调用证据。"
    elif distinct_nodes >= 3 or valid_count >= 5:
        direction = "自身问题"
        location = " ".join(value for value in (src_node, src_ip) if value)
        result = f"{src_pod} 与多个下游目标的 RTT 同时异常，倾向自身网络问题。{location}".strip()
    else:
        direction = "下游实例问题"
        names = "、".join(instance["instance_name"] for instance in instances)
        result = f"{src_pod} 与下游实例 {names} 的 RTT 异常，将结合高耗时 Span 补充具体调用证据。"

    return {
        "result": result,
        "direction_summary": direction,
        "abnormal_downstream_instances": json.dumps(instances),
        "evidence_quality": evidence_quality,
        "requires_span_fallback": direction != "自身问题" or evidence_quality != "complete",
    }
'''

P90_CODE = '''import json
import math


FALLBACK_US = 200000


def _fallback():
    return {"p90_value_us": FALLBACK_US, "threshold_source": "fallback"}


def main(data_json):
    try:
        data = json.loads(data_json).get("data", [])
    except (TypeError, json.JSONDecodeError):
        return _fallback()

    values = []
    unit = ""
    for item in data:
        if item.get("title") != "Response Time":
            continue
        item_unit = str(item.get("unit", "") or "").lower().strip()
        if not unit:
            unit = item_unit
        if item_unit != unit:
            continue
        for timeseries in item.get("timeseries", []) or []:
            chart = timeseries.get("chart", {}).get("chartData", {}) or {}
            for raw in chart.values():
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    continue
                value = float(raw)
                if math.isfinite(value) and value > 0:
                    values.append(value)

    if not values or unit not in {"ms", "s", "us"}:
        return _fallback()

    values.sort()
    index = (len(values) - 1) * 0.9
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    p90 = values[lower] * (1 - fraction) + values[upper] * fraction
    multiplier = {"us": 1, "ms": 1000, "s": 1000000}[unit]
    return {
        "p90_value_us": round(p90 * multiplier),
        "threshold_source": "response_time_p90",
    }
'''

MERGE_DOWNSTREAM_CODE = '''import json


def _loads(value, default):
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _statement_summary(value):
    text = str(value or "").strip()
    return text if len(text) <= 240 else text[:237] + "..."


def _span_items(span_data):
    payload = _loads(span_data, {})
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if isinstance(data, dict):
        items = data.get("data", [])
    else:
        items = []
    return items if isinstance(items, list) else []


def main(rtt_instances, span_data):
    rtt = _loads(rtt_instances, [])
    if not isinstance(rtt, list):
        rtt = []
    dependencies = []
    for span in _span_items(span_data):
        if not isinstance(span, dict):
            continue
        attributes = span.get("attributes", {}) or {}
        dependencies.append({
            "service": span.get("peerService") or span.get("serviceName") or attributes.get("peer.service") or "",
            "instance": span.get("instance") or attributes.get("server.address") or attributes.get("net.peer.name") or "",
            "operation": span.get("name", ""),
            "db_system": attributes.get("db.system", ""),
            "statement": _statement_summary(attributes.get("db.statement", "")),
            "duration": span.get("duration", 0),
            "error": bool(span.get("error") or span.get("isError") or span.get("status") == "error"),
            "trace_id": span.get("traceId", ""),
            "span_id": span.get("spanId", ""),
        })

    if rtt and dependencies:
        status = "complete"
    elif rtt or dependencies:
        status = "partial"
    else:
        status = "empty"
    return {
        "result": json.dumps({
            "rtt_instances": rtt,
            "span_dependencies": dependencies,
            "evidence_status": status,
        })
    }
'''


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def node_by_id(document: dict, node_id: str) -> dict:
    for node in document["workflow"]["graph"]["nodes"]:
        if node["id"] == node_id:
            return node
    raise KeyError(node_id)


def add_environment_context(document: dict) -> None:
    graph = document["workflow"]["graph"]
    graph["nodes"].append(
        {
            "id": ENVIRONMENT_NODE_ID,
            "type": "custom",
            "position": {"x": 4118, "y": 420},
            "positionAbsolute": {"x": 4118, "y": 420},
            "width": 244,
            "height": 54,
            "selected": False,
            "sourcePosition": "right",
            "targetPosition": "left",
            "data": {
                "type": "code",
                "title": "运行环境上下文",
                "desc": "",
                "code_language": "python3",
                "code": ENVIRONMENT_CODE,
                "selected": False,
                "variables": [
                    {"variable": "pod", "value_selector": ["1742807803325", "pod"]},
                    {"variable": "container_id", "value_selector": ["1742807803325", "containerId"]},
                    {"variable": "node", "value_selector": ["1742807803325", "node"]},
                    {"variable": "pid", "value_selector": ["1742807803325", "pid"]},
                ],
                "outputs": {
                    "scene": {"type": "string", "children": None},
                    "instance_term": {"type": "string", "children": None},
                    "location_text": {"type": "string", "children": None},
                    "allowed_command_context": {"type": "string", "children": None},
                    "forbidden_terms": {"type": "string", "children": None},
                    "prompt_context": {"type": "string", "children": None},
                },
            },
        }
    )
    graph["edges"].append(
        {
            "id": f"1742807803325-source-{ENVIRONMENT_NODE_ID}-target",
            "type": "custom",
            "source": "1742807803325",
            "sourceHandle": "source",
            "target": ENVIRONMENT_NODE_ID,
            "targetHandle": "target",
            "selected": False,
            "zIndex": 0,
            "data": {
                "isInIteration": False,
                "sourceType": "code",
                "targetType": "code",
            },
        }
    )


def inject_environment_prompts(document: dict) -> None:
    section = (
        "\n\n# 运行环境约束\n"
        "{{#v2_runtime_environment_context.prompt_context#}}\n"
        "运行环境上下文优先于知识库或通用示例；若知识库命令与当前环境冲突，必须忽略冲突命令。"
    )
    for node in document["workflow"]["graph"]["nodes"]:
        data = node.get("data", {})
        if data.get("title") not in ENV_AWARE_TITLES:
            continue
        for prompt in data.get("prompt_template", []):
            if prompt.get("role") == "user":
                prompt["text"] = prompt.get("text", "") + section


def replace_rtt_nodes(document: dict) -> None:
    detection = node_by_id(document, "17515143872690")
    detection["data"]["code"] = RTT_DETECTION_CODE

    attribution = node_by_id(document, "1754298166852")
    attribution["data"]["code"] = RTT_ATTRIBUTION_CODE
    attribution["data"]["outputs"] = {
        "abnormal_downstream_instances": {"type": "string", "children": None},
        "direction_summary": {"type": "string", "children": None},
        "evidence_quality": {"type": "string", "children": None},
        "requires_span_fallback": {"type": "boolean", "children": None},
        "result": {"type": "string", "children": None},
    }


def replace_p90_and_merge_nodes(document: dict) -> None:
    p90 = node_by_id(document, "1754462485033")
    p90["data"]["code"] = P90_CODE
    p90["data"]["outputs"] = {
        "p90_value_us": {"type": "number", "children": None},
        "threshold_source": {"type": "string", "children": None},
    }

    merge = node_by_id(document, "1754375770920")
    merge["data"] = {
        "type": "code",
        "title": "合并RTT与Span下游证据",
        "desc": "",
        "code_language": "python3",
        "code": MERGE_DOWNSTREAM_CODE,
        "selected": False,
        "variables": [
            {
                "variable": "rtt_instances",
                "value_selector": ["1754298166852", "abnormal_downstream_instances"],
            },
            {"variable": "span_data", "value_selector": ["1754634901289", "result"]},
        ],
        "outputs": {"result": {"type": "string", "children": None}},
    }

    for node in document["workflow"]["graph"]["nodes"]:
        for prompt in node.get("data", {}).get("prompt_template", []):
            prompt["text"] = prompt.get("text", "").replace(
                "{{#1754375770920.output#}}", "{{#1754375770920.result#}}"
            )


def rewire_span_enrichment(document: dict) -> None:
    graph = document["workflow"]["graph"]
    condition = node_by_id(document, "1754299061896")
    downstream_instance_handle = None
    for case in condition["data"]["cases"]:
        conditions = case.get("conditions", [])
        if conditions and conditions[0].get("value") == "下游实例问题":
            downstream_instance_handle = case["case_id"]
            break
    if downstream_instance_handle is None:
        raise ValueError("missing downstream instance branch")

    node_case_handle = "v2_downstream_node_case"
    condition["data"]["cases"].append(
        {
            "case_id": node_case_handle,
            "id": node_case_handle,
            "logical_operator": "and",
            "conditions": [
                {
                    "id": "v2_downstream_node_condition",
                    "comparison_operator": "contains",
                    "value": "下游节点问题",
                    "varType": "string",
                    "variable_selector": ["1754298166852", "direction_summary"],
                }
            ],
        }
    )

    for edge in graph["edges"]:
        if edge["source"] == "1754299061896" and edge.get("sourceHandle") == downstream_instance_handle:
            edge["target"] = "1754462459105"
            edge["id"] = f"1754299061896-{downstream_instance_handle}-1754462459105-target"
            edge["data"]["targetType"] = "tool"

    graph["edges"].append(
        {
            "id": f"1754299061896-{node_case_handle}-1754462459105-target",
            "type": "custom",
            "source": "1754299061896",
            "sourceHandle": node_case_handle,
            "target": "1754462459105",
            "targetHandle": "target",
            "selected": False,
            "zIndex": 0,
            "data": {
                "isInIteration": False,
                "sourceType": "if-else",
                "targetType": "tool",
            },
        }
    )


def build() -> dict:
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document = copy.deepcopy(document)
    document["app"]["name"] = "告警简单根因分析V2"
    add_environment_context(document)
    inject_environment_prompts(document)
    replace_rtt_nodes(document)
    replace_p90_and_merge_nodes(document)
    rewire_span_enrichment(document)
    return document


def main() -> None:
    document = build()
    TARGET.write_text(
        yaml.dump(
            document,
            Dumper=NoAliasDumper,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
