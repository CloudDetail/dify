import unittest

from apo_utils import get_history_timeseries


class TestGetHistoryTimeseries(unittest.TestCase):

    def test_match_legend(self):
        history = {
            "data": {
                "timeseries": [
                    {
                        "labels": {"key": "value"},
                        "legend": "test_legend",
                        "chart": {
                            "chartData": {
                                "1760148371410000": 12.121
                            }
                        }
                    }
                ]
            }
        }

        result = get_history_timeseries("test_legend", {}, history)
        self.assertEqual(result, {"1760148371410000": 12.121})

    def test_match_labels(self):
        history = {
            "data": {
                "timeseries": [
                    {
                        "labels": {"env": "prod"},
                        "legend": "another_legend",
                        "chart": {
                            "chartData": {
                                "1760148371410000": 99.99
                            }
                        }
                    }
                ]
            }
        }

        result = get_history_timeseries("not_exist", {"env": "prod"}, history)
        self.assertEqual(result, {"1760148371410000": 99.99})

    def test_not_found(self):
        history = {
            "data": {
                "timeseries": [
                    {
                        "labels": {"env": "prod"},
                        "legend": "another_legend",
                        "chart": {
                            "chartData": {
                                "1760148371410000": 1.23
                            }
                        }
                    }
                ]
            }
        }

        result = get_history_timeseries("unknown", {"env": "dev"}, history)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
