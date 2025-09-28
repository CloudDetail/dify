from typing import Any, Optional

import numpy as np
from scipy import stats

_HAS_SM = False


class ShockAnomalyDetector:
    def __init__(self, k_tukey: float = 1.5, min_duration: int = 1, window_size: int = 5):
        self.k_tukey = k_tukey
        self.min_duration = min_duration
        self.window_size = window_size

    @staticmethod
    def diff_positive(series: np.ndarray) -> np.ndarray:
        d = np.diff(series, prepend=series[0])
        return np.maximum(d, 0.0)

    @staticmethod
    def tukey_upper(data: np.ndarray, k: float = 1.5) -> float:
        if data.size == 0:
            return float("inf")
        q1, q3 = np.percentile(data, [25, 75])
        iqr = q3 - q1
        if iqr == 0:
            return q3
        return q3 + k * iqr

    def detect(
        self, current_series: np.ndarray, history_series: Optional[np.ndarray] = None
    ) -> list[tuple[int, float]]:
        if len(current_series) < 2:
            return []

        curr_pos_diff = self.diff_positive(current_series)
        hist_pos_diff = self.diff_positive(
            history_series) if history_series is not None else None

        anomalies = []
        global_positive = curr_pos_diff[curr_pos_diff > 0]
        upper_curr = self.tukey_upper(global_positive, self.k_tukey)

        for t in range(1, len(current_series)):
            x_t = curr_pos_diff[t]
            if x_t <= upper_curr:
                continue

            if hist_pos_diff is not None:
                upper_hist = self.tukey_upper(
                    hist_pos_diff[hist_pos_diff > 0], self.k_tukey)
                if x_t <= upper_hist:
                    continue

            # 持续性检查（简单实现）
            dur_count = 1
            for back in range(1, self.min_duration):
                if t - back >= 0 and curr_pos_diff[t - back] > upper_curr:
                    dur_count += 1
            if dur_count < self.min_duration:
                continue

            # 局部子窗口（包含中心），但计算本地上限时**排除中心点**
            left = max(0, t - self.window_size // 2)
            right = min(len(curr_pos_diff), t + self.window_size // 2 + 1)
            window_vals = curr_pos_diff[left:right]
            center_idx = t - left
            window_except = np.delete(window_vals, center_idx)
            window_positive = window_except[window_except > 0]
            upper_sub = self.tukey_upper(window_positive, self.k_tukey)
            if x_t <= upper_sub:
                continue

            anomalies.append((t, float(current_series[t])))

        return anomalies


class TrendAnomalyDetector:
    def __init__(
        self,
        mk_alpha: float = 0.05,
        increase_ratio_threshold: float = 0.2,
        min_length: int = 8,
    ):
        """
        :param mk_alpha: Mann-Kendall 显著性水平
        :param increase_ratio_threshold: 上涨幅度比率阈值
        :param min_length: 最小序列长度
        """
        self.mk_alpha = mk_alpha
        self.increase_ratio_threshold = increase_ratio_threshold
        self.min_length = min_length

    @staticmethod
    def mann_kendall_test(x: np.ndarray) -> dict[str, Any]:
        """Mann-Kendall 趋势检验"""
        n = len(x)
        S = 0
        for k in range(n - 1):
            S += np.sum(np.sign(x[k + 1:] - x[k]))
        varS = n * (n - 1) * (2 * n + 5) / 18.0
        if S > 0:
            Z = (S - 1) / np.sqrt(varS)
        elif S < 0:
            Z = (S + 1) / np.sqrt(varS)
        else:
            Z = 0.0
        p = 2 * (1 - stats.norm.cdf(abs(Z)))
        trend = "increasing" if Z > 0 else ("decreasing" if Z < 0 else "no")
        return {
            "S": float(S),
            "varS": float(varS),
            "Z": float(Z),
            "p_value": float(p),
            "trend": trend,
        }

    def detect(self, today: np.ndarray, history: Optional[np.ndarray] = None) -> dict[str, Any]:
        """
        趋势异常检测
        - 若 history 为 None，则直接检测 today 的趋势
        - 若 history 存在，则检测 today 与 history 的相对差值趋势

        返回:
        {
            "is_anomaly": bool,
            "reason": str,
            "anomaly_points": List[(idx, value)],
            "mk": {...},
            "adf": {...} or None
        }
        """
        today = np.asarray(today, dtype=float)
        if history is not None:
            history = np.asarray(history, dtype=float)
            if len(today) != len(history):
                raise ValueError("today 和 history 必须长度一致")
            series = today - history
        else:
            series = today

        n = len(series)
        if n < self.min_length:
            return {
                "is_anomaly": False,
                "reason": f"序列过短 (n={n})",
                "anomaly_points": [],
            }

        # ADF 检验（可选）
        adf_res = None
        # if _HAS_SM:
        #     try:
        #         stat, pval, _, _, crit, _ = adfuller(series, autolag="AIC")
        #         adf_res = {"adf_stat": float(stat), "pvalue": float(pval), "crit": crit}
        #     except Exception as e:
        #         adf_res = {"error": str(e)}

        # MK 检验
        mk = self.mann_kendall_test(series)
        if mk["trend"] != "increasing" or mk["p_value"] > self.mk_alpha:
            return {
                "is_anomaly": False,
                "reason": "无显著上涨趋势",
                "anomaly_points": [],
                "mk": mk,
                "adf": adf_res,
            }

        # 计算上涨幅度比率
        abs_increase = float(series[-1] - series[0])
        base_value = float(series[0]) if series[0] != 0 else 1.0
        inc_ratio = abs_increase / base_value

        if inc_ratio <= self.increase_ratio_threshold:
            return {
                "is_anomaly": False,
                "reason": f"上涨比率 {inc_ratio:.3f} <= 阈值 {self.increase_ratio_threshold}",
                "anomaly_points": [],
                "mk": mk,
                "adf": adf_res,
            }

        # ✅ 缓慢上涨异常 → 最后一个点为异常点
        anomaly_points: list[tuple[int, float]] = [
            (len(today) - 1, float(today[-1]))]

        return {
            "is_anomaly": True,
            "reason": f"检测到缓慢上涨异常，最后点为异常点 (ratio={inc_ratio:.3f})",
            "anomaly_points": anomaly_points,
            "mk": mk,
            "adf": adf_res,
        }


class FrequencyAnomalyDetector:
    """
    基于分位数聚合特征 (Double Rolling Aggregate) 的频率异常检测模块
    """

    def __init__(
        self,
        window_size: int = 10,
        agg_window: int = 5,
        quantiles: Optional[list[float]] = None,
        threshold: float = 3.0,
    ):
        self.window_size = window_size
        self.agg_window = agg_window
        self.quantiles = quantiles if quantiles is not None else [
            0.25, 0.5, 0.75]
        self.threshold = threshold

    def _rolling_windows(self, series: np.ndarray, size: int) -> np.ndarray:
        n = len(series)
        if n < size:
            return np.array([])
        return np.array([series[i: i + size] for i in range(n - size + 1)])

    def _compute_quantiles(self, windows: np.ndarray) -> np.ndarray:
        return np.array([[np.quantile(w, q) for q in self.quantiles] for w in windows])

    def _double_rolling(self, features: np.ndarray) -> np.ndarray:
        if len(features) < self.agg_window:
            return features.mean(axis=1)

        agg_features = []
        for i in range(len(features) - self.agg_window + 1):
            window = features[i: i + self.agg_window]
            agg_features.append(window.mean())
        return np.array(agg_features)

    def _is_monotonic(self, series: np.ndarray) -> bool:
        """判断序列是否单调上升或单调下降"""
        diffs = np.diff(series)
        return np.all(diffs >= 0) or np.all(diffs <= 0)

    def detect(self, series: np.ndarray) -> list[tuple[int, float]]:
        if len(series) < self.window_size:
            return []

        windows = self._rolling_windows(series, self.window_size)
        if len(windows) == 0:
            return []

        quantile_features = self._compute_quantiles(windows)
        agg_features = self._double_rolling(quantile_features)

        # --- Step 1: 正常 Z-score 检测 ---
        mean_val = np.mean(agg_features)
        std_val = np.std(agg_features) + 1e-8
        z_scores = (agg_features - mean_val) / std_val

        anomalies = []
        for i, z in enumerate(z_scores):
            if abs(z) > self.threshold:
                idx = i + self.window_size + self.agg_window - 2
                if idx < len(series):
                    anomalies.append((idx, series[idx]))

        # --- Step 2: 如果没有找到局部异常，检测整体趋势 ---
        if not anomalies and self._is_monotonic(series):
            if np.ptp(series) > 0:
                anomalies.append((len(series) - 1, series[-1]))

        return anomalies


class SingleMetricAnomalyDetector:
    def __init__():
        pass

    def detect(self, data: np.ndarray, history: Optional[np.ndarray] = None) -> dict:
        """
        调整后的主检测函数 V2。
        首先识别整个曲线的宏观类型（趋势或高频），如果不属于这两类，
        则进一步检测并定位局部的突刺点。

        参数:
            data: 需要检测的数据序列 (np.array)
            history: 历史数据，用于比较 (np.array, 可选)

        返回:
            一个字典，包含整体的异常类型和具体的异常点位列表。
            格式为 {'type': str, 'points': List[Dict]}。
            - type: 'trend', 'frequency', 'spike', 或 'normal'.
            - points: 异常点列表 [{'index': int, 'value': float}, ...].
        """
        if len(data) < 3:
            return {"type": "normal", "points": []}

        trend_detector = TrendAnomalyDetector()
        res = trend_detector.detect(data, history)
        if res["is_anomaly"]:
            return {
                "type": "trend",
                "points": [{"index": p[0], "value": p[1]} for p in res["anomaly_points"]],
            }
        freq = FrequencyAnomalyDetector()
        f = freq.detect(data)
        if f:
            return {"type": "frequency", "points": f}

        spike_detector = ShockAnomalyDetector()
        spike_points = spike_detector.detect(data, history)
        if spike_points:
            return {"type": "spike", "points": spike_points}
        return {"type": "normal", "points": []}


def detect_metrics(data: dict, history: Optional[dict] = None):
    detect = SingleMetricAnomalyDetector()
    latency_15min = list(v for v in data["chart"]["chartData"].values())
    data_now = np.array(latency_15min)
    history_data = None
    if history:
        h = list(v for v in history["chart"]["chartData"].values())
        history_data = np.array(h)
    return detect.detect(data_now, history_data)
