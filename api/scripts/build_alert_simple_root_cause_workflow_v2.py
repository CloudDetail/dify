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

PROMPT_REFINEMENT_NODE_IDS = {
    "1741512806512",
    "17430596469370",
    "17473569800940",
    "1750662084996",
    "1750662408086",
    "1764048001002",
    "1754382620041",
}

EPOLL_NETWORK_GUIDANCE = (
    "根因为 EPOLL：保留 EPOLL 作为异常方向，但建议从网络连接和等待原因排查。"
    "优先结合 RTT、下游 Span、超时和重传证据；可按证据选择 ss -s、ss -antp、nstat -az、"
    "sar -n TCP,ETCP 1、ip -s link。不要默认建议跟踪 epoll 系统调用，也不要机械输出全部命令。"
)

COMMON_OUTPUT_IDENTITY_RULES = '''

# 输出身份与环境规则
- 服务名：{{#1754299310647.service#}}。服务名为空时省略服务字段，禁止输出任何占位服务名或“未知服务”。
- 运行对象：{{#v2_runtime_environment_context.location_text#}}。
- 对象类型：{{#v2_runtime_environment_context.instance_term#}}。
- {{#v2_runtime_environment_context.prompt_context#}}
- 不得因为指标或工具名称包含“按Pod统计”就推断当前一定是 Pod 或容器；必须服从运行环境上下文。
- 示例中的 xx、xxx、XXXX 仅用于说明格式，禁止原样复制到最终报告或 JSON。
'''

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
            "requires_span_fallback": "true",
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
            "requires_span_fallback": "true",
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
        "requires_span_fallback": "true" if direction != "自身问题" or evidence_quality != "complete" else "false",
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

TRACE_MERGE_CODE = '''import json


def _loads(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _trace_items(value):
    payload = _loads(value)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("data", data.get("traces", []))
        return items if isinstance(items, list) else []
    return []


def _attributes(span):
    value = span.get("attributes", {})
    return value if isinstance(value, dict) else {}


def _normalize_span(span):
    attributes = _attributes(span)
    return {
        "spanId": span.get("spanId", ""),
        "parentSpanId": span.get("parentSpanId", ""),
        "service": span.get("serviceName", ""),
        "operation": span.get("name", ""),
        "duration": span.get("duration", 0) or 0,
        "error": bool(span.get("error") or span.get("isError") or span.get("status") == "error"),
        "dbSystem": attributes.get("db.system", ""),
        "dbStatement": str(attributes.get("db.statement", "") or "")[:240],
        "peerService": span.get("peerService") or attributes.get("peer.service") or "",
    }


def _normalize_trace(trace):
    spans = [span for span in trace.get("spans", []) if isinstance(span, dict)]
    roots = [span for span in spans if span.get("parentSpanId") in ("", None, "0", 0)]
    root = roots[0] if roots else (spans[0] if spans else {})
    dependencies = [span for span in spans if span is not root]
    slowest_source = dependencies or spans
    slowest = max(slowest_source, key=lambda item: item.get("duration", 0) or 0, default={})
    errors = [
        span
        for span in spans
        if span.get("error") or span.get("isError") or span.get("status") == "error"
    ]
    error_span = max(errors, key=lambda item: item.get("duration", 0) or 0, default={})
    duration = trace.get("duration", 0) or max(
        (span.get("duration", 0) or 0 for span in spans),
        default=0,
    )
    is_error = bool(trace.get("error") or trace.get("isError") or errors)
    return {
        "traceId": str(trace.get("traceId", trace.get("trace_id", "")) or ""),
        "duration": duration,
        "error": is_error,
        "timestamp": trace.get("timestamp", trace.get("startTime", 0)) or 0,
        "entry": {
            "service": root.get("serviceName", ""),
            "endpoint": root.get("name", ""),
        },
        "slowestSpan": _normalize_span(slowest) if slowest else None,
        "errorSpan": _normalize_span(error_span) if error_span else None,
    }


def main(slow_trace_data, error_trace_data):
    slow_raw = _trace_items(slow_trace_data)
    error_raw = _trace_items(error_trace_data)
    merged = {}

    for trace in slow_raw + error_raw:
        if not isinstance(trace, dict):
            continue
        normalized = _normalize_trace(trace)
        trace_id = normalized["traceId"]
        if not trace_id:
            continue
        previous = merged.get(trace_id)
        if previous is None or normalized["duration"] > previous["duration"]:
            merged[trace_id] = normalized
        elif normalized["error"]:
            previous["error"] = True
            if normalized["errorSpan"]:
                previous["errorSpan"] = normalized["errorSpan"]

    slow_ids = []
    for trace in sorted(
        (_normalize_trace(item) for item in slow_raw if isinstance(item, dict)),
        key=lambda item: item["duration"],
        reverse=True,
    ):
        trace_id = trace["traceId"]
        if trace_id and trace_id not in slow_ids:
            slow_ids.append(trace_id)
        if len(slow_ids) == 10:
            break

    selected = [merged[trace_id] for trace_id in slow_ids if trace_id in merged]
    selected_ids = {item["traceId"] for item in selected}
    remaining = [item for trace_id, item in merged.items() if trace_id not in selected_ids]
    remaining.sort(
        key=lambda item: (
            item["error"],
            item["duration"],
            (item["slowestSpan"] or {}).get("duration", 0),
            item["timestamp"],
        ),
        reverse=True,
    )
    selected.extend(remaining[: max(0, 30 - len(selected))])
    return {"result": json.dumps({"traces": selected})}
'''

TRACE_ENTRY_CODE = '''import json


def main(data_json: str, current_service: str):
    try:
        traces = json.loads(data_json).get("traces", [])
    except (TypeError, json.JSONDecodeError):
        traces = []
    entries = []
    seen = set()
    trace_evidence = []
    services = {current_service} if current_service else set()

    for trace in traces:
        entry = trace.get("entry", {}) or {}
        service = str(entry.get("service", "") or "").strip()
        endpoint = str(entry.get("endpoint", "") or "").strip()
        if service and endpoint and (service, endpoint) not in seen:
            entries.append({"service": service, "endpoint": endpoint})
            seen.add((service, endpoint))
            services.add(service)
        trace_evidence.append({
            "traceId": trace.get("traceId", ""),
            "duration": trace.get("duration", 0),
            "error": trace.get("error", False),
            "slowestSpan": trace.get("slowestSpan"),
            "errorSpan": trace.get("errorSpan"),
        })

    return {
        "entries": entries,
        "service_query": " ".join(sorted(services)),
        "trace_evidence": trace_evidence,
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
    for edge in graph["edges"]:
        if edge["source"] == "1742807803325":
            edge["source"] = ENVIRONMENT_NODE_ID
            edge["id"] = edge["id"].replace("1742807803325-source", f"{ENVIRONMENT_NODE_ID}-source")
            edge["data"]["sourceType"] = "code"
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


def _user_prompt(node: dict) -> dict:
    for prompt in node.get("data", {}).get("prompt_template", []):
        if prompt.get("role") == "user":
            return prompt
    raise ValueError(f"user prompt missing: {node['id']}")


def _replace(text: str, old: str, new: str) -> str:
    return text.replace(old, new)


def refine_output_prompts(document: dict) -> None:
    nodes = {node["id"]: node for node in document["workflow"]["graph"]["nodes"]}

    action = _user_prompt(nodes["1741512806512"])
    action_text = action["text"]
    action_text = _replace(
        action_text,
        "基于服务层级聚合Pod信息并输出服务级概览报告。需确保各Pod具体运行状态的可视化呈现清晰直观。",
        "基于服务层级聚合运行对象信息并输出服务级概览报告，清晰呈现各主机进程、实例或 Pod 的实际运行状态。",
    )
    action_text = _replace(
        action_text,
        "根因为EPOLL：strace -e epoll_wait,epoll_pwait -tt -T -p <PID>追踪epoll调用耗时，perf trace -e epoll:*查看epoll相关事件等命令",
        EPOLL_NETWORK_GUIDANCE,
    )
    action_text = _replace(action_text, "服务级汇总指标与Pod明细指标", "服务级汇总指标与运行对象明细指标")
    action["text"] = action_text

    root_cause = _user_prompt(nodes["17430596469370"])
    root_text = root_cause["text"]
    root_text = _replace(
        root_text,
        "基于跨资源类别的异常线程数据，判断应用实例{{#17430589567120.pod#}}是否受告警事件",
        "基于跨资源类别的异常线程数据，判断运行对象{{#v2_runtime_environment_context.location_text#}}是否受告警事件",
    )
    root_text = _replace(root_text, "根据xx文档，推断出/可能是xxx", "根据知识库文档，推断出具体根因")
    root_text = _replace(
        root_text,
        "根因为xx（如果总结中明确指出下游）下游依赖问题",
        "根因为总结中明确指出的具体下游依赖问题",
    )
    root_text = _replace(
        root_text,
        "只能给出一个问题方向，不要出现xx和xx方向问题，只能说明主要问题。",
        "只能给出一个主要问题方向，禁止并列多个根因方向。",
    )
    root_text = _replace(
        root_text,
        "**服务xx**的**应用实例**:{{#17430589567120.pod#}}  ",
        "**服务**：{{#1754299310647.service#}}  \n**运行对象**：{{#v2_runtime_environment_context.location_text#}}  \n**对象类型**：{{#v2_runtime_environment_context.instance_term#}}  ",
    )
    root_text = _replace(
        root_text,
        "按指标维度描述显著变化，如xxx个线程xxxxx,若无异常标注",
        "按实际线程数量和指标维度描述显著变化，若无异常标注",
    )
    root_cause["text"] = root_text

    network = _user_prompt(nodes["17473569800940"])
    network_text = network["text"]
    network_text = _replace(
        network_text,
        "判断应用实例{{#17430589567120.pod#}}是否受告警事件",
        "判断运行对象{{#v2_runtime_environment_context.location_text#}}是否受告警事件",
    )
    network_text = _replace(network_text, "Pod相关下游容器网络链路", "当前运行对象相关的下游网络链路")
    network_text = _replace(network_text, "容器自身网络出现问题", "当前运行对象自身网络出现问题")
    network_text = _replace(
        network_text,
        "**应用实例**:{{#17430589567120.pod#}}",
        "**运行对象**：{{#v2_runtime_environment_context.location_text#}}",
    )
    network_text = network_text.replace("下游容器网络链路", "下游网络链路")
    network_text = network_text.replace("容器网络链路", "网络链路")
    network["text"] = network_text

    description = _user_prompt(nodes["1750662084996"])
    description_text = description["text"]
    description_text = _replace(
        description_text,
        "xx服务的xxx实例当前告警事件为XXXX (简洁，不要有其他内容)",
        "使用真实服务名和运行对象描述当前告警事件；服务名为空时省略服务字段。",
    )
    description_text = _replace(
        description_text,
        "影响到界面上xx功能，请求延时从xx升高到xx，错误率从xx升高到xx。（根据受影响服务数据进行描述，不要修改）",
        "根据受影响服务数据描述具体业务功能、响应时间和错误率变化；缺少数据时不要编造。",
    )
    description_text = _replace(
        description_text,
        "初步分析是XXX问题（CPU方向、网络质量、CPU抢占、xx下游依赖、文件读写），不要有其他内容，给出方向即可",
        "只输出已确认的单一根因方向，例如 CPU、网络质量、CPU 抢占、具体下游依赖或文件读写。",
    )
    description_text = _replace(description_text, "执行XXXX命令（必须和故障方向有关）", "执行与故障方向和运行环境匹配的命令。")
    description_text = _replace(
        description_text,
        "当前实例：{{#17430589567120.pod#}}",
        "当前运行对象：{{#v2_runtime_environment_context.location_text#}}",
    )
    description_text = _replace(description_text, "根据xx文档，推测是xx，建议执行xx", "根据知识库文档，说明判断依据并给出具体建议")
    description["text"] = description_text

    suggest_json = _user_prompt(nodes["1750662408086"])
    suggest_text = suggest_json["text"]
    suggest_text = _replace(
        suggest_text,
        "根因为EPOLL：strace -e epoll_wait,epoll_pwait -tt -T -p <PID>追踪epoll调用耗时，perf trace -e epoll:*查看epoll相关事件等命令",
        EPOLL_NETWORK_GUIDANCE,
    )
    suggest_text = _replace(suggest_text, "根据知识库文档，建议执行xx，联系xx进行解决", "根据知识库文档给出具体建议；有真实负责人信息时再给出联系方式")
    suggest_json["text"] = suggest_text

    report_view = _user_prompt(nodes["1764048001002"])
    report_text = report_view["text"]
    report_text = _replace(
        report_text,
        "infra/system 使用 Pod 重启、OOMKill、节点资源、容器状态、K8s Event、CPU、内存",
        "infra/system 按运行环境选择证据：VM 使用主机资源、进程状态和系统日志；容器使用 Pod 重启、OOMKill、节点资源、容器状态和 K8s Event；环境不明确时使用通用 CPU、内存和系统证据",
    )
    report_text = _replace(
        report_text,
        "excluded.title 示例：已排除xx、xx方向",
        "excluded.title 使用真实方向，例如“已排除 CPU、文件方向”",
    )
    report_view["text"] = report_text

    downstream = _user_prompt(nodes["1754382620041"])
    downstream_text = downstream["text"]
    downstream_text = _replace(
        downstream_text,
        "当前实例{{#1742807803325.pod#}}",
        "当前运行对象{{#v2_runtime_environment_context.location_text#}}",
    )
    downstream_text = _replace(
        downstream_text,
        "添加下游实例对当前实例产生告警的描述，如：”当前实例产生xx告警，初步推断为下游xxx实例/服务引起。“",
        "使用真实告警名称和下游服务/实例描述下游影响；没有具体下游证据时明确说明证据不足，不得使用占位词。",
    )
    downstream_text = _replace(
        downstream_text,
        "细化报告根因问题，如“下游依赖问题”改为“xxx下游依赖问题”xx为具体下游服务。",
        "有具体下游服务时将“下游依赖问题”细化为该服务的下游依赖问题；没有具体服务时保留通用表述。",
    )
    downstream["text"] = downstream_text

    for node_id in PROMPT_REFINEMENT_NODE_IDS:
        prompt = _user_prompt(nodes[node_id])
        prompt["text"] = prompt["text"] + COMMON_OUTPUT_IDENTITY_RULES


def replace_rtt_nodes(document: dict) -> None:
    detection = node_by_id(document, "17515143872690")
    detection["data"]["code"] = RTT_DETECTION_CODE

    attribution = node_by_id(document, "1754298166852")
    attribution["data"]["code"] = RTT_ATTRIBUTION_CODE
    attribution["data"]["outputs"] = {
        "abnormal_downstream_instances": {"type": "string", "children": None},
        "direction_summary": {"type": "string", "children": None},
        "evidence_quality": {"type": "string", "children": None},
        "requires_span_fallback": {"type": "string", "children": None},
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


def add_representative_trace_sampling(document: dict) -> None:
    graph = document["workflow"]["graph"]
    slow = node_by_id(document, "1759065773395")
    slow["data"]["title"] = "在数据平面查询慢traces"
    slow["data"]["tool_label"] = "在数据平面查询慢traces"
    slow_params = slow["data"]["tool_parameters"]
    slow_params["limit"] = {"type": "constant", "value": 30}
    slow_params["minDuration"] = {"type": "constant", "value": 200000}

    error = copy.deepcopy(slow)
    error_id = "v2_error_trace_query"
    error["id"] = error_id
    error["position"] = {"x": 11414, "y": 1170}
    error["positionAbsolute"] = {"x": 11414, "y": 1170}
    error["data"]["title"] = "在数据平面查询错误traces"
    error["data"]["tool_label"] = "在数据平面查询错误traces"
    error_params = error["data"]["tool_parameters"]
    error_params["limit"] = {"type": "constant", "value": 20}
    error_params["isError"] = {"type": "constant", "value": True}
    error_params.pop("minDuration", None)
    graph["nodes"].append(error)

    merge_id = "v2_trace_merge"
    graph["nodes"].append(
        {
            "id": merge_id,
            "type": "custom",
            "position": {"x": 11718, "y": 900},
            "positionAbsolute": {"x": 11718, "y": 900},
            "width": 244,
            "height": 54,
            "selected": False,
            "sourcePosition": "right",
            "targetPosition": "left",
            "data": {
                "type": "code",
                "title": "合并慢Trace与错误Trace",
                "desc": "",
                "code_language": "python3",
                "code": TRACE_MERGE_CODE,
                "selected": False,
                "variables": [
                    {"variable": "slow_trace_data", "value_selector": ["1759065773395", "text"]},
                    {"variable": "error_trace_data", "value_selector": [error_id, "text"]},
                ],
                "outputs": {"result": {"type": "string", "children": None}},
            },
        }
    )

    entry = node_by_id(document, "1759065776597")
    entry["data"]["code"] = TRACE_ENTRY_CODE
    entry["data"]["variables"][0]["value_selector"] = [merge_id, "result"]
    entry["data"]["outputs"]["trace_evidence"] = {"type": "array[object]", "children": None}

    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if not (edge["source"] == "1759065773395" and edge["target"] == "1759065776597")
    ]
    graph["edges"].extend(
        [
            {
                "id": f"1759065773395-source-{error_id}-target",
                "type": "custom",
                "source": "1759065773395",
                "sourceHandle": "source",
                "target": error_id,
                "targetHandle": "target",
                "selected": False,
                "zIndex": 0,
                "data": {"isInIteration": False, "sourceType": "tool", "targetType": "tool"},
            },
            {
                "id": f"{error_id}-source-{merge_id}-target",
                "type": "custom",
                "source": error_id,
                "sourceHandle": "source",
                "target": merge_id,
                "targetHandle": "target",
                "selected": False,
                "zIndex": 0,
                "data": {"isInIteration": False, "sourceType": "tool", "targetType": "code"},
            },
            {
                "id": f"{merge_id}-source-1759065776597-target",
                "type": "custom",
                "source": merge_id,
                "sourceHandle": "source",
                "target": "1759065776597",
                "targetHandle": "target",
                "selected": False,
                "zIndex": 0,
                "data": {"isInIteration": False, "sourceType": "code", "targetType": "code"},
            },
        ]
    )


def build() -> dict:
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document = copy.deepcopy(document)
    document["app"]["name"] = "告警简单根因分析V2"
    add_environment_context(document)
    inject_environment_prompts(document)
    refine_output_prompts(document)
    replace_rtt_nodes(document)
    replace_p90_and_merge_nodes(document)
    rewire_span_enrichment(document)
    add_representative_trace_sampling(document)
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
