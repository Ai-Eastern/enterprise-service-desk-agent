import asyncio
import unittest

from src.capacity_baseline import run_capacity_baseline


class CapacityBaselineTests(unittest.TestCase):
    def test_small_mixed_workload(self) -> None:
        report = asyncio.run(run_capacity_baseline(total=20, concurrency=4))
        self.assertEqual("PASS", report["status"])
        self.assertEqual(20, report["results"]["succeeded"])
        self.assertEqual(0, report["results"]["failed"])
        self.assertEqual(
            {"diagnostic": 6, "knowledge": 8, "ticket": 6},
            report["workload"]["routes"],
        )

    def test_invalid_workload_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(run_capacity_baseline(total=0, concurrency=1))


if __name__ == "__main__":
    unittest.main()
