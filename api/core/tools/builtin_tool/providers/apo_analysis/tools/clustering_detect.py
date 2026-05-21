import json
from collections.abc import Generator
from typing import Any, Optional

import numpy as np

from configs.apo import APOConfig
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


def mse_anomaly_score(current: np.ndarray, history: np.ndarray = None) -> float:
    """
    均方误差 (Mean Squared Error) 异常分数
    如果 history 为空 -> 自身与均值比较
    如果 history 存在 -> 与历史数据对齐比较
    """
    current = np.asarray(current, dtype=float)

    if history is None or len(history) == 0:
        baseline = np.mean(current)
        return np.mean((current - baseline) ** 2)

    history = np.asarray(history, dtype=float)
    n = min(len(current), len(history))
    return np.mean((current[:n] - history[:n]) ** 2)


def corr_anomaly_score(current: np.ndarray, history: np.ndarray = None) -> float:
    """
    相关系数 (Pearson Correlation) 异常分数
    返回 (1 - 相关系数)，越大表示越异常
    """
    current = np.asarray(current, dtype=float)

    if history is None or len(history) == 0:
        # 自身内部的变化：与趋势（线性拟合）相关性作为 baseline
        x = np.arange(len(current))
        if len(current) < 2:
            return 1.0  # 无法计算相关性
        trend = np.poly1d(np.polyfit(x, current, 1))(x)
        corr = np.corrcoef(current, trend)[0, 1]
        return 1 - corr

    history = np.asarray(history, dtype=float)
    n = min(len(current), len(history))
    if n < 2:
        return 1.0
    corr = np.corrcoef(current[:n], history[:n])[0, 1]
    return 1 - corr


def dtw_distance(current: np.ndarray, history: np.ndarray = None) -> float:
    """
    动态时间规整 (DTW) 距离（简化版）
    如果没有历史 -> 返回曲线自身的变化量
    """
    current = np.asarray(current, dtype=float)

    if history is None or len(history) == 0:
        # 用一阶差分的绝对值和衡量自身异常
        return np.sum(np.abs(np.diff(current)))

    history = np.asarray(history, dtype=float)
    n, m = len(current), len(history)

    # 初始化 DP 矩阵
    dp = np.full((n + 1, m + 1), np.inf)
    dp[0, 0] = 0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(current[i - 1] - history[j - 1])
            dp[i, j] = cost + min(dp[i - 1, j], dp[i, j - 1], dp[i - 1, j - 1])

    return dp[n, m] / (n + m)


def zscore_anomaly(current: np.ndarray, history: np.ndarray = None) -> float:
    """
    Z-Score 异常分数
    如果有历史 -> 基于历史均值和方差
    如果无历史 -> 基于自身的分布
    返回的是均值的 zscore
    """
    current = np.asarray(current, dtype=float)

    if history is None or len(history) == 0:
        mu, sigma = np.mean(current), np.std(current) + 1e-8
        return float(np.max(np.abs((current - mu) / sigma)))

    history = np.asarray(history, dtype=float)
    mu, sigma = np.mean(history), np.std(history) + 1e-8
    return float(np.max(np.abs((current - mu) / sigma)))


def filter_abnormal(data_str, algorithm: str, history=None):
    """
    根据算法计算 score 并过滤异常指标
    """
    data = json.loads(data_str)
    timeseries = data.get("data", {}).get("timeseries", [])
    results = []

    unit = data.get("unit", "")
    config = APOConfig()
    for entry in timeseries:
        chart_data = entry["chart"]["chartData"]
        values = np.array(list(chart_data.values()), dtype=float)

        # 算法计算
        if algorithm == "mse_detect":
            score = mse_anomaly_score(values)
            is_abnormal = score > np.mean(
                values) * config.APO_DETECT_CLUSTERING_MSE_THRESHOLD

        elif algorithm == "corr_detect":
            score = corr_anomaly_score(values)
            is_abnormal = score > config.APO_DETECT_CLUSTERING_CORR_THRESHOLD

        elif algorithm == "dtw_detect":
            score = dtw_distance(values)
            is_abnormal = score > np.mean(
                values) * config.APO_DETECT_CLUSTERING_DTW_THRESHOLD

        elif algorithm == "zscore_detect":
            score = zscore_anomaly(values)
            is_abnormal = score > config.APO_DETECT_CLUSTERING_ZSCORE_THRESHOLD

        else:
            continue

        if is_abnormal:
            results.append({
                "chart": chart_data,
                "score": float(score),
                "labels": entry["labels"],
                "avg": float(np.mean(values)),
                "unit": unit
            })

    return results


class ClusteringAnalysisTool(BuiltinTool):
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

        res = filter_abnormal(data, detect_name, history)
        yield self.create_text_message(json.dumps(res, ensure_ascii=False))
