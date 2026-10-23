#!/usr/bin/env bash
# Run inside a privileged container with the workspace mounted at /workspace.
set -euo pipefail
cd /workspace
mkdir -p benchmarks/reports
mount -t tracefs tracefs /sys/kernel/tracing
trap 'umount /sys/kernel/tracing 2>/dev/null || true' EXIT
for trial in 1 2; do
    prefix="benchmarks/reports/analysis-trial-${trial}"
    build/coreflux-ebpf-loader build/sched.bpf.o "${prefix}-events.jsonl" 5 > "${prefix}-reader.txt" &
    reader=$!
    sleep 0.1
    python3 scripts/sample-signals.py --seconds 4 --threads 48 --output "${prefix}-system.csv"
    wait "$reader"
    python3 scripts/merge-event-intensity.py "${prefix}-system.csv" "${prefix}-events.jsonl" "${prefix}-signals.csv"
    build/coreflux-analyze "${prefix}-signals.csv" "${prefix}-decisions.jsonl"
done
python3 - <<'PY'
import json
from pathlib import Path
report = {'schema_version': 1, 'trials': []}
for trial in (1, 2):
    prefix = Path(f'benchmarks/reports/analysis-trial-{trial}')
    decisions = [json.loads(line) for line in Path(f'{prefix}-decisions.jsonl').read_text().splitlines()]
    states = sorted({item['state'] for item in decisions})
    report['trials'].append({'trial': trial, 'samples': len(decisions), 'states': states,
                             'peak_score': max(item['score'] for item in decisions),
                             'dominant_at_peak': max(decisions, key=lambda item: item['score'])['dominant']})
Path('benchmarks/reports/analysis-reproducibility.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
PY
