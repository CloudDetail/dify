import numpy as np

from libs.apo_oscillation import OscillationDetector


def test_detector_requires_two_complete_cycles():
    one_cycle = np.array([10, 20, 10, 20, 10], dtype=float)
    two_cycles = np.array([10, 20, 10, 20, 10, 20, 10], dtype=float)

    assert OscillationDetector().analyze(one_cycle)["is_oscillating"] is False
    assert OscillationDetector().analyze(two_cycles)["is_oscillating"] is True


def test_detector_does_not_require_a_fixed_period():
    series = np.array([10, 20, 10, 10, 20, 10, 10, 10, 20, 10, 10, 10, 10, 20, 10], dtype=float)

    analysis = OscillationDetector().analyze(series)

    assert analysis["is_oscillating"] is True
    assert analysis["has_stable_envelope"] is True
    assert analysis["has_center_drift"] is False


def test_detector_marks_a_rising_oscillation_center():
    series = np.array([10, 20, 11, 21, 12, 22, 13, 23, 14, 24, 15, 25, 16, 26, 17, 27], dtype=float)

    analysis = OscillationDetector().analyze(series)

    assert analysis["is_oscillating"] is True
    assert analysis["has_center_drift"] is True


def test_normal_envelope_candidate_is_filtered():
    series = np.array([10, 20, 10, 20, 10, 20, 10, 21.4, 10], dtype=float)

    filtered = OscillationDetector().filter_expected_points(series, [7])

    assert filtered == []
