# Scheduler backend parity

The custom module and eBPF backend both observe `sched_switch` and write the same JSONL fields: `timestamp_ns`, `cpu`, `prev_pid`, `next_pid` and `type`. Both use a kernel monotonic timestamp, scheduler task IDs and CPU numbers. The shared serializer is `include/coreflux/json_record.hpp`. `type=1` means scheduler switch.

The module uses bounded per-CPU pages exposed through `mmap`; the eBPF path uses a BPF ring buffer. Both backends report accepted events and rejected events, so the comparison runner can compute `dropped / (emitted + dropped)` for each observation. Accepted events still unread when a collector stops are reported separately.

`scripts/run-backend-parity.sh` runs the same mixed workload settings for each backend in separate 2-second observations. It verifies nonempty streams, field equivalence, nontrivial PID changes and consistency between output rows and reported event counts. It saves `benchmarks/reports/backend-parity.json` plus both JSONL streams. Event totals need not match: scheduler activity from the host and start timing vary between runs. This test establishes semantic parity of the scheduler event class, not a performance comparison or event-by-event equivalence.

The eBPF context layout follows the current WSL kernel's `sched_switch` tracepoint format. Check the format before using the program on another kernel. Repeated overhead and scaling measurements are in [the backend comparison](backend-comparison.md).

The loss path was also tested: delaying eBPF consumption by 1.5 seconds while running the 16-thread mixed workload produced 257,878 reported drops. This verifies that failed ring reservations are visible. The delay is a test argument to `coreflux-ebpf-loader`, not a production setting.
