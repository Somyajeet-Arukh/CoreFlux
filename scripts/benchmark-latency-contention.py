#!/usr/bin/env python3
"""Compare periodic wake latency alone and beside a CPU-bound neighbor."""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, default=Path("build/coreflux-workload"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/reports/latency-contention.json"))
    parser.add_argument("--seconds", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--with-ebpf", action="store_true", help="capture scheduler events during each trial")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30 or not 1 <= args.repeats <= 20:
        parser.error("seconds must be 1..30 and repeats must be 1..20")
    if not args.workload.exists():
        parser.error("build the workload first")
    if args.with_ebpf and not (Path("build/coreflux-ebpf-loader").exists() and Path("build/sched.bpf.o").exists()):
        parser.error("build the eBPF loader and object first")
    cpu = min(os.sched_getaffinity(0))
    binary = str(args.workload.resolve())
    pairs = []
    for index in range(args.repeats):
        pair = {}
        order = ("baseline", "contended") if index % 2 == 0 else ("contended", "baseline")
        for label in order:
            neighbor = None
            reader = None
            trace = None
            try:
                if args.with_ebpf:
                    trace_fd, trace_name = tempfile.mkstemp(prefix="coreflux-latency-", suffix=".jsonl")
                    os.close(trace_fd)
                    trace = Path(trace_name)
                    reader = subprocess.Popen(["build/coreflux-ebpf-loader", "build/sched.bpf.o", str(trace), str(args.seconds + 2)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    time.sleep(0.2)
                if label == "contended":
                    neighbor = subprocess.Popen(["taskset", "-c", str(cpu), binary, "--mode", "cpu", "--seconds", str(args.seconds + 2), "--threads", "1"], stdout=subprocess.DEVNULL)
                    time.sleep(0.2)
                start_ns = time.monotonic_ns()
                workload = subprocess.Popen(["taskset", "-c", str(cpu), binary, "--mode", "latency", "--seconds", str(args.seconds), "--threads", "1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = workload.communicate(timeout=args.seconds + 5)
                end_ns = time.monotonic_ns()
                if workload.returncode:
                    raise RuntimeError(f"latency workload failed: {stderr}")
                pair[label] = {"workload": json.loads(stdout), "scheduler_events_on_cpu": None}
                if reader is not None:
                    reader_out, reader_err = reader.communicate(timeout=args.seconds + 5)
                    if reader.returncode:
                        raise RuntimeError(f"eBPF capture failed: {reader_err}")
                    matched = 0
                    with trace.open() as stream:
                        for line in stream:
                            event = json.loads(line)
                            matched += event["cpu"] == cpu and start_ns <= event["timestamp_ns"] <= end_ns
                    pair[label]["scheduler_events_on_cpu"] = matched
                    pair[label]["reader_summary"] = reader_out.strip()
                    summary_match = re.match(r"events=(\d+) emitted=(\d+) dropped=(\d+) ", reader_out.strip())
                    if not summary_match:
                        raise RuntimeError(f"unrecognized eBPF reader summary: {reader_out.strip()}")
                    pair[label]["ebpf_dropped_events"] = int(summary_match[3])
                    if matched == 0:
                        raise RuntimeError(f"no scheduler events were observed on CPU {cpu} during the workload; reader: {reader_out.strip()}")
            finally:
                if reader is not None and reader.poll() is None:
                    reader.terminate()
                    reader.wait(timeout=5)
                if trace is not None:
                    trace.unlink(missing_ok=True)
                if neighbor is not None:
                    neighbor.terminate()
                    neighbor.wait(timeout=5)
        pairs.append(pair)
    summary = {}
    for label in ("baseline", "contended"):
        summary[label] = {key: statistics.median(pair[label]["workload"][key] for pair in pairs) for key in ("latency_p50_us", "latency_p95_us", "latency_p99_us")}
        if args.with_ebpf:
            summary[label]["scheduler_events_on_cpu"] = statistics.median(pair[label]["scheduler_events_on_cpu"] for pair in pairs)
    report = {"schema_version": 1, "host": os.uname().release, "cpu_affinity": cpu, "seconds_per_trial": args.seconds,
              "repeats": args.repeats, "ebpf_enabled": args.with_ebpf, "pairs": pairs, "median": summary,
              "interpretation": "Periodic sleep wake-up delay in microseconds; the competing CPU process runs on the same CPU. Scheduler event counts are CPU-wide within the workload interval and may include unrelated tasks. Differences reflect this host and load, not a universal policy effect."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"saved {args.output}")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
