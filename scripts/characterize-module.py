#!/usr/bin/env python3
"""Measure module-only telemetry scaling, occupancy, saturation, and recovery."""
import argparse
import fcntl
import json
import mmap
import os
from pathlib import Path
import statistics
import struct
import subprocess
import tempfile
import threading
import time

MODULE = "/kernel/phase2/coreflux_main.ko"
GET_RING_INFO = 0xC0204306
GET_STATS = 0xC0204303
SCENARIOS = (("cpu", 1, 1), ("telemetry-stress", 1, 1),
             ("telemetry-stress", 2, 1), ("telemetry-stress", 4, 1),
             ("telemetry-stress", 8, 2), ("telemetry-stress", 16, 4),
             ("telemetry-stress", 32, 8), ("telemetry-stress", 64, 4))


def minor_number():
    for line in Path("/proc/misc").read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == "coreflux":
            return int(fields[0])
    raise RuntimeError("coreflux misc device not found")


def get_info(fd):
    value = bytearray(struct.pack("=IIIIIIQ", 32, 1, 0, 0, 0, 0, 0))
    fcntl.ioctl(fd, GET_RING_INFO, value, True)
    _, _, cpu_slots, region_size, capacity, event_size, mapping_size = struct.unpack("=IIIIIIQ", value)
    if not cpu_slots or not capacity or event_size != 32 or mapping_size != cpu_slots * region_size:
        raise RuntimeError("incompatible module ring layout")
    return {"cpu_slots": cpu_slots, "region_size": region_size,
            "capacity": capacity, "mapping_size": mapping_size}


def get_stats(fd):
    value = bytearray(struct.pack("=IIQQII", 32, 1, 0, 0, 0, 0))
    fcntl.ioctl(fd, GET_STATS, value, True)
    _, _, emitted, dropped, _, _ = struct.unpack("=IIQQII", value)
    return {"emitted": emitted, "dropped": dropped, "attempted": emitted + dropped}


class OccupancySampler:
    def __init__(self, mapping, info, interval_ms=10):
        self.mapping, self.info = mapping, info
        self.interval_ms = interval_ms
        self.stop_event = threading.Event()
        self.samples = []
        self.per_cpu_peak = [0] * info["cpu_slots"]
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join()

    def run(self):
        while True:
            stamp = time.monotonic_ns()
            occupancies = []
            for cpu in range(self.info["cpu_slots"]):
                offset = cpu * self.info["region_size"]
                head, tail = struct.unpack_from("=QQ", self.mapping, offset)
                used = head - tail if head >= tail else 0
                if used > self.info["capacity"]:
                    used = self.info["capacity"]
                occupancies.append(used)
                self.per_cpu_peak[cpu] = max(self.per_cpu_peak[cpu], used)
            self.samples.append({"monotonic_ns": stamp, "max_occupancy": max(occupancies),
                                 "full_cpus": sum(value == self.info["capacity"] for value in occupancies),
                                 "near_full_cpus": sum(value * 5 >= self.info["capacity"] * 4 for value in occupancies)})
            if self.stop_event.wait(self.interval_ms / 1000):
                break

    def summary(self):
        near_ns = full_ns = 0
        for before, after in zip(self.samples, self.samples[1:]):
            elapsed = after["monotonic_ns"] - before["monotonic_ns"]
            if before["near_full_cpus"]:
                near_ns += elapsed
            if before["full_cpus"]:
                full_ns += elapsed
        return {"sample_period_ms": self.interval_ms, "samples": len(self.samples),
                "peak_occupancy": max(self.per_cpu_peak),
                "peak_occupancy_fraction": max(self.per_cpu_peak) / self.info["capacity"],
                "cpus_reaching_full": sum(value == self.info["capacity"] for value in self.per_cpu_peak),
                "any_cpu_near_full_ms_estimate": near_ns / 1e6,
                "any_cpu_full_ms_estimate": full_ns / 1e6,
                "per_cpu_peak": self.per_cpu_peak}


def workload(mode, threads, cpus, seconds):
    result = subprocess.run(["taskset", "-c", cpus, "build/coreflux-workload", "--mode", mode,
                             "--seconds", str(seconds), "--threads", str(threads)],
                            check=True, capture_output=True, text=True, timeout=seconds + 10)
    return json.loads(result.stdout)


def check_events(path):
    count = 0
    last_by_cpu = {}
    with path.open() as stream:
        for line in stream:
            record = json.loads(line)
            if (set(record) != {"timestamp_ns", "cpu", "prev_pid", "next_pid", "type"} or
                    record["type"] != 1 or record["timestamp_ns"] <= 0 or
                    record["cpu"] < 0 or record["prev_pid"] < 0 or record["next_pid"] < 0):
                raise RuntimeError("malformed module event")
            cpu = record["cpu"]
            if record["timestamp_ns"] < last_by_cpu.get(cpu, 0):
                raise RuntimeError("per-CPU event timestamps reversed")
            last_by_cpu[cpu] = record["timestamp_ns"]
            count += 1
    return count


def parse_reader(text):
    values = {}
    for part in text.split():
        key, sep, value = part.partition("=")
        if sep:
            values[key] = int(value)
    required = {"events", "emitted", "dropped", "latency_samples", "latency_p50_us",
                "latency_p95_us", "latency_p99_us", "latency_clamped", "latency_invalid"}
    if not required.issubset(values) or values["latency_samples"] + values["latency_invalid"] != values["events"]:
        raise RuntimeError(f"invalid reader summary: {text}")
    return values


def prepared_module(directory):
    subprocess.run(["insmod", MODULE], check=True)
    device = Path(directory) / "coreflux-device"
    fd = None
    try:
        os.mknod(device, 0o20000 | 0o600, os.makedev(10, minor_number()))
        fd = os.open(device, os.O_RDWR)
        info = get_info(fd)
        mapping = mmap.mmap(fd, info["mapping_size"], access=mmap.ACCESS_WRITE)
        return device, fd, info, mapping
    except Exception:
        if fd is not None:
            os.close(fd)
        device.unlink(missing_ok=True)
        subprocess.run(["rmmod", "coreflux_main"], check=True)
        raise


def wait_reader(reader):
    _, status, usage = os.wait4(reader.pid, 0)
    reader.returncode = os.waitstatus_to_exitcode(status)
    stdout, stderr = reader.stdout.read(), reader.stderr.read()
    reader.stdout.close()
    reader.stderr.close()
    if reader.returncode:
        raise RuntimeError(f"module reader failed: {stderr}")
    return parse_reader(stdout), usage.ru_utime + usage.ru_stime, usage.ru_maxrss


def module_trial(mode, threads, cpus, seconds, directory):
    device = Path(directory) / "coreflux-device"
    output = Path(directory) / "events.jsonl"
    fd = mapping = sampler = reader = None
    loaded = False
    try:
        device, fd, info, mapping = prepared_module(directory)
        loaded = True
        sampler = OccupancySampler(mapping, info)
        sampler.start()
        started = time.monotonic()
        reader = subprocess.Popen(["build/coreflux-ring-reader", str(device), str(output), str(seconds + 1)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.3)
        result = workload(mode, threads, cpus, seconds)
        reader_summary, reader_cpu, reader_rss = wait_reader(reader)
        elapsed = time.monotonic() - started
        sampler.stop()
        occupancy = sampler.summary()
        stats = get_stats(fd)
        if reader_summary["emitted"] > stats["emitted"] or reader_summary["dropped"] > stats["dropped"]:
            raise RuntimeError("module counters moved backwards")
        if check_events(output) != reader_summary["events"]:
            raise RuntimeError("event stream and reader count disagree")
        accepted_unread = reader_summary["emitted"] - reader_summary["events"]
        if accepted_unread < 0:
            raise RuntimeError("reader consumed more events than accepted")
        attempted = reader_summary["emitted"] + reader_summary["dropped"]
        return {"workload": result, "reader": reader_summary, "occupancy": occupancy,
                "attempted": attempted, "accepted": reader_summary["emitted"],
                "received": reader_summary["events"], "dropped": reader_summary["dropped"],
                "accepted_unread_at_stop": accepted_unread,
                "loss_fraction": reader_summary["dropped"] / attempted if attempted else None,
                "attempted_per_second": attempted / elapsed,
                "received_per_second": reader_summary["events"] / elapsed,
                "reader_cpu_seconds": reader_cpu, "reader_peak_rss_kib": reader_rss,
                "module_ring_bytes": info["mapping_size"], "collector_window_seconds": elapsed}
    finally:
        if reader is not None and reader.poll() is None and reader.returncode is None:
            reader.kill()
            reader.wait()
        if sampler is not None and sampler.thread.is_alive():
            sampler.stop()
        if mapping is not None:
            mapping.close()
        if fd is not None:
            os.close(fd)
        device.unlink(missing_ok=True)
        if loaded:
            subprocess.run(["rmmod", "coreflux_main"], check=True)
        output.unlink(missing_ok=True)


def recovery_trial(cpus, directory):
    device = Path(directory) / "coreflux-device"
    output = Path(directory) / "recovery-events.jsonl"
    fd = mapping = sampler = reader = None
    loaded = False
    try:
        device, fd, info, mapping = prepared_module(directory)
        loaded = True
        sampler = OccupancySampler(mapping, info)
        sampler.start()
        high = workload("telemetry-stress", 32, cpus, 1)
        before = get_stats(fd)
        pre_reader_occupancy = sampler.samples[-1]["max_occupancy"]
        pre_reader_full_cpus = sampler.samples[-1]["full_cpus"]
        reader_start = time.monotonic_ns()
        reader = subprocess.Popen(["build/coreflux-ring-reader", str(device), str(output), "3"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        low = workload("cpu", 1, cpus.split(",")[0], 1)
        reader_summary, reader_cpu, _ = wait_reader(reader)
        sampler.stop()
        after = get_stats(fd)
        if check_events(output) != reader_summary["events"]:
            raise RuntimeError("recovery stream and reader count disagree")
        samples = [sample for sample in sampler.samples if sample["monotonic_ns"] >= reader_start]
        threshold = info["capacity"] // 5
        recovered_at = next((samples[i]["monotonic_ns"] for i in range(len(samples) - 2)
                             if all(samples[j]["max_occupancy"] <= threshold for j in range(i, i + 3))), None)
        return {"high_pressure_workload": high, "post_pressure_workload": low,
                "before_reader": before, "after_reader": after, "reader": reader_summary,
                "reader_cpu_seconds": reader_cpu, "occupancy": sampler.summary(),
                "pre_reader_max_occupancy": pre_reader_occupancy,
                "pre_reader_full_cpus": pre_reader_full_cpus,
                "recovery_to_below_20_percent_ms": (recovered_at - reader_start) / 1e6 if recovered_at else None,
                "new_events_received_after_reader_start_lower_bound": max(0, reader_summary["events"] - before["emitted"]),
                "recovery_observed": recovered_at is not None and before["dropped"] > 0 and pre_reader_full_cpus > 0}
    finally:
        if reader is not None and reader.poll() is None and reader.returncode is None:
            reader.kill()
            reader.wait()
        if sampler is not None and sampler.thread.is_alive():
            sampler.stop()
        if mapping is not None:
            mapping.close()
        if fd is not None:
            os.close(fd)
        device.unlink(missing_ok=True)
        if loaded:
            subprocess.run(["rmmod", "coreflux_main"], check=True)
        output.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/reports/module-characterization.json"))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30 or not 1 <= args.repeats <= 10:
        parser.error("seconds must be 1..30 and repeats 1..10")
    allowed = sorted(os.sched_getaffinity(0))
    if len(allowed) < 8:
        parser.error("at least eight allowed CPUs are required")
    if "coreflux_main" in Path("/proc/modules").read_text():
        parser.error("coreflux module is already loaded")
    report = {"schema_version": 1, "kernel": os.uname().release,
              "scope": "WSL2 host-wide scheduler telemetry; occupancy sampled every 10 ms; per-trial isolated module load",
              "seconds_per_workload": args.seconds, "repeats": args.repeats, "scenarios": [], "recovery": []}
    with tempfile.TemporaryDirectory(prefix="coreflux-module-") as directory:
        for mode, threads, count in SCENARIOS:
            cpus = ",".join(map(str, allowed[:count]))
            trials = []
            for index in range(args.repeats):
                if index % 2:
                    measured = module_trial(mode, threads, cpus, args.seconds, directory)
                    baseline = workload(mode, threads, cpus, args.seconds)
                else:
                    baseline = workload(mode, threads, cpus, args.seconds)
                    measured = module_trial(mode, threads, cpus, args.seconds, directory)
                measured["throughput_change_percent"] = (measured["workload"]["operations"] / baseline["operations"] - 1) * 100
                trials.append({"baseline": baseline, "module": measured})
            fields = ("attempted_per_second", "received_per_second", "loss_fraction", "reader_cpu_seconds",
                      "reader_peak_rss_kib", "throughput_change_percent")
            medians = {key: statistics.median(trial["module"][key] for trial in trials) for key in fields}
            for key in ("peak_occupancy_fraction", "any_cpu_near_full_ms_estimate", "any_cpu_full_ms_estimate"):
                medians[key] = statistics.median(trial["module"]["occupancy"][key] for trial in trials)
            for key in ("latency_p50_us", "latency_p95_us", "latency_p99_us"):
                medians[key] = statistics.median(trial["module"]["reader"][key] for trial in trials)
            no_drop_all = all(trial["module"]["dropped"] == 0 for trial in trials)
            report["scenarios"].append({"mode": mode, "threads": threads, "cpus": cpus,
                                        "trials": trials, "medians": medians, "zero_drops_in_all_trials": no_drop_all})
            print(f"{mode} threads={threads} cpus={cpus}: attempted/s={medians['attempted_per_second']:.0f} loss={medians['loss_fraction']:.3%} peak occupancy={medians['peak_occupancy_fraction']:.0%}", flush=True)
        cpus = ",".join(map(str, allowed[:4]))
        for _ in range(args.repeats):
            report["recovery"].append(recovery_trial(cpus, directory))
        recovered = [trial["recovery_to_below_20_percent_ms"] for trial in report["recovery"]
                     if trial["recovery_to_below_20_percent_ms"] is not None]
        report["recovery_summary"] = {
            "all_trials_recovered": all(trial["recovery_observed"] for trial in report["recovery"]),
            "median_recovery_ms": statistics.median(recovered) if recovered else None}
    reliable = [scenario for scenario in report["scenarios"] if scenario["zero_drops_in_all_trials"]]
    report["observed_zero_drop_region"] = {
        "scenarios": [{"mode": item["mode"], "threads": item["threads"], "cpus": item["cpus"]} for item in reliable],
        "highest_median_attempted_per_second": max((item["medians"]["attempted_per_second"] for item in reliable), default=None)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
