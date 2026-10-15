"""从真实图变量绑定执行 Code 和日志工具，核对出站范围及分段窗口。"""
import pytest
import requests
from test_ecloud_tools import Response, context, invoke  # noqa: F401
from test_ecloud_workflow_queries import nodes, parameters, run

CASES = [
    ("告警简单根因分析", "1750830567613", "1750830747193"),
    ("可用性告警分析", "1779266302359", "1753414547927"),
    ("可用性告警分析", "1758786771169017587867711701", "1758786771169017587867711700"),
]
START = 1791786245502000
END = START + 900_000_000


def evaluate(ns, node_id, values):
    args = {v["variable"]: values[tuple(v["value_selector"])] for v in ns[node_id]["data"]["variables"]}
    return run(ns[node_id], **args)


@pytest.mark.parametrize("name,code_id,tool_id", CASES)
@pytest.mark.parametrize("service", ["test:v1::grid-orchestrator|csp|", "test:v1::crud-server", "a' OR serviceName='b", r"svc\path"])
def test_service_scope_reaches_dataplane(context, monkeypatch, name, code_id, tool_id, service):
    _, load = context
    ns = nodes(name)
    # 不提供 Pod、PID、容器或实例目录，模拟 Backend 的服务级告警。
    values = {
        ("1742807803325", "service"): service,
        ("1742807803325", "tenantId"): "tenant-a",
        ("1741227526517", "startTime"): START,
        ("1741227526517", "endTime"): END,
        ("1753414924837", "startTime"): START,
        ("1753414924837", "endTime"): END,
        ("17587867711690", "item"): {"startTime": START, "endTime": END},
    }
    out = evaluate(ns, code_id, values)
    values.update({(code_id, key): value for key, value in out.items()})
    calls = []

    def post(url, json, **kwargs):
        calls.append(json)
        assert url.endswith("/datasource/queryLogs")
        assert json["filter"] == {"serviceName": service}
        assert json["tenantId"] == "tenant-a"
        assert json["providerId"] == 0
        assert (json["startTime"], json["endTime"]) == (START, END)
        return Response({"success": True, "data": [{"dataSource": "cos", "logs": []}]})

    monkeypatch.setattr(requests, "post", post)
    result = invoke(load("query_full_logs"), parameters(ns[tool_id], values))
    assert len(calls) == 1
    assert result["status"] == "no_data"


@pytest.mark.parametrize("name,code_id,tool_id", CASES)
@pytest.mark.parametrize("service", ["", "   ", None])
def test_missing_service_never_becomes_tenant_wide_query(name, code_id, tool_id, service):
    values = {
        ("1742807803325", "service"): service,
        ("17587867711690", "item"): {"startTime": START, "endTime": END},
    }
    with pytest.raises(ValueError, match="缺少告警服务名"):
        evaluate(nodes(name), code_id, values)


def test_all_extended_segments_use_their_own_end_time(context, monkeypatch):
    _, load = context
    ns = nodes("可用性告警分析")
    segments = run(ns["17587867711701"], start_time=START, end_time=END)["result"]
    calls = []

    def post(url, json, **kwargs):
        calls.append((json["startTime"], json["endTime"]))
        assert json["startTime"] < json["endTime"]
        return Response({"success": True, "data": [{"dataSource": "cos", "logs": []}]})

    monkeypatch.setattr(requests, "post", post)
    tool = load("query_full_logs")
    for item in segments:
        values = {
            ("1742807803325", "service"): "test:v1::grid-orchestrator|csp|",
            ("1742807803325", "tenantId"): "tenant-a",
            ("1741227526517", "endTime"): END,
            ("17587867711690", "item"): item,
        }
        out = evaluate(ns, "1758786771169017587867711701", values)
        values.update({("1758786771169017587867711701", k): v for k, v in out.items()})
        result = invoke(tool, parameters(ns["1758786771169017587867711700"], values))
        assert result["status"] == "no_data"
    assert len(calls) == 10
    assert calls[0][0] == START
    assert calls[-1][1] == END + 300_000_000
    assert all(left[1] == right[0] for left, right in zip(calls, calls[1:]))
    assert all(start > END for start, _ in calls[-2:])
