#!/usr/bin/env python3
"""Run one no-telemetry baseline and save its inputs and measurements."""
import argparse
import json
import os
import platform
import resource
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--binary", default="build/coreflux-workload")
parser.add_argument("--mode", choices=["cpu", "mixed"], default="cpu")
parser.add_argument("--seconds", type=int, default=2)
parser.add_argument("--threads", type=int, default=2)
parser.add_argument("--output", default="benchmarks/baseline/latest.json")
args = parser.parse_args()
if not 1 <= args.seconds <= 60 or not 1 <= args.threads <= 64:
    parser.error("seconds must be 1..60 and threads 1..64")

command = [args.binary, "--mode", args.mode, "--seconds", str(args.seconds), "--threads", str(args.threads)]
before = resource.getrusage(resource.RUSAGE_CHILDREN)
started = time.perf_counter_ns()
result = subprocess.run(command, check=True, capture_output=True, text=True)
elapsed = time.perf_counter_ns() - started
after = resource.getrusage(resource.RUSAGE_CHILDREN)
workload = json.loads(result.stdout)
record = {
    "schema_version": 1,
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "telemetry": "off",
    "policy": "off",
    "command": command,
    "environment": {"kernel": platform.release(), "machine": platform.machine(), "cpu_count": os.cpu_count()},
    "workload": workload,
    "measurements": {
        "elapsed_ns": elapsed,
        "operations_per_second": workload["operations"] / (elapsed / 1e9),
        "child_user_cpu_seconds": after.ru_utime - before.ru_utime,
        "child_system_cpu_seconds": after.ru_stime - before.ru_stime,
        "child_max_rss_kib": after.ru_maxrss,
    },
}
destination = Path(args.output)
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(f"saved baseline to {destination}")
