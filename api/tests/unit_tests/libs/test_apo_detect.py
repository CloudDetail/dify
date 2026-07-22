import numpy as np

from libs.apo_detect import ShockAnomalyDetector


def test_expected_oscillation_peak_is_not_reported_as_shock():
    series = np.array([10, 20, 10, 20, 10, 20, 10, 21.4, 10], dtype=float)

    result = ShockAnomalyDetector().detect(series)

    assert result == []


def test_peak_outside_oscillation_envelope_is_reported():
    series = np.array([10, 20, 10, 20, 10, 20, 10, 24, 10], dtype=float)

    result = ShockAnomalyDetector().detect(series)

    assert result == [(7, 24.0)]
