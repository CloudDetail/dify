import json
from collections.abc import Generator
from typing import Any, Optional

from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class AbnormalChartTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        result_str = tool_parameters.get('result')

        data = json.loads(result_str)
        timeseries = data.get('data', {}).get('timeseries', [])
        unit = data.get('unit', '')
        filtered = []

        for entry in timeseries:
            labels = entry.get('labels', {})

            chart = entry.get('chart', {}).get('chartData', {})
            # 仅在统计时跳过缺失点，原始曲线保留 null 和真实零值。
            values = [v for v in chart.values() if v is not None and v != 0]

            if len(values) == 0:
                continue

            avg = _get_avg(values)
            variance = _get_standard_deviation(avg, values)

            threshold = avg + 1 * variance
            
            count = 0
            for _, value in chart.items():
                if value is not None and value > threshold:
                    count += 1

            if count / len(values) >= 0.16:
                res = {
                    "chart": chart,
                    "abnormalCount": count,
                    "labels": labels,
                    "avg": avg,
                    "unit": unit
                }
                filtered.append(res)
                
        yield self.create_json_message({
            'type': 'metric',
            'data': filtered
        })

        yield self.create_text_message(json.dumps(filtered))
    

def _get_avg(values):
    if not values:
        return 0
    return sum(values) / len(values)


def _get_standard_deviation(avg, values):
    if len(values) == 0:
        return 0
    squared_diffs = [(x - avg)**2 for x in values]
    sum_squared_diffs = sum(squared_diffs)
    variance = sum_squared_diffs / (len(values))
    return variance**0.5
