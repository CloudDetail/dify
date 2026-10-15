"""按告警→实例→原图工具参数验证标签适配，不要求名为 instance 的标签。"""

import json
from types import SimpleNamespace

import pytest
from test_core_workflow_engine import END, SERVICE, START
from test_core_workflow_engine import test_original_graph_to_report as run_graph

from core.tools.builtin_tool.providers.data_source import QueryMetricResult


def discover(monkeypatch, attrs):
    from core.tools.builtin_tool.providers import service_instances as module

    monkeypatch.setattr(module, "dify_config", SimpleNamespace(DATAPLANE_URL="http://dataplane"))
    monkeypatch.setattr(
        module.requests,
        "post",
        lambda *a, **k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "success": True,
                "data": [{"serviceName": SERVICE, **attrs}],
            },
        ),
    )
    return module.query_instances(SERVICE, "tenant-a", START, END)


@pytest.mark.parametrize(
    ("attrs", "field", "value"),
    [
        ({"podName": "pod-a", "namespace": "ns"}, "podName", "pod-a"),
        ({"podName": "pod-a", "containerPid": "7", "hostName": "pod-a"}, "pid", ""),
        ({"nodeName": "node-a", "processId": "42"}, "nodeName", "node-a"),
        ({"containerId": "container-a"}, "containerId", "container-a"),
        ({"hostName": "node-a", "processId": "42"}, "pid", "42"),
    ],
)
def test_real_labels_are_enough_without_instance_id(monkeypatch, attrs, field, value):
    result = discover(monkeypatch, attrs)
    assert result["status"] == "ok"
    assert len(result["data"]) == 1
    item = result["data"][0]
    assert item["instanceId"] == ""
    assert item["identityStatus"] == "resolved"
    assert item[field] == value


def test_pod_only_cos_record_reaches_original_latency_graph(monkeypatch):
    result = discover(monkeypatch, {"podName": "pod-a", "namespace": "ns"})
    record = {}
    run_graph("告警简单根因分析", "cpu", record=record, instance_records=result["data"])
    assert "1779332497301" in record["visited"]
    cpu = next(c for c in record["tool_calls"] if c["node"] == "17430595109950")
    assert cpu["params"]["pod"] == "pod-a"
    assert record["saved"]


def test_last_seen_uses_actual_template_parameters(monkeypatch):
    from core.tools.builtin_tool.providers.apo_select.tools import service_last_seen as module

    monkeypatch.setattr(module, "dify_config", SimpleNamespace(DATA_SOURCE="dataplane"))
    calls = []

    def query(**kwargs):
        calls.append(kwargs)
        return QueryMetricResult(data={"timeseries": [{"chart": {"chartData": {str(START): 100}}}]})

    monkeypatch.setattr(module, "query_metric", query)
    tool = module.ServiceLastSeen.__new__(module.ServiceLastSeen)
    result = json.loads(
        next(
            tool._invoke(
                "u",
                {
                    "nodeName": "node-a",
                    "workloadName": "worker",
                    "startTime": START,
                    "endTime": END,
                    "tenantId": "tenant-a",
                },
            )
        ).message.text
    )
    assert result["data"] == 100
    assert calls[0]["labels"]["service_name"] == "node-a"
    assert calls[0]["labels"]["max_by"] == "node_name,workload_name"
    assert calls[0]["start_time"] < calls[0]["end_time"]


def test_process_zero_is_distinct_from_missing(monkeypatch):
    from core.tools.builtin_tool.providers.apo_select.tools import service_process_count as module

    monkeypatch.setattr(module, "dify_config", SimpleNamespace(DATA_SOURCE="dataplane"))
    tool = module.ServiceProcessCount.__new__(module.ServiceProcessCount)
    for values, expected in [({str(START): 0}, 0), ({}, "")]:
        monkeypatch.setattr(
            module,
            "query_metric",
            lambda values=values, **k: QueryMetricResult(data={"timeseries": [{"chart": {"chartData": values}}]}),
        )
        result = json.loads(next(tool._invoke("u", {"endTime": END, "tenantId": "tenant-a"})).message.text)
        assert result["data"] == expected


def test_container_hostname_is_not_a_node(monkeypatch):
    result = discover(monkeypatch, {"hostName": "pod-like-name", "containerPid": "1"})
    assert result["data"][0]["nodeName"] == ""
    assert result["data"][0]["pid"] == ""
    assert result["data"][0]["identityStatus"] == "unresolved"


def test_instance_directory_timeout_and_empty(monkeypatch):
    import requests

    from core.tools.builtin_tool.providers import service_instances as module
    monkeypatch.setattr(module, "dify_config", SimpleNamespace(DATAPLANE_URL="http://dataplane"))

    def timeout(*args, **kwargs):
        raise requests.Timeout("COS timed out")
    monkeypatch.setattr(module.requests, "post", timeout)
    result = module.query_instances(SERVICE, "tenant-a", START, END)
    assert result["status"] == "error" and not result["complete"]
    monkeypatch.setattr(module.requests, "post", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"success": True, "data": []}))
    result = module.query_instances(SERVICE, "tenant-a", START, END)
    assert result["status"] == "no_data" and result["complete"]
