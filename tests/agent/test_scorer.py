import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

binary = sys.argv[1]

def run(rows, weights=None):
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / "signals.csv"
        output = Path(temp) / "decisions.jsonl"
        with source.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["timestamp_ns", "cpu_pressure", "runnable_pressure",
                             "context_switch_intensity", "memory_pressure", "scheduler_latency"])
            writer.writerows(rows)
        command = [binary, str(source), str(output)]
        if weights:
            command.append(weights)
        subprocess.run(command, check=True, capture_output=True, text=True)
        return [json.loads(line) for line in output.read_text().splitlines()]

high = [0.9, 0.9, 0.9, 0.9, -1]
low = [0.0, 0.0, 0.0, 0.0, -1]
decisions = run([[1_000_000_000, *low], [2_000_000_000, *high],
                 [2_100_000_000, *high], [3_000_000_000, *high],
                 [4_000_000_000, *high], [4_100_000_000, *low],
                 [5_000_000_000, *low]])
assert [item["state"] for item in decisions] == [
    "NORMAL", "WATCH", "WATCH", "CONTENTION", "SEVERE", "SEVERE", "CONTENTION"]
assert decisions[1]["dominant"] == "cpu_pressure"
assert abs(sum(decisions[1]["contributions"].values()) - decisions[1]["score"]) < 1e-5

unknown = run([[1_000_000_000, -1, -1, -1, 0.9, -1]])
assert unknown[0]["state"] == "UNKNOWN" and unknown[0]["coverage"] < 0.5

custom = run([[1_000_000_000, *high]], "0,0,1,0,0")
assert custom[0]["dominant"] == "context_switch_intensity" and custom[0]["coverage"] == 1

hysteresis = run([[1_000_000_000, 0.32, -1, -1, -1, -1],
                  [2_000_000_000, 0.36, -1, -1, -1, -1],
                  [3_000_000_000, 0.28, -1, -1, -1, -1],
                  [4_000_000_000, 0.24, -1, -1, -1, -1]], "1,0,0,0,0")
assert [item["state"] for item in hysteresis] == ["NORMAL", "WATCH", "WATCH", "NORMAL"]
