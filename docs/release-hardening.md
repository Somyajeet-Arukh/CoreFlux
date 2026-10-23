# Hardening and release checks

The release check builds CoreFlux, runs the user-space tests, and exercises the live module, module-only characterization smoke run, eBPF, analysis, policy, and backend-comparison paths. It requires the prepared `coreflux-kernel-build` Docker volume containing kernel sources matching the running WSL2 kernel. Rebuild the development image from `Dockerfile.dev` after changing it. From PowerShell in the repository directory:

```powershell
docker build -f Dockerfile.dev -t coreflux-dev .
docker run --rm --privileged --pid=host --cgroupns=host -v coreflux-kernel-build:/kernel -v "${PWD}:/workspace" coreflux-dev bash -lc 'cd /workspace && bash scripts/run-release-checks.sh'
```

The check refuses to start if `coreflux_main` is already loaded and verifies that it is unloaded on success. Live test scripts remove their temporary device nodes and unload the module on exit. Reports are written under `benchmarks/reports/` and are ignored by `.gitignore`; preserve them separately when sharing benchmark evidence. `release-manifest.json` records the checked source and binary hashes, tool versions, kernel, and key report hashes so the result can be tied to an exact local snapshot. The Dockerfile installs distribution packages without version pins, so a later image rebuild may differ; compare manifests when repeating the check. The container needs privilege because its module and eBPF tests attach to the shared WSL kernel. Do not run another CoreFlux live-kernel test concurrently.

Hardening coverage includes malformed ioctl sizes, versions, pointers, masks and control values; concurrent configuration writes and statistics reads; repeated module load/unload; invalid and shared `mmap` sizes; a mapped process exiting while another mapping remains; rejection of unload while a mapping is live; ring overflow accounting and per-CPU event ordering; backend event shape and count parity; policy dry run, affinity/nice/cgroup rollback, signal cleanup and target-exit cleanup. The eBPF loader now rejects objects missing required programs or maps and fails if it cannot read counter maps. The ring reader rejects inconsistent mapping geometry before using it.

The full check includes a one-repeat module characterization smoke run and a two-repeat backend comparison, writing separate `release-*.json` reports. These smoke results do not replace the three-repeat [telemetry scalability](telemetry-scalability.md) and [backend comparison](backend-comparison.md) reports. Repeated checks can overwrite other ignored local reports. The original hardware-counter tools are optional. A native Linux release check also needs a kernel module built for that host's exact kernel and a compatible eBPF tracepoint layout.
