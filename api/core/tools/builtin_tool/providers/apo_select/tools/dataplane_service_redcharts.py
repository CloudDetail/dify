import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import dataplane_scope, query_red_metrics, to_int
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class ServiceEndpointsTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        service = tool_parameters.get("service")
        cluster = tool_parameters.get("cluster")
        endpoint = tool_parameters.get("endpoint")
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")

        try:
            formatted_data = query_service_redcharts(
                service=service or "",
                cluster=cluster or "",
                endpoint=endpoint or "",
                start_time=start_time,
                end_time=end_time,
                tenant_id=tool_parameters.get("tenantId"),
            )
            yield self.create_text_message(formatted_data)
        except requests.RequestException as e:
            yield self.create_text_message(json.dumps({"error": f"Error: Failed to fetch data from API. {str(e)}"}))
        except json.JSONDecodeError:
            yield self.create_text_message(json.dumps({"error": "Error: Invalid JSON response from API."}))
        except Exception as e:
            yield self.create_text_message(json.dumps({"error": f"Error: An unexpected error occurred. {str(e)}"}))


def query_service_redcharts(
    service: str,
    cluster: str,
    endpoint: str,
    start_time: Any,
    end_time: Any,
    tenant_id: Optional[str] = None,
) -> str:
    start_ts = to_int(start_time)
    end_ts = to_int(end_time)

    if dify_config.DATA_SOURCE == "dataplane":
        if endpoint and endpoint not in ("*", ".*"):
            # 专用 RED 接口只有服务汇总，精确端点继续走指标映射。
            result = []
            for name in ("cpm", "errorRate", "avgDurationMs"):
                metric = query_red_metrics(name, service, cluster, start_ts, end_ts, endpoint, tenant_id)
                result.append({"title": name, "unit": metric.unit, **metric.data})
        else:
            response = requests.post(
                f"{dify_config.DATAPLANE_URL}/datasource/queryServiceRedCharts",
                json={
                    **dataplane_scope(tenant_id),
                    "serviceName": service,
                    "startTime": start_ts,
                    "endTime": end_ts,
                    "step": 60_000_000,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("success") is not True:
                raise ValueError(payload.get("error", "RED query failed"))
            result = []
            for name, unit in (("cpm", "requests/min"), ("errorRate", "percentunit"), ("avgDurationMs", "ms")):
                series = []
                for service_name, chart in (payload.get("data") or {}).items():
                    if name not in chart:
                        raise ValueError("Expected COS RED fields cpm/errorRate/avgDurationMs")
                    series.append(
                        {
                            "legend": service_name,
                            "legendFormat": "{{serviceName}}",
                            "labels": {"serviceName": service_name},
                            "chart": {"chartData": chart[name] or {}},
                            "step": chart["step"],
                        }
                    )
                result.append({"title": name, "unit": unit, "timeseries": series})
        return json.dumps({"type": "metric", "display": True, "data": result})

    request_params = {
        "service": service,
        "cluster": cluster,
        "startTime": start_ts,
        "endTime": end_ts,
        "endpoint": endpoint,
    }

    url = f"{dify_config.APO_BACKEND_URL}/api/dataplane/redcharts"

    response = requests.get(
        url,
        params=request_params,
        timeout=10,
    )
    response.raise_for_status()

    result = response.json().get("results", [])
    formatted_data = json.dumps(
        {
            "type": "metric",
            "display": True,
            "data": result,
        },
        indent=2,
    )
    return formatted_data
