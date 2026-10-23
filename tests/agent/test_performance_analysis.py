import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[2] / "scripts" / "analyze-performance.py"
spec = importlib.util.spec_from_file_location("performance_analysis", path)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def measurement(value, unit="count", multiplexed=False):
    return {"status": "available", "value": value, "unit": unit, "multiplexed": multiplexed}


def run(mode, misses):
    counters = {"cycles": measurement(100), "instructions": measurement(200),
                "cache-misses": measurement(misses), "branch-misses": measurement(10),
                "context-switches": measurement(20), "task-clock": measurement(1000, "msec")}
    trial = {"counters": counters, "workload": {"operations": 1}}
    return {"mode": mode, "trials": [trial, trial]}


class PerformanceAnalysisTest(unittest.TestCase):
    def test_ratios_and_normalization(self):
        suite = {"schema_version": 2, "host": "test", "seconds_per_trial": 2,
                 "runs": [run("cpu", 1), run("sequential", 2), run("random", 4), run("context-switch", 1)]}
        report = analysis.analyze(suite)
        self.assertEqual(report["hardware_validation_status"], "ready_for_interpretation")
        self.assertEqual(report["hardware_validation_gaps"], [])
        self.assertEqual(report["workloads"][0]["medians"]["ipc"], 2)
        self.assertEqual(report["workloads"][0]["medians"]["task_clock_ms_per_second"], 500)
        self.assertEqual(report["comparisons"][0]["metric_ratios_to_over_from"]["cache_misses_per_million_instructions"], 2)

    def test_missing_and_multiplexed_hardware(self):
        suite = {"schema_version": 2, "host": "test", "seconds_per_trial": 2,
                 "runs": [run("cpu", 1), run("sequential", 2), run("random", 4), run("context-switch", 1)]}
        suite["runs"][0]["trials"][0]["counters"]["cycles"] = {"status": "unavailable", "reason": "not supported"}
        suite["runs"][2]["trials"][0]["counters"]["cache-misses"]["multiplexed"] = True
        report = analysis.analyze(suite)
        self.assertEqual(report["hardware_validation_status"], "awaiting_supported_unmultiplexed_counters")
        self.assertEqual({item["reason"] for item in report["hardware_validation_gaps"]}, {"not supported", "multiplexed"})
        self.assertIsNone(report["workloads"][0]["medians"]["ipc"])
        self.assertIsNone(report["comparisons"][0]["metric_ratios_to_over_from"]["cache_misses_per_million_instructions"])


if __name__ == "__main__":
    unittest.main()
