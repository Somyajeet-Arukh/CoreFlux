# CoreFlux

CoreFlux is an experimental Linux resource-contention and telemetry framework. It collects live scheduler events through a custom kernel module or eBPF, combines those observations with system pressure signals, scores contention, and can apply temporary resource controls to a specified workload. It also measures the reliability and cost of its own telemetry pipeline.

The implementation and reported experiments were validated on a WSL2 kernel using Docker. Controlled workloads generate pressure, while scheduler events are observed from the running kernel. The results describe this environment and are not production or bare-metal performance claims.

## Features

- **Two scheduler collectors:** a kernel module with bounded per-CPU shared-memory rings and an eBPF program with a BPF ring buffer.
- **Observable loss:** accepted, dropped, received, and unread event counts are kept distinct.
- **Contention scoring:** weighted CPU, runnable, context-switch, memory, and available latency signals produce explainable states with hysteresis.
- **Bounded intervention:** a dry-run-first tool can temporarily change affinity, nice priority, or CPU cgroup quota for a CoreFlux workload and restore its prior state.
- **Reproducible experiments:** module saturation and recovery, matched-workload backend comparison, integration checks, and a source-and-report hash manifest.

## Architecture

```text
Controlled workloads ──→ Linux scheduler and system pressure
                            │                 │
                   kernel module or eBPF     signal sampler
                            │                 │
                            └─→ event and signal windows
                                         │
                                  contention scorer
                                         │
                              optional bounded policy
                                         │
                               reports and release checks
```

The module exposes `/dev/coreflux` for control and maps one bounded ring per possible CPU. Its reader writes scheduler events as JSONL. The eBPF collector observes the same `sched_switch` event class and writes equivalent fields. Analysis and policy are separate tools; collecting events does not automatically change system resources. See the [architecture](docs/architecture.md), [device ABI](docs/abi.md), and [ring design](docs/ring-buffer.md).

## Requirements

- Windows with WSL2 and Docker Desktop, or a compatible Linux host with Docker.
- A privileged container for live module, eBPF, and cgroup experiments.
- For module builds, kernel sources and generated artifacts matching the **running** kernel. The tested WSL2 setup keeps them in the `coreflux-kernel-build` Docker volume; [environment notes](docs/environment.md) explain how it was prepared.

Docker containers share the WSL2 kernel. Run live-kernel experiments one at a time. A different Linux host requires a module rebuilt for its kernel and a checked eBPF tracepoint layout.

## Build and test

From PowerShell in the project directory:

```powershell
docker build -f Dockerfile.dev -t coreflux-dev .
docker run --rm -v "${PWD}:/workspace" coreflux-dev bash -lc 'cd /workspace && cmake -S . -B build && cmake --build build -j4 && ctest --test-dir build --output-on-failure'
```

The full live release check requires the prepared kernel volume:

```powershell
docker run --rm --privileged --pid=host --cgroupns=host -v coreflux-kernel-build:/kernel -v "${PWD}:/workspace" coreflux-dev bash -lc 'cd /workspace && bash scripts/run-release-checks.sh'
```

It builds and tests the userspace tools, module, eBPF collector, analysis, policy, and benchmark paths. See [release checks](docs/release-hardening.md) for coverage and cleanup behavior. Reports are written under `benchmarks/reports/`; that generated directory is ignored by Git rules, so retain report files separately when sharing numerical results.

## Run the experiments

These commands use the built development image and prepared kernel volume. Run each independently from PowerShell.

| Experiment | Command inside the container | Documentation |
| --- | --- | --- |
| Baseline | `python3 scripts/run-baseline.py` | [Environment](docs/environment.md) |
| Module telemetry | `bash scripts/run-module-characterization.sh --seconds 2 --repeats 3` | [Scalability](docs/telemetry-scalability.md) |
| Backend comparison | `bash scripts/run-backend-comparison.sh --seconds 2 --repeats 3` | [Comparison](docs/backend-comparison.md) |
| Contention analysis | `bash scripts/run-analysis-experiment.sh` | [Analysis](docs/contention-analysis.md) |
| Affinity policy benchmark | `python3 scripts/benchmark-policy.py` | [Resource policy](docs/resource-policy.md) |

For live commands, use the privileged container and namespaces shown in the [release guide](docs/release-hardening.md) or the corresponding script documentation. The individual scripts preserve raw trials as JSON or JSONL for inspection. `coreflux-agent --synthetic` is a recorder fixture only; those artificial records are never used as kernel-observation or performance evidence.

## Findings

In the module characterization, the tested one-CPU two-thread stress setting attempted a median 25,076 events/s with 0.20% dropped. The one-CPU four-thread setting attempted 51,892 events/s with 20.76% dropped and a sampled full ring. This brackets the tested transition from low loss to saturation; it is not a universal capacity threshold. In three deliberate saturation-and-recovery trials, occupancy stayed below 20% within 9.5–17.9 ms after reading resumed.

In the four-CPU stress comparison, the module read about 150,692 events/s with 13.9% median drop fraction; eBPF read about 167,236 events/s with zero reported drops. Their buffer sizes and reader schedules differed, and short workload-throughput results varied across trials. The data therefore does not establish a general efficiency ranking. See [module scalability](docs/telemetry-scalability.md) and [backend comparison](docs/backend-comparison.md) for methods and limits.

The contention scorer reached CONTENTION in both live analysis trials with CPU pressure dominant. A separate paired affinity experiment improved the competing workload's median throughput by 95.31% in its defined two-workload isolation scenario. These controlled results are not claims of production prediction accuracy or general speedup.

## Project layout

```text
agent/       Userspace recorder, module reader, analysis, and policy tools
ebpf/        eBPF scheduler collector and loader
kernel/      Custom kernel module
include/     Shared event, scoring, and device ABI contracts
workloads/   Controlled workload generator
scripts/     Reproducible experiments and release orchestration
tests/       Unit, smoke, and integration checks
docs/        Architecture, methods, limitations, and final Word report
benchmarks/  Baseline and generated experiment outputs
```

The [validation scope](docs/validation-scope.md) summarizes what was established and what remains environment-specific. [Optional performance-counter tools](docs/performance-layer.md) are retained for future native-Linux study; IPC, cache-miss, branch-miss, and microarchitectural claims are outside this project's completed validation.
