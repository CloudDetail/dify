import json
from collections.abc import Generator
from dataclasses import asdict
from typing import Any, Optional

from configs import dify_config
from core.tools.builtin_tool.providers.data_source import QueryMetricResult, query_metric, query_red_metrics
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_utils import APOUtils


class OriginxServiceRedRespOkTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        service_name = tool_parameters.get("service_name")
        content_key = tool_parameters.get("content_key")
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")

        metric_name = "Originx 北极星指标 (服务层级) - RED指标 - 请求成功率"

        try:
            if dify_config.DATA_SOURCE == "apo":
                labels = {
                    "service_name": service_name or "",
                    "content_key": content_key or ""
                }
                query_result = query_metric(
                    metric_name=metric_name,
                    start_time=start_time,
                    end_time=end_time,
                    step=APOUtils.get_step(start_time, end_time),
                    labels=labels,
                )
                resp = asdict(query_result)
                resp_str = json.dumps(resp)
            else:
                query_result = query_red_metrics(
                   title="Success Rate",
                   service=service_name or "",
                   cluster="",
                   start_time=start_time,
                   end_time=end_time,
                   endpoint=content_key or "",
                )
                resp = asdict(query_result)
                resp_str = json.dumps(resp)
        except Exception as e:
            # 捕获异常，返回空 QueryResult 或自定义错误处理
            print(f"Error querying metric {metric_name} by {dify_config.DATA_SOURCE}: {e}")
            resp_str = json.dumps(QueryMetricResult(
                type="metric",
                display=True,
                unit="",
                data={"timeseries": []},
            ))

        yield self.create_text_message(resp_str)


