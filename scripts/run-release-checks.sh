#!/usr/bin/env bash
# Run in a privileged, host-PID and host-cgroup container with /kernel and /workspace mounted.
set -euo pipefail
cd /workspace

if grep -q '^coreflux_main ' /proc/modules; then
    echo 'coreflux_main is already loaded; release checks need exclusive module ownership' >&2
    exit 1
fi

cmake -S . -B build
cmake --build build -j4
ctest --test-dir build --output-on-failure

bash scripts/run-kernel-smoke.sh
bash scripts/run-telemetry-smoke.sh
bash scripts/run-module-characterization.sh --seconds 1 --repeats 1 --output benchmarks/reports/release-module-characterization.json
python3 scripts/verify-module-characterization.py benchmarks/reports/release-module-characterization.json --minimum-repeats 1 --output benchmarks/reports/release-module-characterization-validation.json
bash scripts/run-backend-parity.sh
bash scripts/run-analysis-experiment.sh
python3 tests/integration/test_policy.py build/coreflux-policy build/coreflux-workload
bash scripts/run-backend-comparison.sh --seconds 2 --repeats 2 --output benchmarks/reports/release-backend-comparison.json

if grep -q '^coreflux_main ' /proc/modules; then
    echo 'coreflux_main remained loaded after release checks' >&2
    exit 1
fi
python3 scripts/write-release-manifest.py
echo 'CoreFlux release checks passed; reports are in benchmarks/reports'
