"""七条内置资源规则：真实 GraphEngine + 工具实现，HTTP 数据边界受控。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from test_core_workflow_engine import test_original_graph_to_report as run_graph

from core.tools.builtin_tool.providers.apo_select.tools import dataplane_instance_service_name as lookup
from core.tools.builtin_tool.providers.apo_select.tools import dataplane_service_topology as topology
from core.tools.builtin_tool.providers.apo_select.tools import resource_alert_metric as resource
from core.tools.builtin_tool.providers.data_source import QueryMetricResult

ROOT = Path(__file__).parents[3]
START = 1791873662346000
END = 1791874562346000
CASES = [('CPU高负载', 'cpu', '主机CPU使用率'), ('CPU高IO Wait', 'iowait', '主机CPU IO Wait'), ('异常网络入吞吐量', 'network_receive', '主机网络接收带宽'), ('主机内存使用率持续10分钟超过90%', 'memory', '主机内存使用率'), ('磁盘不足20%', 'disk', '文件系统使用率'), ('容器内存使用率超过80%', 'memory', 'Pod 内存使用率'), ('容器CPU使用率超过80%', 'cpu', 'Pod CPU使用率')]


@pytest.mark.parametrize('alert,kind,metric', CASES)
@pytest.mark.parametrize('has_samples', [False, True])
def test_builtin_resource_alert_chain(monkeypatch, alert, kind, metric, has_samples):
    calls = []

    def query(**kw):
        calls.append(kw)
        labels = {'node': 'work1'}
        if 'Pod ' in kw['metric_name']: labels.update(pod='grid-orchestrator-5f477bdd56-xjtfx', namespace='paas-cos-product')
        samples = [{'labels': labels, 'legend': 'object', 'chart': {'chartData': {str(START): 82, str(END): 95}, 'value': 90}}] if has_samples else []
        return QueryMetricResult(unit='MiB/s' if '带宽' in kw['metric_name'] else '%', data={'timeseries': samples})
    monkeypatch.setattr(resource, 'query_metric', query)
    params = {'tenantId': 'tenant-a', 'alertName': alert, 'nodeName': 'work1', 'instanceName': 'work1', 'mountpoint': '/data', 'alertEventId': 'test', 'status': 'firing'}
    if alert.startswith('容器'): params.update(pod='grid-orchestrator-5f477bdd56-xjtfx', namespace='paas-cos-product')

    def tool(name, p):
        if name == 'resource_alert_metric': return json.loads(next(resource.ResourceAlertMetricTool.__new__(resource.ResourceAlertMetricTool)._invoke('u', p)).message.text)
        if name == 'originx_service_monitor': return {'data': {'timeseries': [{'labels': {'node': 'work1', 'pod': 'grid-orchestrator-5f477bdd56-xjtfx', 'namespace': 'paas-cos-product', 'pid': ''}}] if has_samples else []}}
        if name == 'dataplane_instance_service': return {'type': 'list', 'data': 'orders' if p.get('pod') else ''}
        if name == 'dataplane_service_topology': return {'data': {}}
        if name == 'dataplane_service_redcharts': return {'data': []}
        if name == 'knowledge_retrieval': return {'records': []}
        if name == 'dataplane_traces': return {'data': {'data': []}}
        if name == 'timeSeriesAnalysis': return {}
        return {'data': {'timeseries': []}, 'unit': ''}
    record = {}
    run_graph('资源告警分析', alert, live_inputs={'params': json.dumps(params), 'startTime': START, 'endTime': END}, tool_runner=tool, record=record)
    assert record['saved']
    assert any(c['metric_name'] == 'COS 资源告警 - ' + metric for c in calls)
    for c in calls:
        assert c['tenant_id'] == 'tenant-a' and c['start_time'] == START and c['end_time'] == END
        assert c['labels']['node'] == 'work1'
        if alert.startswith('容器'): assert c['labels']['pod'] and c['labels']['namespace']
        else: assert 'pod' not in c['labels']
        if kind == 'disk': assert c['labels']['mountpoint'] == '/data'
    assert not any('进程在' in c['tool'] or c['tool'] == '进程在某类资源上的时间消耗' for c in record['tool_calls'])


def test_service_lookup_preserves_body_and_passes_tenant_header(monkeypatch):
    monkeypatch.setattr(lookup, 'dify_config', SimpleNamespace(DATA_SOURCE='dataplane', DATAPLANE_URL='http://dataplane'))

    def post(url, json, headers, **kw):
        assert url == 'http://dataplane/dataplane/servicename'
        assert json == {'cluster': '', 'startTime': START, 'endTime': END, 'tags': {'pod': 'pod-a', 'nodeName': 'work1', 'pid': '', 'containerId': ''}}
        assert headers == {'X-Tenant-Id': 'tenant-a'}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'msg': '', 'result': 'orders'})
    monkeypatch.setattr(lookup.requests, 'post', post)
    result = json.loads(lookup.query_service_name('', 'pod-a', '', '', 'work1', START, END, tenant_id='tenant-a'))
    assert result == {'type': 'list', 'display': True, 'data': 'orders'}


def test_unresolved_service_skips_topology_http(monkeypatch):
    monkeypatch.setattr(topology.requests, 'post', lambda *a, **k: pytest.fail('empty service must not query topology'))
    tool = topology.ServiceTopologyTool.__new__(topology.ServiceTopologyTool)
    result = json.loads(next(tool._invoke('u', {'service': '', 'startTime': START, 'endTime': END})).message.text)
    assert result['status'] == 'unresolved_instance' and result['data'] == {}


def test_native_alert_labels_and_graph_references():
    doc = yaml.safe_load((ROOT / 'init_data/workflows/zh/资源告警分析.yml').read_text())
    assert not doc['workflow']['environment_variables']
    nodes = {n['id']: n for n in doc['workflow']['graph']['nodes']}
    ns = {}; exec(nodes['1744959389144']['data']['code'], ns)
    result = ns['main'](json.dumps({'raw_tags': {'k8s_pod_name': 'pod-a', 'k8s_namespace_name': 'ns', 'k8s_node_name': 'work1', 'tenant_id': 'tenant-a', 'mountpoint': '/data'}}), '')
    assert (result['pod'], result['namespace'], result['nodeName'], result['mountpoint']) == ('pod-a', 'ns', 'work1', '/data')
    for e in doc['workflow']['graph']['edges']: assert e['source'] in nodes and e['target'] in nodes
