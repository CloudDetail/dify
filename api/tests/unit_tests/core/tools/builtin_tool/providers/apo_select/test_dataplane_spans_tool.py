import json
import sys
from importlib import import_module
from types import ModuleType
from types import SimpleNamespace


def test_dataplane_spans_returns_inner_data_of_first_non_empty_provider(monkeypatch):
    stub_configs = ModuleType("configs")
    stub_configs.dify_config = SimpleNamespace(DATAPLANE_URL="http://dataplane")

    stub_tool_module = ModuleType("core.tools.builtin_tool.tool")

    class StubBuiltinTool:
        def create_text_message(self, text):
            return SimpleNamespace(message=SimpleNamespace(text=text))

    stub_tool_module.BuiltinTool = StubBuiltinTool

    stub_entities_module = ModuleType("core.tools.entities.tool_entities")
    stub_entities_module.ToolInvokeMessage = object

    stub_utils_module = ModuleType("libs.apo_utils")
    stub_utils_module.APOUtils = object

    monkeypatch.setitem(sys.modules, "configs", stub_configs)
    monkeypatch.setitem(sys.modules, "core.tools.builtin_tool.tool", stub_tool_module)
    monkeypatch.setitem(sys.modules, "core.tools.entities.tool_entities", stub_entities_module)
    monkeypatch.setitem(sys.modules, "libs.apo_utils", stub_utils_module)
    monkeypatch.delitem(
        sys.modules,
        "core.tools.builtin_tool.providers.apo_select.tools.dataplane_spans",
        raising=False,
    )

    tool_module = import_module("core.tools.builtin_tool.providers.apo_select.tools.dataplane_spans")
    tool_cls = getattr(tool_module, "DataplaneSpansTool")
    tool = tool_cls.__new__(tool_cls)

    expected_data = [
        {
            "traceId": "trace-1",
            "spans": [{"spanId": "span-1"}],
        }
    ]
    response_data = [
        {"providerId": 1, "dataSource": "apo", "data": [], "hasData": False},
        {"providerId": 2, "dataSource": "nbs3", "data": expected_data, "hasData": True},
    ]

    def fake_post(url, json):
        return SimpleNamespace(json=lambda: {"data": response_data})

    monkeypatch.setattr(tool_module.requests, "post", fake_post)

    result = next(
        tool._invoke(
            user_id="user-1",
            tool_parameters={
                "providerId": "provider-1",
                "startTime": 1,
                "endTime": 2,
                "limit": 10,
            },
        )
    )

    payload = json.loads(result.message.text)
    assert payload["type"] == "span"
    assert payload["data"] == expected_data
