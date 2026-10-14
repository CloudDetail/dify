"""内置资源规则的指标口径；对象来自告警，不以环境变量或模型推断。"""
import json
import re
from dataclasses import asdict

from core.tools.builtin_tool.providers.data_source import query_metric
from core.tools.builtin_tool.tool import BuiltinTool
from libs.apo_utils import APOUtils


class ResourceAlertMetricTool(BuiltinTool):
    def _invoke(self, user_id, tool_parameters, **kwargs):
        p = tool_parameters
        kind = p["kind"]
        pod = p.get("pod") or ""
        names = {
            "cpu": "Pod CPU使用率" if pod else "主机CPU使用率",
            "memory": "Pod 内存使用率" if pod else "主机内存使用率",
            "iowait": "主机CPU IO Wait",
            "network_receive": "Pod 网络接收带宽" if pod else "主机网络接收带宽",
            "network_transmit": "Pod 网络发送带宽" if pod else "主机网络发送带宽",
            "disk": "文件系统使用率",
        }
        labels = {k: str(p[k]) for k in ("node", "pod", "namespace", "mountpoint") if p.get(k)}
        # Query APIs accept regex object matchers; an alert supplies a literal identity.
        for key in ("node", "pod", "namespace"):
            if key in labels:
                labels[key] = re.escape(labels[key])
        result = query_metric(
            metric_name="COS 资源告警 - " + names[kind],
            start_time=p["startTime"], end_time=p["endTime"],
            step=APOUtils.get_step(p["startTime"], p["endTime"]),
            labels=labels, tenant_id=p.get("tenantId"),
        )
        if not result.unit:
            result.unit = "MiB/s" if kind.startswith("network_") else "%"
        yield self.create_text_message(json.dumps(asdict(result), ensure_ascii=False))
