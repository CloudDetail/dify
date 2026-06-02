import json
import math
import sys
from importlib import util
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _install_series_detect_stubs(monkeypatch):
    stub_core_module = ModuleType("core")
    stub_core_tools_module = ModuleType("core.tools")
    stub_builtin_tool_package = ModuleType("core.tools.builtin_tool")
    stub_tool_module = ModuleType("core.tools.builtin_tool.tool")

    class StubBuiltinTool:
        def create_text_message(self, text):
            return SimpleNamespace(message=SimpleNamespace(text=text))

    stub_tool_module.BuiltinTool = StubBuiltinTool

    stub_entities_module = ModuleType("core.tools.entities.tool_entities")
    stub_entities_module.ToolInvokeMessage = object

    stub_configs_apo = ModuleType("configs.apo")

    class StubAPOConfig:
        APO_DETECT_SERIES_FREQUENCY_WINDOW_SIZE = 10
        APO_DETECT_SERIES_FREQUENCY_AGG_WINDOW_SIZE = 5
        APO_DETECT_SERIES_FREQUENCY_THRESHOLD = 3.0

    stub_configs_apo.APOConfig = StubAPOConfig

    stub_scipy = ModuleType("scipy")
    stub_stats = ModuleType("scipy.stats")

    class StubNorm:
        @staticmethod
        def cdf(value):
            return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))

    stub_stats.norm = StubNorm
    stub_scipy.stats = stub_stats

    monkeypatch.setitem(sys.modules, "core", stub_core_module)
    monkeypatch.setitem(sys.modules, "core.tools", stub_core_tools_module)
    monkeypatch.setitem(sys.modules, "core.tools.builtin_tool", stub_builtin_tool_package)
    monkeypatch.setitem(sys.modules, "core.tools.builtin_tool.tool", stub_tool_module)
    monkeypatch.setitem(sys.modules, "core.tools.entities.tool_entities", stub_entities_module)
    monkeypatch.setitem(sys.modules, "configs", ModuleType("configs"))
    monkeypatch.setitem(sys.modules, "configs.apo", stub_configs_apo)
    monkeypatch.setitem(sys.modules, "scipy", stub_scipy)
    monkeypatch.setitem(sys.modules, "scipy.stats", stub_stats)
    monkeypatch.delitem(sys.modules, "libs.apo_detect", raising=False)


def _load_series_detect_module():
    module_path = (
        Path(__file__).parents[7]
        / "core"
        / "tools"
        / "builtin_tool"
        / "providers"
        / "apo_analysis"
        / "tools"
        / "series_detect.py"
    )
    spec = util.spec_from_file_location("series_detect_under_test", module_path)
    module = util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_trend_detect_uses_history_to_detect_baseline_shift(monkeypatch):
    _install_series_detect_stubs(monkeypatch)
    module = _load_series_detect_module()
    tool = module.TimeSeriersAnalysisTool.__new__(module.TimeSeriersAnalysisTool)

    data = {
        "data": {
            "timeseries": [
                {
                    "legend": "ygqh-testjpa-demo-client",
                    "legendFormat": "",
                    "labels": {
                        "endpoint": "SpringController/api/jpa-demo/queryRemoteDbs/{sleepMs}",
                        "service": "ygqh-testjpa-demo-client",
                    },
                    "chart": {
                        "chartData": {
                            "1780370880000000": 2694175,
                            "1780370940000000": 3129763,
                            "1780371000000000": 2498224,
                            "1780371060000000": 2812215,
                            "1780371120000000": 2530632,
                            "1780371180000000": 2710876,
                            "1780371240000000": 2550947,
                            "1780371300000000": 2534900,
                            "1780371360000000": 2452728,
                            "1780371420000000": 2559777,
                            "1780371480000000": 2476422,
                            "1780371540000000": 2708300,
                            "1780371600000000": 2510345,
                            "1780371660000000": 2623844,
                            "1780371720000000": 2646960,
                            "1780371780000000": 2638968,
                        },
                        "value": 2619990.895295903,
                    },
                }
            ]
        },
        "unit": "us",
    }
    history = {
        "data": {
            "timeseries": [
                {
                    "legend": "ygqh-testjpa-demo-client",
                    "legendFormat": "",
                    "labels": {
                        "endpoint": "SpringController/api/jpa-demo/queryRemoteDbs/{sleepMs}",
                        "service": "ygqh-testjpa-demo-client",
                    },
                    "chart": {
                        "chartData": {
                            "1780282800000000": 505531,
                            "1780284600000000": 1402145,
                            "1780286400000000": 1492009,
                            "1780288200000000": 942514,
                            "1780290000000000": 950124,
                            "1780291800000000": 1919686,
                            "1780293600000000": 2052151,
                            "1780295400000000": 2054744,
                            "1780297200000000": 658163,
                            "1780299000000000": 1120019,
                            "1780300800000000": 1134205,
                            "1780302600000000": 977667,
                            "1780304400000000": 456948,
                            "1780306200000000": 496568,
                            "1780308000000000": 1104749,
                            "1780309800000000": 1122594,
                            "1780311600000000": 1182643,
                            "1780313400000000": 1119918,
                            "1780315200000000": 1134303,
                            "1780317000000000": 910678,
                            "1780318800000000": 1122828,
                            "1780320600000000": 1132326,
                            "1780322400000000": 861394,
                            "1780324200000000": 1194241,
                            "1780326000000000": 967659,
                            "1780327800000000": 1131447,
                            "1780329600000000": 1177538,
                            "1780331400000000": 1112345,
                            "1780333200000000": 1045268,
                            "1780335000000000": 1162013,
                            "1780336800000000": 1157116,
                            "1780338600000000": 864124,
                            "1780340400000000": 1173345,
                            "1780342200000000": 1141230,
                            "1780344000000000": 1098669,
                            "1780345800000000": 1168613,
                            "1780347600000000": 1190035,
                            "1780349400000000": 1162346,
                            "1780351200000000": 1167478,
                            "1780353000000000": 1134131,
                            "1780354800000000": 1163114,
                            "1780356600000000": 1040954,
                            "1780358400000000": 1110566,
                            "1780360200000000": 1053083,
                            "1780362000000000": 1110332,
                            "1780363800000000": 976556,
                            "1780365600000000": 777829,
                            "1780367400000000": 587508,
                            "1780369200000000": 1440303,
                        },
                        "value": 1050595.3979383786,
                    },
                }
            ]
        },
        "unit": "us",
    }

    result_message = next(
        tool._invoke(
            user_id="user-1",
            tool_parameters={
                "algorithmName": "trend_detect",
                "data": json.dumps(data),
                "history": json.dumps(history),
            },
        )
    )

    payload = json.loads(result_message.message.text)

    assert len(payload) == 1
    assert set(payload[0]) == {"chart", "labels", "avg", "unit", "result"}
    assert payload[0]["unit"] == "us"
    assert payload[0]["result"]["is_anomaly"] is True
    assert payload[0]["result"]["reason"].startswith("检测到相对历史基线抬升异常")
