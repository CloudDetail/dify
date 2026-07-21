from pathlib import Path
from typing import Callable
import json
from collections import defaultdict, deque

import yaml

from core.workflow.graph_engine.entities.graph import Graph
from core.workflow.nodes.code.entities import CodeNodeData
from scripts.build_alert_simple_root_cause_workflow_v2 import build, main as generate_v2


WORKFLOW_DIR = Path(__file__).parents[3] / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
V2 = WORKFLOW_DIR / "告警简单根因分析V2.yml"
OUTPUT_PROMPT_NODE_IDS = {
    "1741512806512",
    "17430596469370",
    "17473569800940",
    "1750662084996",
    "1750662408086",
    "1764048001002",
    "1754382620041",
}


def load_workflow(path: Path = V2) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def nodes_by_title(title: str) -> list[dict]:
    nodes = load_workflow()["workflow"]["graph"]["nodes"]
    return [node for node in nodes if node.get("data", {}).get("title") == title]


def code_node_main(title: str) -> Callable:
    matches = nodes_by_title(title)
    assert len(matches) == 1
    namespace: dict = {}
    exec(matches[0]["data"]["code"], namespace)
    return namespace["main"]


def prompt_text(node: dict) -> str:
    return "\n".join(item.get("text", "") for item in node["data"].get("prompt_template", []))


def node_prompt(node_id: str) -> str:
    nodes = load_workflow()["workflow"]["graph"]["nodes"]
    node = next(node for node in nodes if node["id"] == node_id)
    return prompt_text(node)


def complete_labels(**overrides) -> dict:
    labels = {
        "src_pod": "source-pod",
        "src_node": "source-node",
        "src_ip": "10.0.0.1",
        "dst_pod": "target-pod",
        "dst_node": "target-node",
        "dst_ip": "10.0.0.2",
    }
    labels.update(overrides)
    return labels


def series(values: list[float], labels: dict, legend: str = "target") -> dict:
    return {
        "legend": legend,
        "labels": labels,
        "chart": {"chartData": {str(index): value for index, value in enumerate(values)}},
    }


def run_rtt_detection(timeseries: list[dict]) -> list[dict]:
    main = code_node_main("RTT分析")
    payload = json.dumps({"unit": "s", "data": {"timeseries": timeseries}})
    return json.loads(main(payload)["result"])


def run_rtt_attribution(detected: list[dict]) -> dict:
    main = code_node_main("分析RTT问题")
    return main(json.dumps(detected))


def graph_path_exists(source: str, target: str, source_handle: str | None = None) -> bool:
    graph = load_workflow()["workflow"]["graph"]
    outgoing = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["source"]].append(edge)
    queue = deque([(source, True)])
    seen = set()
    while queue:
        current, first = queue.popleft()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        for edge in outgoing[current]:
            if first and source_handle is not None and edge.get("sourceHandle") != source_handle:
                continue
            queue.append((edge["target"], False))
    return False


def condition_case_handle(value: str) -> str:
    node = nodes_by_title("条件分支 5")[0]
    for case in node["data"]["cases"]:
        conditions = case.get("conditions", [])
        if conditions and conditions[0].get("value") == value:
            return case["case_id"]
    raise AssertionError(value)


def trace_payload(traces: list[dict]) -> str:
    return json.dumps({"type": "trace", "data": {"data": traces}})


def span(
    name: str,
    duration: int,
    *,
    service: str = "app",
    parent_span_id: str = "root",
    error: bool = False,
    attributes: dict | None = None,
) -> dict:
    return {
        "spanId": f"span-{name}",
        "parentSpanId": parent_span_id,
        "name": name,
        "serviceName": service,
        "duration": duration,
        "error": error,
        "attributes": attributes or {},
    }


def trace(trace_id: str, duration: int, *, error: bool = False, child: dict | None = None) -> dict:
    spans = [
        span(
            "GET /entry",
            duration,
            service="entry-service",
            parent_span_id="",
            error=error,
        )
    ]
    if child:
        spans.append(child)
    return {"traceId": trace_id, "duration": duration, "error": error, "spans": spans}


def database_span(duration: int, *, error: bool = True) -> dict:
    return span(
        "SELECT orders",
        duration,
        service="mysql",
        error=error,
        attributes={"db.system": "mysql", "db.statement": "SELECT * FROM orders"},
    )


def test_v2_workflow_exists_and_has_distinct_name():
    workflow = load_workflow()

    assert workflow["app"]["name"] == "告警简单根因分析V2"
    assert SOURCE.read_bytes() != V2.read_bytes()


def test_v2_graph_has_unique_nodes_and_valid_edges():
    graph = load_workflow()["workflow"]["graph"]
    node_ids = [node["id"] for node in graph["nodes"]]

    assert len(node_ids) == len(set(node_ids))
    known = set(node_ids)
    for edge in graph["edges"]:
        assert edge["source"] in known
        assert edge["target"] in known


def test_v2_graph_respects_parallel_depth_limit():
    graph_config = load_workflow()["workflow"]["graph"]

    Graph.init(graph_config)


def test_v2_code_node_output_schemas_are_supported():
    nodes = load_workflow()["workflow"]["graph"]["nodes"]

    for node in nodes:
        if node.get("data", {}).get("type") == "code":
            CodeNodeData.model_validate(node["data"])


def test_v2_generation_is_deterministic_and_preserves_source():
    source_before = SOURCE.read_bytes()
    first = build()
    second = build()

    generate_v2()

    assert first == second
    assert load_workflow() == first
    assert SOURCE.read_bytes() == source_before


def test_environment_context_detects_vm_container_and_unknown():
    main = code_node_main("运行环境上下文")

    vm = main(pod="", container_id="", node="vm-01", pid="123")
    container = main(pod="pod-1", container_id="", node="node-1", pid="123")
    unknown = main(pod="", container_id="", node="", pid="")

    assert vm["scene"] == "vm"
    assert "kubectl" in vm["forbidden_terms"]
    assert "主机" in vm["prompt_context"]
    assert container["scene"] == "container"
    assert unknown["scene"] == "unknown"
    assert "中性术语" in unknown["prompt_context"]


def test_key_llm_prompts_reference_environment_context():
    titles = {
        "llm analysis root cause",
        "网络方向分析",
        "总结下游影响",
        "可行动方向建议",
        "可行动建议JSON",
        "根因方向JSON",
        "生成报告展示结构",
    }

    for title in titles:
        matches = nodes_by_title(title)
        assert matches, title
        for node in matches:
            text = prompt_text(node)
            assert "{{#v2_runtime_environment_context.prompt_context#}}" in text, title
            assert "运行环境上下文优先" in text, title


def test_epoll_guidance_uses_network_diagnostics_instead_of_epoll_tracing():
    prompts = node_prompt("1741512806512") + node_prompt("1750662408086")

    assert "strace -e epoll_wait" not in prompts
    assert "epoll_pwait" not in prompts
    assert "perf trace -e epoll:" not in prompts
    for expected in ("ss -s", "nstat -az", "RTT", "下游 Span"):
        assert expected in prompts


def test_root_cause_prompt_uses_real_service_and_environment_identity():
    prompt = node_prompt("17430596469370")

    assert "服务xx" not in prompt
    assert "{{#1754299310647.service#}}" in prompt
    assert "{{#v2_runtime_environment_context.location_text#}}" in prompt
    assert "服务名为空时省略" in prompt


def test_output_prompts_do_not_treat_pod_as_the_only_instance_type():
    for node_id in OUTPUT_PROMPT_NODE_IDS:
        prompt = node_prompt(node_id)
        assert "{{#v2_runtime_environment_context.prompt_context#}}" in prompt
        assert "不得因为指标或工具名称包含“按Pod统计”" in prompt


def test_sparse_40ms_rtt_spike_is_detected():
    detected = run_rtt_detection([series([0.0] * 99 + [0.04], complete_labels())])

    assert len(detected) == 1
    assert "sparse_spike" in detected[0]["detectionReasons"]


def test_rtt_detection_processes_series_after_first_ten():
    normal = [
        series([0.0, 0.0], complete_labels(dst_pod=f"normal-{index}"))
        for index in range(10)
    ]
    detected = run_rtt_detection(
        normal + [series([0.0, 0.08], complete_labels(dst_pod="late"), legend="late")]
    )

    assert detected[0]["labels"]["dst_pod"] == "late"


def test_missing_dst_node_or_ip_does_not_drop_instance():
    detected = [
        {
            "labels": {"dst_pod": "db-1"},
            "legend": "db-1",
            "avg": 0.04,
            "spike": 0.04,
            "unit": "s",
        }
    ]

    result = run_rtt_attribution(detected)
    instances = json.loads(result["abnormal_downstream_instances"])

    assert result["direction_summary"] == "下游实例问题"
    assert instances[0]["instance_name"] == "db-1"
    assert result["evidence_quality"] == "partial"


def test_attribution_never_returns_empty_downstream_problem():
    result = run_rtt_attribution(
        [{"labels": {}, "legend": "", "avg": 0.04, "spike": 0.04, "unit": "s"}]
    )

    assert result["direction_summary"] == "未明确归因"
    assert result["requires_span_fallback"] == "true"
    assert json.loads(result["abnormal_downstream_instances"]) == []


def test_p90_uses_all_response_time_series_and_ignores_zeroes():
    main = code_node_main("计算延时P90数据")
    payload = json.dumps(
        {
            "data": [
                {
                    "title": "吞吐量",
                    "unit": "count",
                    "timeseries": [{"chart": {"chartData": {"1": 999}}}],
                },
                {
                    "title": "Response Time",
                    "unit": "ms",
                    "timeseries": [
                        {"chart": {"chartData": {"1": 0, "2": 100}}},
                        {"chart": {"chartData": {"1": 200, "2": 300}}},
                    ],
                },
            ]
        }
    )

    result = main(payload)

    assert result["threshold_source"] == "response_time_p90"
    assert result["p90_value_us"] == 280000


def test_downstream_instance_branch_reaches_span_query():
    handle = condition_case_handle("下游实例问题")

    assert graph_path_exists("1754299061896", "1754442999808", source_handle=handle)


def test_downstream_node_branch_reaches_span_query():
    handle = condition_case_handle("下游节点问题")

    assert graph_path_exists("1754299061896", "1754442999808", source_handle=handle)


def test_merge_keeps_rtt_and_database_span_evidence():
    main = code_node_main("合并RTT与Span下游证据")
    rtt_instances = json.dumps([{"instance_name": "mysql-1", "rtt_avg": "40ms"}])
    span_data = json.dumps(
        {
            "data": {
                "data": [
                    {
                        "serviceName": "mysql",
                        "spanKind": "client",
                        "name": "SELECT orders",
                        "duration": 900000,
                        "traceId": "trace-1",
                        "spanId": "span-1",
                        "attributes": {"db.system": "mysql", "db.statement": "SELECT * FROM orders"},
                    }
                ]
            }
        }
    )

    result = json.loads(main(rtt_instances, span_data)["result"])

    assert result["rtt_instances"][0]["instance_name"] == "mysql-1"
    assert result["span_dependencies"][0]["db_system"] == "mysql"
    assert result["evidence_status"] == "complete"


def test_trace_merge_deduplicates_and_preserves_slow_trace():
    main = code_node_main("合并慢Trace与错误Trace")
    slow = trace_payload([trace("slow-db", 2_000_000, child=database_span(1_800_000))])
    errors = trace_payload(
        [trace(f"short-{index}", 5_000, error=True) for index in range(20)]
        + [trace("slow-db", 2_000_000, error=True, child=database_span(1_800_000))]
    )

    result = json.loads(main(slow, errors)["result"])
    ids = [item["traceId"] for item in result["traces"]]

    assert ids.count("slow-db") == 1
    assert "slow-db" in ids


def test_trace_merge_extracts_root_slowest_and_error_spans():
    main = code_node_main("合并慢Trace与错误Trace")
    payload = trace_payload(
        [trace("database", 2_000_000, child=database_span(1_800_000, error=True))]
    )

    item = json.loads(main(payload, trace_payload([]))["result"])["traces"][0]

    assert item["entry"]["service"] == "entry-service"
    assert item["slowestSpan"]["dbSystem"] == "mysql"
    assert item["errorSpan"] is not None


def test_trace_queries_split_slow_and_error_samples():
    slow = nodes_by_title("在数据平面查询慢traces")[0]
    error = nodes_by_title("在数据平面查询错误traces")[0]
    slow_params = slow["data"]["tool_parameters"]
    error_params = error["data"]["tool_parameters"]

    assert slow_params["limit"]["value"] == 30
    assert slow_params["minDuration"]["value"] == 200000
    assert error_params["limit"]["value"] == 20
    assert error_params["isError"]["value"] is True
