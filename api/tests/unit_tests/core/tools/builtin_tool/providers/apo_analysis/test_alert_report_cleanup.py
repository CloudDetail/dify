import sys
from importlib import util
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _install_tool_stubs(monkeypatch):
    stub_configs = ModuleType("configs")
    stub_configs.dify_config = SimpleNamespace(APO_BACKEND_URL="http://apo-backend")

    stub_tool_module = ModuleType("core.tools.builtin_tool.tool")

    class StubBuiltinTool:
        def create_text_message(self, text):
            return SimpleNamespace(message=SimpleNamespace(text=text))

    stub_tool_module.BuiltinTool = StubBuiltinTool

    stub_entities_module = ModuleType("core.tools.entities.tool_entities")
    stub_entities_module.ToolInvokeMessage = object

    stub_requests_module = ModuleType("requests")

    monkeypatch.setitem(sys.modules, "configs", stub_configs)
    monkeypatch.setitem(sys.modules, "core.tools.builtin_tool.tool", stub_tool_module)
    monkeypatch.setitem(sys.modules, "core.tools.entities.tool_entities", stub_entities_module)
    monkeypatch.setitem(sys.modules, "requests", stub_requests_module)


def _load_apo_analysis_tool_module(module_name: str):
    module_path = (
        Path(__file__).parents[7]
        / "core"
        / "tools"
        / "builtin_tool"
        / "providers"
        / "apo_analysis"
        / "tools"
        / f"{module_name}.py"
    )
    spec = util.spec_from_file_location(f"{module_name}_under_test", module_path)
    module = util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_convert_to_json_removes_details_thinking_and_extracts_first_json(monkeypatch):
    _install_tool_stubs(monkeypatch)
    tool_module = _load_apo_analysis_tool_module("alert_report_gen")
    errormsgs = []

    payload = tool_module.convert_to_json(
        """
        <details open>
        <summary>Thinking...</summary>
        internal reasoning
        </details>
        reportView:
        {"reportView": {"title": "延迟升高", "evidenceHighlights": [{"evidenceIndex": "1"}]}}
        trailing text
        """,
        "reportView",
        errormsgs,
    )

    assert errormsgs == []
    assert payload == {
        "reportView": {
            "title": "延迟升高",
            "evidenceHighlights": [{"evidenceIndex": "1"}],
        }
    }


def test_get_alert_report_url_removes_thinking_blocks_from_report_text(monkeypatch):
    _install_tool_stubs(monkeypatch)
    tool_module = _load_apo_analysis_tool_module("alert_report_url")
    tool = tool_module.GetAlertReportURL.__new__(tool_module.GetAlertReportURL)

    result = next(
        tool._invoke(
            user_id="user-1",
            tool_parameters={
                "alertEventId": "alert-1",
                "reportText": (
                    "<think>hidden</think>\n"
                    "<details class='think'><summary>Thinking...</summary>hidden</details>\n"
                    "分析报告正文\n"
                    "<think>unfinished hidden"
                ),
                "frontPrefix": "http://frontend",
                "startTime": "100",
                "endTime": "200",
            },
        )
    )

    assert (
        result.message.text
        == "分析报告正文\nhttp://frontend/#/report?alertEventId=alert-1&startTime=100&endTime=1000200"
    )


def test_report_retry_reuses_only_explicit_duplicate(monkeypatch):
    _install_tool_stubs(monkeypatch)
    module = _load_apo_analysis_tool_module("alert_report_gen")
    duplicate = SimpleNamespace(status_code=400, json=lambda: {"code": "B1504", "message": "alert event report already exists"})
    assert module.is_existing_alert_report(duplicate, {"alertEventId": "event-1"})
    assert not module.is_existing_alert_report(duplicate, {})
    for code, message, status in [("B1504", "database unavailable", 400), ("B0001", "alert event report already exists", 400), ("B1504", "alert event report already exists", 500)]:
        response = SimpleNamespace(status_code=status, json=lambda: {"code": code, "message": message})
        assert not module.is_existing_alert_report(response, {"alertEventId": "event-1"})
    assert not module.is_existing_alert_report(SimpleNamespace(status_code=400, json=lambda: []), {"alertEventId": "event-1"})


def test_duplicate_report_yields_existing_status_without_second_write(monkeypatch):
    import json
    _install_tool_stubs(monkeypatch)
    module = _load_apo_analysis_tool_module("alert_report_gen")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=400, json=lambda: {"code": "B1504", "message": "alert event report already exists"})
    module.requests.post = post
    tool = module.AlertReportGen.__new__(module.AlertReportGen)
    params = dict.fromkeys(['overview', 'topology', 'rootCauseAnalysis', 'suggest', 'evidence'], '{}')
    params['tags'] = '{"alertEventId":"event-1"}'
    result = list(tool._invoke('user-1', params))
    output = json.loads(result[0].message.text)
    assert output['status'] == 'existing'
    assert '未覆盖' in output['msg'][0]
    assert len(calls) == 1


def test_unrelated_report_error_still_fails(monkeypatch):
    import pytest
    _install_tool_stubs(monkeypatch)
    module = _load_apo_analysis_tool_module("alert_report_gen")

    def fail():
        raise RuntimeError('database unavailable')
    module.requests.post = lambda *a, **kw: SimpleNamespace(status_code=400, json=lambda: {"code": "B1504", "message": "database unavailable"}, raise_for_status=fail)
    tool = module.AlertReportGen.__new__(module.AlertReportGen)
    params = dict.fromkeys(['overview', 'topology', 'rootCauseAnalysis', 'suggest', 'evidence'], '{}')
    params['tags'] = '{"alertEventId":"event-1"}'
    with pytest.raises(RuntimeError, match='database unavailable'):
        list(tool._invoke('user-1', params))


def test_successful_report_still_returns_created(monkeypatch):
    import json
    _install_tool_stubs(monkeypatch)
    module = _load_apo_analysis_tool_module("alert_report_gen")
    module.requests.post = lambda *a, **kw: SimpleNamespace(status_code=200, raise_for_status=lambda: None)
    tool = module.AlertReportGen.__new__(module.AlertReportGen)
    params = dict.fromkeys(['overview', 'topology', 'rootCauseAnalysis', 'suggest', 'evidence'], '{}')
    params['tags'] = '{"alertEventId":"event-1"}'
    output = json.loads(next(tool._invoke('user-1', params)).message.text)
    assert output['status'] == 'created'
    assert output['msg'] == []


def test_non_json_failure_is_not_duplicate(monkeypatch):
    _install_tool_stubs(monkeypatch)
    module = _load_apo_analysis_tool_module("alert_report_gen")

    def invalid_json():
        raise ValueError('not JSON')
    assert not module.is_existing_alert_report(SimpleNamespace(status_code=400, json=invalid_json), {'alertEventId': 'event-1'})
