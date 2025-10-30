import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class PolarisTimeByPidTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        resource_type = tool_parameters.get('type', '')

        pid = tool_parameters.get('pid', '')
        node = tool_parameters.get('node', '')
        pids = pid.split('|')
        nodes = node.split('|')

        if resource_type == 'cpu':
            metric_name = 'Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - OnCPU'
        elif resource_type == 'net':
            metric_name = 'Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - Net'
        elif resource_type == 'runq':
            metric_name = 'Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - Runqueue'
        elif resource_type == 'idle':
            metric_name = 'Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - Idle'
        elif resource_type == 'other':
            metric_name = 'Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - Other'
        elif resource_type == 'epoll':
            metric_name = 'Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - Epoll'
        elif resource_type == 'file':
            metric_name = 'Thread Polaris Metrics - 北极星指标（进程） - 各类型耗时折线图 - File'
        params = {
            'metricName': metric_name,
            'params': {},
            'startTime': start_time,
            'endTime': end_time,
            'step': APOUtils.get_step(start_time, end_time),
        }
        resp = requests.post(dify_config.APO_BACKEND_URL +
                             '/api/metric/query', json=params)
        timeseries = resp.json()['result']['timeseries']
        result = []
        for ts in timeseries:
            labels = ts['labels']
            if labels['pid'] in pids and (not nodes or labels['node'] in nodes):
                result.append(ts)

        resp_json = json.dumps({
            'type': 'metric',
            'display': True,
            'unit': 'us',
            'data': {
                'timeseries': result
            }
        })
        yield self.create_text_message(resp_json)
