#!/usr/bin/env python3
"""Measure affinity isolation under a controlled single-CPU competition."""
import json
import os
import statistics
import subprocess
import time
from pathlib import Path

available = sorted(os.sched_getaffinity(0))
if len(available) < 2:
    raise SystemExit("two allowed CPUs required")
shared_cpu, isolated_cpu = available[:2]
binary = "build/coreflux-workload"
decision = "benchmarks/reports/analysis-trial-2-decisions.jsonl"
if not Path(decision).exists():
    raise SystemExit("run the contention analysis experiment before this benchmark")

def pin(cpu):
    os.sched_setaffinity(0, {cpu})

def trial(intervention):
    noisy = subprocess.Popen([binary, "--mode", "cpu", "--seconds", "5", "--threads", "1"],
                             stdout=subprocess.DEVNULL, preexec_fn=lambda: pin(shared_cpu))
    policy = None
    try:
        time.sleep(0.2)
        if intervention:
            policy = subprocess.Popen(["build/coreflux-policy", str(noisy.pid), "affinity",
                                       str(isolated_cpu), "3", decision,
                                       "benchmarks/reports/policy-events.jsonl", "--apply"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert policy.stdout.readline().startswith("applied ")
            assert os.sched_getaffinity(noisy.pid) == {isolated_cpu}
        sensitive = subprocess.run([binary, "--mode", "cpu", "--seconds", "2", "--threads", "1"],
                                   check=True, capture_output=True, text=True,
                                   preexec_fn=lambda: pin(shared_cpu))
        operations = json.loads(sensitive.stdout)["operations"]
        if policy:
            stdout, stderr = policy.communicate(timeout=5)
            assert policy.returncode == 0, stderr
            assert "restored PID" in stdout
            assert os.sched_getaffinity(noisy.pid) == {shared_cpu}
        return operations / 2
    finally:
        if policy and policy.poll() is None:
            policy.terminate()
            policy.wait(timeout=5)
        noisy.terminate()
        noisy.wait(timeout=5)

results = []
for _ in range(3):
    baseline = trial(False)
    isolated = trial(True)
    results.append({"baseline_ops_per_second": baseline,
                    "isolated_ops_per_second": isolated,
                    "improvement_percent": (isolated / baseline - 1) * 100})
report = {"schema_version": 1, "workload": "two CPU-bound one-thread processes",
          "shared_cpu": shared_cpu, "isolated_cpu": isolated_cpu,
          "decision_source": decision, "trials": results,
          "median_improvement_percent": statistics.median(item["improvement_percent"] for item in results)}
destination = Path("benchmarks/reports/policy-affinity.json")
destination.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
