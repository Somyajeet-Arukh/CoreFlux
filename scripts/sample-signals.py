#!/usr/bin/env python3
"""Sample host pressure while a controlled workload runs."""
import argparse
import csv
import os
import subprocess
import time
from pathlib import Path

def pressure(path):
    with open(path, encoding="ascii") as stream:
        for line in stream:
            if line.startswith("some "):
                return int(dict(part.split("=", 1) for part in line.split()[1:])["total"])
    raise RuntimeError(f"missing PSI some total in {path}")

def context_switches():
    with open("/proc/stat", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("ctxt "):
                return int(line.split()[1])
    raise RuntimeError("missing ctxt in /proc/stat")

def runnable():
    return int(Path("/proc/loadavg").read_text().split()[3].split("/")[0])

parser = argparse.ArgumentParser()
parser.add_argument("--binary", default="build/coreflux-workload")
parser.add_argument("--mode", choices=["cpu", "mixed"], default="cpu")
parser.add_argument("--seconds", type=int, default=5)
parser.add_argument("--threads", type=int, default=32)
parser.add_argument("--interval-ms", type=int, default=200)
parser.add_argument("--output", default="benchmarks/reports/signals.csv")
args = parser.parse_args()
if not 1 <= args.seconds <= 60 or not 1 <= args.threads <= 64 or not 50 <= args.interval_ms <= 2000:
    parser.error("invalid duration, thread count, or sample interval")

cores = os.cpu_count() or 1
previous = (time.monotonic_ns(), pressure("/proc/pressure/cpu"),
            pressure("/proc/pressure/memory"), context_switches())
rows = []
command = [args.binary, "--mode", args.mode, "--seconds", str(args.seconds),
           "--threads", str(args.threads)]
workload = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
while workload.poll() is None:
    time.sleep(args.interval_ms / 1000)
    current = (time.monotonic_ns(), pressure("/proc/pressure/cpu"),
               pressure("/proc/pressure/memory"), context_switches())
    elapsed_seconds = (current[0] - previous[0]) / 1e9
    elapsed_us = elapsed_seconds * 1e6
    rows.append((current[0],
                 min(1.0, max(0.0, (current[1] - previous[1]) / elapsed_us)),
                 min(1.0, runnable() / cores),
                 min(1.0, max(0.0, (current[3] - previous[3]) / elapsed_seconds / cores / 1000)),
                 min(1.0, max(0.0, (current[2] - previous[2]) / elapsed_us)),
                 -1))
    previous = current
stdout, _ = workload.communicate()
if workload.returncode:
    raise SystemExit(workload.returncode)
destination = Path(args.output)
destination.parent.mkdir(parents=True, exist_ok=True)
with destination.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["timestamp_ns", "cpu_pressure", "runnable_pressure",
                     "context_switch_intensity", "memory_pressure", "scheduler_latency"])
    writer.writerows(rows)
print(f"saved {len(rows)} samples to {destination}; workload: {stdout.strip()}")
