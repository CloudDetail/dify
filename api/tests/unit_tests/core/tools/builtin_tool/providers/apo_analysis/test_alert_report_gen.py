import importlib.util
import json
import sys
import types
from pathlib import Path


TOOL_PATH = (
    Path(__file__).resolve().parents[7]
    / "core/tools/builtin_tool/providers/apo_analysis/tools/alert_report_gen.py"
)


def _load_tool_module(monkeypatch):
    class BuiltinTool:
        def create_text_message(self, text):
            return types.SimpleNamespace(message=types.SimpleNamespace(text=text))

    builtin_tool_module = types.ModuleType("core.tools.builtin_tool.tool")
    builtin_tool_module.BuiltinTool = BuiltinTool

    tool_entities_module = types.ModuleType("core.tools.entities.tool_entities")
    tool_entities_module.ToolInvokeMessage = object

    configs_module = types.ModuleType("configs")
    configs_module.dify_config = types.SimpleNamespace(APO_BACKEND_URL="http://localhost:8080")

    monkeypatch.setitem(sys.modules, "core.tools.builtin_tool.tool", builtin_tool_module)
    monkeypatch.setitem(sys.modules, "core.tools.entities.tool_entities", tool_entities_module)
    monkeypatch.setitem(sys.modules, "configs", configs_module)

    spec = importlib.util.spec_from_file_location("alert_report_gen_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Response:
    status_code = 200
    text = ""


def test_report_payload_merges_identity_fields_into_tags_overview_and_evidence(monkeypatch):
    module = _load_tool_module(monkeypatch)
    posted = {}

    def fake_post(url, json):
        posted["url"] = url
        posted["json"] = json
        return _Response()

    monkeypatch.setattr(module.requests, "post", fake_post)
    monkeypatch.setattr(module.dify_config, "APO_BACKEND_URL", "http://apo-backend")

    params = {
        "reportType": "error",
        "overview": json.dumps(
            {
                "timestamp": 1710000000000000,
                "detail": "detail",
                "reason": "reason",
                "tags": {"service": "checkout"},
            }
        ),
        "tags": json.dumps({"alertId": "alert-1"}),
        "topology": json.dumps({}),
        "rootCauseAnalysis": json.dumps({"cause": "code", "other": []}),
        "suggest": json.dumps(
            {
                "suggest": [
                    {
                        "action": "rollback checkout",
                        "level": "high",
                        "category": "rollback",
                        "verification": "error rate recovers",
                        "risk": "new deploy may be reverted",
                        "trigger": "error rate > 20%",
                    }
                ]
            }
        ),
        "evidence": json.dumps(
            {
                "evidence": [
                    {
                        "type": "log",
                        "name": "application logs",
                        "description": "error logs",
                        "data": [],
                    }
                ]
            }
        ),
        "alertEventId": "event-1",
        "service": "checkout",
        "endpoint": "/pay",
        "pod": "checkout-0",
        "namespace": "prod",
        "nodeName": "node-a",
        "pid": "123",
        "containerId": "container-1",
        "startTime": 1709999900000000,
        "endTime": 1710000000000000,
    }

    messages = list(module.AlertReportGen()._invoke(user_id="user-1", tool_parameters=params))

    assert posted["url"] == "http://apo-backend/api/alerts/events/report/add"
    assert posted["json"]["tags"] == {
        "alertId": "alert-1",
        "alertEventId": "event-1",
        "service": "checkout",
        "endpoint": "/pay",
        "pod": "checkout-0",
        "namespace": "prod",
        "nodeName": "node-a",
        "pid": "123",
        "containerId": "container-1",
    }
    assert posted["json"]["overview"]["tags"] == {
        "service": "checkout",
        "alertEventId": "event-1",
        "endpoint": "/pay",
        "pod": "checkout-0",
        "namespace": "prod",
        "nodeName": "node-a",
        "pid": "123",
        "containerId": "container-1",
    }
    assert posted["json"]["suggest"][0]["category"] == "rollback"
    assert posted["json"]["evidence"][0]["identifiers"] == {
        "alertEventId": "event-1",
        "service": "checkout",
        "endpoint": "/pay",
        "pod": "checkout-0",
        "namespace": "prod",
        "nodeName": "node-a",
        "pid": "123",
        "containerId": "container-1",
        "timeRange": {
            "startTime": 1709999900000000,
            "endTime": 1710000000000000,
        },
    }
    assert json.loads(messages[0].message.text)["msg"] == []


def test_report_payload_without_identity_fields_keeps_legacy_payload(monkeypatch):
    module = _load_tool_module(monkeypatch)
    posted = {}

    def fake_post(url, json):
        posted["json"] = json
        return _Response()

    monkeypatch.setattr(module.requests, "post", fake_post)

    params = {
        "reportType": "slow",
        "overview": json.dumps({"timestamp": 1, "detail": "d", "reason": "r", "tags": {"service": "legacy"}}),
        "tags": json.dumps({"alertEventId": "legacy-event"}),
        "topology": json.dumps({"current": {"service": "legacy"}}),
        "rootCauseAnalysis": json.dumps({"cause": "system", "other": []}),
        "suggest": json.dumps({"suggest": [{"action": "check cpu", "level": "high"}]}),
        "evidence": json.dumps({"evidence": [{"type": "metrics", "name": "cpu", "data": []}]}),
    }

    list(module.AlertReportGen()._invoke(user_id="user-1", tool_parameters=params))

    assert posted["json"] == {
        "reportType": "slow",
        "overview": {"timestamp": 1, "detail": "d", "reason": "r", "tags": {"service": "legacy"}},
        "tags": {"alertEventId": "legacy-event"},
        "topology": {"current": {"service": "legacy"}},
        "rootCauseAnalysis": {"cause": "system", "other": []},
        "suggest": [{"action": "check cpu", "level": "high"}],
        "evidence": [{"type": "metrics", "name": "cpu", "data": []}],
        "alertDirection": None,
        "analyzeRunId": None,
        "impactScope": None,
        "infraCheckResult": None,
        "networkCheckResult": None,
    }
