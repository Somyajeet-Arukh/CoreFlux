#!/usr/bin/env bash
# Run in a privileged container with the prepared WSL kernel volume and workspace.
set -euo pipefail
cd /workspace
mkdir -p benchmarks/reports
mount -t tracefs tracefs /sys/kernel/tracing
cleanup() {
    rm -f /tmp/coreflux-device
    rmmod coreflux_main 2>/dev/null || true
    umount /sys/kernel/tracing 2>/dev/null || true
}
trap cleanup EXIT

insmod /kernel/phase2/coreflux_main.ko
minor=$(awk '$2 == "coreflux" {print $1}' /proc/misc)
test -n "$minor"
mknod /tmp/coreflux-device c 10 "$minor"
build/coreflux-ring-reader /tmp/coreflux-device benchmarks/reports/module-events.jsonl 2 > /tmp/module-summary.txt &
reader=$!
sleep 0.1
build/coreflux-workload --mode mixed --seconds 1 --threads 8 > /tmp/module-workload.json
wait "$reader"
rmmod coreflux_main
rm /tmp/coreflux-device

build/coreflux-ebpf-loader build/sched.bpf.o benchmarks/reports/ebpf-events.jsonl 2 > /tmp/ebpf-summary.txt &
reader=$!
sleep 0.1
build/coreflux-workload --mode mixed --seconds 1 --threads 8 > /tmp/ebpf-workload.json
wait "$reader"

python3 - <<'PY'
import json
import platform
import re
from pathlib import Path

required = {'timestamp_ns', 'cpu', 'prev_pid', 'next_pid', 'type'}
summary = {}
for backend in ('module', 'ebpf'):
    path = Path(f'benchmarks/reports/{backend}-events.jsonl')
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records and all(set(record) == required for record in records)
    assert all(record['type'] == 1 and record['timestamp_ns'] > 0 for record in records)
    assert any(record['prev_pid'] != record['next_pid'] for record in records)
    text = Path(f'/tmp/{backend}-summary.txt').read_text().strip()
    match = re.match(r'events=(\d+) emitted=(\d+) dropped=(\d+) ', text)
    assert match and int(match[1]) == len(records)
    summary[backend] = {'events': len(records), 'emitted': int(match[2]), 'dropped': int(match[3]),
                        'cpus_observed': len({record['cpu'] for record in records}),
                        'workload': json.loads(Path(f'/tmp/{backend}-workload.json').read_text())}
report = {'schema_version': 1, 'kernel': platform.release(),
          'comparison': 'same workload settings, separate 2-second observations',
          'backends': summary}
Path('benchmarks/reports/backend-parity.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(summary))
PY
