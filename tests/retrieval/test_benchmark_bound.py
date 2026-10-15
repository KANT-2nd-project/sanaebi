import unittest

from retrieval.experiments.optimization_benchmark import p95_lower_bound


class BenchmarkBoundTests(unittest.TestCase):
    def test_unknown_nonnegative_durations_cannot_lower_bound(self):
        self.assertGreater(p95_lower_bound([4000] * 4, 48), 3000)
        self.assertLess(p95_lower_bound([4000] * 3, 48), 3000)
        self.assertGreaterEqual(
            p95_lower_bound([4000] * 4 + [1] * 44, 48), p95_lower_bound([4000] * 4, 48)
        )

    def test_invalid_samples_rejected(self):
        for samples, count in [([-1], 48), ([1, 2], 1), ([float("nan")], 48)]:
            with self.assertRaises(ValueError):
                p95_lower_bound(samples, count)
