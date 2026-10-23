#!/usr/bin/env bash
set -euo pipefail
cd /workspace
mount -t tracefs tracefs /sys/kernel/tracing
trap 'umount /sys/kernel/tracing 2>/dev/null || true' EXIT
python3 scripts/benchmark-backends.py "$@"
