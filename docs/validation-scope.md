# Validation scope

CoreFlux was built and tested as an experimental framework on a WSL2 development host. Its release checks cover the device ABI, live scheduler collection through both backends, contention analysis, bounded resource actions, telemetry characterization, backend comparison, and cleanup behavior.

Controlled workloads generate CPU activity and event pressure. The module and eBPF collectors observe actual scheduler events from the running WSL2 kernel. Event timestamps, task identifiers, and loss counts come from those live collectors. The synthetic recorder fixture checks serialization only and is not performance evidence. The policy experiment changes real workload affinity, priority, or cgroup state and checks restoration.

No external production dataset or production traffic was used. The experiments establish behavior under their documented controlled conditions, including saturation and recovery; they do not establish production prediction accuracy or universal Linux capacity. Results may differ on native Linux or other hardware. Hardware performance counters, IPC, cache misses, branch misses, and microarchitectural analysis remain optional experimental infrastructure.

The [telemetry scalability report](telemetry-scalability.md) defines the observed operating-range bracket on this WSL2 setup. The [backend comparison](backend-comparison.md) records an exploratory module-versus-eBPF comparison. The [release guide](release-hardening.md) explains how to repeat the full checks. Machine-readable reports are generated under `benchmarks/reports/` and should be retained separately when sharing measurements.
