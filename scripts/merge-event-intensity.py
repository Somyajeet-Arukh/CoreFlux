#!/usr/bin/env python3
"""Replace the context-switch signal with the normalized backend's event rate."""
import argparse
import csv
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("signals")
parser.add_argument("events")
parser.add_argument("output")
args = parser.parse_args()
with open(args.signals, newline="", encoding="utf-8") as stream:
    rows = list(csv.DictReader(stream))
times = sorted(json.loads(line)["timestamp_ns"] for line in Path(args.events).read_text().splitlines())
if not rows or not times:
    raise SystemExit("signals and events must be nonempty")
cores = os.cpu_count() or 1
start = int(rows[0]["timestamp_ns"])
previous = start - (int(rows[1]["timestamp_ns"]) - start if len(rows) > 1 else 200_000_000)
index = 0
for row in rows:
    end = int(row["timestamp_ns"])
    while index < len(times) and times[index] <= previous:
        index += 1
    first = index
    while index < len(times) and times[index] <= end:
        index += 1
    interval = max((end - previous) / 1e9, 1e-9)
    row["context_switch_intensity"] = min(1.0, (index - first) / interval / cores / 1000)
    previous = end
with open(args.output, "w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"merged {len(rows)} signal windows with {len(times)} backend events")
