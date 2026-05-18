import json
import sys
from dataclasses import asdict
from importlib import import_module
from types import ModuleType
from types import SimpleNamespace

import pytest

from core.tools.builtin_tool.providers.data_source import QueryMetricResult


START_TIME = 1_700_000_000_000_000
END_TIME = 1_700_000_600_000_000
STEP = 60_000_000

PROCESS_TOOL_CASES = [
    (
        "process_cpu_usage",
        "ProcessCPUUsageTool",
        "进程监控指标 - 进程 CPU 使用速率",
        False,
    ),
    (
        "process_memory_usage",
        "ProcessMemoryUsageTool",
        "进程监控指标 - 进程内存使用",
        False,
    ),
    (
        "process_disk_read_bytes",
        "ProcessDiskReadBytesTool",
        "进程监控指标 - 进程读取字节速率",
        False,
    ),
    (
        "process_disk_write_bytes",
        "ProcessDiskWriteBytesTool",
        "进程监控指标 - 进程写入字节速率",
        False,
    ),
]


@pytest.mark.parametrize(
    ("module_name", "class_name", "metric_name", "use_backend_api"),
    PROCESS_TOOL_CASES,
)
def test_process_resource_tools_call_expected_metric(module_name, class_name, metric_name, use_backend_api, monkeypatch):
    stub_configs = ModuleType("configs")
    stub_configs.dify_config = SimpleNamespace(APO_BACKEND_URL="http://apo-backend")

    stub_tool_module = ModuleType("core.tools.builtin_tool.tool")

    class StubBuiltinTool:
        def create_text_message(self, text):
            return SimpleNamespace(message=SimpleNamespace(text=text))

    stub_tool_module.BuiltinTool = StubBuiltinTool

    stub_entities_module = ModuleType("core.tools.entities.tool_entities")
    stub_entities_module.ToolInvokeMessage = object

    stub_utils_module = ModuleType("libs.apo_utils")

    class StubAPOUtils:
        @staticmethod
        def get_step(start_time, end_time):
            return STEP

        @staticmethod
        def get_and_build_metric_params(param, key_map):
            result = {}
            for source_key, target_key in key_map.items():
                value = param.get(source_key)
                if value is not None and value != "":
                    result[target_key] = value
            return result

    stub_utils_module.APOUtils = StubAPOUtils

    monkeypatch.setitem(sys.modules, "configs", stub_configs)
    monkeypatch.setitem(sys.modules, "core.tools.builtin_tool.tool", stub_tool_module)
    monkeypatch.setitem(sys.modules, "core.tools.entities.tool_entities", stub_entities_module)
    monkeypatch.setitem(sys.modules, "libs.apo_utils", stub_utils_module)
    monkeypatch.delitem(
        sys.modules,
        "core.tools.builtin_tool.providers.apo_select.tools.process_resource_metric_base",
        raising=False,
    )
    monkeypatch.delitem(
        sys.modules,
        f"core.tools.builtin_tool.providers.apo_select.tools.{module_name}",
        raising=False,
    )

    base_module = import_module("core.tools.builtin_tool.providers.apo_select.tools.process_resource_metric_base")
    tool_module = import_module(f"core.tools.builtin_tool.providers.apo_select.tools.{module_name}")
    tool_cls = getattr(tool_module, class_name)
    tool = tool_cls.__new__(tool_cls)

    query_metric_calls = []
    post_calls = []

    def fake_query_metric(metric_name, start_time, end_time, step, labels):
        query_metric_calls.append(
            {
                "metric_name": metric_name,
                "start_time": start_time,
                "end_time": end_time,
                "step": step,
                "labels": labels,
            }
        )
        return QueryMetricResult(
            unit="core",
            data={
                "timeseries": [
                    {
                        "legend": "proc-a",
                        "labels": {"groupname": "proc-a"},
                        "chart": {"chartData": {"1700000000000000": 1.0}},
                    }
                ]
            },
        )

    def fake_post(url, json):
        post_calls.append({"url": url, "json": json})
        return SimpleNamespace(
            json=lambda: {
                "result": {
                    "unit": "count",
                    "timeseries": [
                        {
                            "legend": "proc-a",
                            "labels": {"groupname": "proc-a"},
                            "chart": {"chartData": {"1700000000000000": 2.0}},
                        }
                    ],
                }
            }
        )

    monkeypatch.setattr(base_module, "query_metric", fake_query_metric)
    monkeypatch.setattr(base_module.requests, "post", fake_post)
    result = next(
        tool._invoke(
            user_id="user-1",
            tool_parameters={
                "nodeName": "node-1",
                "pid": "12345",
                "startTime": START_TIME,
                "endTime": END_TIME,
            },
        )
    )

    payload = json.loads(result.message.text)
    assert payload["type"] == "metric"
    assert payload["display"] is True

    if use_backend_api:
        assert query_metric_calls == []
        assert len(post_calls) == 1
        assert post_calls[0] == {
            "url": "http://apo-backend/api/metric/query",
            "json": {
                "metricName": metric_name,
                "params": {"instance_name": "node-1", "pid": "12345"},
                "startTime": START_TIME,
                "endTime": END_TIME,
                "step": STEP,
            },
        }
        assert payload["unit"] == "count"
    else:
        assert post_calls == []
        assert query_metric_calls == [
            {
                "metric_name": metric_name,
                "start_time": START_TIME,
                "end_time": END_TIME,
                "step": STEP,
                "labels": {"instance_name": "node-1", "pid": "12345"},
            }
        ]
        assert payload == asdict(
            QueryMetricResult(
                unit="core",
                data={
                    "timeseries": [
                        {
                            "legend": "proc-a",
                            "labels": {"groupname": "proc-a"},
                            "chart": {"chartData": {"1700000000000000": 1.0}},
                        }
                    ]
                },
            )
        )
