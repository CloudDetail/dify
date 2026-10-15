"""将 dataplane 的统一服务实例契约转换为既有工作流字段。"""

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import dataplane_scope, to_int


def query_instances(service, tenant_id, start_time, end_time):
    scope = dataplane_scope(tenant_id)
    start, end = to_int(start_time), to_int(end_time)
    if not service or service in ("*", ".*") or start <= 0 or end <= start:
        raise ValueError("实例查询需要明确服务和有效时间范围")
    result = {
        "type": "list",
        "display": True,
        "data": [],
        "status": "no_data",
        "source": "service_instances",
        "complete": False,
        "note": "实例来自服务实例接口；缺失对象字段保留为空，不从实例名猜测 Pod 或 PID。",
    }
    try:
        response = requests.post(
            dify_config.DATAPLANE_URL + "/datasource/queryServiceInstances",
            json={**scope, "serviceName": service, "startTime": start, "endTime": end},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), list):
            raise ValueError(str(payload.get("error") if isinstance(payload, dict) else "实例查询响应无效"))
        items = []
        for record in payload["data"]:
            if not isinstance(record, dict) or record.get("serviceName") != service:
                raise ValueError("实例查询返回了无效记录或其他服务的数据")
            # 原 dataplane 契约为字符串字段；不要把错误对象或 null 转成查询条件。
            fields = ("instanceId", "podName", "namespace", "nodeName", "hostName", "processId", "containerId", "containerPid")
            if any(not isinstance(record.get(key, ""), str) for key in fields):
                raise ValueError("实例查询字段类型无效")
            node = record.get("nodeName", "")
            if not node and not (record.get("podName") or record.get("containerId") or record.get("containerPid")):
                node = record.get("hostName", "")
            item = {
                "service": service,
                "instanceId": record.get("instanceId", ""),
                "podName": record.get("podName", ""),
                "namespace": record.get("namespace", ""),
                "nodeName": node,
                "pid": record.get("processId", ""),  # 不将容器 PID 作为宿主机 PID 查询。
                "containerPid": record.get("containerPid", ""),
                "containerId": record.get("containerId", ""),
            }
            item["identityStatus"] = (
                "resolved" if item["podName"] or item["containerId"] or (node and item["pid"]) else "unresolved"
            )
            items.append(item)
        failed = payload.get("failedDS") or []
        result["data"] = items
        result["complete"] = not bool(failed)
        result["status"] = ("partial" if items else "error") if failed else ("ok" if items else "no_data")
        if failed:
            result["error"] = "部分数据源查询失败: " + str(failed)
    except (requests.RequestException, ValueError, TypeError) as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:500]
    return result
