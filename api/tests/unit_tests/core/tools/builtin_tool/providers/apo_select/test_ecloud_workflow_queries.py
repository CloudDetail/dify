"""Execute migrated YAML queries with real tools and controlled HTTP responses."""

import json
import re
from pathlib import Path

import pytest
import requests
import yaml
from test_ecloud_tools import END, START, Response, context, invoke, metric_payload  # noqa: F401

WORKFLOWS = Path(__file__).resolve().parents[7] / "init_data/workflows/zh"
DAY = 86_400_000_000


def nodes(name):
    graph = yaml.safe_load((WORKFLOWS / (name + ".yml")).read_text())["workflow"]["graph"]
    return {node["id"]: node for node in graph["nodes"]}


def run(node, **kwargs):
    namespace = {}
    exec(compile(node["data"]["code"], node["id"], "exec"), namespace)
    return namespace["main"](**kwargs)


def parameters(node, values):
    result = {}
    for key, param in node["data"]["tool_parameters"].items():
        if param["type"] == "variable":
            result[key] = values[tuple(param["value"])]
        elif param["type"] == "mixed":
            result[key] = re.sub(r"\{\{#([^#]+)#\}\}", lambda m: str(values[tuple(m[1].split("."))]), param["value"])
        else:
            result[key] = param["value"]
    return result


def metric(service, title, unit, value):
    return {
        "title": title,
        "unit": unit,
        "timeseries": [
            {
                "labels": {"serviceName": service},
                "chart": {"chartData": {str(START): value, str(END): None}},
                "step": 60_000_000,
            }
        ],
    }


@pytest.mark.parametrize("tenant", ["tenant-a", "tenant-b"])
def test_latency_exact_24h_history(context, monkeypatch, tenant):
    _, load = context
    ns = nodes("告警有效性确认")
    values = {
        ("1742806924635", "service"): "orders",
        ("1742806924635", "endpoint"): "GET /orders",
        ("1742806924635", "tenantId"): tenant,
        ("1741157526222", "startTime"): START,
        ("1741157526222", "endTime"): END,
        ("1742433446760", "history_st"): START - DAY,
    }
    calls = []

    def post(url, json, **kwargs):
        assert url.endswith("/datasource/queryMetrics")
        calls.append(json)
        assert json["tenantId"] == tenant
        assert json["providerId"] == 0
        assert json["labels"] == {"service_name": "orders", "content_key": "GET /orders"}
        history = json["startTime"] < START
        assert json["endTime"] - json["startTime"] <= DAY
        step = 3_600_000_000 if history else 60_000_000
        chart = {str(json["startTime"] + i * step): 100 if history else 150 for i in range(3)}
        payload = metric_payload()
        result = payload["data"][0]["metrics"]["result"]
        result["unit"] = "ms"
        result["timeseries"][0]["chart"]["chartData"] = chart
        return Response(payload)

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("legacy HTTP"))
    for id in ["1741328045214", "17424339242280"]:
        values[(id, "text")] = json.dumps(invoke(load("originx_service_red_avg_resp"), parameters(ns[id], values)))
    node = ns["1744599772545"]
    args = {v["variable"]: values[tuple(v["value_selector"])] for v in node["data"]["variables"]}
    assert run(node, **args)["abnormal"] == "false"
    assert len(calls) == 2
    assert (calls[1]["startTime"], calls[1]["endTime"]) == (START - DAY, START)


def test_peak_duration_and_empty_policy():
    node = nodes("告警有效性确认")["1744599772545"]

    def payload(points):
        return json.dumps({"data": {"timeseries": [{"chart": {"chartData": points}}]}})

    history = payload({str(START - DAY): 100})
    result = run(
        node,
        current_json=payload({str(START): 200, str(START + 60_000_000): 100, str(END): 100}),
        history_json=history,
        start=START,
        end=END,
    )
    assert "峰值持续时间约1.0分钟" in result["conclusion"]
    for points in [{}, {str(START): None}]:
        assert run(node, current_json=payload(points), history_json=history, start=START, end=END)["abnormal"] == "unknown"


@pytest.mark.parametrize(
    ("name", "prefix", "output"),
    [("可用性告警分析", "1790208002", "1750941439700"), ("告警简单根因分析", "1790208001", "1750750056742")],
)
@pytest.mark.parametrize("tenant", ["tenant-a", "tenant-b"])
def test_topology_iteration(context, monkeypatch, name, prefix, output, tenant):
    _, load = context
    ns = nodes(name)
    calls = []
    offset = 0 if tenant == "tenant-a" else 1000
    values = {
        ("1742807803325", "tenantId"): tenant,
        ("1742807803325", "service"): "B",
        ("1741227526517", "startTime"): START,
        ("1741227526517", "endTime"): END,
    }

    def post(url, json, **kwargs):
        assert json["tenantId"] == tenant
        assert json["providerId"] == 0
        assert "groupId" not in json
        assert (json["startTime"], json["endTime"]) == (START, END)
        calls.append((url, json))
        if url.endswith("/queryTopology"):
            return Response(
                {
                    "success": True,
                    "data": [
                        {"parentService": a, "childService": b}
                        for a, b in [("A", "B"), ("B", "C"), ("A", "B"), ("B", "A")]
                    ],
                }
            )
        assert url.endswith("/queryServiceRedCharts")
        service = json["serviceName"]
        return Response(
            {
                "success": True,
                "data": {
                    service: {
                        "cpm": {str(START): 120 + offset, str(END): 0},
                        "avgDurationMs": {str(START): ord(service) + offset, str(END): None},
                        "errorRate": {str(START): 0.02},
                        "step": 60_000_000,
                    }
                },
            }
        )

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("legacy HTTP"))
    tid, lid, iid, sid, rid = [prefix + s for s in ["01", "02", "03", "04", "05"]]
    text = json.dumps(invoke(load("dataplane_service_topology"), parameters(ns[tid], values)))
    services = run(ns[lid], topology_json=text)["result"]
    assert services == ["B", "A", "C"]
    assert ns[iid]["data"]["iterator_selector"] == [lid, "result"]
    assert ns[iid]["data"]["output_selector"] == [rid, "text"]
    assert ns[sid]["parentId"] == ns[rid]["parentId"] == iid
    outputs = []
    for service in services:
        values[(iid, "item")] = service
        outputs.append(json.dumps(invoke(load("dataplane_service_redcharts"), parameters(ns[rid], values))))
    report = json.loads(run(ns[output], topology_json=text, services_red=outputs)["result"])
    assert report["current"]["service"] == "B"
    assert [s["service"] for s in report["parents"]] == ["A"]
    assert [s["service"] for s in report["children"]] == ["C", "A"]
    for item in [report["current"], *report["parents"], *report["children"]]:
        m = item["metrics"]["avgDurationMs"]
        assert m["unit"] == "ms"
        assert m["chartData"] == {str(START): ord(item["service"]) + offset, str(END): None}
    assert len(calls) == 4
    assert run(ns[output], topology_json='{"error":"failed"}', services_red=[]) == {"result": "{}"}


def test_red_named_fields_legacy_units_and_duplicates():
    node = nodes("告警简单根因分析")["1750819000832"]
    data = [
        metric("orders", n, u, v)
        for n, u, v in [("Tpm", "requests/minute", 120), ("Error Rate", "%", 2), ("Response Time", "us", 120000)]
    ]
    data[2]["timeseries"][0]["chart"]["value"] = 120000
    result = json.loads(run(node, red_json=json.dumps({"data": data}), service="orders")["result"])
    assert [(x["type"], x["unit"], x["chartData"][str(START)]) for x in result["data"]] == [
        ("avgDurationMs", "ms", 120),
        ("errorRate", "percentunit", 0.02),
        ("cpm", "requests/min", 120),
    ]
    assert all(x["chartData"][str(END)] is None for x in result["data"])
    assert result["data"][0]["value"] == 120
    with pytest.raises(ValueError, match="Ambiguous"):
        run(node, red_json=json.dumps({"data": data + [data[0]]}), service="orders")


@pytest.mark.parametrize(("name", "id"), [("告警简单根因分析", "1759066552234"), ("可用性告警分析", "1760103472918")])
def test_existing_consumers(name, id):
    text = json.dumps(
        {"data": [metric("orders", "avgDurationMs", "ms", 120), metric("orders", "errorRate", "percentunit", 0.02)]}
    )
    result = run(nodes(name)[id], red_json=text, history_red_json=text)
    assert json.loads(result["request_latency"])["unit"] == "ms"
    assert json.loads(result["request_error_rate"])["unit"] == "percentunit"
    assert json.loads(result["request_latency"])["data"]["timeseries"]
