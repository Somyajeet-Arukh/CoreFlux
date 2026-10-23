#!/usr/bin/env python3
"""Record the exact source, binaries, environment, and reports checked by a release run."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "benchmarks" / "reports"
SOURCE_SUFFIXES = {".c", ".cpp", ".h", ".hpp", ".py", ".sh", ".md"}
BINARIES = ("coreflux-agent", "coreflux-workload", "coreflux-ring-reader",
            "coreflux-ebpf-loader", "coreflux-analyze", "coreflux-policy", "sched.bpf.o")
REPORT_NAMES = ("release-module-characterization.json", "release-module-characterization-validation.json",
                "backend-parity.json", "analysis-reproducibility.json",
                "release-backend-comparison.json")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version(*command):
    return subprocess.check_output(command, text=True).splitlines()[0]


sources = sorted(path for path in ROOT.rglob("*") if path.is_file()
                 and "build" not in path.relative_to(ROOT).parts
                 and "benchmarks" not in path.relative_to(ROOT).parts
                 and (path.suffix in SOURCE_SUFFIXES or path.name in {"CMakeLists.txt", "Dockerfile.dev", ".gitignore"}))
source_hashes = {str(path.relative_to(ROOT)).replace(os.sep, "/"): sha256(path) for path in sources}
tree_hash = hashlib.sha256()
for name, digest in source_hashes.items():
    tree_hash.update(f"{name} {digest}\n".encode())

manifest = {
    "schema_version": 1,
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "kernel": platform.release(),
    "distribution": platform.platform(),
    "tools": {"cmake": version("cmake", "--version"),
              "clang": version("clang", "--version"),
              "cxx": version("c++", "--version"),
              "python": platform.python_version(),
              "libbpf": version("pkg-config", "--modversion", "libbpf")},
    "source_tree_sha256": tree_hash.hexdigest(),
    "source_files_sha256": source_hashes,
    "binaries_sha256": {name: sha256(ROOT / "build" / name) for name in BINARIES},
    "reports_sha256": {name: sha256(REPORTS / name) for name in REPORT_NAMES},
}
REPORTS.mkdir(parents=True, exist_ok=True)
destination = REPORTS / "release-manifest.json"
destination.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"saved {destination.relative_to(ROOT)}; source tree {manifest['source_tree_sha256']}")
