import json
from collections.abc import Generator
from typing import Any, Optional

import numpy as np

from configs.apo import APOConfig
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.apo_detect import FrequencyAnomalyDetector, ShockAnomalyDetector, TrendAnomalyDetector


def _get_avg(values):
    if not values:
        return 0
    return sum(values) / len(values)


def _get_standard_deviation(avg, values):
    if len(values) == 0:
        return 0
    squared_diffs = [(x - avg) ** 2 for x in values]
    sum_squared_diffs = sum(squared_diffs)
    variance = sum_squared_diffs / (len(values))
    return variance**0.5


def _check_metrics(timeseries: list):
    res = []
    for item in timeseries:
        chart = item.get("chart", {}).get("chartData", {})
        has_data = False
        for v in chart.values():
            if v > 0:
                has_data = True
        if has_data:
            res.append(item)
    return res


class TimeSeriersAnalysisTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        detect_name = tool_parameters.get("algorithmName")
        data = tool_parameters.get("data")
        history = tool_parameters.get("history")
        res = ""
        match detect_name:
            case "ebpf_detect":
                res = self.metrics_detect(data)
            case "rtt_detect":
                res = self.rtt_detect(data)
            case "spike_detect":
                res = self.spike_detect(data)
            case "trend_detect":
                res = self.trend_detect(data)
            case "frequency_detect":
                res = self.frequent_detect(data)
        yield self.create_text_message(res)

    def spike_detect(self, data_str):
        detect = ShockAnomalyDetector()
        data = json.loads(data_str)
        timeseries = _check_metrics(data.get("data", {}).get("timeseries", []))
        res = []
        unit = data.get("unit", "")
        results = []
        for entry in timeseries:
            chart_data = entry["chart"]["chartData"]
            values = list(chart_data.values())
            data_now = np.array(values)
            r = detect.detect(data_now)
            if r:
                results.append({
                    "chart": chart_data,
                    "abnormalCount": len(r),
                    "spikes": [item[1] for item in r],
                    "labels": entry["labels"],
                    "avg": float(np.mean(values)),
                    "unit": unit
                })

        return json.dumps(results)

    def trend_detect(self, data_str):
        detect = TrendAnomalyDetector()
        data = json.loads(data_str)
        timeseries = _check_metrics(data.get("data", {}).get("timeseries", []))

        unit = data.get("unit", "")
        results = []
        for entry in timeseries:
            chart_data = entry["chart"]["chartData"]
            values = list(chart_data.values())
            data_now = np.array(values)
            r = detect.detect(data_now)
            if r['is_anomaly']:
                results.append({
                    "chart": chart_data,
                    "labels": entry["labels"],
                    "avg": float(np.mean(values)),
                    "unit": unit,
                    "result": r
                })

        return json.dumps(results)

    def frequent_detect(self, data_str):
        config = APOConfig()
        detect = FrequencyAnomalyDetector(
            window_size=config.APO_DETECT_SERIES_FREQUENCY_WINDOW_SIZE,
            agg_window_size=config.APO_DETECT_SERIES_FREQUENCY_AGG_WINDOW_SIZE,
            threshold=config.APO_DETECT_SERIES_FREQUENCY_THRESHOLD,
        )
        data = json.loads(data_str)
        timeseries = _check_metrics(data.get("data", {}).get("timeseries", []))

        unit = data.get("unit", "")
        results = []
        for entry in timeseries:
            chart_data = entry["chart"]["chartData"]
            values = list(chart_data.values())
            data_now = np.array(values)
            r = detect.detect(data_now)
            if r:
                r = [[t[0], int(t[1])] for t in r]
                results.append({
                    "chart": chart_data,
                    "abnormalCount": len(r),
                    "spikes": [item[1] for item in r],
                    "labels": entry["labels"],
                    "avg": float(np.mean(values)),
                    "unit": unit,
                    "result": r
                })

        return json.dumps(results)

    def metrics_detect(self, result_str):
        data = json.loads(result_str)
        timeseries = _check_metrics(data.get("data", {}).get("timeseries", []))
        unit = data.get("unit", "")
        filtered = []

        for entry in timeseries:
            labels = entry.get("labels", {})

            chart = entry.get("chart", {}).get("chartData", {})
            values = [v for v in chart.values() if v != 0]

            if len(values) == 0:
                continue

            avg = _get_avg(values)
            variance = _get_standard_deviation(avg, values)

            threshold = avg + 1 * variance

            count = 0
            for _, value in chart.items():
                if value > threshold:
                    count += 1

            if count != 0:
                res = {
                    "chart": chart,
                    "abnormalCount": count,
                    "labels": labels,
                    "avg": avg,
                    "unit": unit
                }
                filtered.append(res)

        return json.dumps(filtered)

    def rtt_detect(self, result_str: str):
        data = json.loads(result_str)
        timeseries = data.get("data", {}).get("timeseries", [])
        unit = data.get("unit", "")
        filtered = []

        for entry in timeseries:
            labels = entry.get("labels", {})

            chart = entry.get("chart", {}).get("chartData", {})
            values = [v for v in chart.values() if v != 0]

            if len(values) == 0:
                continue

            avg = _get_avg(values)
            variance = _get_standard_deviation(avg, values)

            threshold = avg + 1 * variance

            count = 0
            for _, value in chart.items():
                if value > 0.05:
                    count += 1

            if count != 0:
                res = {
                    "chart": chart,
                    "abnormalCount": count,
                    "labels": labels,
                    "avg": avg,
                    "unit": unit,
                    "spike": max(values),
                }
                filtered.append(res)

        return json.dumps(filtered)
