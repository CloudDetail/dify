import json
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

import yaml

from core.workflow.graph_engine.entities.graph import Graph
from core.workflow.nodes.code.entities import CodeNodeData

WORKFLOW_DIR = Path(__file__).parents[3] / "init_data" / "workflows" / "zh"
WORKFLOW = WORKFLOW_DIR / "告警简单根因分析.yml"
OUTPUT_PROMPT_NODE_IDS = {
    "1741512806512",
    "17430596469370",
    "17473569800940",
    "1750662084996",
    "1750662408086",
    "1764048001002",
    "1754382620041",
}


def load_workflow(path: Path = WORKFLOW) -> dict:
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


def test_workflow_uses_canonical_name():
    workflow = load_workflow()

    assert workflow["app"]["name"] == "告警简单根因分析"


def test_workflow_graph_has_unique_nodes_and_valid_edges():
    graph = load_workflow()["workflow"]["graph"]
    node_ids = [node["id"] for node in graph["nodes"]]

    assert len(node_ids) == len(set(node_ids))
    known = set(node_ids)
    for edge in graph["edges"]:
        assert edge["source"] in known
        assert edge["target"] in known


def test_workflow_graph_respects_parallel_depth_limit():
    graph_config = load_workflow()["workflow"]["graph"]

    Graph.init(graph_config)


def test_workflow_code_node_output_schemas_are_supported():
    nodes = load_workflow()["workflow"]["graph"]["nodes"]

    for node in nodes:
        if node.get("data", {}).get("type") == "code":
            CodeNodeData.model_validate(node["data"])


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
    for expected in ("ss -s", "nstat -az", "下游 Span"):
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


def test_span_evidence_keeps_database_details_without_assuming_root_cause():
    main = code_node_main("整理Span下游证据")
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

    result = json.loads(main(span_data)["result"])

    assert result["span_dependencies"][0]["db_system"] == "mysql"
    assert result["evidence_status"] == "partial"


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


def test_simple_workflow_has_no_rtt_nodes_prompts_or_variable_references():
    graph = load_workflow()["workflow"]["graph"]
    serialized = json.dumps(graph, ensure_ascii=False)
    assert "rtt" not in serialized, "残留小写 RTT 引用"
    assert "RTT" not in serialized, "残留 RTT 节点或提示词"
    assert "网络往返" not in serialized
    assert "网络Ping" not in serialized
    ids = {n["id"] for n in graph["nodes"]}

    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("value_selector") or key == "variable_selector":
                    if item and item[0] not in {"env", "sys"}:
                        assert item[0] in ids, item
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(graph)


def test_network_route_queries_spans_without_quality_gate_and_other_route_remains():
    assert graph_path_exists("1754385298311", "1754442999808", source_handle="1")
    assert graph_path_exists("1754385298311", "1754385689812", source_handle="2")
    assert not graph_path_exists("1754385298311", "1754442999808", source_handle="2")
    assert graph_path_exists("17430598907140", "17511128736240")
    assert graph_path_exists("17430610599980", "17511127594560")


def test_net_and_epoll_preserve_strong_candidates_and_empty_data_boundary():
    for title, direction in [("NET analyze", "net"), ("EPOLL analyze", "epoll")]:
        main = code_node_main(title)
        detected = {
            "activeThreadCount": 2,
            "candidateCount": 1,
            "candidateContribution": 0.65,
            "directionSummary": {"peak": 50},
            "directionSignals": [{"score": 0.9, "type": "step"}],
            "candidates": [{"threadId": "42", "score": 0.85, "contribution": 0.65,
                            "chart": {"1": 5, "2": 50}, "labels": {"tid": "42"}}],
        }
        result = json.loads(main(json.dumps(detected))["result"])
        assert result["direction"] == direction
        assert result["status"] == "strong_potential_anomaly"
        assert result["candidateContribution"] == 0.65
        assert result["directionSignals"] == detected["directionSignals"]
        assert result["directionSummary"] == detected["directionSummary"]
        assert result["candidates"][0]["relatedEvidence"] == []
        assert result["candidates"][0]["threadId"] == "42"
        assert json.loads(main("{}")["result"])["status"] == "insufficient_data"


def test_empty_span_evidence_does_not_claim_downstream_fault():
    result = json.loads(code_node_main("整理Span下游证据")('{"data":{"data":[]}}')["result"])
    assert result == {"span_dependencies": [], "evidence_status": "empty"}
    prompt = node_prompt("1754382620041")
    assert "尚不能确定自身或下游原因" in prompt
    assert "缺少调用证据时保留原线程结论" in prompt


def test_report_evidence_retains_logs_and_red_without_network_quality_chart():
    result = code_node_main("生成验证数据")(
        json.dumps({"type": "metrics", "name": "RED", "data": [{"value": 123}]}),
        json.dumps({"logs": [{"message": "timeout"}]}), "响应延时升高", "调用超时")
    evidence = json.loads(result["result"])["evidence"]
    assert len(evidence) == 2
    assert evidence[0]["data"] == [{"message": "timeout"}]
    assert evidence[1]["data"] == [{"value": 123}]
    assert evidence[1]["description"] == "响应延时升高"


def test_span_evidence_accepts_real_filtered_provider_array():
    main = code_node_main("整理Span下游证据")
    payload = {"providerId": 1, "dataSource": "cos", "unit": "us", "data": [
        {"serviceName": "test:v1::orders", "peerService": "inventory", "spanKind": "client",
         "name": "GET /stock", "duration": 6000, "traceId": "trace-real-shape",
         "spanId": "span-2", "attributes": {"server.address": "inventory.internal"}}
    ]}
    result = json.loads(main(json.dumps(payload))["result"])
    assert result["evidence_status"] == "partial"
    assert len(result["span_dependencies"]) == 1
    dependency = result["span_dependencies"][0]
    assert dependency["service"] == "inventory"
    assert dependency["duration"] == 6000
    assert dependency["operation"] == "GET /stock"
    assert dependency["trace_id"] == "trace-real-shape"
