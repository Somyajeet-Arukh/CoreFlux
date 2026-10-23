#!/usr/bin/env bash
set -euo pipefail
insmod /kernel/phase2/coreflux_main.ko
trap 'rm -f /tmp/coreflux-device; rmmod coreflux_main 2>/dev/null || true' EXIT
minor=$(awk '$2 == "coreflux" {print $1}' /proc/misc)
test -n "$minor"
mknod /tmp/coreflux-device c 10 "$minor"
cd /workspace
cc -Wall -Wextra -Werror -Iinclude tests/kernel/mmap_smoke.c -o /tmp/coreflux-mmap-smoke
/tmp/coreflux-mmap-smoke /tmp/coreflux-device
# Let the bounded rings fill before consumption to verify explicit loss accounting.
build/coreflux-workload --mode mixed --seconds 1 --threads 8 >/tmp/coreflux-workload.json
summary=$(build/coreflux-ring-reader /tmp/coreflux-device benchmarks/baseline/telemetry-smoke.jsonl 2)
echo "$summary"
python3 - "$summary" <<'PY'
import re
import sys
match = re.fullmatch(r'events=(\d+) emitted=(\d+) dropped=(\d+) latency_samples=(\d+) latency_p50_us=(\d+) latency_p95_us=(\d+) latency_p99_us=(\d+) latency_clamped=(\d+) latency_invalid=(\d+)', sys.argv[1])
assert match and int(match[1]) > 0 and int(match[3]) > 0
assert int(match[1]) == int(match[4]) + int(match[9])
PY
python3 - <<'PY'
import json
from pathlib import Path
events = [json.loads(line) for line in Path('benchmarks/baseline/telemetry-smoke.jsonl').read_text().splitlines()]
assert events
assert all(event['type'] == 1 and event['timestamp_ns'] > 0 for event in events)
last_by_cpu = {}
for event in events:
    assert event['timestamp_ns'] >= last_by_cpu.get(event['cpu'], 0)
    last_by_cpu[event['cpu']] = event['timestamp_ns']
print(f'verified {len(events)} scheduler events across {len(last_by_cpu)} CPUs')
PY
