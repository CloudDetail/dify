from typing import Any

import numpy as np


class OscillationDetector:
    """Recognize a stable oscillation envelope without requiring a fixed period."""

    def __init__(
        self,
        min_complete_cycles: int = 2,
        envelope_tolerance_ratio: float = 0.25,
        center_drift_threshold: float = 0.2,
    ):
        self.min_complete_cycles = min_complete_cycles
        self.envelope_tolerance_ratio = envelope_tolerance_ratio
        self.center_drift_threshold = center_drift_threshold

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "is_oscillating": False,
            "has_stable_envelope": False,
            "has_center_drift": False,
            "turning_points": [],
            "peaks": [],
            "troughs": [],
        }

    @staticmethod
    def _extrema_are_stable(values: np.ndarray, amplitude: float, tolerance_ratio: float) -> bool:
        if len(values) < 2:
            return False
        center = float(np.median(values))
        mad = float(np.median(np.abs(values - center)))
        allowed = min(
            max(3 * 1.4826 * mad, 0.15 * amplitude),
            tolerance_ratio * amplitude,
        )
        return bool(np.max(np.abs(values - center)) <= allowed)

    @staticmethod
    def _drift_ratio(points: list[dict[str, Any]], amplitude: float) -> float:
        if len(points) < 2 or amplitude <= 1e-12:
            return 0.0
        indices = np.asarray([point["index"] for point in points], dtype=float)
        values = np.asarray([point["value"] for point in points], dtype=float)
        slope = float(np.polyfit(indices, values, 1)[0])
        drift = slope * float(indices[-1] - indices[0])
        return drift / amplitude

    def analyze(self, series: np.ndarray) -> dict[str, Any]:
        values = np.asarray(series, dtype=float)
        if len(values) < 5 or not np.all(np.isfinite(values)):
            return self._empty_result()

        raw_amplitude = float(np.ptp(values))
        if raw_amplitude <= 1e-12:
            return self._empty_result()

        tolerance = max(raw_amplitude * 1e-6, 1e-12)
        nonzero_diffs = [
            (index, int(np.sign(value)))
            for index, value in enumerate(np.diff(values))
            if abs(value) > tolerance
        ]
        turning_points = []
        peaks = []
        troughs = []
        for previous, current in zip(nonzero_diffs, nonzero_diffs[1:]):
            _, previous_sign = previous
            current_index, current_sign = current
            if previous_sign == current_sign:
                continue
            point = {"index": current_index, "value": float(values[current_index])}
            turning_points.append(point)
            if previous_sign > 0 and current_sign < 0:
                peaks.append(point)
            else:
                troughs.append(point)

        complete_cycles = max(len(peaks), len(troughs)) - 1
        is_oscillating = complete_cycles >= self.min_complete_cycles
        if not is_oscillating:
            return {
                **self._empty_result(),
                "turning_points": turning_points,
                "peaks": peaks,
                "troughs": troughs,
            }

        peak_values = np.asarray([point["value"] for point in peaks], dtype=float)
        trough_values = np.asarray([point["value"] for point in troughs], dtype=float)
        peak_center = float(np.median(peak_values))
        trough_center = float(np.median(trough_values))
        envelope_amplitude = peak_center - trough_center
        if envelope_amplitude <= 1e-12:
            return self._empty_result()

        peak_drift_ratio = self._drift_ratio(peaks, envelope_amplitude)
        trough_drift_ratio = self._drift_ratio(troughs, envelope_amplitude)
        center_drift_ratio = (peak_drift_ratio + trough_drift_ratio) / 2
        has_center_drift = abs(center_drift_ratio) > self.center_drift_threshold
        has_stable_envelope = (
            self._extrema_are_stable(peak_values, envelope_amplitude, self.envelope_tolerance_ratio)
            and self._extrema_are_stable(trough_values, envelope_amplitude, self.envelope_tolerance_ratio)
        )

        return {
            "is_oscillating": True,
            "has_stable_envelope": has_stable_envelope,
            "has_center_drift": has_center_drift,
            "center_drift_ratio": float(center_drift_ratio),
            "turning_points": turning_points,
            "peaks": peaks,
            "troughs": troughs,
            "center": float((peak_center + trough_center) / 2),
            "amplitude": float(envelope_amplitude),
        }

    def is_expected_point(self, series: np.ndarray, index: int, analysis: dict[str, Any]) -> bool:
        if not analysis.get("is_oscillating"):
            return False
        values = np.asarray(series, dtype=float)
        value = float(values[index])
        center = float(analysis["center"])
        amplitude = float(analysis["amplitude"])
        extrema = analysis["peaks"] if value >= center else analysis["troughs"]
        references = np.asarray(
            [point["value"] for point in extrema if point["index"] != index],
            dtype=float,
        )
        if len(references) < 2:
            return False
        reference_center = float(np.median(references))
        mad = float(np.median(np.abs(references - reference_center)))
        allowed = min(
            max(3 * 1.4826 * mad, 0.15 * amplitude),
            self.envelope_tolerance_ratio * amplitude,
        )
        return abs(value - reference_center) <= allowed

    def filter_expected_points(self, series: np.ndarray, candidate_indices: list[int]) -> list[int]:
        analysis = self.analyze(series)
        if (
            not analysis.get("has_stable_envelope")
            or analysis.get("has_center_drift")
        ):
            return candidate_indices

        return [
            index
            for index in candidate_indices
            if not self.is_expected_point(series, index, analysis)
        ]
