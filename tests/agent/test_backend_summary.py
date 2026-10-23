import importlib.util
from pathlib import Path

script = Path(__file__).resolve().parents[2] / "scripts" / "benchmark-backends.py"
spec = importlib.util.spec_from_file_location("benchmark_backends", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

valid = "events=8 emitted=10 dropped=2 latency_samples=7 latency_p50_us=200 latency_p95_us=900 latency_p99_us=1100 latency_clamped=0 latency_invalid=1"
summary = module.parse_summary(valid)
assert summary["events"] == 8 and summary["emitted"] == 10 and summary["dropped"] == 2

for invalid in (valid.replace("latency_samples=7", "latency_samples=6"),
                valid.replace(" emitted=10", "")):
    try:
        module.parse_summary(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted invalid summary: {invalid}")
