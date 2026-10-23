#!/usr/bin/env python3
"""Derive OS/CPU measurements from the repeated CoreFlux performance suite."""
import argparse
import json
from pathlib import Path
import statistics


def counter(trial, name):
    item = trial["counters"][name]
    if item["status"] != "available" or item["multiplexed"]:
        return None
    return item["value"]


def task_clock_ms(trial):
    value = counter(trial, "task-clock")
    if value is None:
        return None
    unit = trial["counters"]["task-clock"]["unit"]
    factors = {"nsec": 0.000001, "usec": 0.001, "msec": 1, "sec": 1000}
    return value * factors[unit] if unit in factors else None


def divide(numerator, denominator, multiplier=1):
    return multiplier * numerator / denominator if numerator is not None and denominator not in (None, 0) else None


def median_available(values, total):
    values = list(values)
    return statistics.median(values) if len(values) == total and all(value is not None for value in values) else None


def summarize(run, seconds):
    trials = run["trials"]
    per_trial = []
    for trial in trials:
        cycles = counter(trial, "cycles")
        instructions = counter(trial, "instructions")
        per_trial.append({
            "ipc": divide(instructions, cycles),
            "cache_misses_per_million_instructions": divide(counter(trial, "cache-misses"), instructions, 1_000_000),
            "branch_misses_per_million_instructions": divide(counter(trial, "branch-misses"), instructions, 1_000_000),
            "context_switches_per_second": divide(counter(trial, "context-switches"), seconds),
            "task_clock_ms_per_second": divide(task_clock_ms(trial), seconds),
            "latency_p99_us": trial["workload"].get("latency_p99_us"),
        })
    keys = per_trial[0].keys()
    return {"mode": run["mode"], "trial_count": len(trials),
            "medians": {key: median_available((trial[key] for trial in per_trial), len(trials)) for key in keys},
            "per_trial": per_trial}


def compare(a, b, metrics):
    result = {"from": a["mode"], "to": b["mode"], "metric_ratios_to_over_from": {}}
    for metric in metrics:
        first, second = a["medians"][metric], b["medians"][metric]
        result["metric_ratios_to_over_from"][metric] = divide(second, first)
    return result


def hardware_gaps(suite):
    required = {"cpu": ("cycles", "instructions"),
                "sequential": ("cycles", "instructions", "cache-misses"),
                "random": ("cycles", "instructions", "cache-misses"),
                "context-switch": ("cycles", "instructions")}
    by_mode = {run["mode"]: run for run in suite["runs"]}
    gaps = []
    for mode, events in required.items():
        if mode not in by_mode:
            gaps.append({"mode": mode, "reason": "workload missing"})
            continue
        for trial_number, trial in enumerate(by_mode[mode]["trials"], 1):
            for event in events:
                item = trial["counters"][event]
                if item["status"] != "available":
                    gaps.append({"mode": mode, "trial": trial_number, "event": event, "reason": item.get("reason", "unavailable")})
                elif item["multiplexed"]:
                    gaps.append({"mode": mode, "trial": trial_number, "event": event, "reason": "multiplexed"})
    if suite.get("memory_exceeds_last_level_cache") is False:
        gaps.append({"reason": "memory footprint does not exceed last-level cache; increase --memory-mib"})
    return gaps


def analyze(suite):
    if suite.get("schema_version") != 2 or not suite.get("runs"):
        raise ValueError("expected a nonempty CoreFlux performance suite schema v2")
    rows = [summarize(run, suite["seconds_per_trial"]) for run in suite["runs"]]
    by_mode = {row["mode"]: row for row in rows}
    comparisons = []
    if "sequential" in by_mode and "random" in by_mode:
        comparisons.append(compare(by_mode["sequential"], by_mode["random"],
                                   ("ipc", "cache_misses_per_million_instructions", "context_switches_per_second")))
    if "cpu" in by_mode and "context-switch" in by_mode:
        comparisons.append(compare(by_mode["cpu"], by_mode["context-switch"],
                                   ("ipc", "context_switches_per_second", "task_clock_ms_per_second")))
    required_modes = ("cpu", "sequential", "random", "context-switch")
    ipc_available = all(mode in by_mode and by_mode[mode]["medians"]["ipc"] is not None for mode in required_modes)
    cache_available = all(mode in by_mode and by_mode[mode]["medians"]["cache_misses_per_million_instructions"] is not None for mode in ("sequential", "random"))
    gaps = hardware_gaps(suite)
    return {"schema_version": 1, "source_schema_version": 2, "host": suite["host"],
            "hardware_validation_status": "ready_for_interpretation" if not gaps else "awaiting_supported_unmultiplexed_counters",
            "ipc_available_for_core_modes": ipc_available, "cache_comparison_available": cache_available,
            "hardware_validation_gaps": gaps, "host_details": suite.get("host_details"), "memory_exceeds_last_level_cache": suite.get("memory_exceeds_last_level_cache"),
            "workloads": rows, "comparisons": comparisons,
            "interpretation": "Ratios compare medians of repeated trials and do not establish causation. Null means unavailable, multiplexed, or zero-denominator data. Operation counts across modes have different units."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=Path("benchmarks/reports/performance-suite.json"))
    parser.add_argument("output", nargs="?", type=Path, default=Path("benchmarks/reports/performance-correlation.json"))
    parser.add_argument("--require-hardware", action="store_true", help="exit 3 unless required CPU counters are usable")
    args = parser.parse_args()
    report = analyze(json.loads(args.input.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"saved {args.output}: {report['hardware_validation_status']}")
    if args.require_hardware and report["hardware_validation_gaps"]:
        grouped = {}
        for gap in report["hardware_validation_gaps"]:
            key = (gap.get("mode", "host"), gap.get("event", "configuration"), gap["reason"])
            grouped[key] = grouped.get(key, 0) + 1
        for (mode, event, reason), count in sorted(grouped.items()):
            print(f"{mode} {event}: {reason} ({count} trial(s))")
        raise SystemExit(3)


if __name__ == "__main__":
    main()
