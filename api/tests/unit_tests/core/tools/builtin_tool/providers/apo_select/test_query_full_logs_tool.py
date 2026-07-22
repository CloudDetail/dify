import json
import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace

import pytest


def _load_tool(monkeypatch):
    stub_configs = ModuleType("configs")
    stub_configs.dify_config = SimpleNamespace(DATAPLANE_URL="http://dataplane")

    stub_tool_module = ModuleType("core.tools.builtin_tool.tool")

    class StubBuiltinTool:
        def create_text_message(self, text):
            return SimpleNamespace(message=SimpleNamespace(text=text))

    stub_tool_module.BuiltinTool = StubBuiltinTool
    stub_entities_module = ModuleType("core.tools.entities.tool_entities")
    stub_entities_module.ToolInvokeMessage = object

    monkeypatch.setitem(sys.modules, "configs", stub_configs)
    monkeypatch.setitem(sys.modules, "core.tools.builtin_tool.tool", stub_tool_module)
    monkeypatch.setitem(sys.modules, "core.tools.entities.tool_entities", stub_entities_module)
    module_path = "core.tools.builtin_tool.providers.apo_select.tools.query_full_logs"
    monkeypatch.delitem(sys.modules, module_path, raising=False)
    return import_module(module_path)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_query_full_logs_uses_dataplane_and_converts_all_providers(monkeypatch):
    module = _load_tool(monkeypatch)
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _Response(
            {
                "success": True,
                "data": [
                    {
                        "providerId": 1,
                        "clusterId": "cluster-a",
                        "dataSource": "apo",
                        "logs": [
                            {
                                "timestamp": "2026-07-22T10:00:00.000Z",
                                "level": "error",
                                "message": "failed",
                                "attributes": {
                                    "source": "stdout",
                                    "pod": "pod-a",
                                    "container_name": "container-a",
                                },
                            }
                        ],
                    },
                    {
                        "providerId": 2,
                        "clusterId": "cluster-b",
                        "dataSource": "elastic",
                        "logs": [
                            {
                                "timestamp": "2026-07-22T09:00:00.000Z",
                                "level": "info",
                                "message": "started",
                                "attributes": {},
                            }
                        ],
                    },
                ],
            }
        )

    monkeypatch.setattr(module.requests, "post", fake_post)
    tool = module.QueryFullLogsTool.__new__(module.QueryFullLogsTool)
    result = next(
        tool._invoke(
            user_id="user-1",
            tool_parameters={
                "query": "k8s_pod_name='pod-a' and container_name='container-a'",
                "pageNum": 1,
                "pageSize": 99,
                "startTime": 100,
                "endTime": 200,
            },
        )
    )

    assert calls == [
        {
            "url": "http://dataplane/datasource/queryLogs",
            "json": {
                "providerId": 0,
                "startTime": 100,
                "endTime": 200,
                "filter": {"podName": "pod-a", "containerName": "container-a"},
                "limit": 99,
            },
            "timeout": 15,
        }
    ]
    payload = json.loads(result.message.text)
    assert payload["data"]["logContents"]["contents"] == [
        {
            "body": "failed",
            "timestamp": "2026-07-22T10:00:00.000Z",
            "tags": {
                "source": "stdout",
                "pod": "pod-a",
                "container_name": "container-a",
                "level": "error",
                "dataSource": "apo",
                "clusterId": "cluster-a",
            },
        },
        {
            "body": "started",
            "timestamp": "2026-07-22T09:00:00.000Z",
            "tags": {"level": "info", "dataSource": "elastic", "clusterId": "cluster-b"},
        },
    ]


def test_query_full_logs_expands_or_filters_and_applies_source_locally(monkeypatch):
    module = _load_tool(monkeypatch)
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        pod = json["filter"]["podName"]
        return _Response(
            {
                "success": True,
                "data": [
                    {
                        "providerId": 1,
                        "clusterId": "cluster-a",
                        "dataSource": "apo",
                        "logs": [
                            {
                                "timestamp": f"2026-07-22T10:00:0{len(calls)}.000Z",
                                "level": "error",
                                "message": pod,
                                "attributes": {"source": "stdout" if pod == "pod-a" else "stderr"},
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr(module.requests, "post", fake_post)
    tool = module.QueryFullLogsTool.__new__(module.QueryFullLogsTool)
    result = next(
        tool._invoke(
            user_id="user-1",
            tool_parameters={
                "query": "(k8s_pod_name='pod-a' OR k8s_pod_name='pod-b') AND source='stdout'",
                "pageNum": 1,
                "pageSize": 10,
                "startTime": 100,
                "endTime": 200,
            },
        )
    )

    assert [call["filter"] for call in calls] == [{"podName": "pod-a"}, {"podName": "pod-b"}]
    payload = json.loads(result.message.text)
    assert [item["body"] for item in payload["data"]["logContents"]["contents"]] == ["pod-a"]


def test_query_full_logs_rejects_unsupported_raw_sql(monkeypatch):
    module = _load_tool(monkeypatch)
    tool = module.QueryFullLogsTool.__new__(module.QueryFullLogsTool)

    with pytest.raises(ValueError, match="Unsupported log query"):
        next(
            tool._invoke(
                user_id="user-1",
                tool_parameters={
                    "query": "content LIKE '%error%'",
                    "pageNum": 1,
                    "pageSize": 10,
                    "startTime": 100,
                    "endTime": 200,
                },
            )
        )
