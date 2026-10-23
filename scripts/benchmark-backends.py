#!/usr/bin/env python3
"""Run paired baseline/module/eBPF measurements in a privileged Linux container."""
import argparse
import json
import os
from pathlib import Path
import re
import resource
import statistics
import subprocess
import tempfile
import time


SCENARIOS = (("cpu", 1, 1), ("cpu", 4, 2), ("cpu", 8, 4), ("telemetry-stress", 16, 4))
MODULE = "/kernel/phase2/coreflux_main.ko"


def parse_summary(line):
    values = {}
    for part in line.strip().split():
        key, sep, value = part.partition("=")
        if sep:
            values[key] = int(value)
    required = {"events", "emitted", "dropped", "latency_samples", "latency_p50_us", "latency_p95_us", "latency_p99_us", "latency_clamped", "latency_invalid"}
    if not required.issubset(values) or values["latency_samples"] + values["latency_invalid"] != values["events"]:
        raise ValueError(f"invalid collector summary: {line}")
    return values


def minor_number():
    for line in Path("/proc/misc").read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == "coreflux":
            return int(fields[0])
    raise RuntimeError("coreflux misc device not found")


def workload(mode, threads, cpus, seconds):
    command = ["taskset", "-c", cpus, "build/coreflux-workload", "--mode", mode, "--seconds", str(seconds), "--threads", str(threads)]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=seconds + 5)
    return json.loads(result.stdout)


def collector_trial(backend, mode, threads, cpus, seconds, directory):
    device = Path(directory) / "coreflux-device"
    output = Path(directory) / "events.jsonl"
    loaded = False
    reader = None
    try:
        if backend == "module":
            subprocess.run(["insmod", MODULE], check=True)
            loaded = True
            os.mknod(device, 0o600 | 0o20000, os.makedev(10, minor_number()))
            command = ["build/coreflux-ring-reader", str(device), str(output), str(seconds + 1)]
        else:
            command = ["build/coreflux-ebpf-loader", "build/sched.bpf.o", str(output), str(seconds + 1), "0", "1"]
        started = time.monotonic()
        reader = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.3)
        result = workload(mode, threads, cpus, seconds)
        _, status, usage = os.wait4(reader.pid, 0)
        reader.returncode = os.waitstatus_to_exitcode(status)
        elapsed = time.monotonic() - started
        stdout, stderr = reader.stdout.read(), reader.stderr.read()
        reader.stdout.close()
        reader.stderr.close()
        if reader.returncode:
            raise RuntimeError(f"{backend} collector failed: {stderr}")
        summary = parse_summary(stdout)
        received = sum(1 for _ in output.open())
        if received != summary["events"]:
            raise RuntimeError(f"{backend} event rows differ from reader summary")
        if summary["events"] > summary["emitted"]:
            raise RuntimeError(f"{backend} read more events than were emitted")
        attempts = summary["emitted"] + summary["dropped"]
        return {"workload": result, "collector": summary,
                "collector_wall_seconds": elapsed,
                "collector_cpu_seconds": usage.ru_utime + usage.ru_stime,
                "collector_peak_rss_kib": usage.ru_maxrss,
                "events_per_second": summary["events"] / elapsed,
                "accepted_unread_at_stop": summary["emitted"] - summary["events"],
                "drop_fraction": summary["dropped"] / attempts if attempts else None}
    finally:
        if reader is not None and reader.poll() is None and reader.returncode is None:
            reader.kill()
            reader.wait()
        device.unlink(missing_ok=True)
        if loaded:
            subprocess.run(["rmmod", "coreflux_main"], check=True)
        output.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/reports/backend-comparison.json"))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30 or not 1 <= args.repeats <= 10:
        parser.error("seconds must be 1..30 and repeats 1..10")
    allowed = sorted(os.sched_getaffinity(0))
    if len(allowed) < 4:
        parser.error("at least four allowed CPUs are required")
    if "coreflux_main" in Path("/proc/modules").read_text():
        parser.error("coreflux module is already loaded; benchmark needs exclusive ownership")
    report = {"schema_version": 1, "kernel": os.uname().release, "seconds_per_workload": args.seconds,
              "repeats": args.repeats, "scenarios": [],
              "scope": "separate sequential runs; collectors observe host-wide sched_switch events; workload pinned to selected CPUs; eBPF uses 1 ms paced polling"}
    with tempfile.TemporaryDirectory(prefix="coreflux-backend-") as directory:
        for mode, threads, cpu_count in SCENARIOS:
            cpus = ",".join(str(cpu) for cpu in allowed[:cpu_count])
            trials = []
            for index in range(args.repeats):
                order = ("baseline", "module", "ebpf") if index % 2 == 0 else ("ebpf", "module", "baseline")
                trial = {}
                for backend in order:
                    if backend == "baseline":
                        trial[backend] = {"workload": workload(mode, threads, cpus, args.seconds)}
                    else:
                        trial[backend] = collector_trial(backend, mode, threads, cpus, args.seconds, directory)
                baseline = trial["baseline"]["workload"]["operations"]
                for backend in ("module", "ebpf"):
                    trial[backend]["throughput_change_percent_vs_baseline"] = (trial[backend]["workload"]["operations"] / baseline - 1) * 100 if baseline else None
                trials.append(trial)
            medians = {}
            ranges = {}
            for backend in ("baseline", "module", "ebpf"):
                medians[backend] = {"operations_per_second": statistics.median(t[backend]["workload"]["operations"] / args.seconds for t in trials)}
                if backend != "baseline":
                    for key in ("events_per_second", "drop_fraction", "accepted_unread_at_stop", "collector_cpu_seconds", "collector_peak_rss_kib", "throughput_change_percent_vs_baseline"):
                        medians[backend][key] = statistics.median(t[backend][key] for t in trials if t[backend][key] is not None)
                    for key in ("latency_p50_us", "latency_p95_us", "latency_p99_us", "latency_clamped"):
                        medians[backend][key] = statistics.median(t[backend]["collector"][key] for t in trials)
                    ranges[backend] = {}
                    for key in ("throughput_change_percent_vs_baseline", "drop_fraction"):
                        values = [t[backend][key] for t in trials if t[backend][key] is not None]
                        ranges[backend][key] = {"min": min(values), "max": max(values)}
            report["scenarios"].append({"mode": mode, "threads": threads, "cpus": cpus, "trials": trials, "medians": medians, "ranges": ranges})
            print(f"{mode} threads={threads} cpus={cpus}: module {medians['module']['throughput_change_percent_vs_baseline']:.1f}%, ebpf {medians['ebpf']['throughput_change_percent_vs_baseline']:.1f}% throughput change")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
