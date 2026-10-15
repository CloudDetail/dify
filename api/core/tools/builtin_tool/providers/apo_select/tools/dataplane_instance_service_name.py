import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import to_int
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class InstanceServiceTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        pod = tool_parameters.get('pod')
        container_id = tool_parameters.get('containerId')
        pid = tool_parameters.get('pid')
        node = tool_parameters.get('nodeName') or tool_parameters.get('node')
        start_time = tool_parameters.get('startTime')
        end_time = tool_parameters.get('endTime')
        cluster = tool_parameters.get('cluster', '')

        try:
            # 告警已经携带服务身份时沿用该身份，避免用空实例条件反查。
            if service := tool_parameters.get("service"):
                yield self.create_text_message(json.dumps({"type": "list", "display": True, "data": service}))
                return
            def exact(value):
                return str(value or "").strip() not in ("", ".*", "*", "^$", "/")
            if not (exact(pod) or exact(container_id) or (exact(node) and exact(pid))):
                yield self.create_text_message(json.dumps({"type": "list", "display": True, "data": "", "status": "unresolved_instance", "reason": "缺少可唯一定位服务的实例身份；主机可能关联多个服务"}))
                return
            formatted_data = query_service_name(
                cluster=cluster,
                pod=pod or '',
                container_id=container_id or '',
                pid=pid or '',
                node=node or '',
                start_time=start_time,
                end_time=end_time,
                tenant_id=tool_parameters.get("tenantId"),
            )
            yield self.create_text_message(formatted_data)

        except requests.RequestException as e:
            yield self.create_text_message(json.dumps({"type": "list", "display": True, "data": "", "status": "error", "error": f"Error: Failed to fetch data from API. {str(e)}"}))
        except json.JSONDecodeError:
            yield self.create_text_message(json.dumps({"type": "list", "display": True, "data": "", "status": "error", "error": "Error: Invalid JSON response from API."}))
        except Exception as e:
            yield self.create_text_message(json.dumps({"type": "list", "display": True, "data": "", "status": "error", "error": f"Error: An unexpected error occurred. {str(e)}"}))


def query_service_name(
    cluster: str,
    pod: str,
    container_id: str,
    pid: str,
    node: str,
    start_time: Any,
    end_time: Any,
    tenant_id: Optional[str] = None,
) -> str:
    start_ts = to_int(start_time)
    end_ts = to_int(end_time)

    request_body = {
        "cluster": cluster,
        "endTime": end_ts,
        "startTime": start_ts,
        "tags": {
            "containerId": container_id,
            "nodeName": node,
            "pid": pid,
            "pod": pod
        }
    }

    url = ""
    if dify_config.DATA_SOURCE == 'apo':
        url = f"{dify_config.APO_BACKEND_URL}/api/dataplane/servicename"
    else:
        url = f"{dify_config.DATAPLANE_URL}/dataplane/servicename"

    response = requests.post(
        url,
        json=request_body,
        headers={"X-Tenant-Id": str(tenant_id)} if tenant_id else {},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result", "")
    if not result and payload.get("msg") not in (None, "", "Data Not Found"):
        raise ValueError(payload["msg"])

    formatted_data = json.dumps(
        {
            "type": "list",
            "display": True,
            "data": result,
        },
        indent=2,
    )
    return formatted_data
