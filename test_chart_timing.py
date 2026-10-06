"""Regression tests for dashboard chart timeline alignment."""

import unittest
from collections import deque

from app import wireguard


class TestChartTiming(unittest.TestCase):
    def setUp(self):
        with wireguard._history_lock:
            wireguard._peer_history.clear()
        with wireguard._ping_lock:
            wireguard._ping_history.clear()

    def tearDown(self):
        with wireguard._history_lock:
            wireguard._peer_history.clear()
        with wireguard._ping_lock:
            wireguard._ping_history.clear()

    def test_throughput_and_ping_share_poll_timestamp(self):
        """Both charts must use the same timestamp for one poll cycle."""
        peer = {
            "public_key": "offline_peer",
            "rx_bytes": 1000,
            "tx_bytes": 2000,
            "connected": False,
            "allowed_ips": "10.0.0.2/32",
        }
        poll_ts = 1_700_000_000.0

        wireguard._update_history([peer], poll_ts)
        wireguard._update_ping_history([peer], poll_ts)

        throughput = wireguard.get_throughput_history()["offline_peer"]
        ping = wireguard.get_ping_history()["offline_peer"]

        self.assertEqual(throughput["labels"], ping["labels"])
        self.assertEqual(throughput["rx_bps"], [0.0])
        self.assertEqual(throughput["tx_bps"], [0.0])
        self.assertEqual(ping["latencies"], [None])

    def test_throughput_keeps_initial_zero_point(self):
        """A single poll should still provide a timeline point."""
        peer = {
            "public_key": "offline_peer",
            "rx_bytes": 1000,
            "tx_bytes": 2000,
            "connected": False,
        }
        wireguard._update_history([peer], 1_700_000_000.0)

        history = wireguard.get_throughput_history()["offline_peer"]

        self.assertEqual(len(history["labels"]), 1)
        self.assertEqual(history["rx_bps"], [0.0])
        self.assertEqual(history["tx_bps"], [0.0])


if __name__ == "__main__":
    unittest.main()

    def test_chart_history_is_sampled_without_shortening_retention(self):
        """Chart output is reduced to the configured point count."""
        points = [(float(i), i, i, True) for i in range(60)]
        sampled = wireguard._sample_history_points(points, 30)

        self.assertEqual(len(sampled), 30)
        self.assertEqual(sampled[0], points[0])
        self.assertEqual(sampled[-1], points[-1])
