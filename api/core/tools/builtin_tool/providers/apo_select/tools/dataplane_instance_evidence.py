"""收集原有效性算法所需数据；判据仍由原 Code 节点执行。"""

import json
from dataclasses import asdict

from core.tools.builtin_tool.providers.data_source import query_metric, to_int
from core.tools.builtin_tool.providers.service_instances import query_instances
from core.tools.builtin_tool.tool import BuiltinTool
from libs.apo_utils import APOUtils


class InstanceEvidenceTool(BuiltinTool):
    def _invoke(self, user_id, tool_parameters, **kwargs):
        p = tool_parameters
        start, end = to_int(p["startTime"]), to_int(p["endTime"])
        context = query_instances(p["service"], p["tenantId"], start, end)
        for item in context["data"]:
            if item["identityStatus"] != "resolved":
                item["ebpf"] = {"status": "unresolved_instance"}
                continue
            labels = {
                "pod": item["podName"],
                "node_name": item["nodeName"],
                "pid": item["pid"],
                "container_id": item["containerId"],
            }
            ebpf = {}
            # 原算法比较当前窗口与开始前一小时；不能改为昨日或等长窗口。
            for period, left, right in [("current", start, end), ("history", start - 3_600_000_000, start)]:
                ebpf[period] = {}
                for kind, metric in [("net", "Net"), ("epoll", "Epoll"), ("cpu", "OnCPU"), ("runq", "Runqueue")]:
                    ebpf[period][kind] = asdict(
                        query_metric(
                            "Thread Polaris Metrics - 北极星指标（线程） - 告警有效性一分钟增量",
                            left,
                            right,
                            APOUtils.get_step(left, right),
                            labels={
                                **{k: v or ".*" for k, v in labels.items()},
                                "namespace": item["namespace"] or ".*",
                                "type": kind,
                            },
                            tenant_id=p["tenantId"],
                        )
                    )
            ebpf["rtt"] = asdict(
                query_metric(
                    "基础设施情况 - 容器网络 - 与下游服务RTT",
                    start,
                    end,
                    APOUtils.get_step(start, end),
                    labels={
                        "pod": item["podName"],
                        "namespace": item["namespace"],
                        "node": item["nodeName"],
                        "pid": item["pid"],
                    },
                    tenant_id=p["tenantId"],
                )
            )
            item["ebpf"] = ebpf
        yield self.create_text_message(json.dumps(context, ensure_ascii=False))
