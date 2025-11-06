import json
from collections.abc import Generator
from typing import Any, Dict, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import to_int
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class ServiceEndpointsTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: Dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        service = tool_parameters.get('service')
        cluster = tool_parameters.get("cluster")
        endpoint = tool_parameters.get('endpoint')
        start_time = tool_parameters.get('startTime')
        end_time = tool_parameters.get('endTime')

        try:
            formatted_data = query_service_redcharts(
                service=service or '',
                cluster=cluster or '',
                endpoint=endpoint or '',
                start_time=start_time,
                end_time=end_time,
            )
            yield self.create_text_message(formatted_data)
        except requests.RequestException as e:
            yield self.create_text_message(json.dumps({"error" : f"Error: Failed to fetch data from API. {str(e)}"}))
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
) -> str:
    start_ts = to_int(start_time)
    end_ts = to_int(end_time)

    request_params = {
        "service": service,
        "cluster": cluster,
        "startTime": start_ts,
        "endTime": end_ts,
        "endpoint": endpoint
    }

    url = ""
    if dify_config.DATA_SOURCE == 'apo':
        url = f"{dify_config.APO_BACKEND_URL}/api/dataplane/redcharts"
    else:
        url = f"{dify_config.DATAPLANE_URL}/dataplane/redcharts"

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


