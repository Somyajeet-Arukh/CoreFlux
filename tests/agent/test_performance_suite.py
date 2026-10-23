import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[2] / "scripts" / "run-performance-suite.py"
spec = importlib.util.spec_from_file_location("performance_suite", path)
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class PerfParserTest(unittest.TestCase):
    def test_availability_and_multiplexing(self):
        counters = suite.parse_counters("<not supported>,,cycles,0,100.00,,\n"
                                         "100,,instructions,500,50.00,,\n"
                                         "12,,context-switches,1000,100.00,,\n")
        self.assertEqual(counters["cycles"], {"status": "unavailable", "reason": "not supported"})
        self.assertTrue(counters["instructions"]["multiplexed"])
        self.assertEqual(counters["instructions"]["running_percent"], 50.0)
        self.assertFalse(counters["context-switches"]["multiplexed"])
        self.assertEqual(counters["cache-misses"]["reason"], "not returned by perf")

    def test_invalid_result(self):
        counters = suite.parse_counters("nonsense,,task-clock,0,100.00,,\n")
        self.assertEqual(counters["task-clock"]["reason"], "invalid perf result")


if __name__ == "__main__":
    unittest.main()
