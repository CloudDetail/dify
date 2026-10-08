"""COS 响应经实际工具进入中文工作流，覆盖资源身份和历史窗口。"""

import json
from copy import deepcopy

import pytest
import requests
from test_ecloud_tools import END, START, Response, context, invoke, metric_payload  # noqa: F401
from test_ecloud_workflow_queries import DAY, nodes, parameters, run

from core.tools.builtin_tool.providers import data_source


NATIVE = {
    "k8s_pod_name": "orders-0",
    "k8s_namespace_name": "ns-a",
    "k8s_node_name": "worker-1",
    "k8s_container_name": "app",
}
ALIASES = {"pod": "orders-0", "namespace": "ns-a", "node": "worker-1", "containerName": "app"}


@pytest.mark.parametrize("source", ["cos", "apo", "prometheusmetric"])
@pytest.mark.parametrize("entrypoint", ["query_metric", "query_legacy_metric"])
def test_resource_aliases_at_both_query_entries(context, monkeypatch, source, entrypoint):
    payload = metric_payload()
    result = payload["data"][0]
    result["dataSource"] = source
    series = result["metrics"]["result"]["timeseries"][0]
    series["labels"] = dict(NATIVE)
    series["chart"] = {"chartData": {str(START): 0, str(END): None}, "value": 0}
    original = deepcopy(payload)
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(payload))
    if entrypoint == "query_metric":
        output = data_source.query_metric("resource", START, END, 60_000_000, tenant_id="tenant-a").data
    else:
        output = data_source.query_legacy_metric(
            {"metricName": "resource", "startTime": START, "endTime": END, "step": 60_000_000}, "tenant-a"
        )
    actual = output["timeseries"][0]
    assert actual["labels"] == (NATIVE | ALIASES if source == "cos" else NATIVE)
    assert actual["chart"] == series["chart"]
    assert "containerId" not in actual["labels"] and "pid" not in actual["labels"]
    assert "container" not in actual["labels"]
    assert payload == original


def test_aliases_preserve_existing_fields_and_do_not_invent_missing_identity():
    labels = NATIVE | {"pod": "legacy-pod", "node": "", "pid": "123", "containerId": "real-id"}
    actual = data_source._cos_resource_labels(labels)
    assert actual["pod"] == "legacy-pod"
    assert actual["node"] == "worker-1"
    assert actual["pid"] == "123" and actual["containerId"] == "real-id"
    assert all(actual[k] == v for k, v in NATIVE.items())
    assert data_source._cos_resource_labels({"serviceName": "orders"}) == {"serviceName": "orders"}
    assert data_source._cos_resource_labels({"k8s_pod_name": ""}) == {"k8s_pod_name": ""}


@pytest.mark.parametrize("legacy", [False, True])
def test_tool_to_all_resource_label_consumers(context, monkeypatch, legacy):
    _, load = context
    payload = metric_payload()
    result = payload["data"][0]["metrics"]["result"]
    sample = result["timeseries"][0]
    result["timeseries"] = []
    for namespace in ("ns-a", "ns-b"):
        entry = deepcopy(sample)
        entry["labels"] = (ALIASES | {"namespace": namespace}) if legacy else (NATIVE | {"k8s_namespace_name": namespace})
        result["timeseries"].append(entry)
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(payload))
    output = invoke(load("container_cpu_usage_containerd"), {
        "pod": "orders-0", "startTime": START, "endTime": END, "tenantId": "tenant-a",
    })
    text = json.dumps(output)
    ns = nodes("资源告警分析")
    all_instances = run(ns["1743652552181"], arg1=text)["instances"]
    assert {item["namespace"] for item in all_instances} == {"ns-a", "ns-b"}
    assert run(ns["1752741434678"], data_json=text) == {"node": "worker-1"}
    assert run(ns["1752742381956"], arg1=text, target_pod="other") == {"pods": "orders-0"}
    assert run(ns["1752742381956"], arg1=text, target_pod="orders-0") == {"pods": ""}
    for analysis, extract in [("1752827682722", "1752655200938"), ("1753789618196", "17526596567180")]:
        analyzed = run(ns[analysis], data_json=text)["result"]
        instances = run(ns[extract], result_json_str=analyzed)["instances"]
        assert len(instances) == 2
        assert {item["namespace"] for item in instances} == {"ns-a", "ns-b"}
        assert all(item["pod"] == "orders-0" and item["node"] == "worker-1" for item in instances)
        assert all(item["containerId"] == "" and item["pid"] == "" for item in instances)
    # “其他 pods”消费的是上游算法保留的 labels；重复采样不增加实例数量。
    entries = output["data"]["timeseries"]
    instances = run(ns["1752804688058"], data=json.dumps(entries + entries))["result"]
    assert len(instances) == 2
    assert {item["namespace"] for item in instances} == {"ns-a", "ns-b"}


@pytest.mark.parametrize(("id", "tool"), [
    ("17429835599060", "container_cpu_usage_containerd"),
    ("17429835940550", "container_memory_usage_containerd_bytes"),
])
def test_container_history_queries_previous_day_with_hourly_step(context, monkeypatch, id, tool):
    _, load = context
    ns = nodes("告警有效性确认")
    history = run(ns["1742433446760"], arg1=START, arg2=END)
    values = {
        ("1742433446760", "history_st"): history["history_st"],
        ("1741157526222", "startTime"): START,
        ("1741157526222", "endTime"): END,
        ("1742806924635", "namespace"): "ns-a",
        ("1742806924635", "pod"): "orders-0",
        ("1742806924635", "tenantId"): "tenant-a",
    }
    calls = []

    def post(url, json, **kwargs):
        assert url.endswith("/datasource/queryMetrics")
        calls.append(json)
        return Response(metric_payload())

    monkeypatch.setattr(requests, "post", post)
    invoke(load(tool), parameters(ns[id], values))
    assert len(calls) == 1
    request = calls[0]
    assert (request["startTime"], request["endTime"]) == (START - DAY, START)
    assert request["step"] == 3_600_000_000
    assert request["labels"] == {"pod": "orders-0", "namespace": "ns-a"}
    assert request["tenantId"] == "tenant-a" and request["providerId"] == 0
