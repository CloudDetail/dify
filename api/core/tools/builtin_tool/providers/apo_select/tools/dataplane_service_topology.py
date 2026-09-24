import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import dataplane_scope, to_int
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class ServiceTopologyTool(BuiltinTool):
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
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")

        query_params = {
            "service": service,
            "cluster": cluster,
            "startTime": start_time,
            "endTime": end_time,
        }

        try:
            if dify_config.DATA_SOURCE == "dataplane":
                response = requests.post(
                    f"{dify_config.DATAPLANE_URL}/datasource/queryTopology",
                    json={
                        **dataplane_scope(tool_parameters.get("tenantId")),
                        "startTime": to_int(start_time),
                        "endTime": to_int(end_time),
                    },
                    timeout=10,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("success") is not True:
                    raise ValueError(payload.get("error", "Topology query failed"))
                result = format_service_topology(payload.get("data") or [], service, cluster)
                yield self.create_text_message(json.dumps({"type": "topology", "display": True, "data": result}))
                return
            url = f"{dify_config.APO_BACKEND_URL}/api/dataplane/topology"

            response = requests.get(
                url,
                params=query_params,
                timeout=10,
            )
            response.raise_for_status()

            result = response.json().get("results", [])

            current_node = next((node for node in result if node["name"] == service), None)
            if not current_node:
                yield self.create_text_message(f"Error: Service {service} not found in topology.")
                return

            def format_node(node):
                return {
                    "endpoint": node["id"],
                    "group": node["category"],
                    "isTraced": True,
                    "service": node["name"],
                    "system": node["category"],
                }

            formatted_current = format_node(current_node)

            formatted_children = [format_node(node) for node in result if node["name"] in current_node["children"]]

            formatted_parents = [format_node(node) for node in result if node["name"] in current_node["parents"]]

            formatted_data = json.dumps(
                {
                    "type": "topology",
                    "display": True,
                    "data": {
                        "children": formatted_children,
                        "current": formatted_current,
                        "parents": formatted_parents,
                        "rawResp": result,
                    },
                },
                indent=2,
            )

            yield self.create_text_message(formatted_data)

        except requests.RequestException as e:
            yield self.create_text_message(json.dumps({"error": f"Error: Failed to fetch data from API. {str(e)}"}))
        except json.JSONDecodeError:
            yield self.create_text_message(json.dumps({"error": "Error: Invalid JSON response from API."}))
        except Exception as e:
            yield self.create_text_message(json.dumps({"error": f"Error: An unexpected error occurred. {str(e)}"}))


def format_service_topology(relations, service, cluster=None):
    parents, children = {}, {}
    current = None

    def node(name, kind, edge):
        return {
            "service": name,
            "group": kind,
            "system": kind,
            "clusterId": edge.get("clusterId", ""),
            "dataSource": edge.get("dataSource", ""),
        }

    for edge in relations:
        if cluster and edge.get("clusterId") != cluster:
            continue
        parent, child = edge.get("parentService"), edge.get("childService")
        if parent == service:
            current = node(parent, edge.get("parentType", ""), edge)
            children[(child, edge.get("clusterId"), edge.get("dataSource"))] = node(
                child, edge.get("childType", ""), edge
            )
        if child == service:
            current = node(child, edge.get("childType", ""), edge)
            parents[(parent, edge.get("clusterId"), edge.get("dataSource"))] = node(
                parent, edge.get("parentType", ""), edge
            )
    if current is None:
        raise ValueError(f"Service {service} not found in topology")
    # 关系数据没有 endpoint / isTraced 证据，不生成这些字段。
    return {
        "current": current,
        "parents": list(parents.values()),
        "children": list(children.values()),
        "rawResp": relations,
    }
