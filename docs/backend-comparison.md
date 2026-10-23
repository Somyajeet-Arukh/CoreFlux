# Backend comparison

The comparison runner measures the module and eBPF `sched_switch` collectors alongside a workload-only baseline. It reports workload throughput, collector CPU time and peak resident memory, observed event rate, delivery latency, and event loss. Run it with the command in the [README](../README.md); raw per-trial data is saved in `benchmarks/reports/backend-comparison.json`.

## Method

Each of three trials runs baseline, module, and eBPF observations sequentially, reversing the order on alternate trials. Workloads are pinned to 1, 2, or 4 allowed CPUs. The collectors observe scheduler events from the *whole host*, not just the pinned workload. Each workload runs for two seconds inside a roughly three-second collector window. The eBPF reader pauses one millisecond between nonblocking polls; the module reader waits one millisecond only when its rings are empty. A continuously polling eBPF reader generated a much larger stream of scheduler events from its own wake-ups, so pacing is necessary for this comparison. The different reader schedules still limit direct latency comparisons. Both readers write JSONL and share the same record format.

Workload overhead is each collector trial's percent change in completed operations against its paired baseline. Collector CPU time includes user and system time over the whole window; resident memory is the reader process's reported maximum, not total kernel memory. Event delivery latency is monotonic time from kernel event timestamp to user-space observation. Values above 100 ms are clamped in the histogram and counted separately. Loss fraction is `dropped / (emitted + dropped)`. `emitted - events` is reported as accepted but unread at collector shutdown, separate from ring overflow. Reported table values are medians of three observations, including medians of the per-trial latency percentiles. The raw report also keeps each trial and the min/max range for throughput change and loss; three repeats are too few for a useful confidence interval.

## WSL2 exploratory results

Kernel: `6.6.87.2-microsoft-standard-WSL2`. These are short observations and should not be treated as native Linux performance claims.

| Workload / pinned CPUs | Backend | Throughput vs baseline | Read events/s | Drop fraction | Reader CPU time | Event-to-reader p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| CPU, 1 worker / 1 CPU | Module | +1.9% | 2,134 | 0% | 0.047 s | 1,173 us |
| CPU, 1 worker / 1 CPU | eBPF | -4.6% | 5,317 | 0% | 0.065 s | 1,121 us |
| CPU, 4 workers / 2 CPUs | Module | +1.2% | 2,944 | 0% | 0.052 s | 1,149 us |
| CPU, 4 workers / 2 CPUs | eBPF | +1.9% | 2,482 | 0% | 0.060 s | 1,143 us |
| CPU, 8 workers / 4 CPUs | Module | +3.1% | 2,607 | 0% | 0.076 s | 1,143 us |
| CPU, 8 workers / 4 CPUs | eBPF | +4.5% | 2,661 | 0% | 0.072 s | 1,143 us |
| Stress, 16 workers / 4 CPUs | Module | -1.5% | 150,692 | 13.9% | 0.275 s | 1,047 us |
| Stress, 16 workers / 4 CPUs | eBPF | -1.4% | 167,236 | 0% | 0.238 s | 1,040 us |

Both readers' maximum resident memory was 14,592 KiB in all trials, too coarse a measure to distinguish their kernel-side memory use. The module allocates one page for each possible CPU (64 event slots plus a header per page); the eBPF ring is configured for 64 KiB plus per-CPU counters and ring metadata. These capacities differ, which contributes to their different stress-case loss rates. The module's per-CPU pages and direct shared-memory reader require a custom kernel build and module lifecycle. The eBPF program avoids a custom module but depends on BPF and tracefs support, a compatible tracepoint context layout, and a userspace loader. Neither is a universal drop-in replacement for the other.

The CPU cases show mixed throughput changes, including apparent gains. One four-CPU module trial was 42.1% below its paired baseline even though its other two trials were 3.1% and 9.1% above. The corresponding median therefore hides substantial run-to-run variation; these short runs do not resolve small overhead differences. P95 delivery is near one millisecond because reader cadence contributes substantially. In the stress case, the module's small per-CPU rings dropped 13.1–14.3% of attempted events across the three trials while the larger eBPF ring reported zero drops. Host-wide scheduling activity, the eBPF reader's own wake-ups, differing buffer capacity, thermal/frequency changes, and sequential rather than simultaneous observation prevent a causal ranking of backend efficiency. A longer native Linux experiment with matching ring capacity, isolated CPUs, and more repeats is needed for that claim.
