import json
from core.tools.builtin_tool.providers.data_source import query_legacy_metric, metric_error
from core.tools.builtin_tool.tool import BuiltinTool
from libs.apo_utils import APOUtils


class PolarisTimeByPidTool(BuiltinTool):
    def _invoke(self, user_id, tool_parameters, conversation_id=None, app_id=None, message_id=None):
        response = {"type": "metric", "display": True, "unit": "us", "data": {"timeseries": []}}
        try:
            kind = {"cpu": "OnCPU", "net": "Net", "runq": "Runqueue", "idle": "Idle",
                    "other": "Other", "epoll": "Epoll", "file": "File"}[tool_parameters.get("type")]
            pid = str(tool_parameters.get("pid") or "").strip()
            node = str(tool_parameters.get("node") or "").strip()
            if not pid or not node:
                raise ValueError("进程耗时查询需要明确的 node 和 pid")
            start, end = tool_parameters.get("startTime"), tool_parameters.get("endTime")
            metric = query_legacy_metric({
                "metricName": "Thread Polaris Metrics - 北极星指标（线程） - 各类型耗时折线图 - " + kind,
                "params": {"node_name": node, "pid": pid},
                "startTime": start, "endTime": end, "step": APOUtils.get_step(start, end),
            }, tenant_id=tool_parameters.get("tenantId"))
            response.update(metric_error(metric))
            groups = {}
            for ts in metric["timeseries"]:
                labels = ts.get("labels", {})
                if str(labels.get("pid")) not in pid.split("|") or labels.get("node_name") not in node.split("|"):
                    continue
                labels = {k: v for k, v in labels.items() if k != "tid_key"}
                key = json.dumps(labels, sort_keys=True)
                target = groups.setdefault(key, {**ts, "labels": labels, "chart": {"chartData": {}}})
                for stamp, value in ts.get("chart", {}).get("chartData", {}).items():
                    if value is not None:
                        points = target["chart"]["chartData"]
                        points[stamp] = points.get(stamp, 0) + value / (1000 if metric.get("unit") == "ns" else 1)
            response["data"]["timeseries"] = list(groups.values())
        except Exception as e:
            response["error"] = str(e)
        yield self.create_text_message(json.dumps(response))
