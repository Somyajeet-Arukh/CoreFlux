#!/usr/bin/env bash
# Run with --privileged and the prepared kernel source volume mounted at /kernel.
set -euo pipefail
cd /workspace
bash scripts/run-kernel-smoke.sh >/dev/null
python3 scripts/characterize-module.py "$@"
