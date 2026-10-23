#!/usr/bin/env python3
"""Run each deterministic workload with perf, preserving unsupported counters."""
import argparse
import json
import os
from pathlib import Path
import shutil
import glob
import platform
import select
import statistics
import subprocess
import tempfile

MODES = ("cpu", "sequential", "random", "context-switch", "mixed", "telemetry-stress", "latency")
EVENTS = ("cycles", "instructions", "cache-misses", "branch-misses", "context-switches", "task-clock", "page-faults")


def find_perf():
    candidates = [os.environ.get("PERF_EXE"), shutil.which("perf"), *sorted(glob.glob("/usr/lib/linux-tools/*/perf"), reverse=True)]
    for candidate in candidates:
        if candidate:
            try:
                if subprocess.run([candidate, "--version"], capture_output=True, check=False).returncode == 0:
                    return candidate
            except OSError:
                continue
    return None


def host_details(perf):
    cpu_model = None
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu_model = line.split(":", 1)[1].strip()
            break
    cache_levels = []
    for folder in Path("/sys/devices/system/cpu/cpu0/cache").glob("index*"):
        try:
            if (folder / "type").read_text().strip() != "Unified":
                continue
            level = int((folder / "level").read_text().strip())
            raw = (folder / "size").read_text().strip().upper()
            factor = 1024 if raw.endswith("K") else 1024 * 1024 if raw.endswith("M") else 1
            size = int(raw.rstrip("KM")) * factor
            cache_levels.append((level, size))
        except (OSError, ValueError):
            continue
    llc_bytes = max(cache_levels)[1] if cache_levels else None
    perf_version = subprocess.run([perf, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    return {"kernel": os.uname().release, "architecture": platform.machine(), "cpu_model": cpu_model,
            "last_level_cache_bytes": llc_bytes, "perf_version": perf_version}


def parse_counters(stderr):
    counters = {event: {"status": "unavailable", "reason": "not returned by perf"} for event in EVENTS}
    for line in stderr.splitlines():
        parts = line.split(",")
        if len(parts) < 5 or parts[2] not in counters:
            continue
        raw, unit, event, _, running_pct = parts[:5]
        if raw.startswith("<"):
            counters[event] = {"status": "unavailable", "reason": raw.strip("<>")}
            continue
        try:
            value, percentage = float(raw), float(running_pct)
        except ValueError:
            counters[event] = {"status": "unavailable", "reason": "invalid perf result"}
            continue
        if value.is_integer():
            value = int(value)
        counters[event] = {"status": "available", "value": value, "unit": unit or "count", "running_percent": percentage, "multiplexed": percentage < 99.9}
    return counters


def controlled_memory_run(command, seconds):
    with tempfile.TemporaryDirectory(prefix="coreflux-perf-") as directory:
        control = Path(directory) / "control"
        acknowledgement = Path(directory) / "ack"
        os.mkfifo(control)
        os.mkfifo(acknowledgement)
        control_fd = os.open(control, os.O_RDWR | os.O_NONBLOCK)
        ack_fd = os.open(acknowledgement, os.O_RDWR | os.O_NONBLOCK)
        process = None
        try:
            command[2:2] = ["--delay=-1", f"--control=fifo:{control},{acknowledgement}"]
            command.append("--controlled")
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

            def line_from_child(expected, timeout):
                ready, _, _ = select.select([process.stdout], [], [], timeout)
                if not ready or process.stdout.readline().strip() != expected:
                    raise RuntimeError(f"memory workload did not signal {expected}")

            def perf_command(value):
                os.write(control_fd, (value + "\n").encode())
                ready, _, _ = select.select([ack_fd], [], [], 10)
                if not ready or b"ack" not in os.read(ack_fd, 128):
                    raise RuntimeError(f"perf did not acknowledge {value}")

            line_from_child("READY", seconds + 60)
            perf_command("enable")
            process.stdin.write("GO\n")
            process.stdin.flush()
            line_from_child("DONE", seconds + 10)
            perf_command("disable")
            process.stdin.write("STOP\n")
            process.stdin.flush()
            stdout, stderr = process.communicate(timeout=seconds + 30)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            os.close(control_fd)
            os.close(ack_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, default=Path("build/coreflux-workload"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/reports/performance-suite.json"))
    parser.add_argument("--seconds", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--memory-mib", type=int, default=32, help="per-thread data size for memory modes")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60 or not 1 <= args.repeats <= 20 or not 4 <= args.memory_mib <= 256:
        parser.error("seconds must be 1..60, repeats 1..20, and memory MiB 4..256")
    workload, output = args.workload, args.output
    perf = find_perf()
    if not perf or not workload.exists():
        raise SystemExit("perf and the built coreflux-workload are required")
    cpu = min(os.sched_getaffinity(0))
    runs = []
    for mode in MODES:
        trials = []
        for _ in range(args.repeats):
            command = [perf, "stat", "-x,", "-e", ",".join(EVENTS), "--", "taskset", "-c", str(cpu), str(workload.resolve()), "--mode", mode, "--seconds", str(args.seconds), "--threads", "1" if mode == "latency" else "2"]
            if mode in ("sequential", "random"):
                command.extend(("--memory-mib", str(args.memory_mib)))
            result = controlled_memory_run(command, args.seconds) if mode in ("sequential", "random") else subprocess.run(command, capture_output=True, text=True, check=False, timeout=args.seconds + 30)
            if result.returncode:
                raise RuntimeError(f"{mode} failed ({result.returncode}): {result.stderr}")
            workload_result = json.loads(result.stdout.strip().splitlines()[-1])
            counters = parse_counters(result.stderr)
            cycles, instructions = counters["cycles"], counters["instructions"]
            ipc = instructions["value"] / cycles["value"] if cycles["status"] == instructions["status"] == "available" and cycles["value"] and not (cycles["multiplexed"] or instructions["multiplexed"]) else None
            trials.append({"workload": workload_result, "counters": counters, "ipc": ipc})
        median_ops = statistics.median(t["workload"]["operations"] / args.seconds for t in trials)
        medians = {event: statistics.median(t["counters"][event]["value"] for t in trials) if all(t["counters"][event]["status"] == "available" and not t["counters"][event]["multiplexed"] for t in trials) else None for event in EVENTS}
        runs.append({"mode": mode, "trials": trials, "median_operations_per_second": median_ops, "median_unmultiplexed_counters": medians})
    details = host_details(perf)
    memory_footprint = args.memory_mib * 2 * 1024 * 1024
    report = {"schema_version": 2, "host": os.uname().release, "host_details": details, "perf": perf, "cpu_affinity": cpu, "seconds_per_trial": args.seconds, "repeats": args.repeats, "memory_mib_per_thread": args.memory_mib, "memory_footprint_bytes": memory_footprint,
              "memory_exceeds_last_level_cache": memory_footprint > details["last_level_cache_bytes"] if details["last_level_cache_bytes"] else None, "runs": runs,
              "interpretation": "IPC is omitted when hardware counters are unavailable. Operation counts have mode-specific units and are not comparable across modes."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"saved {output}")
    for run in runs:
        print(run["mode"], "median operations/sec", run["median_operations_per_second"], "median context switches", run["median_unmultiplexed_counters"]["context-switches"])


if __name__ == "__main__":
    main()
