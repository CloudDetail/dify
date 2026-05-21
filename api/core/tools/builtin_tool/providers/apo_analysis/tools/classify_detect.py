import json
from collections.abc import Generator
from typing import Any, Optional

import numpy as np

from configs.apo import APOConfig
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class ClassifierAnomalyDetector:
    def __init__(
        self,
        mode: str = "zscore",  # "quantile", "zscore", "interval"
        lower_q: float = 0.05,
        upper_q: float = 0.95,
        threshold: float = 2.0,
        k: float = 3.0,
    ):
        self.mode = mode
        self.lower_q = lower_q
        self.upper_q = upper_q
        self.threshold = threshold
        self.k = k

    def detect(self, series: np.ndarray, history: Optional[np.ndarray] = None) -> list[tuple[int, float]]:
        """返回 [(下标, 值), ...]"""
        data = history if history is not None and len(history) > 0 else series

        if self.mode == "quantile":
            low, high = np.quantile(data, [self.lower_q, self.upper_q])
            anomalies = np.where((series < low) | (series > high))[0]

        elif self.mode == "kmeans":
            mean = np.mean(data)
            std = np.std(data) + 1e-8
            z_scores = np.abs((series - mean) / std)
            anomalies = np.where(z_scores > self.threshold)[0]

        elif self.mode == "interval":
            mean = np.mean(data)
            std = np.std(data)
            low, high = mean - self.k * std, mean + self.k * std
            anomalies = np.where((series < low) | (series > high))[0]

        else:
            raise ValueError(f"未知模式: {self.mode}")

        return [(int(i), float(series[i])) for i in anomalies]


class ClassifyAnalysisTool(BuiltinTool):
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
            case "quantile_detect":
                res = self.quantile_detect(data)
            case "kmeans_detect":
                res = self.kmeans_detect(data)
            case "interval_detect":
                res = self.interval_detect(data)
        yield self.create_text_message(res)

    def quantile_detect(self, data_str):
        config = APOConfig()
        detect = ClassifierAnomalyDetector(
            mode="quantile",
            lower_q=config.APO_DETECT_CLASSIFY_LOWER_Q,
            upper_q=config.APO_DETECT_CLASSIFY_UPPER_Q,
            threshold=config.APO_DETECT_CLASSIFY_THRESHOLD,
            k=config.APO_DETECT_CLASSIFY_K,
        )
        data = json.loads(data_str)
        timeseries = data.get("data", {}).get("timeseries", [])
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
                    "unit": unit,
                    "result": r
                })

        return json.dumps(results)

    def kmeans_detect(self, data_str):
        config = APOConfig()
        detect = ClassifierAnomalyDetector(
            mode="kmeans",
            lower_q=config.APO_DETECT_CLASSIFY_LOWER_Q,
            upper_q=config.APO_DETECT_CLASSIFY_UPPER_Q,
            threshold=config.APO_DETECT_CLASSIFY_THRESHOLD,
            k=config.APO_DETECT_CLASSIFY_K,
        )
        data = json.loads(data_str)
        timeseries = data.get("data", {}).get("timeseries", [])
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
                    "unit": unit,
                    "result": r
                })

        return json.dumps(results)

    def interval_detect(self, data_str):
        config = APOConfig()
        detect = ClassifierAnomalyDetector(
            mode="interval",
            lower_q=config.APO_DETECT_CLASSIFY_LOWER_Q,
            upper_q=config.APO_DETECT_CLASSIFY_UPPER_Q,
            threshold=config.APO_DETECT_CLASSIFY_THRESHOLD,
            k=config.APO_DETECT_CLASSIFY_K,
        )
        data = json.loads(data_str)
        timeseries = data.get("data", {}).get("timeseries", [])
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
                    "unit": unit,
                    "result": r
                })

        return json.dumps(results)
