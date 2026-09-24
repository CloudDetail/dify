"""工具入口到 dataplane HTTP 合同，不启动数据库或模型。"""

import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import requests
import yaml

from core.tools.builtin_tool.providers import data_source

TOOLS = Path(__file__).resolve().parents[7] / "core/tools/builtin_tool/providers/apo_select/tools"
START = 1_790_208_000_000_000
END = START + 120_000_000


def metric_payload(value=0.9995):
    return {
        "success": True,
        "data": [
            {
                "providerId": 1,
                "clusterId": "",
                "dataSource": "cos",
                "metrics": {
                    "msg": "",
                    "result": {
                        "title": "metric",
                        "unit": "percentunit",
                        "timeseries": [
                            {
                                "legend": "orders",
                                "legendFormat": "{{serviceName}}",
                                "labels": {"serviceName": "orders"},
                                "chart": {"chartData": {str(START): value, str(END): 0.0}, "value": value},
                            }
                        ],
                    },
                },
            }
        ],
    }


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


@pytest.fixture
def context(monkeypatch):
    config = SimpleNamespace(DATA_SOURCE="dataplane", DATAPLANE_URL="http://dataplane", APO_BACKEND_URL="http://apo")
    configs = ModuleType("configs")
    configs.dify_config = config
    monkeypatch.setitem(sys.modules, "configs", configs)
    monkeypatch.setattr(data_source, "dify_config", config)
    tool = ModuleType("core.tools.builtin_tool.tool")

    class BuiltinTool:
        def create_text_message(self, text):
            return SimpleNamespace(message=SimpleNamespace(text=text))

    tool.BuiltinTool = BuiltinTool
    monkeypatch.setitem(sys.modules, tool.__name__, tool)
    entities = ModuleType("core.tools.entities.tool_entities")
    entities.ToolInvokeMessage = object
    monkeypatch.setitem(sys.modules, entities.__name__, entities)
    monkeypatch.delitem(sys.modules, "libs.apo_utils", raising=False)

    def load(name):
        base = "core.tools.builtin_tool.providers.apo_select.tools."
        monkeypatch.delitem(sys.modules, base + "process_resource_metric_base", raising=False)
        monkeypatch.delitem(sys.modules, base + name, raising=False)
        return importlib.import_module(base + name)

    return config, load


def invoke(module, params):
    cls = next(
        v
        for v in vars(module).values()
        if isinstance(v, type) and v.__module__ == module.__name__ and hasattr(v, "_invoke")
    )
    return json.loads(next(cls.__new__(cls)._invoke("user", params)).message.text)


def metric_tools():
    return [
        p.stem
        for p in sorted(TOOLS.glob("*.py"))
        if p.with_suffix(".yaml").exists()
        and (
            "query_metric(" in p.read_text()
            or "query_legacy_metric(" in p.read_text()
            or "ProcessResourceMetricTool)" in p.read_text()
        )
    ]


@pytest.mark.parametrize("name", metric_tools())
def test_metric_tool_tenant_routing(context, monkeypatch, name):
    _, load = context
    params = {
        p["name"]: False if p["type"] == "boolean" else 1 if p["type"] == "number" else "orders"
        for p in yaml.safe_load((TOOLS / f"{name}.yaml").read_text())["parameters"]
    }
    params.update(
        tenantId="tenant-a", startTime=START, endTime=END, providerId=0, pid="123", content_key=".*", type="cpu"
    )
    calls = []

    def post(url, json, **kwargs):
        calls.append(json)
        assert url == "http://dataplane/datasource/queryMetrics"
        assert json["tenantId"] == "tenant-a"
        assert json["providerId"] == 0
        assert "tenantId" not in json["labels"]
        assert "groupId" not in json
        payload = metric_payload()
        if name == "polaris_time_by_pid":
            payload["data"][0]["metrics"]["result"]["timeseries"][0]["labels"] = {"pid": "123", "node_name": "orders"}
        return Response(payload)

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("unexpected APO/VM GET"))
    result = invoke(load(name), params)
    assert calls, name
    assert result["type"] == "metric"


def test_concurrent_tenants_single_value_zero(context, monkeypatch):
    def post(url, json, **kwargs):
        payload = metric_payload(0)
        series = payload["data"][0]["metrics"]["result"]["timeseries"][0]
        series["labels"] = {"tenant": json["tenantId"]}
        series["chart"]["chartData"] = {}
        return Response(payload)

    monkeypatch.setattr(requests, "post", post)

    def query(tenant):
        return data_source.query_metric("single_service_fail_rate", START, END, 60_000_000, tenant_id=tenant)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(query, ["tenant-a", "tenant-b"]))
    for result, tenant in zip(results, ["tenant-a", "tenant-b"]):
        series = result.data["timeseries"][0]
        assert series["labels"]["tenant"] == tenant
        assert series["chart"] == {"chartData": {}, "value": 0}


def test_missing_tenant_and_error_preserve_empty_result(context, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("unscoped network request"))
    assert data_source.query_metric("service_cpm", START, END, 60_000_000).data == {"timeseries": []}

    def failed(*a, **k):
        raise requests.HTTPError("upstream failed")

    monkeypatch.setattr(requests, "post", failed)
    assert data_source.query_metric("service_cpm", START, END, 60_000_000, tenant_id="tenant-a").data == {
        "timeseries": []
    }


def test_success_rate_no_rescaling(context, monkeypatch):
    calls = []

    def post(url, json, **kwargs):
        calls.append(json)
        return Response(metric_payload())

    monkeypatch.setattr(requests, "post", post)
    result = data_source.query_red_metrics("Success Rate", "orders", "", START, END, ".*", "tenant-a")
    assert calls[0]["metric"].endswith("请求成功率")
    assert calls[0]["labels"] == {"service_name": "orders"}
    assert result.data["timeseries"][0]["chart"]["chartData"][str(START)] == 0.9995


def test_red_fields_step_and_exact_endpoint(context, monkeypatch):
    _, load = context
    module = load("dataplane_service_redcharts")
    calls = []

    def post(url, json, **kwargs):
        calls.append(json)
        assert json["tenantId"] == "tenant-a"
        assert json["providerId"] == 0
        if url.endswith("/queryMetrics"):
            assert json["labels"] == {"service_name": "orders", "content_key": "GET /orders"}
            return Response(metric_payload())
        assert url.endswith("/queryServiceRedCharts")
        assert "endpoint" not in json
        return Response(
            {
                "success": True,
                "data": {
                    json["serviceName"]: {
                        "cpm": {str(START): 55.38, str(END): 0},
                        "errorRate": {str(START): 0.0005},
                        "avgDurationMs": {str(START): 1.41},
                        "step": 3_600_000_000,
                    }
                },
            }
        )

    monkeypatch.setattr(requests, "post", post)
    result = json.loads(module.query_service_redcharts("orders", "", ".*", START, END, "tenant-a"))
    assert [m["title"] for m in result["data"]] == ["cpm", "errorRate", "avgDurationMs"]
    assert [m["unit"] for m in result["data"]] == ["requests/min", "percentunit", "ms"]
    series = result["data"][0]["timeseries"][0]
    assert series["chart"]["chartData"] == {str(START): 55.38, str(END): 0}
    assert series["step"] == 3_600_000_000
    module.query_service_redcharts("orders", "", "GET /orders", START, END, "tenant-a")
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("name", "endpoint"),
    [
        ("dataplane_traces", "queryTraces"),
        ("dataplane_spans", "querySpans"),
        ("dataplane_topology", "queryTopology"),
        ("query_full_logs", "queryLogs"),
    ],
)
def test_observation_scope_and_objects(context, monkeypatch, name, endpoint):
    _, load = context
    calls = []

    def post(url, json, **kwargs):
        calls.append(json)
        assert url.endswith("/datasource/" + endpoint)
        assert json["tenantId"] == "tenant-a"
        assert json["providerId"] == 0
        assert json["startTime"] == START
        assert json["endTime"] == END
        return Response({"success": True, "data": []})

    monkeypatch.setattr(requests, "post", post)
    invoke(
        load(name),
        {
            "tenantId": "tenant-a",
            "providerId": "0",
            "startTime": str(START),
            "endTime": str(END),
            "service": "orders",
            "traceId": "trace-a",
            "query": "k8s_pod_name='orders'",
            "isError": False,
        },
    )
    assert len(calls) == 1
    if endpoint in ("queryTraces", "querySpans"):
        assert calls[0]["filter"]["service"] == "orders"
        assert calls[0]["filter"]["traceId"] == "trace-a"
        assert calls[0]["filter"]["error"] is False
    elif endpoint == "queryLogs":
        assert calls[0]["filter"] == {"podName": "orders"}


def test_topology_direction(context, monkeypatch):
    _, load = context
    edges = [
        {"parentService": "web", "parentType": "app", "childService": "orders", "childType": "app"},
        {"parentService": "orders", "parentType": "app", "childService": "db", "childType": "db"},
    ]

    def post(url, json, **kwargs):
        assert json["tenantId"] == "tenant-a"
        return Response({"success": True, "data": edges})

    monkeypatch.setattr(requests, "post", post)
    result = invoke(
        load("dataplane_service_topology"),
        {"tenantId": "tenant-a", "service": "orders", "startTime": START, "endTime": END},
    )["data"]
    assert result["parents"][0]["service"] == "web"
    assert result["children"][0]["service"] == "db"
    assert "endpoint" not in result["current"]
    assert "isTraced" not in result["current"]


def test_apo_contract_unchanged(context, monkeypatch):
    config, load = context
    config.DATA_SOURCE = "apo"

    def post(url, json, **kwargs):
        assert url == "http://apo/api/metric/query"
        assert "tenantId" not in json
        assert json["params"] == {"node": "node-a"}
        return Response({"result": {"unit": "percent", "timeseries": []}})

    monkeypatch.setattr(requests, "post", post)
    assert invoke(load("host_cpu_usage"), {"node": "node-a", "startTime": START, "endTime": END})["unit"] == "percent"


def test_declarations_have_unique_tenant_parameter():
    names = metric_tools() + [
        "dataplane_service_redcharts",
        "dataplane_service_topology",
        "dataplane_topology",
        "dataplane_traces",
        "dataplane_spans",
        "query_full_logs",
    ]
    for name in names:
        params = yaml.safe_load((TOOLS / f"{name}.yaml").read_text())["parameters"]
        assert len([p for p in params if p["name"] == "tenantId"]) == 1, name
        assert len({p["name"] for p in params}) == len(params), name


@pytest.mark.parametrize(("source", "scale"), [("cos", 1000), ("cos", 1), ("apo", 1)])
def test_timestamp_units_not_double_converted(context, monkeypatch, source, scale):
    payload = metric_payload()
    payload["data"][0]["dataSource"] = source
    payload["data"][0]["metrics"]["result"]["timeseries"][0]["chart"]["chartData"] = {
        str(START // scale): 0,
        str(END // scale): None,
    }
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response(payload))
    result = data_source.query_metric("metric", START, END, 60_000_000, tenant_id="tenant-a")
    assert result.data["timeseries"][0]["chart"]["chartData"] == {str(START): 0, str(END): None}


def test_real_http_two_tenants(context):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    config, load = context
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, body))
            assert body["providerId"] == 0
            assert body["tenantId"] in ("tenant-a", "tenant-b")
            payload = metric_payload(0.1 if body["tenantId"] == "tenant-a" else 0.2)
            payload["data"][0]["metrics"]["result"]["timeseries"][0]["labels"] = body["labels"]
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config.DATAPLANE_URL = f"http://127.0.0.1:{server.server_port}"
    module = load("host_cpu_usage")
    try:

        def query(tenant):
            return invoke(module, {"tenantId": tenant, "node": "same-node", "startTime": START, "endTime": END})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(query, ["tenant-a", "tenant-b"]))
        assert [r["data"]["timeseries"][0]["chart"]["chartData"][str(START)] for r in results] == [0.1, 0.2]
        assert len(captured) == 2
        assert all(
            path == "/datasource/queryMetrics" and body["labels"] == {"node": "same-node"} for path, body in captured
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
