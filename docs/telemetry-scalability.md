# Module telemetry scalability and runtime characterization

This study asks how the CoreFlux kernel module's per-CPU scheduler telemetry behaves as event pressure and CPU count rise. The study uses the module only; the separate [backend comparison](backend-comparison.md) compares it with eBPF. Hardware performance counters, IPC, cache/branch metrics, and microarchitectural claims are not completion requirements. The older [counter tools](performance-layer.md) remain optional infrastructure.

Run the experiment with the command in the [README](../README.md), then check the report:

```sh
python3 scripts/verify-module-characterization.py benchmarks/reports/module-characterization.json
```

The raw per-trial report is `benchmarks/reports/module-characterization.json`; the verification result is `benchmarks/reports/module-characterization-validation.json`. The run uses three two-second workload trials per setting and alternates baseline/module order. The workload is pinned to selected CPUs; scheduler telemetry remains host-wide, including other WSL activity. Each module trial gets a fresh module load, a roughly three-second reader window, and a ten-millisecond occupancy sampler. The sampler reads per-CPU `head` and `tail` from the shared mapping without consuming events. A separate experiment runs one second of high event pressure with no reader, then starts the reader and measures how long sampled occupancy takes to stay below 20% for three samples. This deliberately creates saturation and verifies that newly produced events can be received after the reader starts.

Accounting is explicit: **attempted = accepted + dropped** and **accepted = received + accepted-but-unread at reader shutdown**. The drop fraction is `dropped / attempted`. Reader counts and JSONL rows are checked against each other, and every received event is checked for shape, positive timestamp, nonnegative IDs, and nondecreasing per-CPU timestamp order. The ring can accept events that remain unread when a run ends; those are not counted as drops. The reader's event-to-observation latency describes received events only, not events that were dropped. Time near or at full capacity is an estimate from 10 ms samples and can miss shorter bursts. The peak occupancy is the highest sampled occupancy, not a continuous kernel high-water mark.

## WSL2 measurements

Kernel: `6.6.87.2-microsoft-standard-WSL2`. Values below are medians of three separate trials. Rates use the complete reader window, so they include setup and post-workload time as well as the two-second workload.

| Workload | CPUs | Attempted/s | Received/s | Drop fraction | Peak sampled occupancy | Any CPU near full | Delivery p95 | Workload change vs paired baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CPU, 1 thread | 1 | 2,364 | 2,356 | 0.31% | 25% | 0 ms | 1,268 us | +0.37% |
| Stress, 1 thread | 1 | 18,033 | 18,017 | 0.08% | 61% | 0 ms | 1,074 us | +0.39% |
| Stress, 2 threads | 1 | 25,076 | 25,025 | 0.20% | 62% | 0 ms | 1,062 us | -0.77% |
| Stress, 4 threads | 1 | 51,892 | 41,395 | 20.76% | 100% | 701 ms | 1,060 us | -0.89% |
| Stress, 8 threads | 2 | 99,329 | 70,085 | 30.23% | 100% | 1,164 ms | 1,050 us | -0.71% |
| Stress, 16 threads | 4 | 186,721 | 153,689 | 17.74% | 100% | 990 ms | 1,036 us | +0.34% |
| Stress, 32 threads | 8 | 363,116 | 308,643 | 15.13% | 100% | 1,063 ms | 1,037 us | -0.61% |
| Stress, 64 threads | 4 | 632,746 | 202,607 | 68.02% | 100% | 1,617 ms | 1,071 us | +0.41% |

The operating-range screen defines **low loss** as at most 1% dropped in *every* trial of a setting, and **saturated** as at least 5% loss plus a sampled full ring in *every* trial. All three one-CPU settings through the two-thread stress point passed the low-loss screen; all trials of the four-thread one-CPU stress point were saturated. On this host and with these workloads, the transition lies between the tested medians of about **25,000 and 52,000 attempted events/s**. This is a bracket between tested points, not a guaranteed capacity threshold. At fixed four stress threads per pinned CPU, increasing from one to eight CPUs raised attempted and received rates, but loss was not monotonic because the number of per-CPU rings and host activity also changed. The 64-thread/four-CPU point demonstrated more severe saturation.

In all three recovery trials, the no-reader pressure period filled at least one ring and produced more than 500,000 reported drops before the reader started. After it started, sampled occupancy stayed below 20% within **9.5–17.9 ms** (median **11.2 ms**), and thousands of newly produced events were received. This shows recovery in the defined test; it does not promise a fixed recovery time under other host loads. The module mapping was 98,304 bytes for 24 possible CPU slots; the reader's reported peak resident set was roughly 15 MiB. That resident-set figure includes runtime and libraries, while the mapping figure excludes kernel bookkeeping. Reader CPU time rose with delivered event rate, from about 0.06 seconds in the CPU case to 0.39 seconds in the eight-CPU stress case over each roughly three-second window.

Paired workload throughput changes ranged from small losses to small apparent gains. They do not identify kernel-only CPU cost; they include the module and reader together and are affected by WSL scheduling and background activity. The low p95 values under heavy pressure also reflect **survivor bias**: dropped events have no delivery latency. Results characterize this WSL2 setup only and should not be generalized to native Linux hardware.
