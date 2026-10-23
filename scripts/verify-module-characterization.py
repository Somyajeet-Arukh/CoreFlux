#!/usr/bin/env python3
"""Check module telemetry accounting and characterization evidence."""
import argparse
import json
from pathlib import Path
import statistics


def verify(report, minimum_repeats):
    if report.get("repeats", 0) < minimum_repeats:
        raise ValueError(f"need at least {minimum_repeats} repeated trials")
    scenarios = report["scenarios"]
    if {len(scenario["cpus"].split(",")) for scenario in scenarios} != {1, 2, 4, 8}:
        raise ValueError("CPU scaling points 1, 2, 4, and 8 are required")
    low_loss = []
    saturated = []
    for scenario in scenarios:
        if len(scenario["trials"]) != report["repeats"]:
            raise ValueError("missing trials")
        fractions = []
        for trial in scenario["trials"]:
            module = trial["module"]
            if module["attempted"] != module["accepted"] + module["dropped"]:
                raise ValueError("attempted-event accounting failed")
            if module["accepted"] != module["received"] + module["accepted_unread_at_stop"]:
                raise ValueError("accepted-event accounting failed")
            if module["reader"]["events"] != module["received"]:
                raise ValueError("reader count mismatch")
            if module["attempted"] <= 0 or module["received"] <= 0:
                raise ValueError("empty event trial")
            if abs(module["loss_fraction"] - module["dropped"] / module["attempted"]) > 1e-12:
                raise ValueError("loss fraction mismatch")
            if not 0 <= module["occupancy"]["peak_occupancy_fraction"] <= 1:
                raise ValueError("invalid occupancy")
            if module["module_ring_bytes"] <= 0 or module["reader_peak_rss_kib"] <= 0:
                raise ValueError("missing memory footprint")
            if module["reader"]["latency_samples"] + module["reader"]["latency_invalid"] != module["received"]:
                raise ValueError("latency sample mismatch")
            if not isinstance(module["throughput_change_percent"], (int, float)):
                raise ValueError("missing paired overhead")
            fractions.append(module["loss_fraction"])
        label = {"mode": scenario["mode"], "threads": scenario["threads"], "cpus": scenario["cpus"]}
        if all(fraction <= 0.01 for fraction in fractions):
            low_loss.append({**label, "median_attempted_per_second": scenario["medians"]["attempted_per_second"],
                             "maximum_trial_loss_percent": max(fractions) * 100})
        if all(fraction >= 0.05 for fraction in fractions) and all(
                trial["module"]["occupancy"]["peak_occupancy_fraction"] == 1 for trial in scenario["trials"]):
            saturated.append({**label, "median_attempted_per_second": scenario["medians"]["attempted_per_second"],
                              "median_loss_percent": statistics.median(fractions) * 100})
    if not low_loss or not saturated:
        raise ValueError("both low-loss and saturated operating regions must be observed")
    recovery = report["recovery"]
    if len(recovery) != report["repeats"] or not all(
            trial["recovery_observed"] and trial["pre_reader_full_cpus"] > 0 and
            trial["new_events_received_after_reader_start_lower_bound"] > 0 for trial in recovery):
        raise ValueError("saturation recovery not observed in every trial")
    return {"schema_version": 1, "kernel": report["kernel"], "repeats": report["repeats"],
            "status": "complete_for_wsl2_scope", "low_loss_criterion": "each trial <= 1% loss",
            "saturated_criterion": "each trial >= 5% loss and sampled full occupancy",
            "low_loss_region": low_loss, "saturated_region": saturated,
            "highest_observed_low_loss_attempted_per_second": max(item["median_attempted_per_second"] for item in low_loss),
            "lowest_observed_saturated_attempted_per_second": min(item["median_attempted_per_second"] for item in saturated),
            "median_recovery_ms": statistics.median(trial["recovery_to_below_20_percent_ms"] for trial in recovery)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--minimum-repeats", type=int, default=3)
    parser.add_argument("--output", type=Path,
                        default=Path("benchmarks/reports/module-characterization-validation.json"))
    args = parser.parse_args()
    try:
        result = verify(json.loads(args.report.read_text()), args.minimum_repeats)
    except (KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"module characterization validation failed: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"module characterization validation passed for {result['repeats']} trials; saved {args.output}")


if __name__ == "__main__":
    main()
