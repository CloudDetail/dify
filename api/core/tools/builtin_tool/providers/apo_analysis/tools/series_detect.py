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


def _series_match_key(entry: dict) -> tuple:
    labels = entry.get("labels", {})
    return (entry.get("legend", ""), tuple(sorted(labels.items())))


def _get_chart_values(entry: dict) -> list:
    return list(entry.get("chart", {}).get("chartData", {}).values())


def _resample_values(values: list, target_length: int) -> np.ndarray:
    if target_length <= 0:
        return np.array([])
    if len(values) == target_length:
        return np.asarray(values, dtype=float)
    bins = np.array_split(np.asarray(values, dtype=float), target_length)
    return np.asarray([float(np.mean(bucket)) for bucket in bins if len(bucket) > 0])


def _find_history_entry(entry: dict, history_timeseries: list) -> Optional[dict]:
    if not history_timeseries:
        return None

    entry_key = _series_match_key(entry)
    for history_entry in history_timeseries:
        if _series_match_key(history_entry) == entry_key:
            return history_entry

    labels = entry.get("labels", {})
    for history_entry in history_timeseries:
        if labels and history_entry.get("labels", {}) == labels:
            return history_entry

    legend = entry.get("legend", "")
    for history_entry in history_timeseries:
        if legend and history_entry.get("legend", "") == legend:
            return history_entry

    if len(history_timeseries) == 1:
        return history_timeseries[0]
    return None


def _detect_history_baseline_shift(today: np.ndarray, history: np.ndarray) -> Optional[dict[str, Any]]:
    today = np.asarray(today, dtype=float)
    history = np.asarray(history, dtype=float)
    today = today[today > 0]
    history = history[history > 0]

    if len(today) < 3 or len(history) < 3:
        return None

    history_mean = float(np.mean(history))
    today_mean = float(np.mean(today))
    history_median = float(np.median(history))
    today_median = float(np.median(today))
    mad = float(np.median(np.abs(history - history_median)))
    robust_sigma = 1.4826 * mad
    if robust_sigma == 0:
        robust_sigma = float(np.std(history))

    robust_upper = history_median + 3 * robust_sigma
    mean_ratio = today_mean / history_mean if history_mean > 0 else float("inf")
    median_ratio = today_median / history_median if history_median > 0 else float("inf")

    is_shifted = (
        today_median > robust_upper and median_ratio >= 1.5
    ) or mean_ratio >= 2.0
    if not is_shifted:
        return None

    anomaly_points = [
        (idx, float(value))
        for idx, value in enumerate(today)
        if value > robust_upper
    ]
    if not anomaly_points:
        anomaly_points = [(len(today) - 1, float(today[-1]))]

    return {
        "is_anomaly": True,
        "reason": (
            "检测到相对历史基线抬升异常"
            f" (mean_ratio={mean_ratio:.3f}, median_ratio={median_ratio:.3f})"
        ),
        "anomaly_points": anomaly_points,
        "baseline": {
            "history_mean": history_mean,
            "today_mean": today_mean,
            "history_median": history_median,
            "today_median": today_median,
            "robust_upper": float(robust_upper),
            "mean_ratio": float(mean_ratio),
            "median_ratio": float(median_ratio),
        },
    }


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
                res = self.trend_detect(data, history)
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

    def trend_detect(self, data_str, history_str=None):
        detect = TrendAnomalyDetector()
        data = json.loads(data_str)
        timeseries = _check_metrics(data.get("data", {}).get("timeseries", []))
        history_timeseries = []
        if history_str:
            history_data = json.loads(history_str)
            history_timeseries = _check_metrics(history_data.get("data", {}).get("timeseries", []))

        unit = data.get("unit", "")
        results = []
        for entry in timeseries:
            chart_data = entry["chart"]["chartData"]
            values = list(chart_data.values())
            data_now = np.array(values)
            history_entry = _find_history_entry(entry, history_timeseries)
            history_values = _get_chart_values(history_entry) if history_entry else []
            history_now = _resample_values(history_values, len(values)) if history_values else None

            try:
                r = detect.detect(data_now, history_now)
            except ValueError:
                r = detect.detect(data_now)

            baseline_shift = (
                _detect_history_baseline_shift(data_now, np.asarray(history_values, dtype=float))
                if history_values
                else None
            )
            if baseline_shift and not r.get("is_anomaly"):
                r = baseline_shift
            elif baseline_shift:
                r["baseline"] = baseline_shift.get("baseline")
                r["reason"] = f"{r.get('reason', '')}; {baseline_shift['reason']}"

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
