"""COS 输入适配回归：不以缺少对象或请求失败充当有效证据。"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).parents[3]
START = 1791600000000000
END = START + 900000000


def test_instance_discovery_uses_unified_contract_and_preserves_partial(monkeypatch):
    from core.tools.builtin_tool.providers import service_instances as m

    monkeypatch.setattr(m, "dify_config", SimpleNamespace(DATAPLANE_URL="http://dataplane"))
    calls = []

    def post(url, json, **kwargs):
        calls.append(json)
        assert url == "http://dataplane/datasource/queryServiceInstances"
        assert json == {"tenantId": "tenant-a", "providerId": 0, "serviceName": "orders", "startTime": START, "endTime": END}
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"success": True, "data": [{"serviceName": "orders", "podName": "pod-a",
                "nodeName": "node-a", "instanceId": "native-instance-a", "containerPid": "7", "processId": ""}], "failedDS": ["other"]},
        )

    monkeypatch.setattr(m.requests, "post", post)
    result = m.query_instances("orders", "tenant-a", START, END)
    assert len(calls) == 1
    assert result["status"] == "partial"
    assert result["complete"] is False
    assert result["data"][0]["pid"] == ""
    assert result["data"][0]["containerPid"] == "7"
    assert result["data"][0]["instanceId"] == "native-instance-a"
    assert result["data"][0]["podName"] == "pod-a"
    assert result["data"][0]["identityStatus"] == "resolved"


@pytest.mark.parametrize("payload", [
    {"success": False, "error": "COS failed"},
    {"success": True, "data": [], "failedDS": ["COS failed"]},
    {"success": True, "data": [{"error": "COS failed", "data": []}]},
    {"success": True, "data": [{"serviceName": "other-service"}]},
    {"success": True, "data": [{"serviceName": "orders", "instanceId": {"id": "bad"}}]},
    {"success": True, "data": [{"serviceName": "orders", "containerPid": 7}]},
])
def test_provider_error_is_not_empty_success(monkeypatch, payload):
    from core.tools.builtin_tool.providers import service_instances as m

    monkeypatch.setattr(m, "dify_config", SimpleNamespace(DATAPLANE_URL="http://dataplane"))
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: payload))
    result = m.query_instances("orders", "tenant-a", START, END)
    assert result["status"] == "error"
    assert result["data"] == []
    assert result["error"]


@pytest.mark.parametrize("record,expected", [
    ({"hostName": "host-a", "processId": "42"}, ("", "", "42", "host-a", "resolved")),
    ({"instanceId": "cos-a", "hostName": "looks-like-pod", "containerPid": "7"},
     ("cos-a", "7", "", "", "unresolved")),
    ({"instanceId": "cos-b", "podName": "pod-a", "nodeName": "n", "containerPid": "7", "processId": "42000"},
     ("cos-b", "7", "42000", "n", "resolved")),
])
def test_instance_identity_preserves_pid_namespaces_and_legacy_records(monkeypatch, record, expected):
    from core.tools.builtin_tool.providers import service_instances as m

    monkeypatch.setattr(m, "dify_config", SimpleNamespace(DATAPLANE_URL="http://dataplane"))
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"success": True, "data": [{"serviceName": "orders", **record}]}))
    result = m.query_instances("orders", "tenant-a", START, END)
    assert result["status"] == "ok"
    item = result["data"][0]
    assert tuple(item[k] for k in ("instanceId", "containerPid", "pid", "nodeName", "identityStatus")) == expected
    assert item["containerId"] == ""


def test_thread_evidence_preserves_windows_and_thread_identity(monkeypatch):
    from core.tools.builtin_tool.providers.apo_select.tools import dataplane_instance_evidence as m
    from core.tools.builtin_tool.providers.data_source import QueryMetricResult

    instance = {
        "identityStatus": "resolved",
        "podName": "p",
        "namespace": "ns",
        "nodeName": "n",
        "pid": "42",
        "containerId": "",
    }
    monkeypatch.setattr(m, "query_instances", lambda *a: {"data": [instance]})
    calls = []

    def query(metric, start, end, step, labels, tenant_id):
        calls.append((metric, start, end, labels, tenant_id))
        return QueryMetricResult(
            data={"timeseries": [{"labels": {"tid_key": "thread-1"}, "chart": {"chartData": {str(start): 1}}}]}
        )

    monkeypatch.setattr(m, "query_metric", query)
    obj = m.InstanceEvidenceTool.__new__(m.InstanceEvidenceTool)
    result = json.loads(
        next(
            obj._invoke("u", {"service": "orders", "tenantId": "tenant-a", "startTime": START, "endTime": END})
        ).message.text
    )
    assert len(calls) == 9
    for i, (metric, start, end, labels, tenant) in enumerate(calls[:8]):
        assert metric.endswith("北极星指标（线程） - 告警有效性一分钟增量")
        assert (start, end) == ((START, END) if i < 4 else (START - 3600000000, START))
        assert labels["namespace"] == "ns"
        assert labels["pod"] == "p"
        assert tenant == "tenant-a"
    assert result["data"][0]["ebpf"]["current"]["cpu"]["data"]["timeseries"][0]["labels"]["tid_key"] == "thread-1"


def test_node_enumeration_does_not_require_pid(monkeypatch):
    from core.tools.builtin_tool.providers import data_source as m

    monkeypatch.setattr(m, "dify_config", SimpleNamespace(DATA_SOURCE="dataplane"))
    calls = []
    monkeypatch.setattr(
        m, "__query_metric_by_dataplane", lambda **kwargs: calls.append(kwargs) or m.QueryMetricResult()
    )
    metric = "Thread Polaris Metrics - 北极星指标（进程） - 节点上被监控的服务列表"
    m.query_metric(metric, START, END, 60000000, {"node_name": "node-a"}, tenant_id="t")
    assert len(calls) == 1
    missing = m.query_metric(metric, START, END, 60000000, {}, tenant_id="t")
    assert missing.data["status"] == "unresolved_instance"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "name", ["告警事件分类", "告警有效性确认", "告警简单根因分析", "可用性告警分析", "资源告警分析"]
)
def test_all_code_bindings_and_node_references(name):
    graph = yaml.safe_load((ROOT / "init_data/workflows/zh" / (name + ".yml")).read_text())["workflow"]["graph"]
    ids = {n["id"] for n in graph["nodes"]}
    for node in graph["nodes"]:
        data = node["data"]
        if data["type"] == "code":
            tree = ast.parse(data["code"])
            main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
            arguments = {a.arg for a in main.args.args}
            required = {a.arg for a in main.args.args[: len(main.args.args) - len(main.args.defaults)]}
            bound = {v["variable"] for v in data.get("variables", [])}
            assert required <= bound <= arguments, node["id"]
        for v in data.get("variables", []):
            if isinstance(v, dict) and v.get("value_selector"):
                assert v["value_selector"][0] in ids | {"env", "sys", "conversation"}
    if name == "告警简单根因分析":
        # RTT 已移除，仍保留网络、CPU、运行队列、Epoll、文件五类线程查询。
        assert {e["target"] for e in graph["edges"] if e["source"] == "1747355869184" and e["sourceHandle"] == "false"} == {
            "17430598907140", "17430595109950", "17430610719970", "17430610599980", "17430597987060",
        }


@pytest.mark.parametrize(
    ("alert", "category", "app_name"),
    [
        ("平均请求延时相比昨天升高50%以上", "request_latency", "告警简单根因分析"),
        ("请求错误率超过0%", "service_availability", "可用性告警分析"),
        ("容器CPU使用率超过80%", "infrastructure", "资源告警分析"),
    ],
)
def test_classification_routes_match_initializer(alert, category, app_name):
    graph = yaml.safe_load((ROOT / "init_data/workflows/zh/告警事件分类.yml").read_text())["workflow"]["graph"]
    nodes = {n["id"]: n["data"] for n in graph["nodes"]}
    ns = {}
    exec(nodes["1745224789961"]["code"], ns)
    classified = ns["main"](alert, "app", json.dumps({"tenantId": "tenant-a"}))
    assert classified == {"result": category, "tenantId": "tenant-a"}
    exec(nodes["1745304707998"]["code"], ns)
    routed = ns["main"](category)
    tree = ast.parse((ROOT / "initializer/workflow.py").read_text())
    adjust = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_adjust_workflows")
    config = ast.literal_eval(adjust.body[0].value)["zh-Hans"][app_name]
    assert routed["result"] == config["app_id"]
    assert routed["apikey"] == config["api_token"]


def test_empty_pod_cannot_query_all_container_metrics(monkeypatch):
    from core.tools.builtin_tool.providers import data_source as m

    monkeypatch.setattr(m, "dify_config", SimpleNamespace(DATA_SOURCE="dataplane"))
    monkeypatch.setattr(m, "__query_metric_by_dataplane", lambda **kwargs: pytest.fail("全局容器查询"))
    result = m.query_metric(
        "基础设施情况 - 容器CPU - 容器CPU使用率 - Containerd", START, END, 60000000, {"pod": ".*"}, tenant_id="t"
    )
    assert result.data["status"] == "unresolved_instance"


def test_explicit_object_retains_legacy_service_lookup(monkeypatch):
    from core.tools.builtin_tool.providers.apo_select.tools import dataplane_instance_service_name as m

    monkeypatch.setattr(m, "dify_config", SimpleNamespace(DATA_SOURCE="dataplane"))
    calls = []
    monkeypatch.setattr(
        m, "query_service_name", lambda **kwargs: calls.append(kwargs) or json.dumps({"data": "orders"})
    )
    obj = m.InstanceServiceTool.__new__(m.InstanceServiceTool)
    assert (
        json.loads(next(obj._invoke("u", {"pod": "pod-a", "startTime": START, "endTime": END})).message.text)["data"]
        == "orders"
    )
    assert calls[0]["pod"] == "pod-a"
    result = json.loads(next(obj._invoke("u", {"startTime": START, "endTime": END})).message.text)
    assert result["status"] == "unresolved_instance"
    assert len(calls) == 1
