"""资源缺失点与异常样本工具到 Pod 提取的实际合同回归。"""

import importlib.util
import json
import sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import pytest
import yaml

API = Path(__file__).parents[3]
STAT_NODES = [
    '1747206482765', '1752827682722', '1753789618196',
    '1753940660066', '1753940674805', '1753940924986', '1753940931914',
]


@lru_cache
def nodes():
    graph = yaml.safe_load((API / 'init_data/workflows/zh/资源告警分析.yml').read_text())['workflow']['graph']
    return {n['id']: n['data'] for n in graph['nodes']}


def execute(id, payload):
    env = {}
    exec(compile(nodes()[id]['code'], id, 'exec'), env)
    return env['main'](json.dumps(payload))


def payload(chart):
    return {'unit': '%', 'data': {'timeseries': [{
        'labels': {'pod': 'orders-0', 'namespace': 'ns-a', 'node': 'worker-1'},
        'chart': {'chartData': chart},
    }]}}


def without_missing(value):
    if isinstance(value, dict):
        return {k: without_missing(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_missing(v) for v in value]
    return value


@pytest.mark.parametrize('id', STAT_NODES)
def test_null_points_do_not_change_statistics_or_erase_raw_curve(id):
    chart = {'1': 0, '2': 10, '3': 10, '4': 10, '5': 100, '6': None}
    mixed = payload(chart)
    original = deepcopy(mixed)
    result = {k: json.loads(v) for k, v in execute(id, mixed).items()}
    clean = {k: json.loads(v) for k, v in execute(id, payload(without_missing(chart))).items()}
    assert without_missing(result) == clean
    assert mixed == original
    if id in ['1752827682722', '1753789618196']:
        assert result['result']['top_usage'][0]['chart'] == chart
        assert result['result']['top_usage'][0]['avg'] == 32.5
        assert result['result']['abnormal'][0]['abnormalCount'] == 1
    elif id in ['1753940660066', '1753940674805']:
        assert result['result'][0]['chart'] == chart
        assert result['result'][0]['abnormalCount'] == 1
    else:
        assert result['top_three'][0]['avg'] == 32.5


@pytest.mark.parametrize('id', STAT_NODES)
@pytest.mark.parametrize('chart', [{}, {'1': None}, {'1': None, '2': 0}])
def test_empty_or_missing_only_curves_keep_existing_empty_behavior(id, chart):
    result = json.loads(next(iter(execute(id, payload(chart)).values())))
    assert result == ({'top_usage': [], 'abnormal': []} if id in ['1752827682722', '1753789618196'] else [])


@pytest.fixture
def abnormal_tool(monkeypatch):
    stub = ModuleType('core.tools.builtin_tool.tool')

    class BuiltinTool:
        def create_text_message(self, text):
            return ('text', text)

        def create_json_message(self, data):
            return ('json', data)

    stub.BuiltinTool = BuiltinTool
    monkeypatch.setitem(sys.modules, stub.__name__, stub)
    entities = ModuleType('core.tools.entities.tool_entities')
    entities.ToolInvokeMessage = object
    monkeypatch.setitem(sys.modules, entities.__name__, entities)
    path = API / 'core/tools/builtin_tool/providers/apo_analysis/tools/abnormal_chart.py'
    spec = importlib.util.spec_from_file_location('resource_abnormal_chart_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AbnormalChartTool()


def test_abnormal_tool_to_other_pod_usage_to_instances(abnormal_tool):
    chart = {'1': 0, '2': 10, '3': 10, '4': 10, '5': 100, '6': None}
    data = payload(chart)
    second = deepcopy(data['data']['timeseries'][0])
    second['labels']['namespace'] = 'ns-b'
    data['data']['timeseries'].append(second)
    # 全缺失曲线不制造异常样本。
    data['data']['timeseries'].append(payload({'1': None})['data']['timeseries'][0])
    messages = dict(abnormal_tool._invoke('test', {'result': json.dumps(data)}))
    samples = json.loads(messages['text'])
    assert messages['json']['data'] == samples
    assert len(samples) == 2
    assert all(s['chart'] == chart and s['abnormalCount'] == 1 for s in samples)
    usage = json.loads(execute('1752818508497', samples)['result'])
    assert len(usage) == 2
    assert all(s['chartData'] == chart and s['unit'] == '%' and s['avg'] == 32.5 for s in usage)
    instances = execute('1752804688058', usage)['result']
    assert {s['namespace'] for s in instances} == {'ns-a', 'ns-b'}
    assert all(s['pod'] == 'orders-0' and s['containerId'] == '' and s['pid'] == '' for s in instances)


@pytest.mark.parametrize('nested', [False, True])
def test_other_pod_usage_preserves_units_and_ranks_top_three(nested):
    entries = []
    for value, unit in [(20, '%'), (50, 'percentunit'), (10, '%'), (30, '%')]:
        chart = {'1': value, '2': 0, '3': None}
        entries.append({'labels': {'pod': str(value)}, 'unit': unit,
                        'chart': {'chartData': chart} if nested else chart})
    entries.append({'labels': {'pod': 'missing'}, 'chart': {'1': None}})
    result = json.loads(execute('1752818508497', entries)['result'])
    assert [s['avg'] for s in result] == [50, 30, 20]
    assert [s['unit'] for s in result] == ['percentunit', '%', '%']
    assert all(s['chartData']['2'] == 0 and s['chartData']['3'] is None for s in result)


@pytest.mark.parametrize('chart', [{}, {'1': None}, {'1': 0, '2': None}])
def test_abnormal_tool_empty_data(abnormal_tool, chart):
    messages = dict(abnormal_tool._invoke('test', {'result': json.dumps(payload(chart))}))
    assert json.loads(messages['text']) == []
